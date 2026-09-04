"""Entity-id map and the thresholds used to turn readings into verdicts.

Everything user-facing is Fahrenheit; the ESP32 keeps its control maths in
Celsius internally but every entity it publishes is already in F, so nothing
here converts.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- Water chemistry bands ------------------------------------------------
#
# Ammonia is TOTAL ammonia from the API Freshwater Master kit, typed in by
# hand. It used to be free NH3 from a Seneye slide, whose bands (0.02/0.05
# mg/L) were an order of magnitude tighter because at planted-tank pH most
# ammonia is non-toxic NH4+. Do not mix the two scales up.
#
# In a cycled tank ANY detectable total ammonia is worth acting on -- the
# filter should consume it faster than the kit can resolve. 0.25 ppm is the
# kit's first visible band.

TOTAL_AMMONIA_CAUTION = 0.0  # ppm; anything visible at all
TOTAL_AMMONIA_HIGH = 0.5

NITRITE_CAUTION = 0.0  # ppm; anything measurable is a cycle problem
NITRITE_HIGH = 0.25

NITRATE_GOOD = 20.0  # ppm
NITRATE_HIGH = 40.0

# The floor is set by the emerald dwarf danios (Danio erythromicron), an Inle
# Lake fish wanting 7.0-8.0. Every other species here tolerates lower, so one
# fish caps how far CO2 injection can take the pH down.
PH_MIN = 7.0
PH_MAX = 7.8

# Kuhli loaches and blue-eyes set the cold floor; it matches the ESP32's blue
# TOO COLD band and the Home Assistant cold-floor alarm.
TEMP_COLD_FLOOR_F = 73.4
TEMP_BAND_F = 0.5  # how far from setpoint still counts as on-target

# There is no probe cross-check any more. The Seneye that provided the second
# temperature reading was returned on 2026-09-04 after its pH proved ~0.45 low
# against an API liquid test. The controller drives the heater from one
# DS18B20 and nothing independently checks it -- verify by hand occasionally.

# Test strips read GH/KH in ppm; the Home Assistant helpers and their target
# ranges are stored in degrees. One degree of hardness is 17.9 ppm CaCO3.
PPM_PER_DEGREE = 17.9


@dataclass(frozen=True)
class TankEntities:
    """Entity ids for one ESP32 controller, derived from its object-id prefix."""

    prefix: str

    @property
    def temperature(self) -> str:
        return f"sensor.{self.prefix}_water_temperature"

    @property
    def target_temperature(self) -> str:
        return f"number.{self.prefix}_target_temperature"

    @property
    def controller_state(self) -> str:
        return f"sensor.{self.prefix}_controller_state"

    @property
    def heater(self) -> str:
        return f"binary_sensor.{self.prefix}_heater"

    @property
    def fan(self) -> str:
        return f"binary_sensor.{self.prefix}_fan"

    @property
    def heater_output(self) -> str:
        return f"sensor.{self.prefix}_heater_output"

    @property
    def fan_output(self) -> str:
        return f"sensor.{self.prefix}_fan_output"

    @property
    def tds(self) -> str:
        return f"sensor.{self.prefix}_tds"

    @property
    def conductivity(self) -> str:
        return f"sensor.{self.prefix}_electrical_conductivity"

    @property
    def light(self) -> str:
        return f"sensor.{self.prefix}_tank_light_level"

    @property
    def swing_1h(self) -> str:
        return f"sensor.{self.prefix}_temperature_swing_1h"

    @property
    def drift_rate(self) -> str:
        return f"sensor.{self.prefix}_temperature_drift_rate"

    @property
    def predicted_temperature(self) -> str:
        return f"sensor.{self.prefix}_predicted_temperature_15_min"

    @property
    def model_confidence(self) -> str:
        return f"sensor.{self.prefix}_model_confidence"

    @property
    def online(self) -> str:
        return f"binary_sensor.{self.prefix}_status"

    @property
    def temperature_fault(self) -> str:
        return f"binary_sensor.{self.prefix}_temperature_fault"

    @property
    def heater_not_responding(self) -> str:
        return f"binary_sensor.{self.prefix}_heater_not_responding"

    @property
    def fan_not_responding(self) -> str:
        return f"binary_sensor.{self.prefix}_fan_not_responding"

    @property
    def adaptive_learning(self) -> str:
        return f"switch.{self.prefix}_adaptive_learning"

    @property
    def wifi_signal(self) -> str:
        return f"sensor.{self.prefix}_wi_fi_signal"

    @property
    def ip_address(self) -> str:
        return f"sensor.{self.prefix}_ip_address"

    @property
    def ph(self) -> str:
        """DFRobot SEN0169-V2 glass electrode on the controller.

        This entity does not exist until that probe is wired and calibrated,
        so every reader here must tolerate it being absent rather than
        assuming a number. That is deliberate: the previous continuous pH
        source could not be calibrated, and trusting it over a liquid test
        cost this project three days of wrong conclusions.
        """
        return f"sensor.{self.prefix}_water_ph"


# Manual test-kit helpers. These already exist in Home Assistant and are
# shared with the dashboard's "Manual tests" view and the MQTT bridge that
# feeds the ESP32 panel, so this app writes to them rather than duplicating.
MANUAL = {
    "total_ammonia": "input_number.aquarium_total_ammonia",
    "nitrite": "input_number.aquarium_nitrite",
    "nitrate": "input_number.aquarium_nitrate",
    "gh": "input_number.aquarium_gh",
    "kh": "input_number.aquarium_kh",
    "tds": "input_number.aquarium_tds",
    "ph": "input_number.aquarium_ph_manual",
}

TARGETS = {
    "gh_min": "input_number.aquarium_gh_target_min",
    "gh_max": "input_number.aquarium_gh_target_max",
    "kh_min": "input_number.aquarium_kh_target_min",
    "kh_max": "input_number.aquarium_kh_target_max",
}

LAST_TEST = "input_datetime.aquarium_last_manual_test"
LOG_TEST_SCRIPT = "script.aquarium_log_manual_test"
