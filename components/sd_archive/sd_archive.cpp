#include "sd_archive.h"
#include "esphome/core/application.h"
#include "esphome/core/defines.h"
#include "esphome/core/log.h"
#include "esphome/components/json/json_util.h"

#include <driver/sdspi_host.h>
#include <driver/spi_common.h>
#include <esp_app_desc.h>
#include <esp_http_client.h>
#include <esp_http_server.h>
#include <esp_image_format.h>
#include <esp_ota_ops.h>
#include <esp_vfs_fat.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <sdmmc_cmd.h>
#ifdef USE_MDNS
#include <mdns.h>
#endif

#include <dirent.h>
#include <sys/stat.h>
#include <unistd.h>
#include <algorithm>
#include <cmath>
#include <cstring>
#include <memory>

namespace esphome {
namespace sd_archive {

static const char *const TAG = "sd_archive";
static const char *const ROOT = "/sd";
static const char *const DIRS[] = {"history", "backups", "firmware"};
// One backup a night; a year of them is a few MB.
static const size_t KEEP_BACKUPS = 366;
static const uint32_t SLOT_S = 300;

void SdArchive::add_series(const char *name, sensor::Sensor *sens, int decimals) {
  Series s;
  s.name = name;
  s.sensor = sens;
  s.decimals = decimals;
  this->series_.push_back(s);
}

void SdArchive::setup() {
  // Chip-select held asserted for good: the card is alone on this bus, and
  // the expander pin cannot be toggled per transaction anyway.
  this->cs_pin_->setup();
  this->cs_pin_->digital_write(false);
  this->base_->add_handler(this);
  xTaskCreate(SdArchive::worker_, "sd_archive", 8192, this, 1, nullptr);
}

// ------------------------------------------------------------------ rows

// Main loop: average each series over the 5-minute wall-clock slot and, when
// the slot closes, queue its row. Never touches the card.
void SdArchive::update() {
  const auto t = this->time_->now();
  if (!t.is_valid())
    return;
  const uint32_t slot = (uint32_t) t.timestamp / SLOT_S;
  if (this->slot_ != 0 && slot != this->slot_) {
    ESPTime start = ESPTime::from_epoch_local((time_t) this->slot_ * SLOT_S);
    char head[48];
    char month[8];
    start.strftime(month, sizeof(month), "%Y-%m");
    char local[20];
    start.strftime(local, sizeof(local), "%Y-%m-%d %H:%M");
    snprintf(head, sizeof(head), "%s|%u,%s", month, (unsigned) (this->slot_ * SLOT_S), local);
    std::string row = head;
    bool any = false;
    for (auto &s : this->series_) {
      row += ',';
      if (s.count > 0) {
        char v[24];
        snprintf(v, sizeof(v), "%.*f", s.decimals, s.sum / s.count);
        row += v;
        any = true;
      }
      s.sum = 0;
      s.count = 0;
    }
    if (any) {
      std::lock_guard<std::mutex> g(this->rows_lock_);
      if (this->pending_rows_.size() < 288)  // a day's worth if the card is out
        this->pending_rows_.push_back(row);
    }
  }
  this->slot_ = slot;
  for (auto &s : this->series_) {
    const float v = s.sensor->state;
    if (!std::isnan(v)) {
      s.sum += v;
      s.count++;
    }
  }
}

void SdArchive::write_rows_() {
  std::vector<std::string> rows;
  {
    std::lock_guard<std::mutex> g(this->rows_lock_);
    rows.swap(this->pending_rows_);
  }
  if (rows.empty())
    return;
  std::lock_guard<std::recursive_mutex> g(this->lock_);
  size_t done = 0;
  for (const auto &r : rows) {
    const size_t bar = r.find('|');
    const std::string path = std::string(ROOT) + "/history/" + r.substr(0, bar) + ".csv";
    struct stat st;
    const bool fresh = stat(path.c_str(), &st) != 0;
    FILE *f = fopen(path.c_str(), "a");
    if (f == nullptr)
      break;
    if (fresh) {
      fputs("epoch,local", f);
      for (auto &s : this->series_)
        fprintf(f, ",%s", s.name);
      fputc('\n', f);
    }
    fputs(r.c_str() + bar + 1, f);
    fputc('\n', f);
    const bool ok = fclose(f) == 0;
    if (!ok)
      break;
    done++;
    this->last_row_ = (uint32_t) strtoul(r.c_str() + bar + 1, nullptr, 10);
  }
  this->rows_written_ += done;
  if (done < rows.size()) {
    // The card went away or filled up. Keep what was not written and let
    // the worker remount.
    ESP_LOGW(TAG, "History write failed; card unmounted until it answers again");
    {
      std::lock_guard<std::mutex> rg(this->rows_lock_);
      this->pending_rows_.insert(this->pending_rows_.begin(), rows.begin() + done, rows.end());
    }
    esp_vfs_fat_sdcard_unmount(ROOT, this->card_);
    this->card_ = nullptr;
    this->mounted_ = false;
    this->mount_error_ = "write failed";
  }
}

// ----------------------------------------------------------------- mount

bool SdArchive::mount_() {
  std::lock_guard<std::recursive_mutex> g(this->lock_);
  static bool bus_ready = false;
  if (!bus_ready) {
    spi_bus_config_t bus{};
    bus.mosi_io_num = this->mosi_;
    bus.miso_io_num = this->miso_;
    bus.sclk_io_num = this->clk_;
    bus.quadwp_io_num = -1;
    bus.quadhd_io_num = -1;
    bus.max_transfer_sz = 4096;
    const esp_err_t err = spi_bus_initialize(SPI2_HOST, &bus, SPI_DMA_CH_AUTO);
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
      this->mount_error_ = std::string("SPI bus: ") + esp_err_to_name(err);
      return false;
    }
    bus_ready = true;
  }
  sdmmc_host_t host = SDSPI_HOST_DEFAULT();
  host.slot = SPI2_HOST;
  sdspi_device_config_t slot = SDSPI_DEVICE_CONFIG_DEFAULT();
  slot.gpio_cs = SDSPI_SLOT_NO_CS;
  slot.host_id = SPI2_HOST;
  esp_vfs_fat_sdmmc_mount_config_t mc{};
  // Never format: a card that will not mount may hold the only copy of a
  // year of history. Say so and leave it alone.
  mc.format_if_mount_failed = false;
  mc.max_files = 6;
  mc.allocation_unit_size = 16 * 1024;
  const esp_err_t err = esp_vfs_fat_sdspi_mount(ROOT, &host, &slot, &mc, &this->card_);
  if (err != ESP_OK) {
    this->card_ = nullptr;
    this->mount_error_ = err == ESP_FAIL ? "no FAT filesystem (format the card FAT32 on a computer)"
                                         : std::string("no card (") + esp_err_to_name(err) + ")";
    return false;
  }
  for (const char *d : DIRS)
    mkdir((std::string(ROOT) + "/" + d).c_str(), 0775);
  this->mounted_ = true;
  this->mount_error_.clear();
  ESP_LOGI(TAG, "SD card mounted: %s, %llu MB", this->card_->cid.name,
           (unsigned long long) this->card_->csd.capacity * this->card_->csd.sector_size / (1024 * 1024));
  return true;
}

// ---------------------------------------------------------------- worker

void SdArchive::worker_(void *arg) {
  auto *self = static_cast<SdArchive *>(arg);
  uint32_t last_try = 0;
  bool own_done = false, boot_checked = false;
  for (;;) {
    const uint32_t up = millis() / 1000;
    if (!self->mounted_ && (last_try == 0 || up - last_try >= 60)) {
      last_try = up;
      if (!self->mount_())
        ESP_LOGW(TAG, "SD card: %s", self->mount_error_.c_str());
    }
    if (self->mounted_) {
      self->write_rows_();
      if (!own_done && up > 60) {
        self->archive_own_firmware_();
        own_done = true;
      }
      auto t = self->time_->now();
      if (t.is_valid()) {
        bool due = self->backup_now_.exchange(false);
        if (!due && t.hour == 3 && t.day_of_year != self->last_backup_yday_)
          due = true;
        // After a boot, catch up today's backup if the 03:00 one was missed.
        if (!due && !boot_checked && up > 180) {
          boot_checked = true;
          char name[48];
          t.strftime(name, sizeof(name), "/sd/backups/%Y-%m-%d.json");
          struct stat st;
          due = stat(name, &st) != 0;
        }
        if (due) {
          self->last_backup_yday_ = t.day_of_year;
          self->nightly_();
        }
      }
    }
    vTaskDelay(pdMS_TO_TICKS(2000));
  }
}

bool SdArchive::resolve_controller_(std::string &ip) {
#ifdef USE_MDNS
  esp_ip4_addr_t addr{};
  if (mdns_query_a(this->controller_host_.c_str(), 3000, &addr) == ESP_OK && addr.addr != 0) {
    char b[16];
    snprintf(b, sizeof(b), IPSTR, IP2STR(&addr));
    ip = b;
    std::lock_guard<std::recursive_mutex> g(this->lock_);
    this->controller_ip_ = ip;
    return true;
  }
#endif
  return false;
}

static esp_http_client_handle_t open_get(const std::string &url, int &status) {
  esp_http_client_config_t cfg{};
  cfg.url = url.c_str();
  cfg.timeout_ms = 20000;
  cfg.buffer_size = 2048;
  esp_http_client_handle_t c = esp_http_client_init(&cfg);
  if (c == nullptr)
    return nullptr;
  if (esp_http_client_open(c, 0) != ESP_OK) {
    esp_http_client_cleanup(c);
    return nullptr;
  }
  esp_http_client_fetch_headers(c);
  status = esp_http_client_get_status_code(c);
  return c;
}

bool SdArchive::http_to_string_(const std::string &url, std::string &out, std::string &err) {
  int status = 0;
  auto c = open_get(url, status);
  if (c == nullptr || status != 200) {
    err = c == nullptr ? "no connection" : "HTTP " + std::to_string(status);
    if (c)
      esp_http_client_cleanup(c);
    return false;
  }
  char buf[1024];
  int n;
  out.clear();
  while ((n = esp_http_client_read(c, buf, sizeof(buf))) > 0 && out.size() < 64 * 1024)
    out.append(buf, n);
  esp_http_client_close(c);
  esp_http_client_cleanup(c);
  return n >= 0;
}

// Downloads to <path>.part and renames only once complete, so a half
// download never sits on the card looking like a good file.
bool SdArchive::http_to_file_(const std::string &url, const std::string &path, std::string &err) {
  int status = 0;
  auto c = open_get(url, status);
  if (c == nullptr || status != 200) {
    err = c == nullptr ? "no connection" : "HTTP " + std::to_string(status);
    if (c)
      esp_http_client_cleanup(c);
    return false;
  }
  const std::string part = path + ".part";
  FILE *f;
  {
    std::lock_guard<std::recursive_mutex> g(this->lock_);
    f = fopen(part.c_str(), "wb");
  }
  if (f == nullptr) {
    err = "cannot write to the card";
    esp_http_client_cleanup(c);
    return false;
  }
  std::unique_ptr<char[]> buf(new char[4096]);
  int n;
  size_t total = 0;
  bool ok = true;
  while ((n = esp_http_client_read(c, buf.get(), 4096)) > 0) {
    std::lock_guard<std::recursive_mutex> g(this->lock_);
    if (fwrite(buf.get(), 1, n, f) != (size_t) n) {
      ok = false;
      err = "card write failed";
      break;
    }
    total += n;
  }
  if (n < 0) {
    ok = false;
    err = "download interrupted";
  }
  if (ok && !esp_http_client_is_complete_data_received(c)) {
    ok = false;
    err = "download incomplete";
  }
  esp_http_client_close(c);
  esp_http_client_cleanup(c);
  std::lock_guard<std::recursive_mutex> g(this->lock_);
  fclose(f);
  if (!ok || total == 0) {
    unlink(part.c_str());
    if (ok)
      err = "empty download";
    return false;
  }
  unlink(path.c_str());
  return rename(part.c_str(), path.c_str()) == 0;
}

// The controller's settings backup, and a copy of its firmware if this
// build has not been seen before.
void SdArchive::nightly_() {
  auto t = this->time_->now();
  char day[16];
  t.strftime(day, sizeof(day), "%Y-%m-%d");
  std::string ip, err;
  if (!this->resolve_controller_(ip)) {
    std::lock_guard<std::recursive_mutex> g(this->lock_);
    this->last_backup_ = std::string(day) + " failed: controller not found on the network";
    ESP_LOGW(TAG, "%s", this->last_backup_.c_str());
    return;
  }
  const std::string base = "http://" + ip;
  const bool ok = this->http_to_file_(base + "/backup.json", std::string(ROOT) + "/backups/" + day + ".json", err);

  std::string slots, ferr, fw_note;
  if (this->http_to_string_(base + "/firmware/slots.json", slots, ferr)) {
    std::string sha;
    json::parse_json(slots, [&](JsonObject root) -> bool {
      sha = root["running"]["firmware"].as<std::string>();
      return true;
    });
    if (!sha.empty() && sha != "null") {
      const std::string bin = std::string(ROOT) + "/firmware/controller-" + sha + ".bin";
      struct stat st;
      if (stat(bin.c_str(), &st) != 0) {
        if (this->http_to_file_(base + "/firmware/current.bin", bin, ferr)) {
          std::lock_guard<std::recursive_mutex> g(this->lock_);
          FILE *f = fopen((std::string(ROOT) + "/firmware/controller-" + sha + ".json").c_str(), "w");
          if (f != nullptr) {
            fputs(slots.c_str(), f);
            fclose(f);
          }
          fw_note = ", firmware " + sha.substr(0, 8) + " archived";
        } else {
          fw_note = ", firmware copy failed: " + ferr;
        }
      }
    }
  }
  this->prune_("backups", KEEP_BACKUPS);
  std::lock_guard<std::recursive_mutex> g(this->lock_);
  this->last_backup_ = std::string(day) + (ok ? " ok" : " failed: " + err) + fw_note;
  ESP_LOGI(TAG, "Nightly: %s", this->last_backup_.c_str());
}

// This panel's own running firmware, once per build.
void SdArchive::archive_own_firmware_() {
  char sha[17];
  esp_app_get_elf_sha256(sha, sizeof(sha));
  const std::string bin = std::string(ROOT) + "/firmware/panel-" + sha + ".bin";
  std::lock_guard<std::recursive_mutex> g(this->lock_);
  struct stat st;
  if (stat(bin.c_str(), &st) == 0)
    return;
  const esp_partition_t *run = esp_ota_get_running_partition();
  esp_partition_pos_t pos{run->address, run->size};
  esp_image_metadata_t meta{};
  if (esp_image_verify(ESP_IMAGE_VERIFY_SILENT, &pos, &meta) != ESP_OK || meta.image_len == 0)
    return;
  const std::string part = bin + ".part";
  FILE *f = fopen(part.c_str(), "wb");
  if (f == nullptr)
    return;
  std::unique_ptr<uint8_t[]> buf(new uint8_t[4096]);
  bool ok = true;
  for (uint32_t off = 0; ok && off < meta.image_len;) {
    const size_t n = std::min<uint32_t>(4096, meta.image_len - off);
    ok = esp_partition_read(run, off, buf.get(), n) == ESP_OK && fwrite(buf.get(), 1, n, f) == n;
    off += n;
  }
  fclose(f);
  if (!ok) {
    unlink(part.c_str());
    return;
  }
  rename(part.c_str(), bin.c_str());
  const esp_app_desc_t *d = esp_app_get_description();
  FILE *j = fopen((std::string(ROOT) + "/firmware/panel-" + sha + ".json").c_str(), "w");
  if (j != nullptr) {
    fprintf(j, "{\"running\":{\"firmware\":\"%s\",\"built\":\"%s %s\",\"project\":\"%s\"}}", sha, d->date, d->time,
            d->project_name);
    fclose(j);
  }
  ESP_LOGI(TAG, "Archived this panel's firmware %s", sha);
}

void SdArchive::prune_(const char *dir, size_t keep) {
  std::lock_guard<std::recursive_mutex> g(this->lock_);
  const std::string path = std::string(ROOT) + "/" + dir;
  DIR *d = opendir(path.c_str());
  if (d == nullptr)
    return;
  std::vector<std::string> names;
  while (struct dirent *e = readdir(d))
    if (e->d_type == DT_REG)
      names.emplace_back(e->d_name);
  closedir(d);
  if (names.size() <= keep)
    return;
  std::sort(names.begin(), names.end());  // dated names: oldest first
  for (size_t i = 0; i + keep < names.size(); i++)
    unlink((path + "/" + names[i]).c_str());
}

// ------------------------------------------------------------------ HTTP

static bool starts_with(const StringRef &s, const char *p) {
  const size_t n = strlen(p);
  return s.size() >= n && memcmp(s.c_str(), p, n) == 0;
}

bool SdArchive::canHandle(AsyncWebServerRequest *request) const {
  char url_buf[AsyncWebServerRequest::URL_BUF_SIZE];
  const auto url = request->url_to(url_buf);
  const auto m = request->method();
  return (m == HTTP_GET || m == HTTP_POST || m == HTTP_OPTIONS) && starts_with(url, "/sd/");
}

// "dir/name", dir one of ours and name plain: no traversal, no hidden files.
bool SdArchive::safe_path_(const std::string &path, std::string &full) {
  const size_t slash = path.find('/');
  if (slash == std::string::npos)
    return false;
  const std::string dir = path.substr(0, slash), name = path.substr(slash + 1);
  if (std::none_of(std::begin(DIRS), std::end(DIRS), [&](const char *d) { return dir == d; }))
    return false;
  if (name.empty() || name.size() > 64 || name[0] == '.')
    return false;
  for (char c : name)
    if (!isalnum((unsigned char) c) && c != '.' && c != '-' && c != '_')
      return false;
  full = std::string(ROOT) + "/" + dir + "/" + name;
  return true;
}

void SdArchive::send_json_(AsyncWebServerRequest *request, int code, const std::string &body) {
  auto *resp = request->beginResponse(code, "application/json", body);
  resp->addHeader("Access-Control-Allow-Origin", "*");
  resp->addHeader("Cache-Control", "no-store");
  request->send(resp);
}

static void send_text(AsyncWebServerRequest *request, int code, const char *text) {
  auto *resp = request->beginResponse(code, "text/plain", std::string(text));
  resp->addHeader("Access-Control-Allow-Origin", "*");
  request->send(resp);
}

void SdArchive::handleBody(AsyncWebServerRequest *request, uint8_t *data, size_t len, size_t index, size_t total) {
  std::lock_guard<std::recursive_mutex> g(this->lock_);
  if (index == 0) {
    if (this->upload_ != nullptr)
      fclose(this->upload_);
    this->upload_ = nullptr;
    this->upload_failed_ = true;
    std::string full;
    if (!this->mounted_ || (request->arg("dir") != "firmware" && request->arg("dir") != "backups"))
      return;
    if (!safe_path_(request->arg("dir") + "/" + request->arg("name"), full))
      return;
    this->upload_path_ = full;
    this->upload_ = fopen((full + ".part").c_str(), "wb");
    this->upload_failed_ = this->upload_ == nullptr;
  }
  if (this->upload_ != nullptr && !this->upload_failed_ && fwrite(data, 1, len, this->upload_) != len)
    this->upload_failed_ = true;
}

void SdArchive::handleRequest(AsyncWebServerRequest *request) {
  char url_buf[AsyncWebServerRequest::URL_BUF_SIZE];
  const auto url = request->url_to(url_buf);

  if (request->method() == HTTP_OPTIONS) {
    // CORS preflight: the controller's page posts files here.
    auto *resp = request->beginResponse(204, "text/plain", std::string());
    resp->addHeader("Access-Control-Allow-Origin", "*");
    resp->addHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
    resp->addHeader("Access-Control-Allow-Headers", "Content-Type");
    resp->addHeader("Access-Control-Max-Age", "600");
    request->send(resp);
    return;
  }

  if (url == "/sd/status.json") {
    std::lock_guard<std::recursive_mutex> g(this->lock_);
    uint64_t tot = 0, fre = 0;
    if (this->mounted_)
      esp_vfs_fat_info(ROOT, &tot, &fre);
    const std::string out = json::build_json([&](JsonObject root) {
      root["mounted"] = this->mounted_;
      root["error"] = this->mount_error_;
      root["total_mb"] = (uint32_t) (tot / (1024 * 1024));
      root["free_mb"] = (uint32_t) (fre / (1024 * 1024));
      if (this->card_ != nullptr)
        root["card"] = std::string(this->card_->cid.name);
      root["rows_written"] = this->rows_written_;
      root["last_row"] = this->last_row_;
      root["last_backup"] = this->last_backup_;
      root["controller_ip"] = this->controller_ip_;
      JsonArray cols = root["columns"].to<JsonArray>();
      for (auto &s : this->series_)
        cols.add(s.name);
    });
    this->send_json_(request, 200, out);
  } else if (url == "/sd/list.json") {
    this->list_(request);
  } else if (url == "/sd/file") {
    this->send_file_(request);
  } else if (url == "/sd/upload") {
    std::lock_guard<std::recursive_mutex> g(this->lock_);
    bool ok = false;
    if (this->upload_ != nullptr) {
      ok = fclose(this->upload_) == 0 && !this->upload_failed_;
      this->upload_ = nullptr;
      const std::string part = this->upload_path_ + ".part";
      if (ok) {
        unlink(this->upload_path_.c_str());
        ok = rename(part.c_str(), this->upload_path_.c_str()) == 0;
      } else {
        unlink(part.c_str());
      }
    }
    send_text(request, ok ? 200 : 400, ok ? "Saved to the SD card." : "Could not save that file to the SD card.");
  } else if (url == "/sd/delete" && request->method() == HTTP_POST) {
    std::string full;
    std::lock_guard<std::recursive_mutex> g(this->lock_);
    const bool ok = safe_path_(request->arg("path"), full) && unlink(full.c_str()) == 0;
    if (ok && full.size() > 4 && full.compare(full.size() - 4, 4, ".bin") == 0)
      unlink((full.substr(0, full.size() - 4) + ".json").c_str());  // its sidecar
    send_text(request, ok ? 200 : 404, ok ? "Deleted." : "No such file.");
  } else if (url == "/sd/backup-now" && request->method() == HTTP_POST) {
    this->backup_now_ = true;
    send_text(request, 202, "Backing up now.");
  } else {
    send_text(request, 404, "Not found.");
  }
}

void SdArchive::list_(AsyncWebServerRequest *request) {
  const std::string dir = request->arg("dir");
  if (std::none_of(std::begin(DIRS), std::end(DIRS), [&](const char *d) { return dir == d; })) {
    send_text(request, 400, "Unknown folder.");
    return;
  }
  struct Entry {
    std::string name;
    uint32_t size, mtime;
  };
  std::vector<Entry> list;
  {
    std::lock_guard<std::recursive_mutex> g(this->lock_);
    if (!this->mounted_) {
      send_text(request, 503, "No SD card.");
      return;
    }
    const std::string path = std::string(ROOT) + "/" + dir;
    DIR *d = opendir(path.c_str());
    if (d != nullptr) {
      while (struct dirent *e = readdir(d)) {
        const std::string name = e->d_name;
        if (e->d_type != DT_REG || (name.size() > 5 && name.compare(name.size() - 5, 5, ".part") == 0))
          continue;
        struct stat st;
        if (stat((path + "/" + name).c_str(), &st) == 0)
          list.push_back({name, (uint32_t) st.st_size, (uint32_t) st.st_mtime});
      }
      closedir(d);
    }
  }
  std::sort(list.begin(), list.end(), [](const Entry &a, const Entry &b) { return a.name > b.name; });
  const std::string out = json::build_json([&](JsonObject root) {
    JsonArray arr = root["files"].to<JsonArray>();
    for (auto &e : list) {
      JsonObject o = arr.add<JsonObject>();
      o["name"] = e.name;
      o["size"] = e.size;
      o["mtime"] = e.mtime;
    }
  });
  this->send_json_(request, 200, out);
}

void SdArchive::send_file_(AsyncWebServerRequest *request) {
  std::string full;
  const std::string path = request->arg("path");
  if (!safe_path_(path, full)) {
    send_text(request, 400, "Bad path.");
    return;
  }
  FILE *f;
  {
    std::lock_guard<std::recursive_mutex> g(this->lock_);
    f = this->mounted_ ? fopen(full.c_str(), "rb") : nullptr;
  }
  if (f == nullptr) {
    send_text(request, 404, "No such file.");
    return;
  }
  const char *type = "application/octet-stream";
  auto ends = [&](const char *ext) {
    const size_t n = strlen(ext);
    return full.size() > n && full.compare(full.size() - n, n, ext) == 0;
  };
  if (ends(".csv"))
    type = "text/csv";
  else if (ends(".json"))
    type = "application/json";
  httpd_req_t *r = *request;
  httpd_resp_set_type(r, type);
  httpd_resp_set_hdr(r, "Access-Control-Allow-Origin", "*");
  httpd_resp_set_hdr(r, "Cache-Control", "no-store");
  std::string disp;
  if (request->arg("dl") == "1") {
    disp = "attachment; filename=\"" + full.substr(full.rfind('/') + 1) + "\"";
    httpd_resp_set_hdr(r, "Content-Disposition", disp.c_str());
  }
  std::unique_ptr<char[]> buf(new char[4096]);
  for (;;) {
    size_t n;
    {
      std::lock_guard<std::recursive_mutex> g(this->lock_);
      n = fread(buf.get(), 1, 4096, f);
    }
    if (n == 0 || httpd_resp_send_chunk(r, buf.get(), n) != ESP_OK)
      break;
  }
  {
    std::lock_guard<std::recursive_mutex> g(this->lock_);
    fclose(f);
  }
  httpd_resp_send_chunk(r, nullptr, 0);
}

std::string SdArchive::status_text() {
  std::lock_guard<std::recursive_mutex> g(this->lock_);
  if (!this->mounted_)
    return "no card: " + this->mount_error_;
  uint64_t tot = 0, fre = 0;
  esp_vfs_fat_info(ROOT, &tot, &fre);
  char b[64];
  snprintf(b, sizeof(b), "ok, %.1f of %.1f GB free", fre / 1073741824.0, tot / 1073741824.0);
  return b;
}

void SdArchive::dump_config() {
  ESP_LOGCONFIG(TAG, "SD Archive:");
  ESP_LOGCONFIG(TAG, "  SPI MOSI %d, MISO %d, CLK %d; CS held low", this->mosi_, this->miso_, this->clk_);
  LOG_PIN("  CS Pin: ", this->cs_pin_);
  ESP_LOGCONFIG(TAG, "  Controller host: %s.local; %u history columns", this->controller_host_.c_str(),
                (unsigned) this->series_.size());
}

}  // namespace sd_archive
}  // namespace esphome
