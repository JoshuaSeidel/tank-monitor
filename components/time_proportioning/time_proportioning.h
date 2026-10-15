#pragma once

#include "esphome/core/automation.h"
#include "esphome/core/component.h"
#include "esphome/core/hal.h"
#include "esphome/components/output/float_output.h"

namespace esphome::time_proportioning {

// Drives a relay so that the time it is closed equals the commanded level
// times the time elapsed -- whatever the level does in between.
//
// Why not slow_pwm. slow_pwm closes the contacts for the first level*period
// of each fixed window. Constant level, exact. But the controller's level is
// not constant: near setpoint a DS18B20 that flips one 0.1125 degF step
// moves it, sometimes through zero, and the 75's board restarted the window
// on every new call for heat (so a demand arriving mid-window would not wait
// out the rest of it). Each restart grants a fresh level*period, so a demand
// toggling 49%/0 delivered far more than its average: over 17 days the 75's
// relays were closed 21.7% of the time against 12.7% commanded (1.7x).
// Heater Output lied, the tank overshot, and anything learning from the
// commanded duty learned a heater 1.7x too strong. Without the restart the
// bias goes but the latency comes back, and a level that changes mid-window
// is still delivered according to where in the window it changed.
//
// The rule. A credit, in microseconds, accumulates level*dt and pays out dt
// while the relay is closed -- it is commanded minus delivered on-time,
// carried across every window boundary and every change of level; nothing
// ever restarts. The relay closes when the credit is no longer in debt and
// opens once it is period*d*(1-d) in debt. At a steady level d that is one
// cycle per period, closed d*period and open (1-d)*period: slow_pwm's
// cycle, free-running. A new call for heat closes the relay at once unless
// heat is already owed back, and the time it then stays open is exactly the
// debt.
//
// Relay life. min_on_time / min_off_time are floors on each run. A run they
// stretch or delay is accounted in the credit like any other, so they cost
// timing resolution, never energy: |commanded - delivered| stays bounded by
// a few minutes' worth however long the board runs. Level 0 opens the relay
// (after min_on_time) and level 1 closes it (after min_off_time) whatever
// the credit says: the controller cutting heat for safety, or asking for
// all of it, is obeyed at once. Credit left over is still carried.
class TimeProportioningOutput : public output::FloatOutput, public Component {
 public:
  void set_pin(GPIOPin *pin) { this->pin_ = pin; }
  void set_period(uint32_t ms) { this->period_ms_ = ms; }
  void set_min_on_time(uint32_t ms) { this->min_on_ms_ = ms; }
  void set_min_off_time(uint32_t ms) { this->min_off_ms_ = ms; }
  Trigger<bool> *get_state_change_trigger() { return &this->state_change_trigger_; }

  bool is_on() const { return this->on_; }
  float get_level() const { return this->level_; }
  // Commanded minus delivered on-time so far, seconds. Positive = owed.
  float get_credit_s() const { return (float) this->credit_us_ / 1e6f; }

  void setup() override;
  void loop() override;
  void dump_config() override;
  float get_setup_priority() const override { return setup_priority::HARDWARE; }

 protected:
  void write_state(float state) override;
  void switch_(bool on, uint32_t now);

  GPIOPin *pin_{nullptr};
  Trigger<bool> state_change_trigger_;
  uint32_t period_ms_{900000};
  uint32_t min_on_ms_{30000};
  uint32_t min_off_ms_{30000};

  float level_{0.0f};
  bool on_{false};
  int64_t credit_us_{0};
  uint32_t last_ms_{0};
  uint32_t switched_ms_{0};
};

}  // namespace esphome::time_proportioning
