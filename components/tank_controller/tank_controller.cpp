#include "tank_controller.h"
#include "esphome/core/log.h"
#include "esphome/core/hal.h"
#include <cmath>

namespace esphome {
namespace tank_controller {

static const char *const TAG = "tank_controller";

// Learn from a temperature difference taken over this long, not from
// tick-to-tick differences -- see the note in the header.
static const uint32_t LEARN_WINDOW_MS = 300000;  // 5 minutes
// If the probe goes away for longer than this, stop controlling.
static const uint32_t SENSOR_TIMEOUT_MS = 120000;
static const uint32_t SAVE_INTERVAL_MS = 1800000;  // 30 minutes

// A gap longer than this between valid readings means the windows that
// span it are not measuring anything real.
static const uint32_t DISCONTINUITY_MS = 90000;    // 1.5 min -- one missed read
static const uint32_t HISTORY_WIPE_MS = 300000;    // 5 min

// Heater at full for this long with less than this much rise means it is
// not actually heating: unplugged, failed, or a dead relay channel.
static const uint32_t HEAT_STALL_MS = 2700000;     // 45 minutes
static const float HEAT_STALL_RISE = 0.05f;        // degC

// Residual EMA weight. Feeds the Model Bias diagnostic only -- see the
// comment on integral authority below for why this is reported and not
// acted on.
static const float BIAS_EMA_W = 0.2f;

// Ceiling on what the integral term alone may command, as a fraction of
// heater duty. See the clamp for why this is not a fixed rate.
static const float INTEGRAL_AUTHORITY = 0.3f;

// Sign guard deadband. Inside it the feedforward is free to act
// predictively; outside it the measured error decides the direction.
//
// Written in Fahrenheit and converted once, like every other number a
// human sets or reads in this project. Celsius survives below this line
// only because the model's priors and clamps are tuned in degC/min --
// it is an implementation detail and must not reach a log line, a sensor
// or a screen.
static const float GUARD_DEADBAND_F = 0.1f;
static const float GUARD_DEADBAND = GUARD_DEADBAND_F * 5.0f / 9.0f;

// RLS forgetting factor. Very close to 1: the tank changes character over
// days (evaporation, a new heater, summer), not over minutes.
static const float LAMBDA = 0.9995f;

// Physically plausible bounds. Constraining the fit is what keeps the
// closed-loop identification from running off into nonsense when the
// controller isn't exciting the system much.
// theta[4] (the constant) sets where the model thinks the tank settles:
// equilibrium = TEMP_REF + theta[4]/ka. At +/-0.05 with a typical ka that
// spans only ~17-23 C, so a 24 C room could not be represented at all and
// even a trained model would stay biased toward cooling. +/-0.15 covers
// roughly 10-30 C, which brackets any room this tank will sit in.
static const float THETA_MIN[N_PARAMS] = {0.002f, -0.300f, -0.200f, 0.000f, -0.150f};
static const float THETA_MAX[N_PARAMS] = {0.300f, -0.000f, -0.001f, 0.050f, 0.150f};

// Starting guesses: a typical 100-200W heater in a tens-of-gallons tank.
static const float THETA_PRIOR[N_PARAMS] = {0.030f, -0.020f, -0.015f, 0.003f, 0.0f};
// Prior covariance -- how wrong we think the prior is, per parameter.
static const float P_PRIOR[N_PARAMS] = {1e-3f, 1e-3f, 1e-4f, 1e-5f, 1e-5f};

static float clampf(float v, float lo, float hi) {
  if (std::isnan(v))
    return lo;
  return v < lo ? lo : (v > hi ? hi : v);
}

void TankController::load_prior_() {
  for (uint8_t i = 0; i < N_PARAMS; i++) {
    this->model_.theta[i] = THETA_PRIOR[i];
    for (uint8_t j = 0; j < N_PARAMS; j++)
      this->model_.p[i][j] = (i == j) ? P_PRIOR[i] : 0.0f;
  }
  this->model_.updates = 0;
  this->history_idx_ = 0;
  this->history_count_ = 0;
  for (uint8_t i = 0; i < N_SLOTS; i++) {
    this->light_.slot[i] = 0.0f;
    this->light_.weight[i] = 0.0f;
  }
}

void TankController::setup() {
  this->load_prior_();

  this->model_pref_ = global_preferences->make_preference<ThermalModel>(fnv1_hash("tank_model_v2"));
  this->light_pref_ = global_preferences->make_preference<LightProfile>(fnv1_hash("tank_light"));
  this->setpoint_pref_ = global_preferences->make_preference<float>(fnv1_hash("tank_setpoint"));

  ThermalModel stored{};
  if (this->model_pref_.load(&stored) && !std::isnan(stored.theta[0])) {
    this->model_ = stored;
    this->clamp_model_();
    ESP_LOGI(TAG, "Restored thermal model after %" PRIu32 " learning steps", this->model_.updates);
  }
  LightProfile light{};
  if (this->light_pref_.load(&light) && !std::isnan(light.slot[0]))
    this->light_ = light;

  float sp = NAN;
  if (this->setpoint_pref_.load(&sp) && !std::isnan(sp))
    this->setpoint_ = clampf(sp, this->min_temp_, this->max_temp_);

  // Start with everything off until the first real reading arrives.
  this->apply_outputs_(0.0f, 0.0f);
  this->last_update_ms_ = millis();
  this->last_save_ms_ = millis();
}

void TankController::set_setpoint(float v) {
  if (std::isnan(v))
    return;
  v = clampf(v, this->min_temp_, this->max_temp_);
  if (v == this->setpoint_)
    return;
  this->setpoint_ = v;
  // Old integral was accumulated against a different target.
  this->integral_ = 0.0f;
  this->setpoint_pref_.save(&v);
}

void TankController::reset_learning() {
  ESP_LOGW(TAG, "Resetting learned model and light profile to priors");
  this->load_prior_();
  this->integral_ = 0.0f;
  this->bias_ = 0.0f;
  // Windows in flight were accumulated against the old model; carrying
  // them over would fold pre-reset data into the first new learning step.
  this->learn_anchor_temp_ = NAN;
  this->acc_heater_ = this->acc_fan_ = this->acc_light_ = this->acc_temp_ = 0.0f;
  this->acc_n_ = 0;
  this->last_light_slot_ = -1;
  this->heat_stall_since_ms_ = 0;
  this->heater_stalled_ = false;
  this->save_state_();
}

void TankController::clamp_model_() {
  for (uint8_t i = 0; i < N_PARAMS; i++) {
    if (std::isnan(this->model_.theta[i]))
      this->model_.theta[i] = THETA_PRIOR[i];
    this->model_.theta[i] = clampf(this->model_.theta[i], THETA_MIN[i], THETA_MAX[i]);
    for (uint8_t j = 0; j < N_PARAMS; j++) {
      if (std::isnan(this->model_.p[i][j]))
        this->model_.p[i][j] = (i == j) ? P_PRIOR[i] : 0.0f;
    }
    // Keep the covariance from blowing up during long unexcited stretches.
    if (this->model_.p[i][i] > P_PRIOR[i] * 10.0f)
      this->model_.p[i][i] = P_PRIOR[i] * 10.0f;
    if (this->model_.p[i][i] < 0.0f)
      this->model_.p[i][i] = P_PRIOR[i] * 1e-3f;
  }
}

void TankController::save_state_() {
  this->model_pref_.save(&this->model_);
  this->light_pref_.save(&this->light_);
}

int TankController::current_slot_(int minutes_ahead) const {
#ifdef USE_TIME
  if (this->time_ != nullptr) {
    auto now = this->time_->now();
    if (now.is_valid()) {
      int minutes = now.hour * 60 + now.minute + minutes_ahead;
      minutes = ((minutes % 1440) + 1440) % 1440;
      return minutes / 15;
    }
  }
#endif
  (void) minutes_ahead;
  return -1;
}

void TankController::update_light_profile_(float lux_norm) {
  int slot = this->current_slot_();
  if (slot < 0)
    return;
  // Only count a slot's confidence up once per visit. Incrementing on
  // every 30s update instead meant a slot reached "well observed" about a
  // minute after first seeing it, so the profile was never more than one
  // day's data pretending to be a schedule.
  const bool first_seen_today = (slot != this->last_light_slot_);
  this->last_light_slot_ = slot;

  float w = this->light_.weight[slot];
  // Fast to converge on the first day, slow and averaging after that.
  float alpha = w < 1.0f ? 1.0f : 0.15f;
  this->light_.slot[slot] = this->light_.slot[slot] * (1.0f - alpha) + lux_norm * alpha;
  if (first_seen_today && w < 30.0f)
    this->light_.weight[slot] = w + 1.0f;
}

float TankController::predicted_light_for_(int minutes_ahead) const {
  int slot = this->current_slot_(minutes_ahead);
  if (slot < 0 || this->light_.weight[slot] < 2.0f) {
    // No clock or not enough history yet -- assume the lights stay as they are.
    return this->lux_sensor_ == nullptr || std::isnan(this->lux_sensor_->state)
               ? 0.0f
               : clampf(this->lux_sensor_->state / this->full_scale_lux_, 0.0f, 1.5f);
  }
  return this->light_.slot[slot];
}

void TankController::learn_(float dt_min, float measured_rate) {
  // phi = [heater, fan, (T - TREF), light, 1]
  float phi[N_PARAMS] = {this->acc_heater_, this->acc_fan_, this->acc_temp_ - TEMP_REF, this->acc_light_, 1.0f};

  float pred = 0.0f;
  for (uint8_t i = 0; i < N_PARAMS; i++)
    pred += this->model_.theta[i] * phi[i];
  float err = measured_rate - pred;

  // A residual this large is a bad reading or someone doing a water change,
  // not new information about the tank.
  if (std::fabs(err) > 0.5f) {
    ESP_LOGW(TAG, "Discarding learning step, residual %.2f degF/h looks like a disturbance",
             err * 60.0f * 9.0f / 5.0f);
    return;
  }

  float p_phi[N_PARAMS] = {0};
  for (uint8_t i = 0; i < N_PARAMS; i++)
    for (uint8_t j = 0; j < N_PARAMS; j++)
      p_phi[i] += this->model_.p[i][j] * phi[j];

  float denom = LAMBDA;
  for (uint8_t i = 0; i < N_PARAMS; i++)
    denom += phi[i] * p_phi[i];
  if (!(denom > 1e-9f))
    return;

  for (uint8_t i = 0; i < N_PARAMS; i++)
    this->model_.theta[i] += (p_phi[i] / denom) * err;

  for (uint8_t i = 0; i < N_PARAMS; i++)
    for (uint8_t j = 0; j < N_PARAMS; j++)
      this->model_.p[i][j] = (this->model_.p[i][j] - (p_phi[i] * p_phi[j]) / denom) / LAMBDA;

  // P is symmetric by construction but drifts with float rounding over
  // thousands of updates, and an asymmetric covariance can make the gain
  // diverge. Cheap to re-impose, so do it every step.
  for (uint8_t i = 0; i < N_PARAMS; i++)
    for (uint8_t j = i + 1; j < N_PARAMS; j++) {
      const float avg = 0.5f * (this->model_.p[i][j] + this->model_.p[j][i]);
      this->model_.p[i][j] = this->model_.p[j][i] = avg;
    }

  this->clamp_model_();
  this->model_.updates++;

  // Track how wrong the model keeps being, and in which direction, and
  // publish it. Reported, deliberately not acted on: an earlier version
  // of this file used bias to gate the feedforward, on the strength of a
  // drift reading of 0.00 degF/h that turned out to be quantisation --
  // one DS18B20 LSB over a 5 minute window is exactly 1.35 degF/h, so
  // that sensor alternates between 0.00 and 1.35 and a single sample of
  // it says nothing. The model was not biased; the reading was aliased.
  // The number is worth having on a dashboard so that mistake is visible
  // next time, and worth keeping out of the control path until something
  // more than one sample justifies it.
  this->bias_ = (1.0f - BIAS_EMA_W) * this->bias_ + BIAS_EMA_W * err;

  ESP_LOGD(TAG, "learn: rate=%.4f pred=%.4f err=%.4f kh=%.4f kf=%.4f ka=%.4f kl=%.4f c=%.4f", measured_rate, pred, err,
           this->model_.theta[0], -this->model_.theta[1], -this->model_.theta[2], this->model_.theta[3],
           this->model_.theta[4]);
  (void) dt_min;
}

void TankController::apply_outputs_(float heater, float fan) {
  this->heater_duty_ = clampf(heater, 0.0f, 1.0f);
  this->fan_duty_ = this->fan_available_ ? clampf(fan, 0.0f, 1.0f) : 0.0f;
  if (this->heater_ != nullptr)
    this->heater_->set_level(this->heater_duty_);
  if (this->fan_ != nullptr)
    this->fan_->set_level(this->fan_duty_);
}

void TankController::update() {
  const uint32_t now = millis();
  const float dt_min = (now - this->last_update_ms_) / 60000.0f;
  this->last_update_ms_ = now;

  const float t = this->temp_sensor_ == nullptr ? NAN : this->temp_sensor_->state;

  if (std::isnan(t)) {
    if (this->missing_since_ms_ == 0)
      this->missing_since_ms_ = now;
    if (now - this->missing_since_ms_ > SENSOR_TIMEOUT_MS) {
      // No temperature means no safe way to heat. Cutting the heater is the
      // conservative failure: a slowly cooling tank beats a cooked one.
      if (!this->safety_tripped_)
        ESP_LOGE(TAG, "No temperature for %" PRIu32 "s - shutting the heater down", SENSOR_TIMEOUT_MS / 1000);
      this->safety_tripped_ = true;
      this->state_text_ = "fault: no probe";
      this->apply_outputs_(0.0f, 0.0f);
    }
    return;
  }
  this->missing_since_ms_ = 0;

  // A gap in readings invalidates anything measured across it. The learn
  // window would otherwise compute a rate over the whole outage from a
  // single sample's regressor averages and feed that straight into RLS,
  // and the swing figure would report a range that was never observed.
  const uint32_t since_valid = this->last_valid_ms_ == 0 ? 0 : now - this->last_valid_ms_;
  this->last_valid_ms_ = now;
  if (since_valid > HISTORY_WIPE_MS) {
    ESP_LOGW(TAG, "Gap of %" PRIu32 "s in readings - discarding swing history", since_valid / 1000);
    this->history_idx_ = 0;
    this->history_count_ = 0;
  }
  if (since_valid > DISCONTINUITY_MS) {
    this->learn_anchor_temp_ = NAN;
    this->acc_heater_ = this->acc_fan_ = this->acc_light_ = this->acc_temp_ = 0.0f;
    this->acc_n_ = 0;
    this->heat_stall_since_ms_ = 0;
  }

  this->history_[this->history_idx_] = t;
  this->history_idx_ = (this->history_idx_ + 1) % N_HISTORY;
  if (this->history_count_ < N_HISTORY)
    this->history_count_++;

  // --- heater stall ------------------------------------------------------
  // Judged on the duty already commanded, so it covers every path out of
  // update() including the hard temperature limits below.
  if (this->heater_duty_ >= 0.9f) {
    if (this->heat_stall_since_ms_ == 0) {
      this->heat_stall_since_ms_ = now;
      this->heat_stall_temp_ = t;
    } else if (now - this->heat_stall_since_ms_ > HEAT_STALL_MS) {
      const bool rose = (t - this->heat_stall_temp_) >= HEAT_STALL_RISE;
      if (!rose && !this->heater_stalled_)
        ESP_LOGE(TAG, "Heater at full for %" PRIu32 " min with no rise (%.2f degF) - heater may be dead",
                 HEAT_STALL_MS / 60000, (t - this->heat_stall_temp_) * 9.0f / 5.0f);
      this->heater_stalled_ = !rose;
      this->heat_stall_since_ms_ = now;
      this->heat_stall_temp_ = t;
    }
  } else {
    this->heat_stall_since_ms_ = 0;
    this->heater_stalled_ = false;
  }

  if (this->safety_tripped_) {
    ESP_LOGI(TAG, "Temperature probe is back");
    this->safety_tripped_ = false;
    this->integral_ = 0.0f;
  }

  float lux_norm = 0.0f;
  if (this->lux_sensor_ != nullptr && !std::isnan(this->lux_sensor_->state))
    lux_norm = clampf(this->lux_sensor_->state / this->full_scale_lux_, 0.0f, 1.5f);
  this->update_light_profile_(lux_norm);

  // --- accumulate averages for the next learning step -------------------
  this->acc_heater_ += this->heater_duty_;
  this->acc_fan_ += this->fan_duty_;
  this->acc_light_ += lux_norm;
  this->acc_temp_ += t;
  this->acc_n_++;

  if (std::isnan(this->learn_anchor_temp_)) {
    this->learn_anchor_temp_ = t;
    this->learn_anchor_ms_ = now;
    this->acc_heater_ = this->acc_fan_ = this->acc_light_ = this->acc_temp_ = 0.0f;
    this->acc_n_ = 0;
  } else if (now - this->learn_anchor_ms_ >= LEARN_WINDOW_MS && this->acc_n_ > 0) {
    const float window_min = (now - this->learn_anchor_ms_) / 60000.0f;
    const float rate = (t - this->learn_anchor_temp_) / window_min;
    this->drift_rate_ = rate;
    this->acc_heater_ /= this->acc_n_;
    this->acc_fan_ /= this->acc_n_;
    this->acc_light_ /= this->acc_n_;
    this->acc_temp_ /= this->acc_n_;
    if (this->learning_enabled_)
      this->learn_(window_min, rate);
    this->learn_anchor_temp_ = t;
    this->learn_anchor_ms_ = now;
    this->acc_heater_ = this->acc_fan_ = this->acc_light_ = this->acc_temp_ = 0.0f;
    this->acc_n_ = 0;
  }

  // --- hard safety limits ------------------------------------------------
  if (t >= this->max_temp_) {
    this->state_text_ = "over temperature";
    this->integral_ = 0.0f;
    this->apply_outputs_(0.0f, 1.0f);
    return;
  }
  if (t <= this->min_temp_) {
    this->state_text_ = "under temperature";
    this->integral_ = 0.0f;
    this->apply_outputs_(1.0f, 0.0f);
    return;
  }

  // --- predictive control ------------------------------------------------
  const float kh = this->model_.theta[0];
  const float kf = -this->model_.theta[1];

  // Look ahead by roughly one response time: this is what makes the heater
  // back off *before* the lights come on rather than after the tank warms.
  this->predicted_light_ = this->predicted_light_for_((int) this->response_time_);

  // What the tank will do on its own, with no heater and no fan.
  const float passive_raw = this->model_.theta[2] * (t - TEMP_REF) +
                            this->model_.theta[3] * this->predicted_light_ + this->model_.theta[4];

  // Weight the feedforward by how much the model has actually learned.
  //
  // Until RLS has data, `passive_raw` is a guess about an ambient
  // temperature nobody measured -- and it is routinely several times
  // larger than the error term, so it decides the output on its own. Both
  // directions of that guess have already misfired here: an equilibrium
  // set too high refused to heat a cold tank, and one set too low called
  // for heat while the tank sat above target.
  //
  // At zero confidence this collapses to plain feedback on the measured
  // error, which cannot be wrong about the sign. The prediction phases in
  // over roughly a day as the model earns it.
  const float trust = clampf(this->get_confidence() / 100.0f, 0.0f, 1.0f);
  const float passive = passive_raw * trust;

  const float error = this->setpoint_ - t;

  // Aim to close the error over response_time_ minutes, capped so a big step
  // change doesn't demand a thermally impossible ramp.
  float desired = clampf(error / this->response_time_, -0.15f, 0.15f);

  // Integral term: mops up whatever the model still gets wrong. Sized so a
  // 1 degC error saturates it in roughly one response time -- the old
  // 1/(4*rt^2) took about three hours, far too slow to rescue a bad prior.
  const float ki = 1.0f / (this->response_time_ * this->response_time_);
  this->integral_ += error * dt_min * ki;
  // Bound the integral by the actuator authority it can command, not by a
  // fixed rate. This is what caused the overshoot: at the old flat
  // +/-0.05 degC/min and a learned kh of 0.032, the integral ALONE was
  // worth 158% heater duty. Once saturated it held the heater at 100%
  // until the measured error alone could outweigh it, which took 3.6 degF
  // of overshoot -- and that is what the tank did, running 39 minutes at
  // full power from 75.8 F to 77.8 F against a 76.0 F setpoint.
  //
  // Capped at 30% duty the integral can still mop up a steady-state
  // offset the model gets wrong, which is its job, but it can no longer
  // outvote the measurement. Scaled by kh so it tracks the learned heater
  // rather than assuming one.
  const float i_max = INTEGRAL_AUTHORITY * (kh > 1e-4f ? kh : THETA_PRIOR[0]);
  this->integral_ = clampf(this->integral_, -i_max, i_max);

  const float net = desired + this->integral_ - passive;

  float heater = 0.0f, fan = 0.0f;
  if (net > 0.0f) {
    heater = kh > 1e-4f ? net / kh : 0.0f;
    this->state_text_ = heater > 0.99f ? "heating (full)" : "heating";
  } else if (net < 0.0f) {
    if (this->fan_available_ && kf > 1e-4f) {
      fan = -net / kf;
      this->state_text_ = "cooling";
    } else {
      this->state_text_ = "coasting";
    }
  } else {
    this->state_text_ = "holding";
  }

  // Sign guard. The feedforward is a model; the error is a measurement.
  // When the two disagree about which direction the tank needs to move,
  // the measurement wins -- nothing legitimate asks for heat while the
  // water is already above target, or for cooling while it is below.
  //
  // This is the piece the tank's own history actually justifies: with the
  // integral saturated, the controller ran 39 minutes at 100% duty from
  // 75.8 F up to 77.8 F against a 76.0 F setpoint. The integral clamp
  // above is the root fix; this is the backstop that cannot be wrong
  // about the sign whatever the model does. The deadband leaves the
  // genuinely useful case -- pre-empting the lights near setpoint --
  // fully intact.
  if (error < -GUARD_DEADBAND && heater > 0.0f) {
    ESP_LOGW(TAG, "Sign guard: model asked for %.0f%% heat at %.2f degF above setpoint", heater * 100.0f,
             -error * 9.0f / 5.0f);
    heater = 0.0f;
    this->state_text_ = "coasting (overruled)";
  } else if (error > GUARD_DEADBAND && fan > 0.0f) {
    ESP_LOGW(TAG, "Sign guard: model asked for %.0f%% cooling at %.2f degF below setpoint", fan * 100.0f,
             error * 9.0f / 5.0f);
    fan = 0.0f;
    this->state_text_ = "coasting (overruled)";
  }

  // Anti-windup: if we're pinned at an actuator limit, stop integrating.
  if ((heater >= 1.0f && error > 0.0f) || (fan >= 1.0f && error < 0.0f))
    this->integral_ -= error * dt_min * ki;

  this->apply_outputs_(heater, fan);

  // Where the model says we'll be in 15 minutes at this output level.
  // Uses the unweighted prediction: this is the model's honest forecast,
  // not the trust-limited term the controller acts on.
  const float rate_now =
      kh * this->heater_duty_ + this->model_.theta[1] * this->fan_duty_ + passive_raw;
  this->predicted_temp_ = t + rate_now * 15.0f;

  if (now - this->last_save_ms_ > SAVE_INTERVAL_MS) {
    this->save_state_();
    this->last_save_ms_ = now;
  }
}

float TankController::get_swing() const {
  // Ten minutes of data before this number means anything at all.
  if (this->history_count_ < 20)
    return NAN;
  float lo = this->history_[0], hi = this->history_[0];
  for (uint8_t i = 1; i < this->history_count_; i++) {
    const float v = this->history_[i];
    if (v < lo)
      lo = v;
    if (v > hi)
      hi = v;
  }
  return hi - lo;
}

float TankController::get_time_constant() const {
  const float ka = -this->model_.theta[2];
  return ka > 1e-4f ? 1.0f / ka : NAN;  // minutes
}

float TankController::get_confidence() const {
  // Two full learning windows per 10 minutes of data; call it settled after
  // roughly a day of observations.
  const float target = (24.0f * 60.0f) / (LEARN_WINDOW_MS / 60000.0f);
  return clampf(100.0f * this->model_.updates / target, 0.0f, 100.0f);
}

void TankController::dump_config() {
  ESP_LOGCONFIG(TAG, "Tank Controller:");
  ESP_LOGCONFIG(TAG, "  Setpoint: %.1f degF (limits %.1f - %.1f)", this->setpoint_ * 9.0f / 5.0f + 32.0f,
                this->min_temp_ * 9.0f / 5.0f + 32.0f, this->max_temp_ * 9.0f / 5.0f + 32.0f);
  ESP_LOGCONFIG(TAG, "  Response time: %.0f min", this->response_time_);
  ESP_LOGCONFIG(TAG, "  Fan available: %s", YESNO(this->fan_available_));
  ESP_LOGCONFIG(TAG, "  Learning: %s (%" PRIu32 " steps, %.0f%% confidence)", ONOFF(this->learning_enabled_),
                this->model_.updates, this->get_confidence());
  ESP_LOGCONFIG(TAG, "  Model: kh=%.4f kf=%.4f ka=%.4f kl=%.4f c=%.4f", this->model_.theta[0], -this->model_.theta[1],
                -this->model_.theta[2], this->model_.theta[3], this->model_.theta[4]);
}

}  // namespace tank_controller
}  // namespace esphome
