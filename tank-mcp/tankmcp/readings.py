"""Assemble raw Home Assistant states into answers with a verdict attached.

Every tool returns the number *and* what it means. A bare "pH 7.33" makes the
caller re-derive the tank's tolerances on every question; "7.33, in range"
does not.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import entities as E
from .ha import HomeAssistant


def _age_hours(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        stamp = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - stamp).total_seconds() / 3600.0


def _round(value: float | None, places: int = 2) -> float | None:
    return None if value is None else round(value, places)


def temperature_verdict(temp_f: float | None, target_f: float | None) -> str:
    if temp_f is None:
        return "no reading"
    if temp_f < E.TEMP_COLD_FLOOR_F:
        return "too cold — below the cold floor for the loaches and blue-eyes"
    if target_f is None:
        return "no setpoint published"
    delta = temp_f - target_f
    if abs(delta) <= E.TEMP_BAND_F:
        return "on target"
    return f"{abs(delta):.1f} °F {'above' if delta > 0 else 'below'} target"


def total_ammonia_verdict(nh3: float | None) -> str:
    """TOTAL ammonia from the API kit, not free NH3. Different scale entirely."""
    if nh3 is None:
        return "not tested"
    if nh3 > E.TOTAL_AMMONIA_HIGH:
        return "high — water change now"
    if nh3 > E.TOTAL_AMMONIA_CAUTION:
        return "detectable — a cycled filter should read zero"
    return "zero at last test"


def ph_verdict(ph: float | None) -> str:
    if ph is None:
        return "no reading"
    if ph < E.PH_MIN:
        return "low"
    if ph > E.PH_MAX:
        return "high"
    return "in range"


def nitrite_verdict(no2: float | None) -> str:
    if no2 is None:
        return "not tested"
    if no2 > E.NITRITE_HIGH:
        return "high — cycle problem"
    if no2 > E.NITRITE_CAUTION:
        return "detectable — should be zero"
    return "zero"


def nitrate_verdict(no3: float | None) -> str:
    if no3 is None:
        return "not tested"
    if no3 > E.NITRATE_HIGH:
        return "high — water change due"
    if no3 > E.NITRATE_GOOD:
        return "acceptable"
    return "good"


def _range_verdict(value: float | None, low: float | None, high: float | None) -> str:
    if value is None:
        return "not tested"
    if low is None or high is None:
        return "no target set"
    if value < low:
        return "below target"
    if value > high:
        return "above target"
    return "in range"


async def tank_status(ha: HomeAssistant, tank: E.TankEntities) -> dict[str, Any]:
    temp = await ha.number(tank.temperature)
    target = await ha.number(tank.target_temperature)
    online = await ha.is_on(tank.online)

    return {
        "device": tank.prefix,
        "online": online,
        "temperature_f": _round(temp),
        "target_f": _round(target),
        "verdict": temperature_verdict(temp, target),
        "predicted_temperature_15min_f": _round(await ha.number(tank.predicted_temperature)),
        "swing_last_hour_f": _round(await ha.number(tank.swing_1h)),
        "drift_rate_f_per_hour": _round(await ha.number(tank.drift_rate)),
        "controller_state": await ha.value(tank.controller_state),
        "heater_on": await ha.is_on(tank.heater),
        "heater_duty_percent": _round(await ha.number(tank.heater_output), 1),
        "fan_on": await ha.is_on(tank.fan),
        "fan_duty_percent": _round(await ha.number(tank.fan_output), 1),
        "tds_ppm": _round(await ha.number(tank.tds), 0),
        "conductivity_us_cm": _round(await ha.number(tank.conductivity), 0),
        "light_level_lx": _round(await ha.number(tank.light), 0),
        "model_confidence_percent": _round(await ha.number(tank.model_confidence), 0),
        "adaptive_learning": await ha.is_on(tank.adaptive_learning),
        "faults": {
            "temperature_probe": await ha.is_on(tank.temperature_fault),
            "heater_not_responding": await ha.is_on(tank.heater_not_responding),
            "fan_not_responding": await ha.is_on(tank.fan_not_responding),
        },
        "ip_address": await ha.value(tank.ip_address),
        "wifi_signal_dbm": _round(await ha.number(tank.wifi_signal), 0),
    }


async def ph_status(ha: HomeAssistant, tank: E.TankEntities) -> dict[str, Any]:
    """pH from the controller's glass electrode, falling back to the test kit.

    Returns source="unavailable" when neither exists rather than inventing a
    number. Callers must handle that: an absent reading is information, and
    presenting a stale or guessed one as current is how this tank got treated
    for a pH crisis it never had.
    """
    probe = await ha.number(tank.ph)
    if probe is not None:
        return {
            "ph": _round(probe),
            "verdict": ph_verdict(probe),
            "source": "probe",
            "live": True,
            "note": "DFRobot glass electrode on the controller. Calibrate against pH 4.00 and 7.00 buffer every few months.",
        }

    manual = await ha.number(E.MANUAL["ph"])
    last_test = await ha.value(E.LAST_TEST)
    age = _age_hours(last_test.replace(" ", "T") if last_test else None)
    if manual is not None:
        return {
            "ph": _round(manual),
            "verdict": ph_verdict(manual),
            "source": "test kit",
            "live": False,
            "last_tested": last_test,
            "test_age_hours": None if age is None else round(age, 1),
            "note": "No pH probe is wired to the controller, so this is your last manual liquid-kit entry. Use the LOW range bottle - high range bottoms out at 7.4 and cannot resolve this tank.",
        }

    return {
        "ph": None,
        "verdict": "no reading",
        "source": "unavailable",
        "live": False,
        "note": "No pH probe on the controller and nothing logged from a test kit. pH is unknown.",
    }


async def water_chemistry(ha: HomeAssistant, tank: E.TankEntities) -> dict[str, Any]:
    """Every chemistry value the tank has, measured or typed in."""
    ph = await ph_status(ha, tank)

    total_ammonia = await ha.number(E.MANUAL["total_ammonia"])
    nitrite = await ha.number(E.MANUAL["nitrite"])
    nitrate = await ha.number(E.MANUAL["nitrate"])
    gh = await ha.number(E.MANUAL["gh"])
    kh = await ha.number(E.MANUAL["kh"])
    tds = await ha.number(E.MANUAL["tds"])

    gh_min = await ha.number(E.TARGETS["gh_min"])
    gh_max = await ha.number(E.TARGETS["gh_max"])
    kh_min = await ha.number(E.TARGETS["kh_min"])
    kh_max = await ha.number(E.TARGETS["kh_max"])

    last_test = await ha.value(E.LAST_TEST)
    test_age = _age_hours(last_test.replace(" ", "T") if last_test else None)

    def _degrees(ppm: float | None) -> float | None:
        return None if ppm is None else round(ppm / E.PPM_PER_DEGREE, 1)

    return {
        "ph": ph,
        "from_test_kit": {
            "total_ammonia_ppm": _round(total_ammonia, 2),
            "total_ammonia_verdict": total_ammonia_verdict(total_ammonia),
            "nitrite_ppm": _round(nitrite, 2),
            "nitrite_verdict": nitrite_verdict(nitrite),
            "nitrate_ppm": _round(nitrate, 1),
            "nitrate_verdict": nitrate_verdict(nitrate),
            "gh_ppm": _round(gh, 0),
            "gh_dgh": _degrees(gh),
            "gh_target_ppm": [gh_min, gh_max],
            "gh_verdict": _range_verdict(gh, gh_min, gh_max),
            "kh_ppm": _round(kh, 0),
            "kh_dkh": _degrees(kh),
            "kh_target_ppm": [kh_min, kh_max],
            "kh_verdict": _range_verdict(kh, kh_min, kh_max),
            "tds_ppm": _round(tds, 0),
            "last_tested": last_test,
            "test_age_hours": None if test_age is None else round(test_age, 1),
            "test_age_days": None if test_age is None else round(test_age / 24, 1),
        },
        "note": (
            "GH and KH are stored and targeted in PPM, matching how the API kit "
            "and the strips report. The degree figures are the same values "
            f"divided by {E.PPM_PER_DEGREE}. This used to be the other way round "
            "and the conversion was applied to values that were already ppm, "
            "which inflated every reported GH/KH by ~18x."
        ),
    }


def concerns(status: dict[str, Any], chemistry: dict[str, Any]) -> list[str]:
    """Everything currently worth a human's attention, in plain sentences."""
    found: list[str] = []

    if not status.get("online"):
        found.append(
            "The controller is offline, so temperature is unregulated and "
            "unmonitored. There is no second probe to fall back on."
        )
    else:
        verdict = status.get("verdict")
        if verdict and verdict != "on target":
            found.append(f"Temperature is {verdict}.")
        temp = status.get("temperature_f")
        if temp is not None and temp < E.TEMP_COLD_FLOOR_F:
            found.append("The water is below the cold floor for the loaches and blue-eyes.")
        faults = status.get("faults", {})
        if faults.get("temperature_probe"):
            found.append("The temperature probe has stopped responding and the heater is cut.")
        if faults.get("heater_not_responding"):
            found.append("The heater is being driven but the water is not warming.")
        if faults.get("fan_not_responding"):
            found.append("The fan is being driven but the water is not cooling.")

    ph = chemistry.get("ph", {})
    if ph.get("source") == "unavailable":
        found.append("There is no pH reading at all - no probe, and nothing logged from a test kit.")
    elif ph.get("verdict") in ("low", "high"):
        found.append(f"pH is {ph.get('ph')}, {ph.get('verdict')}.")

    kit = chemistry.get("from_test_kit", {})

    nh3 = kit.get("total_ammonia_ppm")
    if nh3 is not None and nh3 > E.TOTAL_AMMONIA_HIGH:
        found.append(f"Total ammonia is {nh3} ppm. Water change, and check the filter chamber.")
    elif nh3 is not None and nh3 > E.TOTAL_AMMONIA_CAUTION:
        found.append(f"Total ammonia is {nh3} ppm - a cycled filter should read zero.")

    if kit.get("nitrite_verdict") not in (None, "safe", "no reading"):
        found.append(f"Nitrite is {kit.get('nitrite_ppm')} ppm.")
    if kit.get("nitrate_verdict") == "high":
        found.append(f"Nitrate is {kit.get('nitrate_ppm')} ppm - due a water change.")

    for name in ("gh", "kh"):
        v = kit.get(f"{name}_verdict")
        if v in ("low", "high"):
            found.append(f"{name.upper()} is {kit.get(f'{name}_ppm')} ppm, {v}.")

    age_days = kit.get("test_age_days")
    if age_days is not None and age_days > 10:
        found.append(
            f"The last test kit entry is {age_days} days old. Every chemistry "
            "value above is that stale."
        )

    return found
