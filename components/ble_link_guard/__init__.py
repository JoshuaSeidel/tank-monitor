"""Keeps the board's BLE GATT server advertising whenever a connection slot
is free, and remembers why each peer's last link ended.

Why this exists (ESPHome 2026.9, ESP-IDF 5.5 Bluedroid):

  * Bluedroid reports EVERY LE link to EVERY registered GATT application
    (gatt_send_conn_cback in stack/gatt/gatt_main.c), so the GATT server sees
    ESP_GATTS_CONNECT_EVT for the board's own outgoing client link to the lamp
    too. ESPHome's BLEServer counts that link as one of its clients and only
    resumes advertising after a connect while client_count < max_clients --
    the lamp silently spends one of the panel's slots.
  * ESPHome never looks at ESP_GAP_BLE_ADV_START_COMPLETE_EVT, so a refused
    advertising start (or a controller that stops advertising when the board
    takes the central role) is invisible: nothing logs it and nothing retries.

This component watches the same events, counts links by their real role, and
re-asserts advertising when a slot is free and advertising is not known to be
running. It also keeps the HCI reason of each peer's last disconnect, which is
the one fact that tells a flaky radio link from a peer hanging up.
"""

import esphome.codegen as cg
from esphome.components import esp32_ble
import esphome.config_validation as cv
from esphome.const import CONF_ID

CODEOWNERS = ["@tank-monitor"]
DEPENDENCIES = ["esp32", "esp32_ble_server"]
AUTO_LOAD = ["esp32_ble"]

CONF_REASSERT_INTERVAL = "reassert_interval"

ble_link_guard_ns = cg.esphome_ns.namespace("ble_link_guard")
BLELinkGuard = ble_link_guard_ns.class_("BLELinkGuard", cg.Component)

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.declare_id(BLELinkGuard),
        cv.GenerateID(esp32_ble.CONF_BLE_ID): cv.use_id(esp32_ble.ESP32BLE),
        # Advertising is re-asserted this often even when it is believed to
        # be running, because the failure being guarded against is exactly
        # the controller stopping without telling the host.
        cv.Optional(
            CONF_REASSERT_INTERVAL, default="60s"
        ): cv.positive_time_period_milliseconds,
    }
).extend(cv.COMPONENT_SCHEMA)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    cg.add(var.set_reassert_interval(config[CONF_REASSERT_INTERVAL]))
    parent = await cg.get_variable(config[esp32_ble.CONF_BLE_ID])
    esp32_ble.register_gap_event_handler(parent, var)
    esp32_ble.register_gatts_event_handler(parent, var)
