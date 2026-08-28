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


def free_ammonia_verdict(nh3: float | None) -> str:
    if nh3 is None:
        return "no reading"
    if nh3 >= E.FREE_AMMONIA_TOXIC:
        return "toxic — act now"
    if nh3 >= E.FREE_AMMONIA_CAUTION:
        return "elevated"
    return "safe"


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


def probe_verdict(esp_f: float | None, seneye_f: float | None) -> dict[str, Any]:
    """Cross-check the controller's DS18B20 against the Seneye's own probe.

    The controller drives the heater from the DS18B20 alone, so this is the
    only independent check that it has not drifted.
    """
    if esp_f is None or seneye_f is None:
        return {"difference_f": None, "verdict": "cannot compare — a probe has no reading"}
    diff = abs(esp_f - seneye_f)
    if diff <= E.PROBE_AGREE_F:
        verdict = "agree"
    elif diff <= E.PROBE_DRIFT_F:
        verdict = "drifting — watch it"
    else:
        verdict = "disagree — one probe has failed"
    return {"difference_f": round(diff, 2), "verdict": verdict}


async def tank_status(ha: HomeAssistant, tank: E.TankEntities, seneye: E.SeneyeEntities) -> dict[str, Any]:
    temp = await ha.number(tank.temperature)
    target = await ha.number(tank.target_temperature)
    seneye_temp = await ha.number(seneye.temperature)
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
        "probe_cross_check": probe_verdict(temp, seneye_temp),
        "ip_address": await ha.value(tank.ip_address),
        "wifi_signal_dbm": _round(await ha.number(tank.wifi_signal), 0),
    }


async def seneye_status(ha: HomeAssistant, seneye: E.SeneyeEntities) -> dict[str, Any]:
    ph = await ha.number(seneye.ph)
    nh3 = await ha.number(seneye.free_ammonia)
    last = await ha.value(seneye.last_reading)
    expires = await ha.value(seneye.slide_expires)

    age = _age_hours(last)
    expiry_age = _age_hours(expires)
    slide_days_left = None if expiry_age is None else round(-expiry_age / 24, 1)

    return {
        "ph": _round(ph),
        "ph_verdict": ph_verdict(ph),
        "free_ammonia_mg_l": None if nh3 is None else round(nh3, 4),
        "free_ammonia_verdict": free_ammonia_verdict(nh3),
        "temperature_f": _round(await ha.number(seneye.temperature)),
        "last_reading": last,
        "reading_age_hours": None if age is None else round(age, 1),
        "stale": None if age is None else age > 2,
        "slide_expires": expires,
        "slide_days_remaining": slide_days_left,
        "slide_verdict": (
            "unknown"
            if slide_days_left is None
            else "expired" if slide_days_left <= 0
            else "replace soon" if slide_days_left <= 7
            else "ok"
        ),
    }


async def water_chemistry(ha: HomeAssistant, seneye: E.SeneyeEntities) -> dict[str, Any]:
    """Every chemistry value the tank has, measured or typed in."""
    ph = await ha.number(seneye.ph)
    nh3 = await ha.number(seneye.free_ammonia)

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

    def _ppm(degrees: float | None) -> float | None:
        return None if degrees is None else round(degrees * E.PPM_PER_DEGREE)

    return {
        "measured_by_seneye": {
            "ph": _round(ph),
            "ph_verdict": ph_verdict(ph),
            "free_ammonia_mg_l": None if nh3 is None else round(nh3, 4),
            "free_ammonia_verdict": free_ammonia_verdict(nh3),
        },
        "from_test_kit": {
            "total_ammonia_ppm": _round(total_ammonia, 2),
            "nitrite_ppm": _round(nitrite, 2),
            "nitrite_verdict": nitrite_verdict(nitrite),
            "nitrate_ppm": _round(nitrate, 1),
            "nitrate_verdict": nitrate_verdict(nitrate),
            "gh_dgh": _round(gh, 1),
            "gh_ppm": _ppm(gh),
            "gh_target_dgh": [gh_min, gh_max],
            "gh_verdict": _range_verdict(gh, gh_min, gh_max),
            "kh_dkh": _round(kh, 1),
            "kh_ppm": _ppm(kh),
            "kh_target_dkh": [kh_min, kh_max],
            "kh_verdict": _range_verdict(kh, kh_min, kh_max),
            "tds_ppm": _round(tds, 0),
            "last_tested": last_test,
            "test_age_hours": None if test_age is None else round(test_age, 1),
            "test_age_days": None if test_age is None else round(test_age / 24, 1),
        },
        "note": (
            "GH and KH are stored in degrees because the Home Assistant target "
            "ranges are; the ppm figures are the same values converted at "
            f"{E.PPM_PER_DEGREE} ppm per degree for comparison against test strips."
        ),
    }


def concerns(status: dict[str, Any], chemistry: dict[str, Any], seneye: dict[str, Any]) -> list[str]:
    """Everything currently wrong, worst first. Empty means the tank is fine."""
    found: list[str] = []

    if status.get("online") is False:
        found.append("The tank controller is offline.")
    if status["faults"]["temperature_probe"]:
        found.append("The temperature probe is faulted.")
    if status["faults"]["heater_not_responding"]:
        found.append("The heater is not responding.")
    if status["faults"]["fan_not_responding"]:
        found.append("The fan is not responding.")

    nh3 = seneye.get("free_ammonia_verdict")
    if nh3 == "toxic — act now":
        found.append(
            f"Free ammonia is {seneye['free_ammonia_mg_l']} mg/L, which is toxic."
        )
    elif nh3 == "elevated":
        found.append(f"Free ammonia is elevated at {seneye['free_ammonia_mg_l']} mg/L.")

    verdict = status.get("verdict", "")
    if verdict not in ("on target", "no reading"):
        found.append(f"Water temperature is {status['temperature_f']} °F — {verdict}.")

    if seneye.get("ph_verdict") in ("low", "high"):
        found.append(f"pH is {seneye['ph']}, {seneye['ph_verdict']}.")

    kit = chemistry["from_test_kit"]
    if kit["nitrite_verdict"] in ("detectable — should be zero", "high — cycle problem"):
        found.append(f"Nitrite is {kit['nitrite_ppm']} ppm — it should be zero.")
    if kit["nitrate_verdict"] == "high — water change due":
        found.append(f"Nitrate is {kit['nitrate_ppm']} ppm, high enough for a water change.")
    for name, key in (("GH", "gh"), ("KH", "kh")):
        if kit[f"{key}_verdict"] in ("below target", "above target"):
            found.append(
                f"{name} is {kit[f'{key}_dgh' if key == 'gh' else f'{key}_dkh']} degrees, "
                f"{kit[f'{key}_verdict']}."
            )

    cross = status["probe_cross_check"]["verdict"]
    if cross.startswith("disagree"):
        found.append(
            "The two temperature probes disagree by "
            f"{status['probe_cross_check']['difference_f']} °F — one has failed."
        )

    if seneye.get("slide_verdict") == "expired":
        found.append("The Seneye slide has expired.")
    elif seneye.get("slide_verdict") == "replace soon":
        found.append(f"The Seneye slide expires in {seneye['slide_days_remaining']} days.")

    if seneye.get("stale"):
        found.append(
            f"The Seneye has not reported for {seneye['reading_age_hours']} hours."
        )

    return found
