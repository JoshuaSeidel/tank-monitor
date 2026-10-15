#include "time_proportioning.h"
#include "esphome/core/log.h"

namespace esphome::time_proportioning {

static const char *const TAG = "time_proportioning";

void TimeProportioningOutput::setup() {
  this->pin_->setup();
  this->pin_->digital_write(false);
  this->on_ = false;
  this->last_ms_ = millis();
  // Neither floor applies to the first switch after boot.
  const uint32_t floor = this->min_on_ms_ > this->min_off_ms_ ? this->min_on_ms_ : this->min_off_ms_;
  this->switched_ms_ = this->last_ms_ - floor;
}

void TimeProportioningOutput::write_state(float state) {
  this->level_ = state < 0.0f ? 0.0f : (state > 1.0f ? 1.0f : state);
}

void TimeProportioningOutput::switch_(bool on, uint32_t now) {
  this->on_ = on;
  this->switched_ms_ = now;
  this->pin_->digital_write(on);
  ESP_LOGV(TAG, "Relay %s, credit %.1f s, level %.3f", ONOFF(on), this->get_credit_s(), this->level_);
  this->state_change_trigger_.trigger(on);
}

void TimeProportioningOutput::loop() {
  const uint32_t now = millis();
  const uint32_t dt = now - this->last_ms_;
  this->last_ms_ = now;

  // Commanded minus delivered over the interval just ended, at the state
  // the relay was in for it. Microseconds in an int64: a float credit near
  // its 225 s working range resolves 16 us, coarser than the ~10 us a
  // single loop at a few percent duty adds, and would drift.
  const float d = this->level_;
  this->credit_us_ += (int64_t) (d * (float) dt * 1000.0f + 0.5f);
  if (this->on_)
    this->credit_us_ -= (int64_t) dt * 1000;
  // Bounded already by the floors (a few tens of seconds past the band);
  // the clamp is only against a level held at 1 with min_off_time pending
  // forever, or a loop stalled for longer than a period.
  const int64_t cap = (int64_t) this->period_ms_ * 1000;
  if (this->credit_us_ > cap)
    this->credit_us_ = cap;
  if (this->credit_us_ < -cap)
    this->credit_us_ = -cap;

  const uint32_t held = now - this->switched_ms_;
  if (this->on_) {
    const int64_t band = (int64_t) ((float) this->period_ms_ * 1000.0f * d * (1.0f - d));
    const bool done = d <= 0.0f || (d < 1.0f && this->credit_us_ <= -band);
    if (done && held >= this->min_on_ms_)
      this->switch_(false, now);
  } else {
    const bool due = d >= 1.0f || (d > 0.0f && this->credit_us_ >= 0);
    if (due && held >= this->min_off_ms_)
      this->switch_(true, now);
  }
}

void TimeProportioningOutput::dump_config() {
  ESP_LOGCONFIG(TAG, "Time-proportioning output:");
  LOG_PIN("  Pin: ", this->pin_);
  ESP_LOGCONFIG(TAG,
                "  Period: %" PRIu32 " s\n"
                "  Minimum on / off: %" PRIu32 " s / %" PRIu32 " s",
                this->period_ms_ / 1000, this->min_on_ms_ / 1000, this->min_off_ms_ / 1000);
  LOG_FLOAT_OUTPUT(this);
}

}  // namespace esphome::time_proportioning
