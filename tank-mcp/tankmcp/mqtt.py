"""Mirror the livestock ledger into Home Assistant over MQTT discovery.

Without this the ledger would only be reachable through MCP, which means no
dashboard card and nothing for an Alexa routine to read. Publishing retained
discovery + state gives Home Assistant real sensor entities that survive both
this app and the broker restarting.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import paho.mqtt.client as mqtt

_LOGGER = logging.getLogger(__name__)

STATE_TOPIC = "tank-monitor/livestock/state"
AVAILABILITY_TOPIC = "tank-monitor/livestock/availability"
DISCOVERY_PREFIX = "homeassistant"
DEVICE_ID = "aquarium_livestock"

DEVICE = {
    "identifiers": [DEVICE_ID],
    "name": "Aquarium Livestock",
    "manufacturer": "tank-monitor",
    "model": "Tank MCP ledger",
}

# (object_id, name, value_template, unit, device_class, icon)
#
# Names are relative to the device: Home Assistant prefixes the device
# name onto each one, so "Total" here becomes
# sensor.aquarium_livestock_total, not ..._livestock_total.
SENSORS: list[tuple[str, str, str, str | None, str | None, str]] = [
    (
        "livestock_total",
        "Total",
        "{{ value_json.total_alive }}",
        "animals",
        None,
        "mdi:fishbowl",
    ),
    (
        "livestock_losses_7d",
        "Losses 7d",
        "{{ value_json.losses_7d }}",
        "animals",
        None,
        "mdi:skull-outline",
    ),
    (
        "livestock_losses_30d",
        "Losses 30d",
        "{{ value_json.losses_30d }}",
        "animals",
        None,
        "mdi:skull-outline",
    ),
    (
        "livestock_last_loss",
        "Last Loss",
        "{{ value_json.last_loss_on if value_json.last_loss_on else 'unknown' }}",
        None,
        "date",
        "mdi:calendar-alert",
    ),
    (
        "livestock_days_since_loss",
        "Days Since Loss",
        "{{ value_json.days_since_loss if value_json.days_since_loss is not none else 'unknown' }}",
        "d",
        None,
        "mdi:calendar-check",
    ),
]


class LivestockPublisher:
    def __init__(
        self, host: str, port: int, username: str, password: str
    ) -> None:
        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id="tank-mcp-livestock"
        )
        if username:
            self._client.username_pw_set(username, password)
        self._client.will_set(AVAILABILITY_TOPIC, "offline", retain=True)
        self._client.on_connect = self._on_connect
        self._host = host
        self._port = port
        self._latest: dict[str, Any] | None = None

    def start(self) -> None:
        self._client.connect_async(self._host, self._port, keepalive=60)
        self._client.loop_start()

    def stop(self) -> None:
        self._client.publish(AVAILABILITY_TOPIC, "offline", retain=True)
        self._client.loop_stop()
        self._client.disconnect()

    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: Any, rc: Any, properties: Any = None) -> None:
        if getattr(rc, "is_failure", False) or (isinstance(rc, int) and rc != 0):
            _LOGGER.error("MQTT connection refused: %s", rc)
            return
        _LOGGER.info("MQTT connected; publishing livestock discovery")
        self._publish_discovery()
        client.publish(AVAILABILITY_TOPIC, "online", retain=True)
        # A reconnect after a broker restart has to replay the payload; the
        # retained state topic may have been lost with it.
        if self._latest is not None:
            self.publish(self._latest)

    def _publish_discovery(self) -> None:
        for object_id, name, template, unit, device_class, icon in SENSORS:
            payload: dict[str, Any] = {
                "name": name,
                "unique_id": f"{DEVICE_ID}_{object_id}",
                "state_topic": STATE_TOPIC,
                "value_template": template,
                "json_attributes_topic": STATE_TOPIC,
                "availability_topic": AVAILABILITY_TOPIC,
                "icon": icon,
                "device": DEVICE,
            }
            if unit:
                payload["unit_of_measurement"] = unit
            if device_class:
                payload["device_class"] = device_class
            self._client.publish(
                f"{DISCOVERY_PREFIX}/sensor/{DEVICE_ID}/{object_id}/config",
                json.dumps(payload),
                retain=True,
            )

    def publish(self, state: dict[str, Any]) -> None:
        """Publish the current ledger summary, retained."""
        self._latest = state
        self._client.publish(STATE_TOPIC, json.dumps(state), retain=True)
