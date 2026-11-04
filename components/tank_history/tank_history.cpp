#include "tank_history.h"
#include "esphome/core/hal.h"
#include "esphome/core/helpers.h"
#include "esphome/core/log.h"

#include <cmath>
#include <cstdlib>
#include <cstring>

namespace esphome {
namespace tank_history {

static const char *const TAG = "tank_history";

// Blob layout for a ring in flash. The hash the preference is keyed on
// includes the series count, so a firmware with a different set of series
// starts empty instead of reading the old layout as if it were the new one.
struct RingHeader {
  uint32_t magic;
  uint32_t step;
  uint32_t slots;
  uint32_t nseries;
  uint32_t last_slot;
};
static const uint32_t RING_MAGIC = 0x54484953;  // "THIS"
static const uint32_t LOG_MAGIC = 0x54484C47;   // "THLG"
// Half an hour between saves: at most that much history is lost to a power
// cut, and the NVS partition sees a few hundred KB a day, which it spreads
// over its pages -- decades of wear at that rate.
static const uint32_t SAVE_EVERY_S = 1800;

void TankHistory::add_series(const char *key, sensor::Sensor *sens, float scale) {
  this->series_.push_back(Series{key, sens, scale});
}

void TankHistory::init_ring_(Ring &r, uint32_t step, uint32_t slots, uint32_t hash) {
  const size_t n = this->series_.size();
  r.step = step;
  r.slots = slots;
  r.data.assign(n * slots, MISSING);
  r.sum.assign(n, 0.0);
  r.count.assign(n, 0);
  r.pref = global_preferences->make_preference(sizeof(RingHeader) + r.data.size() * sizeof(int16_t),
                                               hash ^ (uint32_t) n);
}

void TankHistory::setup() {
  this->init_ring_(this->fast_, 300, 288, fnv1_hash("tank_history_fast"));
  this->init_ring_(this->slow_, 3600, 720, fnv1_hash("tank_history_slow"));
  const bool fast_ok = this->load_ring_(this->fast_);
  const bool slow_ok = this->load_ring_(this->slow_);

  this->log_pref_ = global_preferences->make_preference<TestLog>(fnv1_hash("tank_history_tests"));
  if (!this->log_pref_.load(&this->log_) || this->log_.magic != LOG_MAGIC || this->log_.count > MAX_TESTS) {
    memset(&this->log_, 0, sizeof(this->log_));
    this->log_.magic = LOG_MAGIC;
  }
  ESP_LOGI(TAG, "Restored: 24h ring %s, 30d ring %s, %u water tests", fast_ok ? "yes" : "no",
           slow_ok ? "yes" : "no", this->log_.count);

  this->base_->add_handler(this);
}

bool TankHistory::load_ring_(Ring &r) {
  std::vector<uint8_t> buf(sizeof(RingHeader) + r.data.size() * sizeof(int16_t));
  if (!r.pref.load(buf.data(), buf.size()))
    return false;
  RingHeader h;
  memcpy(&h, buf.data(), sizeof(h));
  if (h.magic != RING_MAGIC || h.step != r.step || h.slots != r.slots || h.nseries != this->series_.size())
    return false;
  memcpy(r.data.data(), buf.data() + sizeof(h), r.data.size() * sizeof(int16_t));
  r.last_slot = h.last_slot;
  return true;
}

void TankHistory::save_ring_(Ring &r) {
  if (r.last_slot == 0)
    return;
  // The open slot goes in as a partial mean, so a reboot mid-slot keeps it.
  this->commit_(r, false);
  std::vector<uint8_t> buf(sizeof(RingHeader) + r.data.size() * sizeof(int16_t));
  const RingHeader h{RING_MAGIC, r.step, r.slots, (uint32_t) this->series_.size(), r.last_slot};
  memcpy(buf.data(), &h, sizeof(h));
  memcpy(buf.data() + sizeof(h), r.data.data(), r.data.size() * sizeof(int16_t));
  r.pref.save(buf.data(), buf.size());
}

uint32_t TankHistory::now_() const {
  if (this->time_ == nullptr)
    return 0;
  const auto t = this->time_->now();
  return t.is_valid() ? (uint32_t) t.timestamp : 0;
}

int16_t TankHistory::pack_(float v, float scale) const {
  if (std::isnan(v))
    return MISSING;
  const float x = roundf(v * scale);
  if (x > 32767.0f)
    return 32767;
  if (x < -32767.0f)
    return -32767;
  return (int16_t) x;
}

// Writes the mean of the open slot. A slot with no samples is left as it is:
// MISSING if it was cleared on entry, or the partial restored from flash.
void TankHistory::commit_(Ring &r, bool reset) {
  const size_t idx = r.last_slot % r.slots;
  for (size_t s = 0; s < this->series_.size(); s++) {
    if (r.count[s] > 0)
      r.data[s * r.slots + idx] = this->pack_((float) (r.sum[s] / r.count[s]), this->series_[s].scale);
    if (reset) {
      r.sum[s] = 0.0;
      r.count[s] = 0;
    }
  }
}

void TankHistory::advance_(Ring &r, uint32_t slot) {
  if (r.last_slot == 0) {
    r.last_slot = slot;
    return;
  }
  if (slot == r.last_slot)
    return;
  if (slot < r.last_slot) {
    // The clock went backwards (a bad SNTP answer, then a good one). Drop
    // what was being averaged and carry on from here.
    ESP_LOGW(TAG, "Clock moved back %u slots; restarting the open slot", (unsigned) (r.last_slot - slot));
    std::fill(r.sum.begin(), r.sum.end(), 0.0);
    std::fill(r.count.begin(), r.count.end(), 0);
    r.last_slot = slot;
    return;
  }
  this->commit_(r, true);
  // Every slot skipped -- and the new one -- is cleared: a ring index holds
  // its slot from one lap ago until then, and that must never read as now.
  const uint32_t clear = std::min(slot - r.last_slot, r.slots);
  for (uint32_t k = 1; k <= clear; k++) {
    const size_t idx = (r.last_slot + k) % r.slots;
    for (size_t s = 0; s < this->series_.size(); s++)
      r.data[s * r.slots + idx] = MISSING;
  }
  r.last_slot = slot;
}

void TankHistory::update() {
  const uint32_t now = this->now_();
  if (now == 0)
    return;  // No clock yet: a sample with no time cannot be placed.
  this->advance_(this->fast_, now / this->fast_.step);
  this->advance_(this->slow_, now / this->slow_.step);
  for (size_t s = 0; s < this->series_.size(); s++) {
    const float v = this->series_[s].sensor->state;
    if (std::isnan(v))
      continue;
    for (Ring *r : {&this->fast_, &this->slow_}) {
      r->sum[s] += v;
      r->count[s]++;
    }
  }
  if (this->last_save_ == 0) {
    this->last_save_ = now;
  } else if (now - this->last_save_ >= SAVE_EVERY_S) {
    this->save_ring_(this->fast_);
    this->save_ring_(this->slow_);
    global_preferences->sync();
    this->last_save_ = now;
  }
}

// OTA, the Restart button and a clean shutdown all come through here, so a
// planned reboot loses nothing.
void TankHistory::on_shutdown() {
  this->save_ring_(this->fast_);
  this->save_ring_(this->slow_);
  global_preferences->sync();
}

bool TankHistory::canHandle(AsyncWebServerRequest *request) const {
  char url_buf[AsyncWebServerRequest::URL_BUF_SIZE];
  const auto url = request->url_to(url_buf);
  if (request->method() == HTTP_GET)
    return url == "/history.json" || url == "/tests.json";
  if (request->method() == HTTP_POST)
    return url == "/tests" || url == "/tests/delete";
  return false;
}

void TankHistory::handleRequest(AsyncWebServerRequest *request) {
  char url_buf[AsyncWebServerRequest::URL_BUF_SIZE];
  const auto url = request->url_to(url_buf);
  if (url == "/history.json") {
    this->history_json_(request, request->arg("range") == "month" ? this->slow_ : this->fast_);
  } else if (url == "/tests.json") {
    this->tests_json_(request);
  } else if (url == "/tests") {
    this->add_test_(request);
  } else {
    this->delete_test_(request);
  }
}

static void append_fixed(std::string &out, int16_t v, float scale) {
  if (v == TankHistory::MISSING) {
    out += "null";
    return;
  }
  char b[16];
  snprintf(b, sizeof(b), "%g", v / scale);
  out += b;
}

void TankHistory::history_json_(AsyncWebServerRequest *request, Ring &r) {
  std::string out;
  out.reserve(64 + this->series_.size() * (40 + r.slots * 6));
  char b[96];
  snprintf(b, sizeof(b), "{\"now\":%u,\"step\":%u,\"slots\":%u,\"end\":%u,\"series\":{", (unsigned) this->now_(),
           (unsigned) r.step, (unsigned) r.slots, (unsigned) (r.last_slot * r.step));
  out += b;
  for (size_t s = 0; s < this->series_.size(); s++) {
    if (s > 0)
      out += ',';
    out += '"';
    out += this->series_[s].key;
    out += "\":[";
    // Oldest first. The newest point is the open slot's running mean, so
    // the chart reaches now rather than ending up to an hour ago.
    for (uint32_t i = 0; i < r.slots; i++) {
      if (i > 0)
        out += ',';
      if (r.last_slot == 0) {
        out += "null";
        continue;
      }
      const uint32_t slot = r.last_slot - (r.slots - 1) + i;
      int16_t v = r.data[s * r.slots + slot % r.slots];
      if (i == r.slots - 1 && r.count[s] > 0)
        v = this->pack_((float) (r.sum[s] / r.count[s]), this->series_[s].scale);
      append_fixed(out, v, this->series_[s].scale);
    }
    out += ']';
  }
  out += "}}";
  auto *resp = request->beginResponse(200, "application/json", out);
  resp->addHeader("Cache-Control", "no-store");
  request->send(resp);
}

void TankHistory::tests_json_(AsyncWebServerRequest *request) {
  std::string out;
  out.reserve(64 + this->log_.count * 90);
  char b[48];
  snprintf(b, sizeof(b), "{\"now\":%u,\"tests\":[", (unsigned) this->now_());
  out += b;
  for (uint8_t i = 0; i < this->log_.count; i++) {
    const Test &t = this->log_.tests[i];
    if (i > 0)
      out += ',';
    snprintf(b, sizeof(b), "{\"t\":%u,\"ph\":", (unsigned) t.t);
    out += b;
    append_fixed(out, t.ph, 100.0f);
    out += ",\"nh3\":";
    append_fixed(out, t.nh3, 100.0f);
    out += ",\"no2\":";
    append_fixed(out, t.no2, 100.0f);
    out += ",\"no3\":";
    append_fixed(out, t.no3, 10.0f);
    out += ",\"gh\":";
    append_fixed(out, t.gh, 1.0f);
    out += ",\"kh\":";
    append_fixed(out, t.kh, 1.0f);
    out += '}';
  }
  out += "]}";
  auto *resp = request->beginResponse(200, "application/json", out);
  resp->addHeader("Cache-Control", "no-store");
  request->send(resp);
}

// Blank or absent = not tested. Out of range is refused outright rather than
// clamped: a typo stored as a plausible number is worse than no number.
static bool parse_field(AsyncWebServerRequest *request, const char *name, float lo, float hi, float scale,
                        int16_t &out, bool &any, bool &bad) {
  out = TankHistory::MISSING;
  if (!request->hasArg(name))
    return true;
  const std::string s = request->arg(name);
  if (s.empty())
    return true;
  char *end = nullptr;
  const float v = strtof(s.c_str(), &end);
  if (end == s.c_str() || *end != '\0' || std::isnan(v) || v < lo || v > hi) {
    bad = true;
    return false;
  }
  out = (int16_t) roundf(v * scale);
  any = true;
  return true;
}

void TankHistory::add_test_(AsyncWebServerRequest *request) {
  Test t{};
  bool any = false, bad = false;
  parse_field(request, "ph", 0.0f, 14.0f, 100.0f, t.ph, any, bad);
  parse_field(request, "nh3", 0.0f, 20.0f, 100.0f, t.nh3, any, bad);
  parse_field(request, "no2", 0.0f, 20.0f, 100.0f, t.no2, any, bad);
  parse_field(request, "no3", 0.0f, 500.0f, 10.0f, t.no3, any, bad);
  parse_field(request, "gh", 0.0f, 1000.0f, 1.0f, t.gh, any, bad);
  parse_field(request, "kh", 0.0f, 1000.0f, 1.0f, t.kh, any, bad);
  if (bad) {
    request->send(400, "text/plain", "A value is out of range or not a number.");
    return;
  }
  if (!any) {
    request->send(400, "text/plain", "Enter at least one result.");
    return;
  }
  const uint32_t now = this->now_();
  // An optional t backdates a test done earlier. Not in the future, and not
  // more than 30 days back: older than that is not a reading to act on.
  t.t = now;
  if (request->hasArg("t") && !request->arg("t").empty()) {
    const uint32_t when = (uint32_t) strtoul(request->arg("t").c_str(), nullptr, 10);
    if (now == 0 || when > now + 300 || when + 30u * 86400u < now) {
      request->send(400, "text/plain", "That date is in the future or more than 30 days ago.");
      return;
    }
    t.t = when;
  }
  if (t.t == 0) {
    request->send(503, "text/plain", "The device has no clock yet. Check Wi-Fi and try again.");
    return;
  }
  // Newest first, by test time, so a backdated test lands in its place.
  uint8_t pos = 0;
  while (pos < this->log_.count && this->log_.tests[pos].t > t.t)
    pos++;
  if (pos >= MAX_TESTS) {
    request->send(400, "text/plain", "Older than every test kept.");
    return;
  }
  const uint8_t keep = std::min<uint8_t>(this->log_.count, MAX_TESTS - 1);
  for (int i = keep; i > pos; i--)
    this->log_.tests[i] = this->log_.tests[i - 1];
  this->log_.tests[pos] = t;
  this->log_.count = keep + 1;
  this->save_tests_();
  ESP_LOGI(TAG, "Water test logged at %u (%u kept)", (unsigned) t.t, this->log_.count);
  request->send(200, "text/plain", "OK");
}

void TankHistory::delete_test_(AsyncWebServerRequest *request) {
  const uint32_t when = (uint32_t) strtoul(request->arg("t").c_str(), nullptr, 10);
  for (uint8_t i = 0; i < this->log_.count; i++) {
    if (this->log_.tests[i].t != when)
      continue;
    for (uint8_t j = i; j + 1 < this->log_.count; j++)
      this->log_.tests[j] = this->log_.tests[j + 1];
    this->log_.count--;
    this->save_tests_();
    ESP_LOGI(TAG, "Water test %u deleted", (unsigned) when);
    request->send(200, "text/plain", "OK");
    return;
  }
  request->send(404, "text/plain", "No test at that time.");
}

// Saved at once, not on the half-hour: a test typed in and lost to a power
// cut a minute later would have to be done again.
void TankHistory::save_tests_() {
  this->log_pref_.save(&this->log_);
  global_preferences->sync();
}

std::string TankHistory::chem_frame() const {
  if (this->log_.count == 0)
    return "C,0,-999,-999,-999,-999,-999,-999";
  const Test &t = this->log_.tests[0];
  auto f = [](int16_t v, float scale) { return v == MISSING ? -999.0f : v / scale; };
  char b[96];
  snprintf(b, sizeof(b), "C,%u,%.2f,%.2f,%.2f,%.1f,%.0f,%.0f", (unsigned) t.t, f(t.ph, 100.0f), f(t.nh3, 100.0f),
           f(t.no2, 100.0f), f(t.no3, 10.0f), f(t.gh, 1.0f), f(t.kh, 1.0f));
  return b;
}

void TankHistory::dump_config() {
  ESP_LOGCONFIG(TAG, "Tank History:");
  ESP_LOGCONFIG(TAG, "  %u series; 24 h at 5 min, 30 d at 1 h; saved every %u s", (unsigned) this->series_.size(),
                (unsigned) SAVE_EVERY_S);
  for (const auto &s : this->series_)
    ESP_LOGCONFIG(TAG, "  - %s (x%g)", s.key, s.scale);
  ESP_LOGCONFIG(TAG, "  Water tests kept: %u of %u", this->log_.count, MAX_TESTS);
}

}  // namespace tank_history
}  // namespace esphome
