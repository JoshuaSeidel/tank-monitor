#pragma once

#include "esphome/core/component.h"
#include "esphome/core/automation.h"
#include "esphome/core/preferences.h"
#include "esphome/components/sensor/sensor.h"
#include "esphome/components/binary_sensor/binary_sensor.h"
#include "esphome/components/output/float_output.h"
#include <cstdio>

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
//   dT/dt = kh*H - kf*F - ka*(T - T_ref) + kl*L + c        [degC per minute]
// estimated as theta = [kh, -kf, -ka, kl, c]
static const uint8_t N_PARAMS = 5;

// Light profile resolution: 96 slots of 15 minutes covers one day.
static const uint8_t N_SLOTS = 96;

// The reference temperature the loss term is measured against is no longer
// a constant. It is the model's own operating point, held in the model
// (ThermalModel::t_ref) and moved with it -- see tank_controller.cpp,
// "Where the model is centred", for the full argument. In short:
//
//   * no ambient sensor (every board today): T_ref is the active setpoint.
//     c is then exactly "the drift the tank shows at the temperature it is
//     held at", which is the one quantity the data measures every five
//     minutes, and ka is learned only from real excursions away from it.
//   * an ambient air probe configured and reporting: T_ref is the room.
//     (T - T_amb) then varies with the room's daily swing, which is what
//     finally makes ka identifiable, and c shrinks to the tank's own heat
//     (pumps, light ballast).
//
// Moving T_ref re-expresses c so the prediction does not step; see
// rebase_(). The model is persisted together with its T_ref, so a stored
// c is never read against the wrong reference.
//
// LEGACY_TEMP_REF is the fixed 24.0 C (75.2 degF) every model saved by
// firmware up to bbf4b6f was centred on. It exists for exactly one
// purpose: to read such a model out of flash (tank_model_v3) and re-centre
// it on first boot. Nothing else may use it. It is the constant that broke
// the 75 gal: a tank held ~1.9 degF above it with ~0.1 degF of swing makes
// (T - 24.0) a near-constant ~1.05, ka and c interchangeable, and the clamp
// on ka the place every correction went to die.
static const float LEGACY_TEMP_REF = 24.0f;

// Which temperature the model is currently centred on.
static const uint8_t REF_SETPOINT = 0;
static const uint8_t REF_AMBIENT = 1;

// What is over the water. Chooses the top surface's heat-loss band; see
// "What the tank's size says" in tank_controller.cpp. Values are persisted.
static const uint8_t COVER_OPEN_TOP = 0;
static const uint8_t COVER_LID = 1;
static const uint8_t COVER_EVAPORATION = 2;
static const uint8_t COVER_UNKNOWN = 3;
static const uint8_t N_COVERS = 4;
// What is around the tank. A closed stand puts a pocket of warm air between
// the tank and the room.
static const uint8_t PLACEMENT_ROOM = 0;
static const uint8_t PLACEMENT_CABINET = 1;
static const uint8_t N_PLACEMENTS = 2;

// The tank's physical description, as Home Assistant last set it (or the
// YAML defaults on the first boot that has none). Persisted on its own key,
// so the thermal model's layout is unchanged.
struct TankPhysics {
  float tank_gal;   // nominal volume, US gal; 0 = not set (no physics)
  float water_gal;  // actual water, US gal; 0 = FILL_DEFAULT of tank_gal
  float heater_w;   // total heater power at 100% duty, W; 0 = unknown
  uint8_t cover;
  uint8_t placement;
};

struct ThermalModel {
  // theta[0] = kh   heater gain, degC/min at 100% duty        (>0)
  // theta[1] = -kf  fan gain, degC/min at 100% duty           (<0)
  // theta[2] = -ka  passive loss per degC above T_ref         (<0)
  // theta[3] = kl   light gain, degC/min at full scale lux    (>=0)
  // theta[4] = c    drift at T_ref with nothing running       (any)
  float theta[N_PARAMS];
  // Upper triangle of the RLS covariance, stored dense for simplicity.
  float p[N_PARAMS][N_PARAMS];
  uint32_t updates;
  // The temperature theta[4] is expressed at, degC. NAN = not yet centred
  // (fresh prior): adopted as-is on the first tick, no re-expression.
  float t_ref;
  // REF_SETPOINT or REF_AMBIENT.
  uint8_t ref_mode;
};

// Layout of the model as firmware up to bbf4b6f saved it, under the key
// "tank_model_v3". Only read, once, to migrate; see setup().
struct ThermalModelV3 {
  float theta[N_PARAMS];
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
  // Optional second probe on its own bus. Never controlled on; only used
  // to veto the control probe when the two disagree.
  void set_cross_check_sensor(sensor::Sensor *s) { this->cross_sensor_ = s; }
  void set_illuminance_sensor(sensor::Sensor *s) { this->lux_sensor_ = s; }
  // Optional room-air probe. Never controlled on; when it is reporting, the
  // model's loss term is measured against it instead of the setpoint. See
  // "Where the model is centred" in tank_controller.cpp.
  void set_ambient_sensor(sensor::Sensor *s) { this->ambient_sensor_ = s; }
  // The heater and fan relays as switched (time_proportioning's
  // state_change_action). When given, the model learns from the fraction of
  // each window the contacts were actually closed, not from the duty it
  // asked for -- before components/time_proportioning the 75's differed by
  // 1.7x; see "Delivered, not commanded".
  void set_heater_relay(binary_sensor::BinarySensor *b) { this->heater_relay_ = b; }
  void set_fan_relay(binary_sensor::BinarySensor *b) { this->fan_relay_ = b; }
  // How long one room reading stays good with no newer one, minutes.
  void set_ambient_timeout(float minutes) { this->ambient_timeout_ms_ = (uint32_t) (minutes * 60000.0f); }
  // Short name of the room source for logs and the Model Reference entity.
  void set_ambient_source(const char *name) {
    this->ambient_source_ = name;
    snprintf(this->ambient_text_, sizeof(this->ambient_text_), "room: %s", name);
  }
  void set_heater(output::FloatOutput *o) { this->heater_ = o; }
  void set_fan(output::FloatOutput *o) { this->fan_ = o; }
#ifdef USE_TIME
  void set_time(time::RealTimeClock *t) { this->time_ = t; }
#endif

  void set_setpoint(float v);
  float get_setpoint() const { return this->setpoint_; }

  // --- Modes -------------------------------------------------------------
  // Hold: every output off, nothing learned, no fault judged, until
  // released. For a tank being filled or drained -- the probes are in
  // air, the heaters may be, and neither the loop nor its detectors
  // should conclude anything from that. Deliberately not persisted: a
  // reboot mid-fill comes up regulating, which is the side to err on.
  // Entry resets the learner's window, because what follows is new
  // water; release regulates at full authority immediately, because the
  // readings never stopped being checked.
  void set_hold(bool v);
  bool get_hold() const { return this->hold_; }
  // A target that stands in for the setpoint without touching it or its
  // persisted copy -- cycling a new tank warm, then back to the number the
  // owner actually set. Clamped to the cutouts like the setpoint. NAN
  // clears it. The loop regulates on get_active_setpoint(); the setpoint
  // entity keeps showing get_setpoint(), which is still the owner's value.
  void set_setpoint_override(float c);
  float get_active_setpoint() const {
    return std::isnan(this->setpoint_override_) ? this->setpoint_ : this->setpoint_override_;
  }
  // How far above setpoint the water must be before the fan may run, degC.
  // Persisted like the setpoint; the config value is the first-boot default.
  void set_fan_deadband(float v);
  float get_fan_deadband() const { return this->fan_deadband_; }
  // How far the two probes may differ before it counts as disagreement, degC.
  void set_disagreement_band(float v);
  float get_disagreement_band() const { return this->disagree_band_; }
  void set_min_temperature(float v) { this->min_temp_ = v; }
  void set_max_temperature(float v) { this->max_temp_ = v; }
  void set_full_scale_lux(float v) { this->full_scale_lux_ = v; }
  void set_response_time(float minutes) { this->response_time_ = minutes; }
  // Explicit ceiling on the learned passive time constant (1/ka), minutes.
  // Overrides the physics band's ceiling when one is configured; without one
  // it is the floor on ka as before (1000 min if never set).
  void set_max_time_constant(float minutes);

  // --- The tank's physics ---------------------------------------------------
  // YAML defaults, applied on the first boot that has nothing persisted.
  void set_physics_default(float tank_gal, float water_gal, float heater_w, uint8_t cover, uint8_t placement) {
    this->physics_ = {tank_gal, water_gal, heater_w, cover, placement};
  }
  // Runtime setters (Home Assistant). Each persists, recomputes the band,
  // resets the parameters it determines to their new physics prior with the
  // covariance re-opened, and re-expresses c so the forecast does not step.
  void set_tank_volume(float gal);
  void set_water_volume(float gal);
  void set_heater_power(float watts);
  void set_tank_cover(uint8_t cover);
  void set_tank_placement(uint8_t placement);
  float get_tank_volume() const { return this->physics_.tank_gal; }
  float get_water_volume() const { return this->physics_.water_gal; }
  float get_heater_power() const { return this->physics_.heater_w; }
  uint8_t get_tank_cover() const { return this->physics_.cover; }
  uint8_t get_tank_placement() const { return this->physics_.placement; }
  static const char *cover_text(uint8_t c);
  static const char *placement_text(uint8_t p);
  static uint8_t cover_from_text(const std::string &s);
  static uint8_t placement_from_text(const std::string &s);
  // The physics prior for Tank Time Constant, minutes (NAN without physics),
  // and the band it is allowed to move in, as text for Home Assistant.
  float get_expected_time_constant() const;
  const char *get_time_constant_band_text() const { return this->band_text_; }
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
  // The temperature the model is currently centred on, degC (setpoint, or
  // the room when an ambient probe is in use). NAN before the first tick.
  float get_reference_temperature() const { return this->model_.t_ref; }
  bool is_ambient_reference() const { return this->model_.ref_mode == REF_AMBIENT; }
  // "room: <source>" in ambient mode, otherwise which setpoint fallback.
  const char *get_reference_text() const;
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
  // Control and cross-check probes have disagreed for DISAGREE_MS; heater
  // is off until they agree again. Always false with no cross-check probe.
  bool is_probe_disagreement() const { return this->probe_disagreement_; }
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
  bool project_bounds_();
  void sync_reference_(uint32_t now, float water);
  void rebase_(float new_ref);
  bool ambient_usable_(uint32_t now, float water);
  float theta_prior_(uint8_t i) const;
  float p_prior_(uint8_t i) const;
  void set_ka_variance_(float target);
  void compute_band_();
  void apply_physics_(bool reset_ka, bool reset_kh, const char *why);
  void reset_param_(uint8_t i, float t_now, float u_now);
  void save_physics_();
  void update_centre_(float dev_avg, float window_min);
  uint64_t relay_on_ms_(bool heater, uint32_t now) const;
  float recent_fraction_(bool heater) const;
  float theta_min_(uint8_t i) const;
  void reset_learn_window_();
  float health_deadband_() const;
  float theta_max_(uint8_t i) const;
  void load_prior_();
  void save_state_();

  sensor::Sensor *temp_sensor_{nullptr};
  sensor::Sensor *cross_sensor_{nullptr};
  sensor::Sensor *lux_sensor_{nullptr};
  sensor::Sensor *ambient_sensor_{nullptr};
  binary_sensor::BinarySensor *heater_relay_{nullptr};
  binary_sensor::BinarySensor *fan_relay_{nullptr};
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
  ESPPreferenceObject fan_deadband_pref_;
  ESPPreferenceObject disagree_band_pref_;
  ESPPreferenceObject physics_pref_;

  float setpoint_{25.0f};
  // Overwritten from config before setup() and from flash during it; the
  // literal only matters if neither happens. 0.25 degF.
  float fan_deadband_{0.25f * 5.0f / 9.0f};
  // 2.0 degF: two uncalibrated DS18B20 (+/-0.5 degC each) can legitimately
  // sit 1.8 degF apart, so anything tighter false-trips until the
  // cross-check probe has been offset-calibrated in the same cup.
  float disagree_band_{2.0f * 5.0f / 9.0f};
  float min_temp_{20.0f};
  float max_temp_{30.0f};
  float full_scale_lux_{2000.0f};
  float response_time_{20.0f};
  // The explicit max_time_constant, minutes; NAN = not configured.
  float max_tc_override_{NAN};
  // The physics, and the band computed from it (compute_band_()). Without
  // physics these are the legacy values: ka floor 1/1000 min (or the
  // override), prior 15x the floor, legacy kh prior and bounds.
  TankPhysics physics_{0.0f, 0.0f, 0.0f, COVER_UNKNOWN, PLACEMENT_ROOM};
  bool physics_active_{false};
  bool physics_pending_{false};
  float ka_min_{0.001f};
  float ka_max_{0.2f};
  float ka_prior_{0.015f};
  float p_ka_{1e-4f};
  float kh_prior_{0.030f};
  float kh_min_{0.002f};
  float kh_max_{0.300f};
  float p_kh_{1e-3f};
  float p_kl_{1e-5f};
  char band_text_[48]{"not configured"};
  // Ambient mode only: the slow offset of the water above the room that the
  // loss term is centred on, so ka sees the room's movement, not its level.
  // See "Only excitation moves ka".
  float centre_off_{0.0f};
  bool centre_init_{false};
  // Delivered on-time bookkeeping, from the relay callbacks.
  uint64_t heater_on_acc_ms_{0};
  uint64_t fan_on_acc_ms_{0};
  uint32_t heater_on_since_ms_{0};
  uint32_t fan_on_since_ms_{0};
  bool heater_on_{false};
  bool fan_on_{false};
  uint64_t anchor_heater_on_ms_{0};
  uint64_t anchor_fan_on_ms_{0};
  // The last 15 minutes of delivered on-time, per tick, for the forecast.
  static const uint8_t N_RECENT = 30;
  uint16_t recent_heater_ms_[N_RECENT]{};
  uint16_t recent_fan_ms_[N_RECENT]{};
  uint16_t recent_dt_ms_[N_RECENT]{};
  uint8_t recent_idx_{0};
  uint8_t recent_n_{0};
  uint64_t last_heater_total_ms_{0};
  uint64_t last_fan_total_ms_{0};
  bool learning_enabled_{true};
  bool fan_available_{true};
  bool hold_{false};
  float setpoint_override_{NAN};

  float heater_duty_{0.0f};
  float fan_duty_{0.0f};
  float integral_{0.0f};
  // "One probe step cannot toggle the demand": the proportional term's
  // debounced temperature (NAN = take the next reading) and the latched
  // rules -- heat forbidden above setpoint, cooling below it, the fan
  // inside its deadband.
  float t_play_{NAN};
  bool heat_blocked_{false};
  bool cool_blocked_{false};
  bool fan_banded_{true};
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
  // EMA of the residual's spread about stale_, (degC/min)^2. The noise
  // floor health is judged against; see get_model_health(). Starts at the
  // quantisation floor rather than zero so a fresh boot is not hair-trigger.
  float resid_var_{0.0f};

  // Ambient probe bookkeeping: when it last delivered a reading, and since
  // when it has been continuously usable (0 = not usable now).
  uint32_t ambient_last_ms_{0};
  uint32_t ambient_ok_since_ms_{0};
  // Since when the room reading has sat on the water temperature.
  uint32_t ambient_close_since_ms_{0};
  // Low-passed room temperature the model reads, and when it was updated.
  float ambient_filt_{NAN};
  uint32_t ambient_filt_ms_{0};
  uint32_t ambient_timeout_ms_{600000};
  const char *ambient_source_{"room probe"};
  char ambient_text_[32]{"room: room probe"};

  // Learning is done over a slow window: a DS18B20 quantises to 0.0625 degC,
  // which swamps the real drift rate if you differentiate every control tick.
  float learn_anchor_temp_{NAN};
  // The cross-check probe's reading at the same anchor, NAN if it was not
  // usable then. Each probe's rate is taken against its OWN anchor, so the
  // fixed offset between two DS18B20s never appears as a rate.
  float learn_anchor_cross_{NAN};
  uint32_t learn_anchor_ms_{0};
  float acc_heater_{0.0f};
  float acc_fan_{0.0f};
  float acc_light_{0.0f};
  // Sum of (T - T_ref) over the window, the loss regressor. Accumulated as
  // a deviation, not as T, so a reference that moves mid-window (a setpoint
  // change, or the room in ambient mode) is accounted for exactly.
  float acc_dev_{0.0f};
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

  // Cross-check disagreement, and when the current reading was last
  // accepted without a recent predecessor (boot or after a gap).
  uint32_t disagree_since_ms_{0};
  bool probe_disagreement_{false};
  uint32_t reanchor_ms_{0};

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

template<typename... Ts> class SetFanDeadbandAction : public Action<Ts...> {
 public:
  explicit SetFanDeadbandAction(TankController *parent) : parent_(parent) {}
  TEMPLATABLE_VALUE(float, value)
  void play(const Ts &...x) override { this->parent_->set_fan_deadband(this->value_.value(x...)); }

 protected:
  TankController *parent_;
};

template<typename... Ts> class SetDisagreementBandAction : public Action<Ts...> {
 public:
  explicit SetDisagreementBandAction(TankController *parent) : parent_(parent) {}
  TEMPLATABLE_VALUE(float, value)
  void play(const Ts &...x) override { this->parent_->set_disagreement_band(this->value_.value(x...)); }

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
