#pragma once

#include "esphome/core/component.h"
#include "esphome/core/defines.h"

#ifdef USE_ESP32

#include <esp_gap_ble_api.h>
#include <esp_gatts_api.h>

namespace esphome {
namespace ble_link_guard {

// See __init__.py for why this component exists. In short: ESPHome's GATT
// server stops re-asserting advertising once the board's own client link to
// the lamp is counted as one of its clients, and nothing in ESPHome notices a
// refused or silently-ended advertising start. This watches the radio's own
// events and puts advertising back whenever a connection slot is free.
class BLELinkGuard : public Component {
 public:
  void setup() override;
  void loop() override;
  void dump_config() override;
  // After the BLE stack and the server, so global_ble_server exists.
  float get_setup_priority() const override { return setup_priority::AFTER_BLUETOOTH - 1.0f; }

  void set_reassert_interval(uint32_t ms) { this->reassert_interval_ms_ = ms; }

  // Called from esp32_ble's main-loop event dispatch (not the BT task).
  void gap_event_handler(esp_gap_ble_cb_event_t event, esp_ble_gap_cb_param_t *param);
  void gatts_event_handler(esp_gatts_cb_event_t event, esp_gatt_if_t gatts_if, esp_ble_gatts_cb_param_t *param);

  // ---- for template entities ----
  // Every LE link the radio has open, whichever side started it.
  uint8_t link_count() const { return this->link_count_; }
  // Links where this board is the central (it connected out: the lamp).
  uint8_t central_links() const;
  // Links where this board is the peripheral (someone connected in: the panel).
  uint8_t peripheral_links() const;
  // Free connection slots: USE_ESP32_BLE_MAX_CONNECTIONS minus open links.
  uint8_t free_slots() const;
  // What the last advertising start/stop event said. True only after a
  // successful ADV_START_COMPLETE with no stop or peripheral connect since.
  bool advertising() const { return this->advertising_; }
  // Times advertising was found off with a free slot and restarted.
  uint32_t restarts() const { return this->restarts_; }
  // esp_bt_status_t of the last REFUSED advertising start, 0 if none.
  uint8_t last_start_error() const { return this->last_start_error_; }

  // Last disconnect of a peer, by its 48-bit address (as ble_client's
  // get_address() returns it). -1 / 0 when nothing has been seen this boot.
  int last_disconnect_reason(uint64_t address) const;
  uint32_t last_disconnect_ms(uint64_t address) const;
  // Human name for an esp_gatt_conn_reason_t / HCI disconnect reason.
  static const char *reason_str(int reason);

 protected:
  struct Link {
    uint16_t conn_id;
    uint8_t role;  // 0 = this board is central, 1 = peripheral
    uint64_t address;
  };
  struct PeerDrop {
    uint64_t address;
    int reason;
    uint32_t at_ms;
  };
  static constexpr uint8_t MAX_LINKS = 9;  // Bluedroid's hard ceiling
  static constexpr uint8_t MAX_PEERS = 4;

  static uint64_t to_address_(const esp_bd_addr_t bda);
  void add_link_(uint16_t conn_id, uint8_t role, uint64_t address);
  void remove_link_(uint16_t conn_id, uint64_t address, int reason);
  void record_drop_(uint64_t address, int reason);

  Link links_[MAX_LINKS]{};
  uint8_t link_count_{0};
  PeerDrop peers_[MAX_PEERS]{};
  uint8_t peer_next_{0};

  bool advertising_{false};
  // A central just connected in, which ends advertising by design: the next
  // restart is routine, not a fault, and is neither warned about nor counted.
  bool resume_expected_{false};
  uint8_t last_start_error_{0};
  uint8_t refused_in_a_row_{0};
  uint32_t restarts_{0};
  uint32_t reassert_interval_ms_{60000};
  uint32_t last_attempt_ms_{0};
  uint32_t next_reassert_ms_{0};
  uint32_t last_check_ms_{0};
};

}  // namespace ble_link_guard
}  // namespace esphome

#endif  // USE_ESP32
