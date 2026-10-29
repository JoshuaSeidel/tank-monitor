# Design brief: 10.1" aquarium wall panel

You are designing the UI for a single wall-mounted touch panel that replaces
three smaller displays. It shows two aquariums and two water-flow meters.
Design a fresh, beautiful, modern UI. Do not reuse or imitate the older
mockups elsewhere in this repo (`design/panel-*.html`); start clean.

## The device

- Elecrow CrowPanel Advanced 10.1", ESP32-P4, **1024 x 600 landscape**, IPS,
  capacitive touch (5 points), 400 nits.
- Mounted on a wall in a home office, read from 1-3 m away and touched up close.
  Must be glanceable from across the room: the important number on each tank
  must be readable at 3 m.
- The UI will be rebuilt in **LVGL 9 (via ESPHome)** from your mockups. Design
  only what LVGL can draw well:
  - Solid fills, rounded rectangles, borders, arcs (`lv_arc`), bars, sliders,
    line/area charts (`lv_chart`), labels, buttons, tabview/tileview pages.
  - Display is **16-bit colour (RGB565)**: avoid large subtle gradients
    (they band). Small accent gradients are OK.
  - **No** backdrop blur, glassmorphism blur, large soft drop shadows, images
    or photos. Thin shadows/glows only if they are small.
  - One font family, from Google Fonts, a few weights and a few sizes. Icons
    from Material Design Icons (mdi) only, used as glyphs.
  - Touch targets at least 56 px.
- The panel is in a room that goes dark at night: include a dim/night look.

## Data available (only design for these)

### 75-gallon tank ("75 Gallon"): live over Bluetooth from its controller
- Water temp probe A and probe B (°F), signed gradient A-B (°F)
- Setpoint (°F, currently 75.0) and control band (swing, ±°F)
- Temperature drift (°F/min, trend direction)
- Heater duty %, heater demand on/off; fan duty %, fan demand on/off
- TDS live ppm and TDS 1-hour mean ppm (target 200-225, alert at 260, never > 300)
- pH (target 7.0-7.5)
- Light level (lux) at the tank
- Model confidence % (adaptive heating model), learning on/off
- Safety tripped yes/no
- Connection state: connected / disconnected, and age of the last update
- Commands the panel can send: change setpoint, learning on/off

### Nano tank ("Nano", ~12 gal): live over Bluetooth from its controller
- Same as the 75 **except** single temperature probe (no B, no gradient).
- pH comes from Home Assistant, not Bluetooth (same display, different source).

### Water-flow meters: over MQTT (Wi-Fi)
- **RO meter** (RO filter output): fill volume this fill (gal), fill target
  (gal), target reached yes/no, flow rate, flowing yes/no, lifetime total
  produced (gal). Actions: reset fill, set target.
- **Water-change meter** (hose, battery powered): mode Draining / Refilling,
  removed this change (gal), added this change (gal), net (gal), percent of
  tank changed, flow rate, flowing yes/no, battery %, low battery.
  Action: start new water change, switch mode.
  The 75's water volume is ~62 gal; a typical change is ~20 gal.

### From Home Assistant (Wi-Fi)
- Active alerts list (e.g. "TDS above target", "Heater not responding",
  "Filter chamber dry"), critical vs warning.
- 24 h history for temperature, TDS and pH, for charts.
- Light schedule: on at civil dawn, off at civil dusk, current light level %.
- CO2 and bubbler on/off (75 only; CO2 is scheduled to start in November).
- Days since last livestock loss; date of last water change.

## Screens to mock up

1. **Home**: both tanks at a glance plus a compact water-flow strip and an
   alert indicator. Temperature is the headline per tank; TDS and pH next.
   Heater/fan activity visible at a glance.
2. **75 Gallon detail**: both probes and gradient, setpoint with a large
   touch control to change it, heater/fan duty, TDS (live + 1 h mean against
   its target band), pH against its target band, 24 h chart, light, CO2 and
   bubbler state, model confidence and learning.
3. **Nano detail**: same structure, single probe.
4. **Water change in progress**: big live view while draining or refilling:
   gallons, percent of tank, flow rate, mode switch, battery. Also the RO
   fill progress toward its target.
5. **Alert**: what the home screen looks like with one critical alert active
   (e.g. "75 Gallon: heater not responding, 71.8 °F and falling").
6. **Offline/stale**: the home screen with the Nano's Bluetooth link down for
   4 minutes. Stale values must look clearly stale, never like live data.
7. **Night**: the home screen in dim night mode.

Use realistic sample values: 75 Gallon at 74.9 °F (A) / 75.1 °F (B),
setpoint 75.0, TDS 218 ppm (1 h 221), pH 7.24, heater 14 %; Nano at 76.8 °F,
setpoint 77.0, TDS 162 ppm, pH 6.9, heater 0 %, fan 0 %.

## Deliverables (write these files in this folder)

- `screen-1-home.html` ... `screen-7-night.html`: each a self-contained
  HTML page with a single element exactly **1024 x 600 px** rendering that
  screen. Pure HTML/CSS and inline SVG; the only external resource allowed is
  the Google Fonts stylesheet for your chosen font and the MDI webfont from
  `https://cdn.jsdelivr.net/npm/@mdi/font/css/materialdesignicons.min.css`.
  No JavaScript needed.
- `index.html`: a gallery showing all seven screens with titles.
- `DESIGN.md`: the design system, so it can be rebuilt in LVGL. Colour tokens
  (hex), the font family and every size/weight used, spacing scale, corner
  radii, component specs (tank card, metric tile, setpoint control, chart,
  alert banner, stale state), and the night palette. Explain the key design
  choices in a few sentences.

Make it genuinely beautiful: calm, premium, aquatic without being cartoonish,
with a clear visual hierarchy and colour used for meaning (normal / warning /
critical / heating / cooling), not decoration.
