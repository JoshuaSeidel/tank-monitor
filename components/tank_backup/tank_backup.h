#pragma once

#include "esphome/core/component.h"
#include "esphome/components/esp32_ble_server/ble_characteristic.h"
#include "esphome/components/switch/switch.h"
#include "esphome/components/web_server_base/web_server_base.h"
#include "esphome/components/tank_controller/tank_controller.h"
#include "esphome/components/tank_history/tank_history.h"

#include <mutex>
#include <string>
#include <vector>

namespace esphome {
namespace tank_backup {

/// Settings backup/restore and firmware slots, served over HTTP.
///
/// A backup is every number, select and time entity on the device (all of
/// them are settings here), the switches named in YAML, the learned heat
/// model and the water-test log -- one JSON document the panel saves to SD
/// nightly. A restore takes that document back, in whichever parts were
/// asked for. Entity changes are deferred to the main loop: HTTP handlers
/// run on the server's own task.
class TankBackup : public Component, public AsyncWebHandler {
 public:
  void set_base(web_server_base::WebServerBase *base) { this->base_ = base; }
  void set_controller(tank_controller::TankController *c) { this->controller_ = c; }
  void set_history(tank_history::TankHistory *h) { this->history_ = h; }
  void add_switch(switch_::Switch *s) { this->switches_.push_back(s); }

  void setup() override;
  void dump_config() override;
  float get_setup_priority() const override { return setup_priority::LATE; }

  bool canHandle(AsyncWebServerRequest *request) const override;
  void handleRequest(AsyncWebServerRequest *request) override;
  void handleBody(AsyncWebServerRequest *request, uint8_t *data, size_t len, size_t index, size_t total) override;

  /// One request from the panel over BLE, answered with notifications on
  /// `out`. Requests are ASCII:
  ///   O,B | O,S | O,F   open the backup, the slot info or the firmware
  ///   R,<offset>,<n>    send up to n chunks from offset
  ///   C                 close
  ///   I,<ip>            the panel's Wi-Fi address (no reply)
  ///   T,<epoch>         the panel's clock, taken only if this has none
  /// and the panel's controls (no reply; the panel re-reads the backup):
  ///   N,<name>,<value>  set the number entity of that name
  ///   P,<name>          press the button of that name
  ///   W,<name>,<0|1>    turn the switch of that name off/on
  ///   M,<name>,<HH:MM:SS> set the time entity of that name
  ///   X,<ph>,<nh3>,<no2>,<no3>,<gh>,<kh>  log a water test now (-999 = not tested)
  /// Replies are 'S' + "<size>,<crc32 hex>,<name>", 'D' + uint32 LE offset +
  /// up to CHUNK bytes, or 'E' + a reason.
  void ble_request(const uint8_t *data, size_t len, esp32_ble_server::BLECharacteristic *out);
  static const size_t CHUNK = 120;

 protected:
  std::string backup_json_();
  void restore_(AsyncWebServerRequest *request);
  void slots_json_(AsyncWebServerRequest *request);
  void rollback_(AsyncWebServerRequest *request);
  void send_firmware_(AsyncWebServerRequest *request);
  void reply_(esp32_ble_server::BLECharacteristic *out, char kind, const std::string &text);

  web_server_base::WebServerBase *base_{nullptr};
  tank_controller::TankController *controller_{nullptr};
  tank_history::TankHistory *history_{nullptr};
  std::vector<switch_::Switch *> switches_;

  std::string body_;        // the restore document as it arrives
  bool body_too_big_{false};
  std::mutex peer_lock_;
  std::string panel_ip_;    // reported by the panel over BLE; empty until then
  uint32_t panel_ip_ms_{0};

  // The one transfer open at a time: a snapshot (backup, slots) or the
  // running firmware partition.
  char xfer_kind_{0};
  std::string xfer_buf_;
  uint32_t xfer_size_{0};
  const void *xfer_part_{nullptr};
};

}  // namespace tank_backup
}  // namespace esphome
