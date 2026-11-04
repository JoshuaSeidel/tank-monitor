#pragma once

#include "esphome/core/component.h"
#include "esphome/core/preferences.h"
#include "esphome/components/sensor/sensor.h"
#include "esphome/components/time/real_time_clock.h"
#include "esphome/components/web_server_base/web_server_base.h"

#include <string>
#include <vector>

namespace esphome {
namespace tank_history {

/// History and the water-test log for a tank with no Home Assistant.
///
/// Each series is sampled every update_interval and averaged into the
/// current wall-clock slot of two rings: 5 min x 288 (24 h) and 1 h x 720
/// (30 days). Values are int16 of value * scale; INT16_MIN is "no data".
/// The slot is the epoch divided by the step, so a ring index is a time and
/// a gap (power off, no clock) stays a visible gap rather than closing up.
class TankHistory : public PollingComponent, public AsyncWebHandler {
 public:
  void set_base(web_server_base::WebServerBase *base) { this->base_ = base; }
  void set_time(time::RealTimeClock *clock) { this->time_ = clock; }
  void add_series(const char *key, sensor::Sensor *sens, float scale);

  void setup() override;
  void update() override;
  void on_shutdown() override;
  void dump_config() override;
  float get_setup_priority() const override { return setup_priority::LATE; }

  bool canHandle(AsyncWebServerRequest *request) const override;
  void handleRequest(AsyncWebServerRequest *request) override;

  /// The newest water test as one BLE-sized line for the panel:
  /// "C,<epoch>,<ph>,<nh3>,<no2>,<no3>,<gh>,<kh>", -999 for not tested.
  std::string chem_frame() const;

  /// The water-test log as a JSON array, newest first (for /tests.json and
  /// the settings backup).
  std::string tests_json_array() const;
  /// Merge one test from a backup: added unless a test at that exact time
  /// is already kept. NAN = not tested. Call save_tests() after a batch.
  bool import_test(uint32_t t, float ph, float nh3, float no2, float no3, float gh, float kh);
  void save_tests() { this->save_tests_(); }

  static const int16_t MISSING = INT16_MIN;

 protected:
  struct Series {
    const char *key;
    sensor::Sensor *sensor;
    float scale;
  };

  // A ring of means. data is [series][slot % slots]. last_slot is the slot
  // being accumulated now; its mean is only written to data when the slot
  // closes (or on save, as a partial).
  struct Ring {
    uint32_t step;
    uint32_t slots;
    uint32_t last_slot{0};
    std::vector<int16_t> data;
    std::vector<double> sum;
    std::vector<uint32_t> count;
    ESPPreferenceObject pref;
  };

  // One manual water test. Values are fixed-point; MISSING = not tested.
  struct Test {
    uint32_t t;
    int16_t ph;   // x100
    int16_t nh3;  // x100 ppm
    int16_t no2;  // x100 ppm
    int16_t no3;  // x10 ppm
    int16_t gh;   // ppm
    int16_t kh;   // ppm
  };
  static const uint8_t MAX_TESTS = 40;
  struct TestLog {
    uint32_t magic;
    uint8_t count;
    Test tests[MAX_TESTS];  // newest first
  };

  void init_ring_(Ring &r, uint32_t step, uint32_t slots, uint32_t hash);
  void advance_(Ring &r, uint32_t slot);
  void commit_(Ring &r, bool reset);
  void save_ring_(Ring &r);
  bool load_ring_(Ring &r);
  int16_t pack_(float v, float scale) const;
  void history_json_(AsyncWebServerRequest *request, Ring &r);
  void tests_json_(AsyncWebServerRequest *request);
  void add_test_(AsyncWebServerRequest *request);
  void delete_test_(AsyncWebServerRequest *request);
  void save_tests_();
  uint32_t now_() const;

  web_server_base::WebServerBase *base_{nullptr};
  time::RealTimeClock *time_{nullptr};
  std::vector<Series> series_;
  Ring fast_;
  Ring slow_;
  TestLog log_{};
  ESPPreferenceObject log_pref_;
  uint32_t last_save_{0};
};

}  // namespace tank_history
}  // namespace esphome
