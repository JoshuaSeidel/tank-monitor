#include "nvs_wipe.h"
#include "esphome/core/log.h"

#include <esp_system.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <nvs.h>
#include <nvs_flash.h>

namespace esphome {
namespace nvs_wipe {

static const char *const TAG = "nvs_wipe";
// Its own namespace: nothing else in ESPHome reads or writes it.
static const char *const NS = "tm_wipe";
static const char *const KEY = "gen";

void NvsWipe::setup() {
  nvs_handle_t h;
  if (nvs_open(NS, NVS_READONLY, &h) == ESP_OK) {
    nvs_get_u32(h, KEY, &this->stored_);
    nvs_close(h);
  }
  if (this->stored_ == this->generation_)
    return;

  ESP_LOGW(TAG, "Wipe generation %u (board last wiped for %u): erasing ALL stored settings and restarting",
           (unsigned) this->generation_, (unsigned) this->stored_);
  // Raw IDF calls, not ESPHome's preferences: the erase takes the whole
  // partition, and the marker is written straight back afterwards so the
  // next boot finds this generation done instead of wiping in a loop.
  if (nvs_flash_erase() != ESP_OK || nvs_flash_init() != ESP_OK) {
    ESP_LOGE(TAG, "NVS erase failed; carrying on with the stored settings");
    return;
  }
  bool marked = false;
  if (nvs_open(NS, NVS_READWRITE, &h) == ESP_OK) {
    marked = nvs_set_u32(h, KEY, this->generation_) == ESP_OK && nvs_commit(h) == ESP_OK;
    nvs_close(h);
  }
  if (!marked) {
    // Restarting now would wipe again on every boot. Run on this time.
    ESP_LOGE(TAG, "Could not record the wipe; not restarting");
    return;
  }
  vTaskDelay(pdMS_TO_TICKS(200));  // let the log line out
  // esp_restart(), not App.safe_reboot(): a safe reboot runs every
  // component's shutdown, and those write the old settings back.
  esp_restart();
}

void NvsWipe::dump_config() {
  ESP_LOGCONFIG(TAG, "NVS wipe: generation %u", (unsigned) this->generation_);
}

}  // namespace nvs_wipe
}  // namespace esphome
