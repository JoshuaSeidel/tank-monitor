#pragma once

#include "esphome/core/component.h"
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
  void set_panel_host(const std::string &host) { this->panel_host_ = host; }

  void setup() override;
  void dump_config() override;
  float get_setup_priority() const override { return setup_priority::LATE; }

  bool canHandle(AsyncWebServerRequest *request) const override;
  void handleRequest(AsyncWebServerRequest *request) override;
  void handleBody(AsyncWebServerRequest *request, uint8_t *data, size_t len, size_t index, size_t total) override;

 protected:
  std::string backup_json_();
  void restore_(AsyncWebServerRequest *request);
  void slots_json_(AsyncWebServerRequest *request);
  void rollback_(AsyncWebServerRequest *request);
  void send_firmware_(AsyncWebServerRequest *request);
  static void peer_task_(void *self);

  web_server_base::WebServerBase *base_{nullptr};
  tank_controller::TankController *controller_{nullptr};
  tank_history::TankHistory *history_{nullptr};
  std::vector<switch_::Switch *> switches_;
  std::string panel_host_;

  std::string body_;        // the restore document as it arrives
  bool body_too_big_{false};
  std::mutex peer_lock_;
  std::string panel_ip_;    // found by mDNS; empty until found
};

}  // namespace tank_backup
}  // namespace esphome
