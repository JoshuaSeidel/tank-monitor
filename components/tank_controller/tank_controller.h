#pragma once

#include "esphome/core/component.h"
#include "esphome/core/automation.h"
#include "esphome/core/preferences.h"
#include "esphome/components/sensor/sensor.h"
#include "esphome/components/output/float_output.h"

#ifdef USE_TIME
#include "esphome/core/time.h"
#include "esphome/components/time/real_time_clock.h"
#endif

namespace esphome {
namespace tank_controller {

// One hour of temperature history at the 30s control interval. Used to
// report how much the tank is actually swinging, which is the thing this
// controller exists to minimise.
static const uint8_t N_HISTORY = 120;

// Number of parameters in the thermal model:
//   dT/dt = kh*H - kf*F - ka*(T - TREF) + kl*L + c        [degC per minute]
// estimated as theta = [kh, -kf, -ka, kl, c]
static const uint8_t N_PARAMS = 5;

// Light profile resolution: 96 slots of 15 minutes covers one day.
static const uint8_t N_SLOTS = 96;

// Reference temperature the ambient term is measured against. It is a
// centring constant, and the value matters far more than it looks.
//
// The regressors are [heater, fan, (T - TEMP_REF), light, 1]. With
// TEMP_REF = 20 and a tank living at 24.1 +/- 0.2 C, the third regressor
// was 4.1 +/- 0.2 -- a large mean with a tiny variance, sitting next to a
// literal constant. Those two columns are then almost perfectly collinear,
// and RLS cannot separate ka from c: only their combination is identified,
// and how it splits between them is decided by noise.
//
// The numbers say it is not close. The identifiable signal for ka is its
// coefficient times the variation in T -- 0.015 * 0.2 = 0.003 degC/min --
// against a quantisation floor of one DS18B20 LSB over a 5 minute window,
// 0.0125 degC/min. The information is four times smaller than one bit of
// the sensor. That is why Tank Time Constant wandered 206 -> 366 -> 93
// minutes across a day: it was not learning, it was random-walking, with c
// absorbing whatever ka did.
//
// Centring on the operating point makes (T - TEMP_REF) about 0.1 +/- 0.2 --
// small, zero-mean, and no longer a near-duplicate of the constant column.
// c then carries the well-identified equilibrium term cleanly, and ka
// degrades to a small correction on deviations, which is all the data can
// support.
//
// The old comment here argued for 20 C on the grounds that an untrained
// model must assume the tank loses heat -- setting it to 25 once predicted
// a 22.6 C tank would warm on its own and held the heater at 0%. That
// reasoning was right and the fix is kept, but it belongs in the prior, not
// the centring: THETA_PRIOR[4] now carries the cooling assumption
// (-0.030 degC/min, the ~3.3 degF/h this tank sheds unaided). The sign of
// the untrained prediction is therefore unchanged, and it is doubly
// covered now that the feedforward is gated by confidence AND health, both
// of which are zero on an untrained model.
static const float TEMP_REF = 24.0f;

struct ThermalModel {
  // theta[0] = kh   heater gain, degC/min at 100% duty        (>0)
  // theta[1] = -kf  fan gain, degC/min at 100% duty           (<0)
  // theta[2] = -ka  passive loss per degC above ambient       (<0)
  // theta[3] = kl   light gain, degC/min at full scale lux    (>=0)
  // theta[4] = c    constant drift                            (any)
  float theta[N_PARAMS];
  // Upper triangle of the RLS covariance, stored dense for simplicity.
  float p[N_PARAMS][N_PARAMS];
  uint32_t updates;
};

struct LightProfile {
  // Exponentially-averaged normalised illuminance per 15-minute slot.
  float slot[N_SLOTS];
  // How much evidence each slot has seen; slots below 1 are untrusted.
  float weight[N_SLOTS];
};

class TankController : public PollingComponent {
 public:
  void setup() override;
  void update() override;
  void dump_config() override;
  float get_setup_priority() const override { return setup_priority::LATE; }

  void set_temperature_sensor(sensor::Sensor *s) { this->temp_sensor_ = s; }
  void set_illuminance_sensor(sensor::Sensor *s) { this->lux_sensor_ = s; }
  void set_heater(output::FloatOutput *o) { this->heater_ = o; }
  void set_fan(output::FloatOutput *o) { this->fan_ = o; }
#ifdef USE_TIME
  void set_time(time::RealTimeClock *t) { this->time_ = t; }
#endif

  void set_setpoint(float v);
  float get_setpoint() const { return this->setpoint_; }
  void set_min_temperature(float v) { this->min_temp_ = v; }
  void set_max_temperature(float v) { this->max_temp_ = v; }
  void set_full_scale_lux(float v) { this->full_scale_lux_ = v; }
  void set_response_time(float minutes) { this->response_time_ = minutes; }
  void set_learning_enabled(bool v) { this->learning_enabled_ = v; }
  bool get_learning_enabled() const { return this->learning_enabled_; }
  void set_fan_available(bool v) { this->fan_available_ = v; }

  // --- Values published to Home Assistant -------------------------------
  float get_heater_duty() const { return this->heater_duty_ * 100.0f; }
  float get_fan_duty() const { return this->fan_duty_ * 100.0f; }
  float get_drift_rate() const { return this->drift_rate_; }
  float get_heater_gain() const { return this->model_.theta[0]; }
  float get_fan_gain() const { return -this->model_.theta[1]; }
  float get_loss_coefficient() const { return -this->model_.theta[2]; }
  float get_light_gain() const { return this->model_.theta[3]; }
  float get_time_constant() const;
  float get_confidence() const;
  // 1.0 = predictions match the tank, 0.0 = persistently wrong. Scales the
  // confidence above, so a model that stops describing the tank loses its
  // authority instead of keeping it forever.
  float get_model_health() const;
  // Running bias of the model's own predictions, degC/min. Positive means
  // the tank is warmer than the model keeps saying it will be. Diagnostic
  // only -- it does not gate anything.
  float get_model_bias() const { return this->bias_; }
  float get_predicted_temperature() const { return this->predicted_temp_; }
  float get_predicted_light_load() const { return this->predicted_light_; }
  bool is_safety_tripped() const { return this->safety_tripped_; }
  // Heater commanded near full for a long stretch with no temperature
  // response: unplugged, failed, or a dead relay channel.
  bool is_heater_stalled() const { return this->heater_stalled_; }
  // Same check for the fan. Weaker evidence than the heater's -- the tank
  // cools on its own, so this only catches a fan that is failing while the
  // water is going the WRONG way. A merely feeble fan will not trip it;
  // watch get_fan_gain() for that.
  bool is_fan_stalled() const { return this->fan_stalled_; }
  // Peak-to-peak temperature swing over the last hour, in degC.
  // NAN until there is enough history to mean anything.
  float get_swing() const;
  const char *get_state_text() const { return this->state_text_; }

  // Wipe the learned model and light profile back to priors.
  void reset_learning();

  /// Adopt a thermal model measured by another controller on the same tank.
  ///
  /// Arguments are in the units the diagnostic sensors publish -- degF per
  /// hour for the gains, minutes for the time constant, percent for
  /// confidence -- so a migration can be driven straight from what the
  /// old device already reports, with no unit maths at the call site.
  void import_model(float heater_f_per_h, float fan_f_per_h, float light_f_per_h, float bias_f_per_h,
                    float time_constant_min, float confidence_pct);

 protected:
  void apply_outputs_(float heater, float fan);
  void learn_(float dt_min, float measured_rate);
  void update_light_profile_(float lux_norm);
  float predicted_light_for_(int minutes_ahead) const;
  int current_slot_(int minutes_ahead = 0) const;
  void clamp_model_();
  void load_prior_();
  void save_state_();

  sensor::Sensor *temp_sensor_{nullptr};
  sensor::Sensor *lux_sensor_{nullptr};
  output::FloatOutput *heater_{nullptr};
  output::FloatOutput *fan_{nullptr};
#ifdef USE_TIME
  time::RealTimeClock *time_{nullptr};
#endif

  ThermalModel model_{};
  LightProfile light_{};
  ESPPreferenceObject model_pref_;
  ESPPreferenceObject light_pref_;
  ESPPreferenceObject setpoint_pref_;

  float setpoint_{25.0f};
  float min_temp_{20.0f};
  float max_temp_{30.0f};
  float full_scale_lux_{2000.0f};
  float response_time_{20.0f};
  bool learning_enabled_{true};
  bool fan_available_{true};

  float heater_duty_{0.0f};
  float fan_duty_{0.0f};
  float integral_{0.0f};
  float drift_rate_{0.0f};
  float predicted_temp_{NAN};
  float predicted_light_{0.0f};
  // Exponentially-averaged residual from learn_(). Published as a
  // diagnostic; not persisted, and not part of the control path.
  float bias_{0.0f};
  // Slow EMA of the same residual, used to gate control authority. Separate
  // from bias_ because that one is tuned for a dashboard, not for deciding
  // how much to believe the model.
  float stale_{0.0f};

  // Learning is done over a slow window: a DS18B20 quantises to 0.0625 degC,
  // which swamps the real drift rate if you differentiate every control tick.
  float learn_anchor_temp_{NAN};
  uint32_t learn_anchor_ms_{0};
  float acc_heater_{0.0f};
  float acc_fan_{0.0f};
  float acc_light_{0.0f};
  float acc_temp_{0.0f};
  uint32_t acc_n_{0};

  float history_[N_HISTORY];
  uint8_t history_idx_{0};
  uint8_t history_count_{0};

  // Wall-clock of the last valid reading, so a gap can be detected and the
  // windows spanning it thrown away rather than learned from.
  uint32_t last_valid_ms_{0};

  // Which 15-minute slot the light profile last saw, so its confidence
  // counts days observed rather than samples taken.
  int16_t last_light_slot_{-1};

  // Heater-stall detection.
  uint32_t heat_stall_since_ms_{0};
  float heat_stall_temp_{NAN};
  bool heater_stalled_{false};

  // Fan-stall detection, same shape.
  uint32_t fan_stall_since_ms_{0};
  float fan_stall_temp_{NAN};
  bool fan_stalled_{false};

  float last_temp_{NAN};
  uint32_t last_update_ms_{0};
  uint32_t missing_since_ms_{0};
  uint32_t last_save_ms_{0};
  bool safety_tripped_{false};
  const char *state_text_{"starting"};
};

template<typename... Ts> class ResetLearningAction : public Action<Ts...> {
 public:
  explicit ResetLearningAction(TankController *parent) : parent_(parent) {}
  void play(const Ts &...x) override { this->parent_->reset_learning(); }

 protected:
  TankController *parent_;
};

template<typename... Ts> class SetSetpointAction : public Action<Ts...> {
 public:
  explicit SetSetpointAction(TankController *parent) : parent_(parent) {}
  TEMPLATABLE_VALUE(float, value)
  void play(const Ts &...x) override { this->parent_->set_setpoint(this->value_.value(x...)); }

 protected:
  TankController *parent_;
};

template<typename... Ts> class SetLearningAction : public Action<Ts...> {
 public:
  explicit SetLearningAction(TankController *parent) : parent_(parent) {}
  TEMPLATABLE_VALUE(bool, value)
  void play(const Ts &...x) override { this->parent_->set_learning_enabled(this->value_.value(x...)); }

 protected:
  TankController *parent_;
};

template<typename... Ts> class ImportModelAction : public Action<Ts...> {
 public:
  explicit ImportModelAction(TankController *parent) : parent_(parent) {}
  TEMPLATABLE_VALUE(float, heater)
  TEMPLATABLE_VALUE(float, fan)
  TEMPLATABLE_VALUE(float, light)
  TEMPLATABLE_VALUE(float, bias)
  TEMPLATABLE_VALUE(float, tc)
  TEMPLATABLE_VALUE(float, confidence)
  void play(const Ts &...x) override {
    this->parent_->import_model(this->heater_.value(x...), this->fan_.value(x...), this->light_.value(x...),
                                this->bias_.value(x...), this->tc_.value(x...), this->confidence_.value(x...));
  }

 protected:
  TankController *parent_;
};

}  // namespace tank_controller
}  // namespace esphome
