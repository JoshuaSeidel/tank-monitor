#!/usr/bin/env python3
"""Desktop preview of the 10.1" P4 panel UI: renders the real generated LVGL
UI with ESPHome's SDL host platform and saves a 1024x600 screenshot.

    python3 tools/p4_preview.py               # every scenario
    python3 tools/p4_preview.py home alert    # just these

Needs ESPHome >= 2026.10 and SDL2 (brew install sdl2). Screenshots land in
design/p4-panel/firmware-shots/<scenario>.png. It renders headless (no window)
and saves each frame with ESPHome's snapshot.take, so no screen-recording
permission is needed.

PREVIEW ONLY. Nothing here is flashed to the panel. The host platform has
no BLE and no MQTT, so this stands in for both: the data globals are lifted
from the real packages (panel_p4_tank.yaml, panel_p4_feeds.yaml) so they
cannot drift, and each scenario fills them with SAMPLE values chosen to
exercise one state of the UI (normal, alert, stale link, night...). The
values are illustrative, not readings.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import gen_panel_p4_ui as gen  # noqa: E402

WORK = ROOT / ".esphome-preview"
SHOTS = ROOT / "design" / "p4-panel" / "firmware-shots"
ESPHOME = os.environ.get("ESPHOME", str(Path.home() / ".venvs/esphome-p4/bin/esphome"))

SCENARIOS = ["home", "t75", "t16", "wc", "alert", "stale", "night"]

TANK_VARS = [
    dict(tank="t75", tank_name="75 Gallon", mac="00:00:00:00:00:00", fields="20",
         version="3", ph_from_ble="true"),
    dict(tank="t16", tank_name="Nano", mac="00:00:00:00:00:00", fields="15",
         version="2", ph_from_ble="false"),
]


class _Loose(yaml.SafeLoader):
    """Reads ESPHome YAML well enough to lift the globals: lists out."""


_Loose.add_multi_constructor("!", lambda loader, suffix, node: None)


def lifted_globals():
    out = []
    for v in TANK_VARS:
        text = (ROOT / "packages/panel_p4_tank.yaml").read_text()
        for k, val in v.items():
            text = text.replace("${" + k + "}", val)
        out += yaml.load(text, Loader=_Loose)["globals"]
    out += yaml.load((ROOT / "packages/panel_p4_feeds.yaml").read_text(), Loader=_Loose)["globals"]
    for g in out:
        g["restore_value"] = False
    return out


# Sample data per scenario. C++ run once at boot, after LVGL is up.
SCENARIO_CPP = r"""
const char *sc = getenv("P4_SCENARIO") ? getenv("P4_SCENARIO") : "home";
const std::string s(sc);
const uint32_t now = millis();
const uint32_t epoch = id(sntp_time).now().is_valid() ? id(sntp_time).now().timestamp : 0;
// ---- 75 gal: healthy, heater trickling
id(t75_temp) = 74.9f; id(t75_temp_b) = 75.1f; id(t75_grad) = -0.2f;
id(t75_sp) = 75.0f; id(t75_swing) = 0.5f; id(t75_drift) = 0.01f; id(t75_conf) = 94;
id(t75_heat) = 14; id(t75_heat_on) = true; id(t75_fan) = 0; id(t75_fan_on) = false;
id(t75_fault) = false; id(t75_learn) = true; id(t75_tds) = 218; id(t75_tds_mean) = 221;
id(t75_lux) = 420; id(t75_ph) = 7.24f; id(t75_ph_ms) = now; id(t75_stamp_ms) = now;
id(t75_stamp) = epoch;
// ---- nano
id(t16_temp) = 74.4f; id(t16_sp) = 74.5f; id(t16_swing) = 0.5f; id(t16_drift) = -0.01f;
id(t16_conf) = 98; id(t16_heat) = 0; id(t16_heat_on) = false; id(t16_fan) = 0;
id(t16_fan_on) = false; id(t16_fault) = false; id(t16_learn) = true; id(t16_tds) = 341;
id(t16_tds_mean) = 341; id(t16_lux) = 280; id(t16_ph) = 7.12f; id(t16_ph_ms) = now;
id(t16_stamp_ms) = now; id(t16_stamp) = epoch;
// ---- 24 h history: gentle daily curves
for (int i = 0; i < 96; i++) {
  const float d = sinf(i / 96.0f * 6.283f);
  id(t75_hist_temp)[i] = 75.0f + 0.15f * d - 0.05f * cosf(i * 0.9f);
  id(t75_hist_temp_b)[i] = 75.2f + 0.12f * d;
  id(t75_hist_tds)[i] = 214 + 6 * d + (i % 7);
  id(t75_hist_ph)[i] = 7.30f - 0.12f * d;
  id(t16_hist_temp)[i] = 74.5f + 0.2f * sinf(i / 12.0f);
  id(t16_hist_temp_b)[i] = NAN;
  id(t16_hist_tds)[i] = 339 + i * 0.03f + (i % 5) * 0.4f;
  id(t16_hist_ph)[i] = 7.12f + 0.09f * d;
}
id(t75_hist_n) = 96; id(t16_hist_n) = 96;
// ---- feeds
id(mqtt_up) = true;
id(ro_fill) = 3.4f; id(ro_target) = 5.0f; id(ro_reached) = false; id(ro_rate) = 0.18f;
id(ro_flowing) = true; id(ro_total) = 1420; id(ro_online) = true;
id(wc_draining) = true; id(wc_removed) = 18.2f; id(wc_added) = 0; id(wc_net) = -18.2f;
id(wc_pct) = 29.4f; id(wc_rate) = 2.4f; id(wc_flowing) = true; id(wc_batt) = 88;
id(wc_batt_low) = false; id(wc_volume) = 62; id(wc_online) = true;
id(wc_last_start) = epoch - 5 * 86400;
id(ha_co2_t75) = 0; id(ha_bubbler_t75) = 1; id(ha_co2_t16) = 1; id(ha_bubbler_t16) = 1;
id(ha_livestock_days) = 142;
id(redraw_charts) = true;
if (s == "home" || s == "t75" || s == "t16" || s == "wc") {
  id(ro_flowing) = s != "home";
  if (s == "home") { id(wc_flowing) = false; id(wc_rate) = 0; }
}
if (s == "alert") {
  id(t75_temp) = 71.8f; id(t75_temp_b) = 71.9f; id(t75_grad) = -0.1f; id(t75_drift) = -0.15f;
  id(t75_heat) = 100; id(t75_heat_on) = true; id(t75_conf) = 62;
  id(alerts)["heater_75"] = "critical|75 Gallon: heater not responding|"
      "Heater on at 100 % but water is falling 0.15 °F/min. Check the heater and its power.";
}
if (s == "stale") {
  // Last frame 4 min 12 s ago (unsigned wrap is fine: only differences are used).
  id(t16_stamp_ms) = now - 252000; id(t16_stamp) = epoch - 252;
}
if (s == "night") { id(night_on) = true; id(t75_lux) = 0; id(t16_lux) = 0; }
"""

PAGE_FOR = {"t75": "w_page_t75", "t16": "w_page_t16", "wc": "w_page_wc"}




def harness():
    gen.PREVIEW = True
    ui = yaml.load(gen.build(), Loader=_RoundTrip)
    doc = {
        "esphome": {"name": "p4-preview", "on_boot": {"priority": -100, "then": [
            {"delay": "300ms"},
            {"lambda": SCENARIO_CPP},
        ] + [{"if": {"condition": {"lambda": f'return getenv("P4_SCENARIO") && std::string(getenv("P4_SCENARIO")) == "{k}";'},
                     "then": [{"lvgl.page.show": {"id": v, "animation": "NONE"}}]}}
             for k, v in PAGE_FOR.items()] + [
            {"delay": "4s"},
            {"snapshot.take": {"id": "main_display",
                               "filename": Lambda('return std::string(getenv("P4_SHOT"));')}},
            {"delay": "1s"},
            {"lambda": "exit(0);"},
        ]}},
        "host": {},
        "logger": {"level": "INFO"},
        "time": [{"platform": "host", "id": "sntp_time", "timezone": "America/New_York"}],
        "sun": {"id": "sun_pa", "latitude": 39.8, "longitude": -76.7},
        "display": [{"platform": "sdl", "id": "main_display", "auto_clear_enabled": False,
                     "headless": True,
                     "dimensions": {"width": 1024, "height": 600}, "update_interval": "never"}],
        "output": [{"platform": "template", "id": "bl_out", "type": "float",
                    "write_action": [{"logger.log": "backlight"}]}],
        "light": [{"platform": "monochromatic", "id": "backlight", "output": "bl_out"}],
        "globals": lifted_globals() + ui.pop("globals"),
        "script": [
            {"id": f"{t}_send_sp", "mode": "restart", "then": [{"logger.log": f"preview: {t} setpoint"}]}
            for t in ("t75", "t16")] + [
            {"id": f"{t}_send_learn", "then": [{"logger.log": f"preview: {t} learning"}]}
            for t in ("t75", "t16")] + ui.pop("script"),
    }
    # Headless SDL has no window to take touches from.
    ui["lvgl"].pop("touchscreens", None)
    doc.update(ui)
    return doc


class _RoundTrip(yaml.SafeLoader):
    """Keeps !lambda as a tagged scalar so it survives a load/dump cycle."""


class Lambda(str):
    pass


_RoundTrip.add_constructor("!lambda", lambda loader, node: Lambda(loader.construct_scalar(node)))
yaml.SafeDumper.add_representer(
    Lambda, lambda d, v: d.represent_scalar("!lambda", str(v), style="|"))


def main(which):
    WORK.mkdir(exist_ok=True)
    SHOTS.mkdir(parents=True, exist_ok=True)
    cfg = WORK / "p4-preview.yaml"
    text = yaml.safe_dump(harness(), sort_keys=False, allow_unicode=True, width=1000)
    # Plain lambda: strings in actions are C++; make them literal blocks.
    cfg.write_text(text)
    r = subprocess.run([ESPHOME, "compile", str(cfg)], capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-6000:], r.stderr[-3000:])
        sys.exit("preview build failed")
    binary = next((WORK / ".esphome" / "build" / "p4-preview").rglob("program"), None) \
        or next((WORK / ".esphome" / "build" / "p4-preview").rglob("firmware"), None)
    if binary is None:
        sys.exit("built, but could not find the host binary")
    for sc in which:
        bmp = Path(f"p4-{sc}.bmp")
        (WORK / ".esphome" / "snapshots" / "p4-preview" / bmp.name).unlink(missing_ok=True)
        env = dict(os.environ, P4_SCENARIO=sc, P4_SHOT=bmp.name)
        subprocess.run([str(binary)], env=env, timeout=60, capture_output=True)
        # snapshot.take writes into ESPHome's own snapshots folder.
        made = WORK / ".esphome" / "snapshots" / "p4-preview" / bmp.name
        png = SHOTS / f"{sc}.png"
        png.unlink(missing_ok=True)
        subprocess.run(["sips", "-s", "format", "png", str(made), "--out", str(png)],
                       capture_output=True)
        made.unlink(missing_ok=True)
        print(f"{sc}: {png if png.exists() else 'NO SCREENSHOT'}")


if __name__ == "__main__":
    main(sys.argv[1:] or SCENARIOS)
