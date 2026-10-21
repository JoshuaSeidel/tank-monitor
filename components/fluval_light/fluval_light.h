#pragma once

#include "esphome/core/component.h"
#include "esphome/core/automation.h"
#include "esphome/components/ble_client/ble_client.h"
#include "esphome/components/text_sensor/text_sensor.h"
#include "esphome/components/sensor/sensor.h"
#include "esphome/components/binary_sensor/binary_sensor.h"

#ifdef USE_TIME
#include "esphome/components/time/real_time_clock.h"
#endif

#include <vector>
#include <string>

namespace esphome {
namespace fluval_light {

// ---------------------------------------------------------------------
// The Fluval Plant 4.0's BLE protocol, as implemented by fluvalble
// ---------------------------------------------------------------------
// Product 545, family "plant_current" -- the FFF0/SPP variant. Two frame
// shapes go to the same write characteristic:
//
//   COMMANDS   0xD1 + a tiny CBOR map, integer keys:
//                 1  mode      uint   0 manual / 1 auto / 2 professional
//                 2  power     bool
//                 3-7 channels uint 0-100, one per emitter
//                 8  sunrise   bstr3  h, m, ramp-minutes
//                 9  sunset    bstr3  h, m, ramp-minutes
//                 10 sleep     bstr2  h, m   (FF FF = none)
//                 11 day lvls  bstr5  0-100 per channel
//                 12 night     bstr5
//                 13 PRO       bstr   count, then count x (h, m, L1..L5)
//
//   CLOCK      0xCD + YY MM DD W hh mm ss, raw -- NOT CBOR-wrapped, and
//              not a key in the map. W is 1=Monday..7=Sunday, matching
//              FluvalConnect's TimeUtil.getWeeks().
//
// The fixture stores the Pro schedule and runs it off its own RTC. That
// is the whole point of this component: push once, and the light keeps
// its day through a Home Assistant reboot, a broker outage, or this
// board being unplugged. Nothing here is in the daily control path.
//
// Source: github.com/MrMooreUK/fluvalble, custom_components/fluvalble/
// core/protocol.py. Read it before changing any constant below.

static const uint8_t SPP_COMMAND_HEADER = 0xD1;
static const uint8_t SPP_STATUS_HEADER = 0xD2;
// Asking the fixture to describe itself. The 0xD2 state frame that comes
// back carries every key it holds -- including 11/12 (day and night
// levels) and 13 (the stored Pro schedule), which is how the real channel
// order gets read off the lamp instead of guessed.
static const uint8_t SPP_READ_PARAMS[2] = {0xD0, 0xFF};
static const uint8_t MESH_OPCODE_CLOCK = 0xCD;

static const uint8_t KEY_MODE = 1;
static const uint8_t KEY_POWER = 2;
// Channels are keys 3..7, one uint 0-100 per emitter, in the same order a
// Pro schedule record lists them. Writing them directly is the only way to
// find out which physical emitter each one drives: the fixture documents
// neither the order nor the colours, and a Pro readback only ever echoes
// what we wrote.
static const uint8_t KEY_CHANNEL_FIRST = 3;
static const uint8_t KEY_PRO_SCHEDULE = 13;

static const uint8_t MODE_MANUAL = 0;
static const uint8_t MODE_AUTO = 1;
static const uint8_t MODE_PRO = 2;

// The fixture accepts 4..12 Pro points. Fewer than 4 is rejected; more
// than 12 overruns its table. daylight::pick_minutes() is told 12 and
// doubles its step until the day fits.
static const uint8_t PRO_MIN_POINTS = 4;
static const uint8_t PRO_MAX_POINTS = 12;

class FluvalLight : public PollingComponent, public ble_client::BLEClientNode {
 public:
  void setup() override;
  void update() override;
  void dump_config() override;
  void loop() override;
  float get_setup_priority() const override { return setup_priority::AFTER_BLUETOOTH; }

  void gattc_event_handler(esp_gattc_cb_event_t event, esp_gatt_if_t gattc_if,
                           esp_ble_gattc_cb_param_t *param) override;

  // --- configuration ---------------------------------------------------
  void set_latitude(double v) { this->lat_ = v; }
  void set_longitude(double v) { this->lon_ = v; }
  void set_channel_count(uint8_t v) { this->channel_count_ = v; }
  void set_daylight_exponent(float v) { this->expo_ = v; }
  // Full-brightness level per channel, 0-100, at solar noon. The curve
  // scales every point against these.
  void set_channel_mix(const std::vector<uint8_t> &v) { this->mix_ = v; }
  // Cap on full-equivalent MINUTES per day. 0 = the natural day. This
  // scales brightness, never duration -- the lamp still runs dawn to
  // dusk, just dimmer, which is how the Chihiros does it too.
  void set_dose_cap_minutes(int v) { this->cap_min_ = v; }
  void set_curve_step(int v) { this->step_ = v; }
  void set_curve_edge_step(int v) { this->edge_ = v; }
  void set_push_hour(int v) { this->push_hour_ = v; }

#ifdef USE_TIME
  void set_time(time::RealTimeClock *t) { this->time_ = t; }
#endif

  void set_status_sensor(text_sensor::TextSensor *s) { this->status_sensor_ = s; }
  void set_curve_sensor(text_sensor::TextSensor *s) { this->curve_sensor_ = s; }
  void set_lamp_state_sensor(text_sensor::TextSensor *s) { this->lamp_state_sensor_ = s; }
  void set_points_sensor(sensor::Sensor *s) { this->points_sensor_ = s; }
  void set_dose_sensor(sensor::Sensor *s) { this->dose_sensor_ = s; }
  void set_connected_sensor(binary_sensor::BinarySensor *s) { this->connected_sensor_ = s; }

  // --- actions ---------------------------------------------------------
  // Each queues one frame; the queue drains a frame at a time in loop()
  // because the fixture drops writes that arrive back to back.
  void push_curve();
  void sync_clock();
  void set_mode(uint8_t mode);
  void set_power(bool on);
  // Drive the emitters directly, 0-100 each, and switch the lamp to Manual
  // so they are actually visible. Callable from a YAML lambda as
  // id(fluval)->set_channels({100, 0, 0, 0, 0}). NOT part of the daily
  // path: the schedule lives in the fixture and this is a bench tool.
  void set_channels(const std::vector<uint8_t> &levels);
  // Ask the lamp what it currently holds. The reply arrives as a notify.
  void read_params();

  bool is_connected() const { return this->char_handle_ != 0; }

 protected:
  bool write_frame_(const std::vector<uint8_t> &frame);
  void queue_(const std::vector<uint8_t> &frame, const char *what);
  void publish_status_(const std::string &s);

  // Tiny CBOR: maps up to 23 entries, uint and byte-string values only.
  // That is everything this protocol uses, and a general encoder would be
  // more code than the whole component.
  static void cbor_uint_(std::vector<uint8_t> &out, uint32_t v);
  static void cbor_bstr_(std::vector<uint8_t> &out, const std::vector<uint8_t> &b);
  static std::vector<uint8_t> spp_command_(const std::vector<std::pair<uint8_t, std::vector<uint8_t>>> &entries);

  std::vector<uint8_t> build_pro_schedule_();

  ble_client::BLEClientNode *node_{nullptr};
  uint16_t char_handle_{0};
  // fff1. Separate from the write characteristic: the fixture answers on
  // its own notify handle, and without registering for it the 0xD2 frames
  // never arrive at all -- which is how the first build could sit
  // "connected" and never once hear the lamp speak.
  uint16_t notify_handle_{0};

  double lat_{0}, lon_{0};
  uint8_t channel_count_{5};
  float expo_{0.5f};
  std::vector<uint8_t> mix_;
  int cap_min_{0};
  int step_{60};
  int edge_{30};
  int push_hour_{1};

#ifdef USE_TIME
  time::RealTimeClock *time_{nullptr};
#endif

  text_sensor::TextSensor *status_sensor_{nullptr};
  text_sensor::TextSensor *curve_sensor_{nullptr};
  text_sensor::TextSensor *lamp_state_sensor_{nullptr};
  sensor::Sensor *points_sensor_{nullptr};
  sensor::Sensor *dose_sensor_{nullptr};
  binary_sensor::BinarySensor *connected_sensor_{nullptr};

  std::vector<std::pair<std::vector<uint8_t>, std::string>> queue_frames_;
  uint32_t last_write_ms_{0};
  int last_push_day_{-1};
  // Cleared on every connect. update() retries the clock until it takes,
  // because the on-connect attempt usually beats SNTP to a valid time.
  bool clock_synced_{false};
};

template<typename... Ts> class PushCurveAction : public Action<Ts...> {
 public:
  explicit PushCurveAction(FluvalLight *p) : parent_(p) {}
  void play(const Ts &...x) override { this->parent_->push_curve(); }

 protected:
  FluvalLight *parent_;
};

template<typename... Ts> class SyncClockAction : public Action<Ts...> {
 public:
  explicit SyncClockAction(FluvalLight *p) : parent_(p) {}
  void play(const Ts &...x) override { this->parent_->sync_clock(); }

 protected:
  FluvalLight *parent_;
};

template<typename... Ts> class SetModeAction : public Action<Ts...> {
 public:
  explicit SetModeAction(FluvalLight *p) : parent_(p) {}
  // uint8_t, not int: the declared type here must match the type the Python
  // codegen gives the generated lambda, or ESPHome warns that the return
  // type does not match and the templated value goes through a deprecated
  // conversion. Mode is a 0..2 enum, so uint8_t is also what it should have
  // been on the merits -- __init__.py passes cg.uint8 to match.
  TEMPLATABLE_VALUE(uint8_t, mode)
  void play(const Ts &...x) override { this->parent_->set_mode(this->mode_.value(x...)); }

 protected:
  FluvalLight *parent_;
};

}  // namespace fluval_light
}  // namespace esphome
