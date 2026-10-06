#pragma once

#include "esphome/core/component.h"
#include "esphome/core/defines.h"
#include "esphome/core/preferences.h"

#include <string>

namespace esphome {
namespace crash_report {

// See __init__.py. Keeps the last crash -- reason, where the main loop was
// stuck, and the backtrace -- across the reboot and across power cuts, as two
// short strings a template text sensor can publish.
class CrashReport : public Component {
 public:
  void setup() override;
  void dump_config() override;
  // Early, so the record is captured before anything else can crash the
  // board again, and before the text sensors first read it.
  float get_setup_priority() const override { return setup_priority::BUS; }

  // "none recorded" until a crash has been seen. Each fits Home Assistant's
  // 255-character state limit.
  std::string summary() const;
  std::string backtrace() const;
  // Crashes recorded since the last clear.
  uint32_t count() const { return this->store_.count; }
  // True if the crash was detected on THIS boot.
  bool fresh() const { return this->fresh_; }
  void clear();

 protected:
  struct Store {
    uint32_t count;
    char summary[200];
    char backtrace[240];
  };

  static void on_log_(void *self, uint8_t level, const char *tag, const char *message, size_t len);
  void capture_line_(const char *message, size_t len);
  void save_();

  Store store_{};
  ESPPreferenceObject pref_;
  bool capturing_{false};
  bool fresh_{false};
  // Built while ESPHome's crash handler prints its record.
  std::string cap_reason_;
  std::string cap_addrs_;
};

}  // namespace crash_report
}  // namespace esphome
