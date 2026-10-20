#include "fluval_light.h"
#include "daylight.h"
#include "esphome/core/log.h"
#include "esphome/core/hal.h"
#include <cstdio>

#ifdef USE_ESP32

namespace esphome {
namespace fluval_light {

static const char *const TAG = "fluval_light";

// The fixture drops a write that lands while it is still digesting the
// previous one, and says nothing about it. Everything is queued and drained
// one frame per this interval instead of written in a burst.
static const uint32_t WRITE_GAP_MS = 400;

void FluvalLight::setup() {
  if (this->connected_sensor_ != nullptr)
    this->connected_sensor_->publish_state(false);
  this->publish_status_("starting");
}

void FluvalLight::dump_config() {
  ESP_LOGCONFIG(TAG, "Fluval Light:");
  ESP_LOGCONFIG(TAG, "  Site: %.4f, %.4f", this->lat_, this->lon_);
  ESP_LOGCONFIG(TAG, "  Channels: %u", this->channel_count_);
  ESP_LOGCONFIG(TAG, "  Daylight exponent: %.2f", this->expo_);
  if (this->cap_min_ > 0) {
    ESP_LOGCONFIG(TAG, "  Dose cap: %d min (%.1f full-equivalent hours)", this->cap_min_, this->cap_min_ / 60.0f);
  } else {
    ESP_LOGCONFIG(TAG, "  Dose cap: none (natural day)");
  }
  ESP_LOGCONFIG(TAG, "  Curve steps: %d min, %d min near dawn/dusk", this->step_, this->edge_);
  ESP_LOGCONFIG(TAG, "  Nightly push at %02d:30", this->push_hour_);
  std::string mix;
  char buf[8];
  for (size_t i = 0; i < this->mix_.size(); i++) {
    snprintf(buf, sizeof(buf), "%s%u", i ? "/" : "", this->mix_[i]);
    mix += buf;
  }
  ESP_LOGCONFIG(TAG, "  Noon mix: %s", mix.c_str());
}

// ---------------------------------------------------------------------
// CBOR -- only what this protocol speaks
// ---------------------------------------------------------------------
void FluvalLight::cbor_uint_(std::vector<uint8_t> &out, uint32_t v) {
  if (v < 24) {
    out.push_back((uint8_t) v);
  } else if (v < 256) {
    out.push_back(0x18);
    out.push_back((uint8_t) v);
  } else {
    out.push_back(0x19);
    out.push_back((uint8_t) (v >> 8));
    out.push_back((uint8_t) (v & 0xFF));
  }
}

void FluvalLight::cbor_bstr_(std::vector<uint8_t> &out, const std::vector<uint8_t> &b) {
  if (b.size() < 24) {
    out.push_back(0x40 | (uint8_t) b.size());
  } else {
    out.push_back(0x58);
    out.push_back((uint8_t) b.size());
  }
  out.insert(out.end(), b.begin(), b.end());
}

std::vector<uint8_t> FluvalLight::spp_command_(const std::vector<std::pair<uint8_t, std::vector<uint8_t>>> &entries) {
  std::vector<uint8_t> out;
  out.push_back(SPP_COMMAND_HEADER);
  // 0xA0 | n is a CBOR map header and only reaches 23 entries. This
  // protocol never sends more than a handful, so the limit is academic --
  // but a silent truncation here would write a frame the lamp would
  // half-apply, so it is worth the branch.
  const size_t n = entries.size() > 23 ? 23 : entries.size();
  out.push_back(0xA0 | (uint8_t) n);
  for (size_t i = 0; i < n; i++) {
    cbor_uint_(out, entries[i].first);
    cbor_bstr_(out, entries[i].second);
  }
  return out;
}

// ---------------------------------------------------------------------
// The curve
// ---------------------------------------------------------------------
std::vector<uint8_t> FluvalLight::build_pro_schedule_() {
  std::vector<uint8_t> blob;
#ifdef USE_TIME
  if (this->time_ == nullptr) {
    ESP_LOGW(TAG, "No time source configured -- cannot build a curve");
    return blob;
  }
  auto now = this->time_->now();
  if (!now.is_valid()) {
    ESP_LOGW(TAG, "No valid time yet -- cannot build a curve");
    return blob;
  }

  // Local midnight as a UTC epoch -- the origin the solar model wants.
  //
  // Subtract the local time of day from the UTC timestamp. now.timestamp
  // is already UTC and now.hour/minute/second are local wall clock, so the
  // difference lands exactly on local midnight whatever the offset, and
  // follows DST without being told about it.
  //
  // The first version zeroed the h/m/s fields and called
  // recalc_timestamp_utc(), which read those local fields as if they were
  // UTC. That put the origin four hours early in EDT and the lamp ran a
  // day shifted four hours late -- dawn at 10:49, sunset at 22:13, the
  // tank dark all morning. The local g++ test never caught it because it
  // supplied local-midnight-as-UTC by hand and so never exercised this
  // conversion at all.
  const time_t mid = (time_t) now.timestamp - (now.hour * 3600 + now.minute * 60 + now.second);

  auto plan = tank_monitor::daylight::plan(mid, this->lat_, this->lon_, this->expo_, this->cap_min_, 0.70f);
  if (!plan.ok) {
    ESP_LOGW(TAG, "No usable day for %.4f,%.4f -- not pushing", this->lat_, this->lon_);
    return blob;
  }

  auto minutes = tank_monitor::daylight::pick_minutes(plan, this->step_, this->edge_, 120, PRO_MAX_POINTS);
  if (minutes.size() < PRO_MIN_POINTS) {
    ESP_LOGW(TAG, "Only %u curve points, fixture needs %u -- not pushing", (unsigned) minutes.size(), PRO_MIN_POINTS);
    return blob;
  }

  // ---------------------------------------------------------------------
  // The night has to be written down
  // ---------------------------------------------------------------------
  // pick_minutes() returns the LIT day, dawn to dusk, and a schedule made
  // only of those points never tells the fixture to go dark: it holds its
  // last point until the next one. A day ending "18:41 = 1%" therefore
  // leaves the tank glowing at 1% until dawn, which is what happened on
  // 2026-10-20 -- the 75 gal went dark on time and the nano sat dim all
  // evening on a curve that was otherwise correct.
  //
  // The fix costs no schedule slots. The first and last points ARE the
  // civil twilight boundaries and the model already puts them at 1%, so
  // pin those two to a hard zero instead of appending new ones. Darkness
  // then holds from dusk to dawn if the fixture holds its last point, and
  // interpolates 0 -> 0 across the night if it ramps between points --
  // unambiguous either way, which matters because which one it does is not
  // documented anywhere verifiable.
  //
  // Appending two extra dark points was the first attempt. It worked, but
  // reserving those slots pushed pick_minutes() past a decimation step and
  // the lit day fell from 12 points to 8, losing every point between 08:00
  // and 12:00. Not worth it for a minute of darkness either side.
  const size_t last_i = minutes.size() - 1;

  blob.push_back((uint8_t) minutes.size());
  std::string human;
  char buf[48];
  // Peak LEVELS, not the peak fraction. The percentages below are the
  // shape of the sun and are identical whatever channel_mix says, so a
  // curve string built from them alone cannot show that the mix changed --
  // and ESPHome skips republishing an unchanged string, so the entity sits
  // at its old timestamp and looks like the push never happened. That is
  // exactly how a mix change from 100 to 75 produced no visible evidence
  // either way. These are the numbers actually written to the fixture.
  std::vector<uint8_t> peak_levels(this->channel_count_, 0);
  for (int m : minutes) {
    const float f = tank_monitor::daylight::frac_at(plan, m);
    for (uint8_t c = 0; c < this->channel_count_; c++) {
      const uint8_t full = c < this->mix_.size() ? this->mix_[c] : 0;
      const int lvl = (int) lroundf(f * full);
      if (lvl > peak_levels[c])
        peak_levels[c] = (uint8_t) (lvl > 100 ? 100 : lvl);
    }
  }
  human += "peak ";
  for (uint8_t c = 0; c < this->channel_count_; c++) {
    snprintf(buf, sizeof(buf), "%s%u", c ? "/" : "", peak_levels[c]);
    human += buf;
  }
  human += " | ";

  for (size_t i = 0; i < minutes.size(); i++) {
    const int m = minutes[i];
    // The two boundary points are forced dark. Not frac_at() rounded down:
    // at civil twilight the model genuinely returns a fraction that rounds
    // to 1%, and 1% all night is the entire complaint.
    const bool dark = (i == 0 || i == last_i);
    const float frac = dark ? 0.0f : tank_monitor::daylight::frac_at(plan, m);
    blob.push_back((uint8_t) (m / 60));
    blob.push_back((uint8_t) (m % 60));
    for (uint8_t c = 0; c < this->channel_count_; c++) {
      const uint8_t full = c < this->mix_.size() ? this->mix_[c] : 0;
      int lvl = (int) lroundf(frac * full);
      if (lvl < 0)
        lvl = 0;
      if (lvl > 100)
        lvl = 100;
      blob.push_back((uint8_t) lvl);
    }
    snprintf(buf, sizeof(buf), "%02d:%02d=%.0f%% ", m / 60, m % 60, frac * 100.0f);
    human += buf;
  }

  // Printed so a repeat of the timezone bug is one line to spot: these are
  // LOCAL clock times, and they are what gets written to the lamp.
  ESP_LOGI(TAG, "Local midnight is UTC epoch %lld; it is now %02d:%02d local", (long long) mid, now.hour, now.minute);
  ESP_LOGI(TAG, "Day: dawn %02d:%02d rise %02d:%02d noon %02d:%02d set %02d:%02d dusk %02d:%02d", plan.d.dawn / 60,
           plan.d.dawn % 60, plan.d.rise / 60, plan.d.rise % 60, plan.d.noon / 60, plan.d.noon % 60, plan.d.set / 60,
           plan.d.set % 60, plan.d.dusk / 60, plan.d.dusk % 60);
  ESP_LOGI(TAG, "Curve: %u points, scale %.3f, %.2f full-equivalent hours", (unsigned) minutes.size(), plan.scale,
           plan.dose_h);
  // Printed on its own line because "is the tank actually dark at night" is
  // the one question the curve string above is read to answer.
  ESP_LOGI(TAG, "  dark from %02d:%02d until %02d:%02d (both boundary points pinned to 0%%)", minutes[last_i] / 60,
           minutes[last_i] % 60, minutes[0] / 60, minutes[0] % 60);
  {
    std::string mixs;
    char mb[8];
    for (uint8_t c = 0; c < this->channel_count_; c++) {
      snprintf(mb, sizeof(mb), "%s%u", c ? "/" : "", c < this->mix_.size() ? this->mix_[c] : 0);
      mixs += mb;
    }
    ESP_LOGI(TAG, "  noon mix %s -> peak levels in the line below", mixs.c_str());
  }
  ESP_LOGI(TAG, "  %s", human.c_str());

  if (this->curve_sensor_ != nullptr)
    this->curve_sensor_->publish_state(human);
  if (this->points_sensor_ != nullptr)
    this->points_sensor_->publish_state(minutes.size());
  if (this->dose_sensor_ != nullptr)
    this->dose_sensor_->publish_state(plan.dose_h);
#endif
  return blob;
}

// ---------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------
void FluvalLight::push_curve() {
  auto blob = this->build_pro_schedule_();
  if (blob.empty()) {
    // build_pro_schedule_() has already logged which of the three ways
    // it gave up: no time source, no valid time yet, or a latitude with
    // no usable day. Saying "curve not built" without that would send
    // someone hunting the BLE link for a clock problem.
    ESP_LOGW(TAG, "No curve to push");
    this->publish_status_("curve not built");
    return;
  }
  this->queue_(spp_command_({{KEY_PRO_SCHEDULE, blob}}), "pro schedule");
  // Professional mode is what RUNS a Pro schedule. Writing the points
  // and leaving the lamp in Auto stores a curve it will never use --
  // which looks exactly like a push that silently failed.
  std::vector<uint8_t> mode;
  cbor_uint_(mode, MODE_PRO);
  this->queue_({SPP_COMMAND_HEADER, 0xA1, KEY_MODE, mode[0]}, "mode=pro");
}

void FluvalLight::sync_clock() {
#ifdef USE_TIME
  if (this->time_ == nullptr) {
    ESP_LOGW(TAG, "No time source configured -- cannot sync the clock");
    return;
  }
  auto now = this->time_->now();
  if (!now.is_valid()) {
    // Not a failure, just early. BLE reaches the lamp about twenty
    // seconds after WiFi associates and SNTP is usually still in flight,
    // so the on-connect sync lands before there is a clock to send.
    // update() retries every 60 s until it takes. Said out loud because
    // the first build returned here in silence and the only symptom was
    // a board that said "connected" and then did nothing at all.
    ESP_LOGI(TAG, "Clock sync deferred: no valid time yet (SNTP still syncing)");
    this->publish_status_("waiting for time");
    return;
  }
  // 0xCD + YY MM DD W hh mm ss, raw. NOT a CBOR map -- the clock is the
  // one frame on this transport that is not 0xD1-wrapped, and sending it
  // wrapped is accepted and ignored.
  // ESPHome's day_of_week is 1=Sunday..7=Saturday; FluvalConnect wants
  // 1=Monday..7=Sunday.
  const uint8_t weekday = now.day_of_week == 1 ? 7 : (uint8_t) (now.day_of_week - 1);
  std::vector<uint8_t> f{MESH_OPCODE_CLOCK,
                         (uint8_t) (now.year % 100),
                         (uint8_t) now.month,
                         (uint8_t) now.day_of_month,
                         weekday,
                         (uint8_t) now.hour,
                         (uint8_t) now.minute,
                         (uint8_t) now.second};
  this->queue_(f, "clock");
  this->clock_synced_ = true;
#endif
}

void FluvalLight::set_mode(uint8_t mode) {
  std::vector<uint8_t> v;
  cbor_uint_(v, mode);
  this->queue_({SPP_COMMAND_HEADER, 0xA1, KEY_MODE, v[0]}, "mode");
}

void FluvalLight::read_params() {
  this->queue_({SPP_READ_PARAMS[0], SPP_READ_PARAMS[1]}, "read params");
}

void FluvalLight::set_power(bool on) {
  this->queue_({SPP_COMMAND_HEADER, 0xA1, KEY_POWER, (uint8_t) (on ? 0xF5 : 0xF4)}, "power");
}

// ---------------------------------------------------------------------
// Transport
// ---------------------------------------------------------------------
void FluvalLight::queue_(const std::vector<uint8_t> &frame, const char *what) {
  this->queue_frames_.emplace_back(frame, std::string(what));
  ESP_LOGD(TAG, "Queued %s (%u bytes), %u in queue", what, (unsigned) frame.size(),
           (unsigned) this->queue_frames_.size());
}

bool FluvalLight::write_frame_(const std::vector<uint8_t> &frame) {
  if (this->char_handle_ == 0 || this->parent() == nullptr)
    return false;
  auto status = esp_ble_gattc_write_char(this->parent()->get_gattc_if(), this->parent()->get_conn_id(),
                                         this->char_handle_, frame.size(), const_cast<uint8_t *>(frame.data()),
                                         ESP_GATT_WRITE_TYPE_NO_RSP, ESP_GATT_AUTH_REQ_NONE);
  if (status != ESP_OK) {
    ESP_LOGW(TAG, "Write failed, status %d", status);
    return false;
  }
  return true;
}

void FluvalLight::loop() {
  if (this->queue_frames_.empty())
    return;
  if (this->char_handle_ == 0)
    return;  // not connected yet; the queue waits rather than being dropped
  const uint32_t now = millis();
  if (now - this->last_write_ms_ < WRITE_GAP_MS)
    return;
  auto &item = this->queue_frames_.front();
  if (this->write_frame_(item.first)) {
    ESP_LOGI(TAG, "Sent %s", item.second.c_str());
    this->publish_status_(std::string("sent ") + item.second);
  } else {
    this->publish_status_(std::string("write failed: ") + item.second);
  }
  this->queue_frames_.erase(this->queue_frames_.begin());
  this->last_write_ms_ = now;
}

void FluvalLight::update() {
#ifdef USE_TIME
  if (this->time_ == nullptr)
    return;
  auto now = this->time_->now();
  if (!now.is_valid())
    return;

  // Catch the clock up once SNTP lands. The on-connect attempt usually
  // fires before there is a time to send, so without this the lamp keeps
  // whatever clock it had -- and a Pro schedule is only as good as the
  // clock running it.
  if (this->is_connected() && !this->clock_synced_) {
    ESP_LOGI(TAG, "Time is valid now -- syncing the clock");
    this->sync_clock();
  }

  // Push once a day, in the small hours, while the lamp is dark. A curve
  // that half-arrives mid-afternoon would be visible in the tank; one
  // that half-arrives at 01:30 is overwritten before anything is lit.
  if (now.hour == this->push_hour_ && now.minute >= 30 && now.day_of_year != this->last_push_day_) {
    this->last_push_day_ = now.day_of_year;
    ESP_LOGI(TAG, "Nightly push for day %d", now.day_of_year);
    this->sync_clock();
    this->push_curve();
  }
#endif
}

void FluvalLight::publish_status_(const std::string &s) {
  if (this->status_sensor_ != nullptr)
    this->status_sensor_->publish_state(s);
}

void FluvalLight::gattc_event_handler(esp_gattc_cb_event_t event, esp_gatt_if_t gattc_if,
                                      esp_ble_gattc_cb_param_t *param) {
  switch (event) {
    case ESP_GATTC_SEARCH_CMPL_EVT: {
      // fluvalble writes to 0000fff2 on the 0000fff0 service for every
      // current-controller fixture. Lowercase matters: esp-idf 5.x
      // compares characteristic UUIDs case-sensitively.
      auto *chr = this->parent()->get_characteristic(esp32_ble_tracker::ESPBTUUID::from_raw("0000fff0-0000-1000-8000-00805f9b34fb"),
                                                     esp32_ble_tracker::ESPBTUUID::from_raw("0000fff2-0000-1000-8000-00805f9b34fb"));
      if (chr == nullptr) {
        ESP_LOGE(TAG, "No fff2 characteristic -- is this a current-controller Fluval?");
        this->publish_status_("fff2 not found");
        break;
      }
      this->char_handle_ = chr->handle;

      // fff1 is where the fixture answers. Registering for it is not
      // optional bookkeeping: without it the stack never delivers a
      // notification and the 0xD2 state frames -- the only way to learn
      // this lamp's real channel order rather than guess it -- simply do
      // not arrive.
      auto *ntf = this->parent()->get_characteristic(
          esp32_ble_tracker::ESPBTUUID::from_raw("0000fff0-0000-1000-8000-00805f9b34fb"),
          esp32_ble_tracker::ESPBTUUID::from_raw("0000fff1-0000-1000-8000-00805f9b34fb"));
      if (ntf == nullptr) {
        ESP_LOGW(TAG, "No fff1 notify characteristic -- commands will still work, but the lamp cannot answer");
      } else {
        this->notify_handle_ = ntf->handle;
        auto status = esp_ble_gattc_register_for_notify(this->parent()->get_gattc_if(),
                                                        this->parent()->get_remote_bda(), ntf->handle);
        if (status != ESP_OK) {
          ESP_LOGW(TAG, "register_for_notify failed, status %d", status);
        } else {
          ESP_LOGI(TAG, "Listening on fff1, handle 0x%04x", this->notify_handle_);
        }
      }

      ESP_LOGI(TAG, "Connected, write handle 0x%04x", this->char_handle_);
      if (this->connected_sensor_ != nullptr)
        this->connected_sensor_->publish_state(true);
      this->publish_status_("connected");
      // The lamp's clock drifts, and a Pro schedule is only as good as the
      // clock running it. Sync on every connect; it costs one frame. This
      // often fires before SNTP has landed, in which case it defers and
      // update() picks it up within the minute.
      this->clock_synced_ = false;
      this->sync_clock();
      // And ask it to describe itself, so the first thing in the log after
      // a connect is the lamp's own account of what it is holding.
      this->read_params();
      break;
    }
    case ESP_GATTC_DISCONNECT_EVT: {
      this->char_handle_ = 0;
      if (this->connected_sensor_ != nullptr)
        this->connected_sensor_->publish_state(false);
      this->publish_status_("disconnected");
      break;
    }
    case ESP_GATTC_NOTIFY_EVT: {
      // 0xD2 frames are the fixture's own state. Logged rather than
      // parsed for now: the point of first connect is to see what this
      // light actually reports back, and guessing at the decode before
      // seeing real bytes is how a readback ends up confirming itself.
      if (param->notify.value_len > 0) {
        std::string hex;
        char b[4];
        for (uint16_t i = 0; i < param->notify.value_len && i < 64; i++) {
          snprintf(b, sizeof(b), "%02x", param->notify.value[i]);
          hex += b;
        }
        ESP_LOGI(TAG, "Lamp says (%u bytes): %s", (unsigned) param->notify.value_len, hex.c_str());
        // Two sensors on purpose. Every frame lands on Status, which is
        // useful for "did anything just happen" -- but the lamp answers a
        // mode write with four bytes (d2a10102 = map, key 1 mode, value 2
        // professional), and that short ack was overwriting the long reply
        // to the params request before anyone could read it.
        //
        // So the long frames get their own entity and short acks cannot
        // clobber them. Eight bytes is comfortably above every ack seen so
        // far and far below a real state dump carrying keys 11, 12 and 13.
        if (param->notify.value[0] == SPP_STATUS_HEADER) {
          this->publish_status_(std::string("lamp: ") + hex.substr(0, 120));
          if (param->notify.value_len > 8 && this->lamp_state_sensor_ != nullptr)
            this->lamp_state_sensor_->publish_state(hex);
        }
      }
      break;
    }
    default:
      break;
  }
}

}  // namespace fluval_light
}  // namespace esphome

#endif  // USE_ESP32
