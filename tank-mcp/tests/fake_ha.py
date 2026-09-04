"""A stand-in Home Assistant REST API for the smoke test.

The state values are copied from the live instance so the tests exercise the
same shapes the app will see in production. Service calls are recorded rather
than performed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

NOW = datetime.now(timezone.utc)

STATES: dict[str, dict[str, Any]] = {}
CALLS: list[dict[str, Any]] = []


def _set(entity_id: str, state: Any, **attributes: Any) -> None:
    STATES[entity_id] = {
        "entity_id": entity_id,
        "state": str(state),
        "attributes": attributes,
        "last_changed": NOW.isoformat(),
        "last_updated": NOW.isoformat(),
    }


def reset() -> None:
    STATES.clear()
    CALLS.clear()

    _set("sensor.tank_monitor_water_temperature", 74.53, unit_of_measurement="°F")
    _set("number.tank_monitor_target_temperature", 74.300003)
    _set("sensor.tank_monitor_controller_state", "coasting (overruled)")
    _set("binary_sensor.tank_monitor_heater", "off")
    _set("binary_sensor.tank_monitor_fan", "off")
    _set("sensor.tank_monitor_heater_output", 0.0)
    _set("sensor.tank_monitor_fan_output", 0.0)
    # No pH probe wired yet, so the entity is deliberately absent: exercises
    # the "unavailable" path that used to be a Seneye reading.
    _set("sensor.tank_monitor_tds", 482)
    _set("sensor.tank_monitor_electrical_conductivity", 964)
    _set("sensor.tank_monitor_tank_light_level", 596)
    _set("sensor.tank_monitor_temperature_swing_1h", 0.34)
    _set("sensor.tank_monitor_temperature_drift_rate", 0.00)
    _set("sensor.tank_monitor_predicted_temperature_15_min", 73.66)
    _set("sensor.tank_monitor_model_confidence", 100)
    _set("binary_sensor.tank_monitor_status", "on")
    _set("binary_sensor.tank_monitor_temperature_fault", "off")
    _set("binary_sensor.tank_monitor_heater_not_responding", "off")
    _set("binary_sensor.tank_monitor_fan_not_responding", "off")
    _set("switch.tank_monitor_adaptive_learning", "on")
    _set("sensor.tank_monitor_wi_fi_signal", -50)
    _set("sensor.tank_monitor_ip_address", "192.168.8.137")


    _set("input_number.aquarium_total_ammonia", 0.0)
    _set("input_number.aquarium_nitrite", 0.0)
    _set("input_number.aquarium_nitrate", 5.0)
    _set("input_number.aquarium_gh", 0.0)
    _set("input_number.aquarium_kh", 0.0)
    _set("input_number.aquarium_tds", 430.0)
    _set("input_number.aquarium_ph_manual", 7.4)
    _set("input_number.aquarium_gh_target_min", 6.0)
    _set("input_number.aquarium_gh_target_max", 8.0)
    _set("input_number.aquarium_kh_target_min", 3.0)
    _set("input_number.aquarium_kh_target_max", 4.0)
    _set("input_datetime.aquarium_last_manual_test", "2026-08-20 17:01:15")
    _set("script.aquarium_log_manual_test", "off", friendly_name="Aquarium: log manual test")

    _set("media_player.office", "idle", friendly_name="Office")
    _set("media_player.master_bedroom", "idle", friendly_name="Master Bedroom")


async def get_state(request: Request) -> JSONResponse:
    entity_id = request.path_params["entity_id"]
    if entity_id not in STATES:
        return JSONResponse({"message": "Entity not found."}, status_code=404)
    return JSONResponse(STATES[entity_id])


async def get_states(request: Request) -> JSONResponse:
    return JSONResponse(list(STATES.values()))


async def call_service(request: Request) -> JSONResponse:
    body = await request.json() if await request.body() else {}
    domain = request.path_params["domain"]
    service = request.path_params["service"]
    CALLS.append({"domain": domain, "service": service, "data": body})

    # Mirror the writes the real services would perform, so a tool that reads
    # back after writing sees what Home Assistant would have shown it.
    if (domain, service) == ("input_number", "set_value"):
        _set(body["entity_id"], body["value"])
    if (domain, service) == ("number", "set_value"):
        _set(body["entity_id"], body["value"])
    if (domain, service) == ("script", "turn_on"):
        _set("input_datetime.aquarium_last_manual_test", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    return JSONResponse([])


async def history(request: Request) -> JSONResponse:
    entity_id = request.query_params.get("filter_entity_id", "")
    if entity_id not in STATES:
        return JSONResponse([])
    base = float(STATES[entity_id]["state"])
    samples = [
        {
            "state": str(round(base + offset, 2)),
            "last_changed": (NOW - timedelta(hours=hours)).isoformat(),
        }
        for hours, offset in ((6, -0.3), (4, 0.1), (2, 0.2), (0, 0.0))
    ]
    samples.append({"state": "unavailable", "last_changed": NOW.isoformat()})
    return JSONResponse([samples])


def build() -> Starlette:
    reset()
    return Starlette(
        routes=[
            Route("/api/states", get_states, methods=["GET"]),
            Route("/api/states/{entity_id}", get_state, methods=["GET"]),
            Route("/api/services/{domain}/{service}", call_service, methods=["POST"]),
            Route("/api/history/period/{start}", history, methods=["GET"]),
        ]
    )
