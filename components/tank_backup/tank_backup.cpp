#include "tank_backup.h"
#include "esphome/core/application.h"
#include "esphome/core/defines.h"
#include "esphome/core/log.h"
#include "esphome/components/json/json_util.h"

#include <esp_app_desc.h>
#include <esp_http_server.h>
#include <esp_image_format.h>
#include <esp_ota_ops.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <esp_rom_crc.h>

#include <sys/time.h>
#include <cmath>
#include <memory>

namespace esphome {
namespace tank_backup {

static const char *const TAG = "tank_backup";
// A backup is a few KB: every setting plus 40 tests. Anything far larger is
// not one of ours.
static const size_t MAX_BODY = 32 * 1024;
static void describe(JsonObject o, const esp_partition_t *p, bool running);

void TankBackup::setup() { this->base_->add_handler(this); }

bool TankBackup::canHandle(AsyncWebServerRequest *request) const {
  char url_buf[AsyncWebServerRequest::URL_BUF_SIZE];
  const auto url = request->url_to(url_buf);
  if (request->method() == HTTP_GET)
    return url == "/backup.json" || url == "/firmware/slots.json" || url == "/firmware/current.bin" ||
           url == "/peer.json";
  if (request->method() == HTTP_POST)
    return url == "/restore" || url == "/firmware/rollback";
  return false;
}

void TankBackup::handleBody(AsyncWebServerRequest *request, uint8_t *data, size_t len, size_t index, size_t total) {
  if (index == 0) {
    this->body_.clear();
    this->body_too_big_ = total > MAX_BODY;
    if (!this->body_too_big_)
      this->body_.reserve(total);
  }
  if (!this->body_too_big_)
    this->body_.append(reinterpret_cast<const char *>(data), len);
}

void TankBackup::handleRequest(AsyncWebServerRequest *request) {
  char url_buf[AsyncWebServerRequest::URL_BUF_SIZE];
  const auto url = request->url_to(url_buf);
  if (url == "/backup.json") {
    auto *resp = request->beginResponse(200, "application/json", this->backup_json_());
    resp->addHeader("Cache-Control", "no-store");
    resp->addHeader("Access-Control-Allow-Origin", "*");
    request->send(resp);
  } else if (url == "/peer.json") {
    std::string ip;
    uint32_t age = 0;
    {
      std::lock_guard<std::mutex> lock(this->peer_lock_);
      ip = this->panel_ip_;
      age = ip.empty() ? 0 : (millis() - this->panel_ip_ms_) / 1000;
    }
    char tail[40];
    snprintf(tail, sizeof(tail), "\",\"age_s\":%u}", (unsigned) age);
    std::string out = "{\"panel_ip\":\"" + ip + tail;
    auto *resp = request->beginResponse(200, "application/json", out);
    resp->addHeader("Cache-Control", "no-store");
    request->send(resp);
  } else if (url == "/restore") {
    this->restore_(request);
  } else if (url == "/firmware/slots.json") {
    this->slots_json_(request);
  } else if (url == "/firmware/rollback") {
    this->rollback_(request);
  } else {
    this->send_firmware_(request);
  }
}

// ---------------------------------------------------------------- backup

std::string TankBackup::backup_json_() {
  const esp_app_desc_t *app = esp_app_get_description();
  char sha[17];
  esp_app_get_elf_sha256(sha, sizeof(sha));
  const std::string tests = this->history_->tests_json_array();
  return json::build_json([&](JsonObject root) {
    root["format"] = 1;
    root["device"] = App.get_name().str();
    root["firmware"] = std::string(sha);
    root["built"] = std::string(app->date) + " " + app->time;
    root["uptime_s"] = millis() / 1000;

    JsonObject numbers = root["numbers"].to<JsonObject>();
    for (auto *n : App.get_numbers()) {
      if (!n->is_internal() && !std::isnan(n->state))
        numbers[n->get_name().str()] = n->state;
    }
    JsonObject selects = root["selects"].to<JsonObject>();
    for (auto *s : App.get_selects()) {
      if (!s->is_internal() && s->has_state())
        selects[s->get_name().str()] = s->current_option().str();
    }
#ifdef USE_DATETIME_TIME
    JsonObject times = root["times"].to<JsonObject>();
    for (auto *t : App.get_times()) {
      if (t->is_internal())
        continue;
      char hms[12];
      snprintf(hms, sizeof(hms), "%02d:%02d:%02d", t->hour, t->minute, t->second);
      times[t->get_name().str()] = std::string(hms);
    }
#endif
    JsonObject switches = root["switches"].to<JsonObject>();
    for (auto *s : this->switches_)
      switches[s->get_name().str()] = s->state;

    // The learned heat model in the units import_model() takes: degF/h for
    // the gains and bias, minutes, percent. A rebuilt controller starts from
    // this instead of from scratch.
    auto *c = this->controller_;
    JsonObject model = root["model"].to<JsonObject>();
    model["heater_f_per_h"] = c->get_heater_gain() * 60.0f * 9.0f / 5.0f;
    model["fan_f_per_h"] = c->get_fan_gain() * 60.0f * 9.0f / 5.0f;
    model["light_f_per_h"] = c->get_light_gain() * 60.0f * 9.0f / 5.0f;
    model["bias_f_per_h"] = c->get_model_bias() * 60.0f * 9.0f / 5.0f;
    model["time_constant_min"] = c->get_time_constant();
    model["confidence_pct"] = c->get_confidence();

    root["tests"] = serialized(tests);
  });
}

// --------------------------------------------------------------- restore

struct Restore {
  std::vector<std::pair<std::string, float>> numbers;
  std::vector<std::pair<std::string, std::string>> selects;
  std::vector<std::pair<std::string, std::string>> times;
  std::vector<std::pair<std::string, bool>> switches;
  bool model{false};
  float m[6]{};
  struct T {
    uint32_t t;
    float v[6];
  };
  std::vector<T> tests;
};

void TankBackup::restore_(AsyncWebServerRequest *request) {
  if (this->body_too_big_ || this->body_.empty()) {
    request->send(400, "text/plain", "Send the backup file as the request body.");
    return;
  }
  const bool want_settings = request->arg("settings") == "1";
  const bool want_model = request->arg("model") == "1";
  const bool want_tests = request->arg("tests") == "1";
  if (!want_settings && !want_model && !want_tests) {
    request->send(400, "text/plain", "Choose what to restore.");
    return;
  }

  auto r = std::make_shared<Restore>();
  bool format_ok = false;
  const bool parsed = json::parse_json(this->body_, [&](JsonObject root) -> bool {
    format_ok = root["format"] == 1;
    if (!format_ok)
      return false;
    if (want_settings) {
      JsonObject o_numbers = root["numbers"];
      for (JsonPair kv : o_numbers)
        r->numbers.emplace_back(kv.key().c_str(), kv.value().as<float>());
      JsonObject o_selects = root["selects"];
      for (JsonPair kv : o_selects)
        r->selects.emplace_back(kv.key().c_str(), kv.value().as<std::string>());
      JsonObject o_times = root["times"];
      for (JsonPair kv : o_times)
        r->times.emplace_back(kv.key().c_str(), kv.value().as<std::string>());
      JsonObject o_switches = root["switches"];
      for (JsonPair kv : o_switches)
        r->switches.emplace_back(kv.key().c_str(), kv.value().as<bool>());
    }
    if (want_model && root["model"].is<JsonObject>()) {
      JsonObject m = root["model"];
      const char *keys[6] = {"heater_f_per_h", "fan_f_per_h",       "light_f_per_h",
                             "bias_f_per_h",   "time_constant_min", "confidence_pct"};
      r->model = true;
      for (int i = 0; i < 6; i++) {
        if (!m[keys[i]].is<float>())
          r->model = false;
        r->m[i] = m[keys[i]].as<float>();
      }
    }
    if (want_tests) {
      const char *keys[6] = {"ph", "nh3", "no2", "no3", "gh", "kh"};
      JsonArray arr = root["tests"];
      for (JsonObject t : arr) {
        Restore::T x{t["t"].as<uint32_t>(), {}};
        for (int i = 0; i < 6; i++)
          x.v[i] = t[keys[i]].isNull() ? NAN : t[keys[i]].as<float>();
        r->tests.push_back(x);
      }
    }
    return true;
  });
  this->body_.clear();
  this->body_.shrink_to_fit();
  if (!parsed || !format_ok) {
    request->send(400, "text/plain", "That is not a tank backup this firmware can read.");
    return;
  }

  // Entities are only ever touched from the main loop.
  this->defer([this, r]() {
    int n = 0;
    for (auto &kv : r->numbers)
      for (auto *e : App.get_numbers())
        if (!e->is_internal() && e->get_name().str() == kv.first) {
          e->make_call().set_value(kv.second).perform();
          n++;
        }
    for (auto &kv : r->selects)
      for (auto *e : App.get_selects())
        if (!e->is_internal() && e->get_name().str() == kv.first) {
          e->make_call().set_option(kv.second).perform();
          n++;
        }
#ifdef USE_DATETIME_TIME
    for (auto &kv : r->times)
      for (auto *e : App.get_times())
        if (!e->is_internal() && e->get_name().str() == kv.first) {
          e->make_call().set_time(kv.second).perform();
          n++;
        }
#endif
    for (auto &kv : r->switches)
      for (auto *e : this->switches_)
        if (e->get_name().str() == kv.first) {
          if (kv.second)
            e->turn_on();
          else
            e->turn_off();
          n++;
        }
    if (r->model)
      this->controller_->import_model(r->m[0], r->m[1], r->m[2], r->m[3], r->m[4], r->m[5]);
    int added = 0;
    for (auto &t : r->tests)
      if (this->history_->import_test(t.t, t.v[0], t.v[1], t.v[2], t.v[3], t.v[4], t.v[5]))
        added++;
    if (added > 0)
      this->history_->save_tests();
    ESP_LOGI(TAG, "Restored %d settings%s, %d water tests", n, r->model ? ", the heat model" : "", added);
  });
  request->send(200, "text/plain", "Restoring.");
}

// -------------------------------------------------------------- firmware

static void describe(JsonObject o, const esp_partition_t *p, bool running) {
  esp_app_desc_t d;
  o["slot"] = p->label;
  o["running"] = running;
  if (esp_ota_get_partition_description(p, &d) != ESP_OK) {
    o["valid"] = false;
    return;
  }
  esp_ota_img_states_t st;
  const bool bad = esp_ota_get_state_partition(p, &st) == ESP_OK &&
                   (st == ESP_OTA_IMG_INVALID || st == ESP_OTA_IMG_ABORTED);
  char sha[17];
  for (int i = 0; i < 8; i++)
    snprintf(sha + i * 2, 3, "%02x", d.app_elf_sha256[i]);
  o["valid"] = !bad;
  o["firmware"] = std::string(sha);
  o["built"] = std::string(d.date) + " " + d.time;
  o["project"] = std::string(d.project_name);
  o["version"] = std::string(d.version);
}

void TankBackup::slots_json_(AsyncWebServerRequest *request) {
  const esp_partition_t *run = esp_ota_get_running_partition();
  const esp_partition_t *other = esp_ota_get_next_update_partition(run);
  const std::string out = json::build_json([&](JsonObject root) {
    describe(root["running"].to<JsonObject>(), run, true);
    if (other != nullptr)
      describe(root["previous"].to<JsonObject>(), other, false);
  });
  auto *resp = request->beginResponse(200, "application/json", out);
  resp->addHeader("Cache-Control", "no-store");
  resp->addHeader("Access-Control-Allow-Origin", "*");
  request->send(resp);
}

// Boots the build in the other slot -- the one this firmware replaced.
// esp_ota_set_boot_partition() checks the image before agreeing.
void TankBackup::rollback_(AsyncWebServerRequest *request) {
  const esp_partition_t *other = esp_ota_get_next_update_partition(nullptr);
  esp_app_desc_t d;
  if (other == nullptr || esp_ota_get_partition_description(other, &d) != ESP_OK) {
    request->send(409, "text/plain", "There is no previous firmware to go back to.");
    return;
  }
  const esp_err_t err = esp_ota_set_boot_partition(other);
  if (err != ESP_OK) {
    request->send(409, "text/plain", "The previous firmware failed its check; staying on this one.");
    return;
  }
  ESP_LOGW(TAG, "Rolling back to the firmware in %s (built %s %s)", other->label, d.date, d.time);
  request->send(200, "text/plain", "Restarting on the previous firmware.");
  this->defer([this]() { this->set_timeout(1500, []() { App.safe_reboot(); }); });
}

// The running image, exactly its own length, streamed from flash.
void TankBackup::send_firmware_(AsyncWebServerRequest *request) {
  const esp_partition_t *run = esp_ota_get_running_partition();
  esp_partition_pos_t pos{run->address, run->size};
  esp_image_metadata_t meta{};
  if (esp_image_verify(ESP_IMAGE_VERIFY_SILENT, &pos, &meta) != ESP_OK || meta.image_len == 0) {
    request->send(500, "text/plain", "Could not read the running firmware.");
    return;
  }
  char sha[17];
  esp_app_get_elf_sha256(sha, sizeof(sha));
  char disp[64];
  snprintf(disp, sizeof(disp), "attachment; filename=\"controller-%s.bin\"", sha);
  httpd_req_t *r = *request;
  httpd_resp_set_type(r, "application/octet-stream");
  httpd_resp_set_hdr(r, "Content-Disposition", disp);
  httpd_resp_set_hdr(r, "Access-Control-Allow-Origin", "*");
  std::unique_ptr<uint8_t[]> buf(new uint8_t[4096]);
  for (uint32_t off = 0; off < meta.image_len;) {
    const size_t n = std::min<uint32_t>(4096, meta.image_len - off);
    if (esp_partition_read(run, off, buf.get(), n) != ESP_OK ||
        httpd_resp_send_chunk(r, reinterpret_cast<const char *>(buf.get()), n) != ESP_OK)
      return;
    off += n;
  }
  httpd_resp_send_chunk(r, nullptr, 0);
}

// ------------------------------------------------------------ BLE transfer

void TankBackup::reply_(esp32_ble_server::BLECharacteristic *out, char kind, const std::string &text) {
  std::vector<uint8_t> p;
  p.reserve(1 + text.size());
  p.push_back((uint8_t) kind);
  p.insert(p.end(), text.begin(), text.end());
  out->set_value(std::move(p));
  out->notify();
}

void TankBackup::ble_request(const uint8_t *data, size_t len, esp32_ble_server::BLECharacteristic *out) {
  const std::string req(reinterpret_cast<const char *>(data), len);
  if (req.rfind("I,", 0) == 0) {
    // The panel's Wi-Fi address, so this page can link to its SD archive.
    const std::string ip = req.substr(2);
    if (ip.size() < 7 || ip.size() > 15 || ip.find_first_not_of("0123456789.") != std::string::npos)
      return;
    std::lock_guard<std::mutex> lock(this->peer_lock_);
    if (this->panel_ip_ != ip)
      ESP_LOGI(TAG, "Panel reports its address as %s", ip.c_str());
    this->panel_ip_ = ip;
    this->panel_ip_ms_ = millis();
    return;
  }
  if (req.rfind("T,", 0) == 0) {
    // The panel's clock. Taken only when this controller has none -- it
    // restarted while Wi-Fi (and so internet time) was down -- so the CO2
    // schedule and the history keep running. SNTP corrects it once Wi-Fi is
    // back.
    const uint32_t epoch = (uint32_t) strtoul(req.c_str() + 2, nullptr, 10);
    if (::time(nullptr) < 1700000000 && epoch > 1700000000) {
      struct timeval tv = {(time_t) epoch, 0};
      settimeofday(&tv, nullptr);
      ESP_LOGW(TAG, "No clock of its own: took the panel's over BLE");
    }
    return;
  }
  if (req == "C") {
    this->xfer_kind_ = 0;
    this->xfer_buf_.clear();
    this->xfer_buf_.shrink_to_fit();
    return;
  }
  if (req.size() == 3 && req[0] == 'O' && req[1] == ',') {
    const char k = req[2];
    std::string name;
    uint32_t crc = 0;
    if (k == 'B' || k == 'S') {
      if (k == 'B') {
        this->xfer_buf_ = this->backup_json_();
        name = "backup.json";
      } else {
        const esp_partition_t *run = esp_ota_get_running_partition();
        const esp_partition_t *other = esp_ota_get_next_update_partition(run);
        this->xfer_buf_ = json::build_json([&](JsonObject root) {
          describe(root["running"].to<JsonObject>(), run, true);
          if (other != nullptr)
            describe(root["previous"].to<JsonObject>(), other, false);
        });
        name = "slots.json";
      }
      this->xfer_size_ = this->xfer_buf_.size();
      crc = esp_rom_crc32_le(0, reinterpret_cast<const uint8_t *>(this->xfer_buf_.data()), this->xfer_size_);
    } else if (k == 'F') {
      const esp_partition_t *run = esp_ota_get_running_partition();
      esp_partition_pos_t pos{run->address, run->size};
      esp_image_metadata_t meta{};
      if (esp_image_verify(ESP_IMAGE_VERIFY_SILENT, &pos, &meta) != ESP_OK || meta.image_len == 0) {
        this->reply_(out, 'E', "cannot read the running firmware");
        return;
      }
      std::unique_ptr<uint8_t[]> buf(new uint8_t[4096]);
      for (uint32_t off = 0; off < meta.image_len;) {
        const size_t n = std::min<uint32_t>(4096, meta.image_len - off);
        esp_partition_read(run, off, buf.get(), n);
        crc = esp_rom_crc32_le(crc, buf.get(), n);
        off += n;
      }
      char sha[17];
      esp_app_get_elf_sha256(sha, sizeof(sha));
      this->xfer_part_ = run;
      this->xfer_size_ = meta.image_len;
      name = std::string("controller-") + sha + ".bin";
    } else {
      this->reply_(out, 'E', "unknown transfer");
      return;
    }
    this->xfer_kind_ = k;
    char head[32];
    snprintf(head, sizeof(head), "%u,%08x,", (unsigned) this->xfer_size_, (unsigned) crc);
    this->reply_(out, 'S', head + name);
    return;
  }
  unsigned off = 0, n = 0;
  if (sscanf(req.c_str(), "R,%u,%u", &off, &n) == 2) {
    if (this->xfer_kind_ == 0) {
      this->reply_(out, 'E', "nothing open");
      return;
    }
    n = std::min<unsigned>(n, 16);
    for (unsigned i = 0; i < n && off < this->xfer_size_; i++) {
      const size_t len = std::min<size_t>(CHUNK, this->xfer_size_ - off);
      std::vector<uint8_t> p(5 + len);
      p[0] = 'D';
      p[1] = off & 0xff;
      p[2] = (off >> 8) & 0xff;
      p[3] = (off >> 16) & 0xff;
      p[4] = (off >> 24) & 0xff;
      if (this->xfer_kind_ == 'F')
        esp_partition_read(static_cast<const esp_partition_t *>(this->xfer_part_), off, p.data() + 5, len);
      else
        memcpy(p.data() + 5, this->xfer_buf_.data() + off, len);
      out->set_value(std::move(p));
      out->notify();
      off += len;
    }
    return;
  }
  this->reply_(out, 'E', "bad request");
}

void TankBackup::dump_config() {
  ESP_LOGCONFIG(TAG, "Tank Backup:");
  ESP_LOGCONFIG(TAG, "  %u setting switches; panel transfers over BLE", (unsigned) this->switches_.size());
}

}  // namespace tank_backup
}  // namespace esphome
