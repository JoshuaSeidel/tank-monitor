#include "ble_link_guard.h"

#ifdef USE_ESP32

#include "esphome/core/application.h"
#include "esphome/core/hal.h"
#include "esphome/core/log.h"
#include "esphome/components/esp32_ble/ble.h"
#include "esphome/components/esp32_ble_server/ble_server.h"

namespace esphome {
namespace ble_link_guard {

static const char *const TAG = "ble_link_guard";

// How long a start request is given to report back before another is sent,
// and the slower pace once starts keep being refused -- a controller that
// rejects every start must not turn into a log flood or an HCI storm.
static constexpr uint32_t RETRY_MS = 5000;
static constexpr uint32_t RETRY_SLOW_MS = 30000;
// After the board connects OUT (the lamp), check advertising this soon. That
// is the moment it was seen to stop on 2026-09-29.
static constexpr uint32_t AFTER_CENTRAL_CONNECT_MS = 1500;

void BLELinkGuard::setup() {
  // Nothing to do until the server is running; loop() waits for it.
  this->last_check_ms_ = millis();
}

uint64_t BLELinkGuard::to_address_(const esp_bd_addr_t bda) {
  // Same byte order as BLEClientBase::set_address(), so a ble_client's
  // get_address() can be passed straight to last_disconnect_reason().
  return ((uint64_t) bda[0] << 40) | ((uint64_t) bda[1] << 32) | ((uint64_t) bda[2] << 24) |
         ((uint64_t) bda[3] << 16) | ((uint64_t) bda[4] << 8) | ((uint64_t) bda[5]);
}

uint8_t BLELinkGuard::central_links() const {
  uint8_t n = 0;
  for (uint8_t i = 0; i < this->link_count_; i++)
    if (this->links_[i].role == 0)
      n++;
  return n;
}

uint8_t BLELinkGuard::peripheral_links() const { return this->link_count_ - this->central_links(); }

uint8_t BLELinkGuard::free_slots() const {
  const int free = (int) USE_ESP32_BLE_MAX_CONNECTIONS - (int) this->link_count_;
  return free > 0 ? (uint8_t) free : 0;
}

void BLELinkGuard::add_link_(uint16_t conn_id, uint8_t role, uint64_t address) {
  for (uint8_t i = 0; i < this->link_count_; i++) {
    if (this->links_[i].conn_id == conn_id) {
      this->links_[i].role = role;
      this->links_[i].address = address;
      return;
    }
  }
  if (this->link_count_ >= MAX_LINKS) {
    ESP_LOGW(TAG, "link table full; conn %u not tracked", conn_id);
    return;
  }
  this->links_[this->link_count_++] = Link{conn_id, role, address};
}

void BLELinkGuard::remove_link_(uint16_t conn_id, uint64_t address, int reason) {
  for (uint8_t i = 0; i < this->link_count_; i++) {
    if (this->links_[i].conn_id == conn_id || this->links_[i].address == address) {
      this->links_[i] = this->links_[--this->link_count_];
      break;
    }
  }
  this->record_drop_(address, reason);
}

void BLELinkGuard::record_drop_(uint64_t address, int reason) {
  for (auto &p : this->peers_) {
    if (p.address == address) {
      p.reason = reason;
      p.at_ms = millis();
      return;
    }
  }
  // Round-robin: four peers is far more than this board ever talks to.
  this->peers_[this->peer_next_] = PeerDrop{address, reason, millis()};
  this->peer_next_ = (this->peer_next_ + 1) % MAX_PEERS;
}

int BLELinkGuard::last_disconnect_reason(uint64_t address) const {
  for (const auto &p : this->peers_)
    if (p.address == address && p.address != 0)
      return p.reason;
  return -1;
}

uint32_t BLELinkGuard::last_disconnect_ms(uint64_t address) const {
  for (const auto &p : this->peers_)
    if (p.address == address && p.address != 0)
      return p.at_ms;
  return 0;
}

const char *BLELinkGuard::reason_str(int reason) {
  // esp_gatt_conn_reason_t carries the HCI disconnect reason for the
  // common cases; the rest are Bluedroid's own codes.
  switch (reason) {
    case 0x01:
      return "L2CAP failure";
    case 0x08:
      return "supervision timeout";
    case 0x13:
      return "peer closed it";
    case 0x16:
      return "this board closed it";
    case 0x1F:
      return "unspecified error";
    case 0x22:
      return "LL response timeout";
    case 0x28:
      return "instant passed";
    case 0x3B:
      return "connection parameters refused";
    case 0x3D:
      return "MIC failure";
    case 0x3E:
      return "failed to establish";
    case 0x100:
      return "cancelled";
    default:
      return "other";
  }
}

void BLELinkGuard::gap_event_handler(esp_gap_ble_cb_event_t event, esp_ble_gap_cb_param_t *param) {
  if (param == nullptr)
    return;
  switch (event) {
    case ESP_GAP_BLE_ADV_START_COMPLETE_EVT:
      if (param->adv_start_cmpl.status == ESP_BT_STATUS_SUCCESS) {
        if (this->last_start_error_ != 0)
          ESP_LOGI(TAG, "advertising started (after refused start, status %u)", this->last_start_error_);
        this->advertising_ = true;
        this->last_start_error_ = 0;
        this->refused_in_a_row_ = 0;
      } else {
        // ESPHome itself never inspects this event, so without this line a
        // refused start is completely silent.
        this->advertising_ = false;
        this->last_start_error_ = (uint8_t) param->adv_start_cmpl.status;
        if (this->refused_in_a_row_ < 255)
          this->refused_in_a_row_++;
        ESP_LOGW(TAG, "advertising start REFUSED by the stack, status %u (%u link(s) open)",
                 (unsigned) param->adv_start_cmpl.status, this->link_count_);
      }
      break;
    case ESP_GAP_BLE_ADV_STOP_COMPLETE_EVT:
      if (param->adv_stop_cmpl.status == ESP_BT_STATUS_SUCCESS)
        this->advertising_ = false;
      break;
    default:
      break;
  }
}

void BLELinkGuard::gatts_event_handler(esp_gatts_cb_event_t event, esp_gatt_if_t gatts_if,
                                       esp_ble_gatts_cb_param_t *param) {
  if (param == nullptr)
    return;
  // Bluedroid delivers CONNECT/DISCONNECT for every LE link to every GATT app,
  // so these two see the lamp link as well as the panel's.
  switch (event) {
    case ESP_GATTS_CONNECT_EVT: {
      const uint64_t addr = to_address_(param->connect.remote_bda);
      const uint8_t role = param->connect.link_role;
      this->add_link_(param->connect.conn_id, role, addr);
      if (role == 1) {
        // A central connected IN: the controller ends legacy connectable
        // advertising as the link forms. Believe that rather than wait for
        // an event that does not come.
        this->advertising_ = false;
        this->resume_expected_ = true;
      } else {
        // The board connected OUT. Advertising should survive this, but this
        // is the transition it was seen to die on -- look again shortly.
        this->next_reassert_ms_ = millis() + AFTER_CENTRAL_CONNECT_MS;
      }
      ESP_LOGI(TAG, "link up (%s, conn %u): %u open, %u free slot(s)", role == 1 ? "peripheral" : "central",
               param->connect.conn_id, this->link_count_, this->free_slots());
      break;
    }
    case ESP_GATTS_DISCONNECT_EVT: {
      const uint64_t addr = to_address_(param->disconnect.remote_bda);
      const int reason = (int) param->disconnect.reason;
      this->remove_link_(param->disconnect.conn_id, addr, reason);
      ESP_LOGI(TAG, "link down (conn %u, reason 0x%02X %s): %u open, %u free slot(s)", param->disconnect.conn_id,
               reason, reason_str(reason), this->link_count_, this->free_slots());
      break;
    }
    default:
      break;
  }
}

void BLELinkGuard::loop() {
  const uint32_t now = millis();
  if (now - this->last_check_ms_ < 1000)
    return;
  this->last_check_ms_ = now;

  auto *ble = esp32_ble::global_ble;
  if (ble == nullptr || !ble->is_active()) {
    // Stack down: every link and advertising went with it.
    this->link_count_ = 0;
    this->advertising_ = false;
    return;
  }
  auto *server = esp32_ble_server::global_ble_server;
  if (server == nullptr || !server->is_running()) {
    // Give the server's own first advertising start time to report back
    // before judging it.
    this->last_attempt_ms_ = now;
    this->next_reassert_ms_ = now + this->reassert_interval_ms_;
    return;
  }
  if (this->free_slots() == 0)
    return;  // nothing could connect anyway

  const bool due = (int32_t) (now - this->next_reassert_ms_) >= 0;
  if (this->advertising_ && !due)
    return;
  const uint32_t pace = this->refused_in_a_row_ > 3 ? RETRY_SLOW_MS : RETRY_MS;
  if (now - this->last_attempt_ms_ < pace && !this->resume_expected_)
    return;

  if (!this->advertising_ && this->resume_expected_) {
    // ESPHome's server only does this itself while its client count, which
    // includes the lamp link, is under max_clients.
    ESP_LOGD(TAG, "resuming advertising after a central connected (%u free slot(s))", this->free_slots());
  } else if (!this->advertising_) {
    this->restarts_++;
    ESP_LOGW(TAG, "advertising was OFF with %u free slot(s) (%u central, %u peripheral link(s)); restarting it (#%u)",
             this->free_slots(), this->central_links(), this->peripheral_links(), (unsigned) this->restarts_);
  } else {
    ESP_LOGV(TAG, "periodic advertising re-assert");
  }
  this->resume_expected_ = false;
  this->last_attempt_ms_ = now;
  this->next_reassert_ms_ = now + this->reassert_interval_ms_;
  // Stop + reconfigure + start through ESPHome's own reference-counted path,
  // so the server's advertising request stays the one in force.
  ble->advertising_refresh();
}

void BLELinkGuard::dump_config() {
  ESP_LOGCONFIG(TAG,
                "BLE link guard:\n"
                "  Connection slots: %u\n"
                "  Re-assert every: %u s",
                (unsigned) USE_ESP32_BLE_MAX_CONNECTIONS, (unsigned) (this->reassert_interval_ms_ / 1000));
}

}  // namespace ble_link_guard
}  // namespace esphome

#endif  // USE_ESP32
