#pragma once

#include "esphome/core/component.h"
#include "esphome/core/hal.h"
#include "esphome/components/ble_client/ble_client.h"
#include "esphome/components/sensor/sensor.h"
#include "esphome/components/time/real_time_clock.h"
#include "esphome/components/web_server_base/web_server_base.h"

#include <sd_protocol_types.h>

#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>

#include <atomic>
#include <functional>
#include <cstdio>
#include <mutex>
#include <string>
#include <vector>


namespace esphome {
namespace sd_archive {

/// The panel's SD card: forever-history, nightly settings backups and every
/// firmware build, served to the controller's web page.
///
/// All card I/O happens on one worker task or in HTTP handlers, under one
/// lock; the main loop only averages readings and queues the row text, so
/// a slow card can never stall the display.
class SdArchive : public PollingComponent, public AsyncWebHandler, public ble_client::BLEClientNode {
 public:
  void set_base(web_server_base::WebServerBase *base) { this->base_ = base; }
  void set_time(time::RealTimeClock *clock) { this->time_ = clock; }
  void set_cs_pin(GPIOPin *pin) { this->cs_pin_ = pin; }
  void set_bus(int mosi, int miso, int clk) {
    this->mosi_ = mosi;
    this->miso_ = miso;
    this->clk_ = clk;
  }
  void add_series(const char *name, sensor::Sensor *sens, int decimals);

  void setup() override;
  void update() override;
  void dump_config() override;
  float get_setup_priority() const override { return setup_priority::LATE; }

  bool canHandle(AsyncWebServerRequest *request) const override;
  void handleRequest(AsyncWebServerRequest *request) override;
  void handleBody(AsyncWebServerRequest *request, uint8_t *data, size_t len, size_t index, size_t total) override;

  void gattc_event_handler(esp_gattc_cb_event_t event, esp_gatt_if_t gattc_if,
                           esp_ble_gattc_cb_param_t *param) override;

  /// One line for a diagnostic text sensor: card state and free space.
  std::string status_text();
  /// Run the nightly backup on the worker's next pass.
  void backup_now() { this->backup_now_ = true; }

 protected:
  struct Series {
    const char *name;
    sensor::Sensor *sensor;
    int decimals;
    double sum{0};
    uint32_t count{0};
  };

  static void worker_(void *self);
  bool mount_();
  void write_rows_();
  void nightly_();
  void archive_own_firmware_();
  // BLE transfer from the controller (components/tank_backup ble_request).
  bool send_(const std::string &req);
  bool open_(char kind, uint32_t &size, uint32_t &crc, std::string &name, std::string &err);
  bool read_all_(uint32_t size, uint32_t crc, const std::function<bool(const uint8_t *, size_t)> &sink,
                 std::string &err);
  bool fetch_to_file_(char kind, const std::string &path, std::string &name, std::string &err);
  bool fetch_to_string_(char kind, std::string &out, std::string &err);
  void tell_controller_();
  void prune_(const char *dir, size_t keep);

  void send_json_(AsyncWebServerRequest *request, int code, const std::string &body);
  void list_(AsyncWebServerRequest *request);
  void send_file_(AsyncWebServerRequest *request);
  static bool safe_path_(const std::string &path, std::string &full);

  web_server_base::WebServerBase *base_{nullptr};
  time::RealTimeClock *time_{nullptr};
  GPIOPin *cs_pin_{nullptr};
  int mosi_{-1}, miso_{-1}, clk_{-1};
  std::vector<Series> series_;

  // History rows: averaged here on the main loop, written by the worker.
  uint32_t slot_{0};
  std::mutex rows_lock_;  // only pending_rows_: the main loop must never wait on the card
  std::vector<std::string> pending_rows_;

  std::recursive_mutex lock_;  // the card, and the fields below
  sdmmc_card_t *card_{nullptr};
  bool mounted_{false};
  std::string mount_error_;
  uint32_t rows_written_{0};
  uint32_t last_row_{0};
  std::string last_backup_;    // "YYYY-MM-DD ok" / "... failed: why"
  // The controller's transfer characteristics, found on each connection.
  uint16_t req_handle_{0};
  uint16_t data_handle_{0};
  std::atomic<bool> link_ready_{false};
  QueueHandle_t rx_{nullptr};
  std::atomic<bool> backup_now_{false};
  int last_backup_yday_{-1};

  // An upload in progress (POST /sd/upload streams its body to here).
  FILE *upload_{nullptr};
  std::string upload_path_;
  bool upload_failed_{false};
};

}  // namespace sd_archive
}  // namespace esphome
