"""Turn readings into something an Echo can say out loud.

Alexa reads text literally, so nothing here emits a degree sign, a slash, or
a bare decimal that would be spelled out oddly. Temperatures are Fahrenheit,
as everywhere else the user sees them.
"""

from __future__ import annotations

from typing import Any

from .store import Inventory


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else (plural or singular + 's')}"


def tank_report(
    status: dict[str, Any],
    chemistry: dict[str, Any],
    seneye: dict[str, Any],
    problems: list[str],
) -> str:
    if status.get("online") is False:
        return "The tank controller is offline, so I have no current readings."

    parts: list[str] = []

    temp = status.get("temperature_f")
    target = status.get("target_f")
    if temp is None:
        parts.append("I have no water temperature reading.")
    else:
        line = f"The tank is {temp:.1f} degrees"
        if target is not None:
            line += f", target {target:.1f}"
        verdict = status.get("verdict")
        if verdict == "on target":
            line += ", on target"
        parts.append(line + ".")

    state = status.get("controller_state")
    if status.get("heater_on"):
        parts.append(f"The heater is on at {status.get('heater_duty_percent', 0):.0f} percent.")
    elif status.get("fan_on"):
        parts.append(f"The cooling fan is on at {status.get('fan_duty_percent', 0):.0f} percent.")
    elif state:
        parts.append(f"The controller is {state}.")

    ph = seneye.get("ph")
    nh3 = seneye.get("free_ammonia_mg_l")
    if ph is not None:
        parts.append(f"pH is {ph:.2f}, {seneye.get('ph_verdict')}.")
    if nh3 is not None:
        verdict = seneye.get("free_ammonia_verdict")
        if verdict == "safe":
            parts.append("Free ammonia is safe.")
        else:
            parts.append(f"Free ammonia is {nh3:.3f} milligrams per litre, {verdict}.")

    kit = chemistry["from_test_kit"]
    if kit.get("nitrate_ppm") is not None:
        parts.append(f"Nitrate is {kit['nitrate_ppm']:.0f} parts per million, {kit['nitrate_verdict']}.")
    if kit.get("tds_ppm") is not None:
        parts.append(f"TDS is {kit['tds_ppm']:.0f}.")

    age_days = kit.get("test_age_days")
    if age_days is not None and age_days >= 7:
        parts.append(f"The last manual test was {age_days:.0f} days ago.")

    if problems:
        parts.append("Things needing attention: " + " ".join(problems))
    else:
        parts.append("Nothing needs attention.")

    return " ".join(parts)


def livestock_report(
    inventory: list[Inventory],
    losses_30d: int,
    days_since_loss: int | None,
) -> str:
    alive = [item for item in inventory if item.alive > 0]
    if not alive:
        return "There is nothing recorded as living in the tank yet."

    total = sum(item.alive for item in alive)
    listing = ", ".join(_plural(item.alive, item.species) for item in alive)
    parts = [f"The tank has {_plural(total, 'animal')} on record: {listing}."]

    if losses_30d:
        parts.append(f"{_plural(losses_30d, 'loss', 'losses')} in the last thirty days.")
    else:
        parts.append("No losses in the last thirty days.")

    if days_since_loss is not None:
        if days_since_loss == 0:
            parts.append("The most recent loss was today.")
        else:
            parts.append(f"The last loss was {_plural(days_since_loss, 'day')} ago.")

    return " ".join(parts)
