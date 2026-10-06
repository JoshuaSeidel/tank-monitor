# Home Assistant

## Aquarium dashboard

Live at **Settings → Dashboards → Aquarium**, or `/aquarium-tank`.
`aquarium-dashboard.json` is the config, kept here for version control.

Three views:

| View | Purpose |
|---|---|
| **Tank** | Live state — temperature, controller, water quality, health |
| **Manual tests** | Type test-kit results, press one button to log them |
| **Trends** | History: is the swing actually falling? |

### No probe cross-check any more

There used to be one here: the ESP32's DS18B20 was compared against a Seneye
Reef/Pond monitor, on the principle that two sensors in the same water should
agree. That monitor was returned on 2026-09-04 after its pH proved ~0.45 LOW
against an API liquid test — it had this project chasing a CO2 crisis and then
a KH crash, neither of which was real.

**So there is no second sensor now, and the gap is worth stating plainly:**
the controller drives the heater from the DS18B20 alone. If that probe reads
low, the controller will happily cook the tank while reporting the target, and
nothing in Home Assistant will notice. Check it against a reference
thermometer occasionally, by hand.

The lesson generalises past this one device. A continuous reading that cannot
be calibrated is not more trustworthy than an intermittent one that can — it
is less, because it is wrong more often and more confidently. That is why pH
is moving to a DFRobot glass electrode on the controller: it can be stood in
a buffer of known pH and proven right.

### The TDS number is an hourly mean, and the mean is computed on the device

The analog TDS probe is honest about the trend and useless about any single
sample. Measured over a day of live data, the spread WITHIN one hour was a
median of 39 ppm and as much as 171 ppm — larger than any dose you would ever
make. That is what had this project explaining a "47 ppm overnight rise" that
was noise.

So the dashboard reads `sensor.tank_monitor_tds_1h_mean`. **That sensor is
computed on the ESP32, not here** — a 120-sample sliding window at 30 s,
republished every minute, defined in `packages/sensors.yaml`.

It was briefly an HA `statistics` helper instead, which was the wrong place.
A correction that only exists in Home Assistant is a correction the tank does
not have: the remote panel over ESP-NOW and the controller's own web page
would still have been showing the raw jittering value, and would have
disagreed with this dashboard by 15–40 ppm at any given moment. The same
argument applies to every calibration — see the note below.

The raw probe is still plotted on the Trends view underneath the mean,
deliberately: seeing the noise band around the mean is what stops the next
spike being read as an event.

### Calibration lives on the device, not here

Every probe correction — TDS K factor, pH two-point, temperature offset — is
a `restore_value` global on the ESP32, applied inside the sensor lambda
before anything is published. Home Assistant receives values that are already
correct; it is a consumer, not the correction.

The entities are exposed to HA for convenience, but the same controls exist
on the device's own web page at its IP address, which is what you use when
the broker is down or when you are standing at a sink with a wet probe. See
the root `README.md` for the procedure.

### Manual entry

Uses the existing `input_number.aquarium_*` helpers and
`script.aquarium_log_manual_test` rather than duplicating them. GH and KH
have no hobby-grade probe, so they stay test-kit values — the Tank view's
target table reads them from the `*_log` sensors so they sit alongside the
measured parameters.

### Rebuilding

`aquarium-dashboard.json` is the source of truth here; the dashboard was
created from it via the HA config API, not hand-edited in the UI. If you
edit it in the UI, export it back to this file.

## 75-gal light — Chihiros WRGB II Pro 120

**The tank's own board owns the light.** Since 2026-09-29 the all-in-one
controller (`tank-monitor-75-gallon`, `boards/allinone-freenove.yaml`) holds a
BLE link to the lamp and pushes the selected phase itself
(`packages/light_wrgb2.yaml`). Home Assistant only shows and sets it, exactly as
it does for the heaters; nothing in HA re-pushes a schedule. The old
`aquarium-light-bridge` ESP32, `input_select.aquarium_75_light_phase` and
`automation.aquarium_75_apply_light_phase` are retired and were deleted from HA
on 2026-10-06.

Lives on the **`dashboard-modern` → Aquarium** view (`/dashboard-modern/aquarium`),
in the 75-gal block, gated on `input_select.aquarium_tank` = `75 Gal` like every
other section there. This is *not* on the `aquarium-tank` dashboard that
`aquarium-dashboard.json` tracks.

| Entity (prefix `tank_monitor_75_gallon_`) | What it is |
|---|---|
| `select…light_phase` | The phase: Off (cycling), Phase 1–4. Changing it pushes at once |
| `text…light_on_time` / `text…light_off_time` | Start and end of the photoperiod (HH:MM) for the selected phase |
| `number…light_ramp` | Dawn/dusk ramp, minutes |
| `number…light_white` / `_red` / `_green` / `_blue` | Plateau brightness, % |
| `number…light_full_brightness_hours` | >0 = this phase follows the sun (below); 0 = fixed times |
| `button…push_light_phase_now` | Re-send the selected phase |
| `button…release_light_for_app_30_min` | Hands the lamp to the Chihiros app for 30 min, then takes it back and re-pushes |
| `button…reset_light_phase_to_defaults` | Restores the selected phase to the table below |
| `binary_sensor…light_linked` | The BLE link to the lamp is up |
| `binary_sensor…light_not_responding` | Three re-pushes did not make the lamp match the schedule |
| `sensor…light_expected` | What the lamp should be doing now: lit / ramping / dark / off phase |
| `sensor…light_link_drops`, `…light_link_uptime`, `…light_link_last_drop` | Link health and the radio's reason for the last drop |

The controls edit **the selected phase** and are stored in the board's flash,
so tuning never needs a reflash; pick another phase and they show its values.

**Follow the sun (Phases 3–4).** With Full Brightness Hours > 0 the board
computes the window from today's sunrise and sunset at the tank (south-central
Pennsylvania, from the board's own clock — no HA needed): lights span sunrise
to sunset, the plateau is capped at that many hours, and the rest of the day
becomes the dawn and dusk ramp (15–150 min; on a long summer day the window is
trimmed symmetrically around solar noon). It is recomputed after midnight and
pushed while the lamp is dark. On Time / Off Time / Ramp then show the
computed values and refuse edits. Phases 1–2 keep fixed hours.

Defaults (`light_seed_defaults` / `light_seed_sun` in
`packages/light_wrgb2.yaml` — what a fresh board and "Reset" write; the live
values are whatever has been tuned since):

| Phase | Window | Ramp | W / R / G / B | Follows the sun |
|---|---|---|---|---|
| Off (cycling) | — | — | 0 / 0 / 0 / 0 (manual mode, dark) | no |
| 1 — Plants in | 09:00–16:00 | 45 | 45 / 36 / 20 / 14 | no |
| 2 — Shrimp | 09:00–16:00 | 45 | 55 / 45 / 28 / 20 | no |
| 3 — Fish | sunrise–sunset (fallback 09:00–16:30) | computed (fallback 45) | 60 / 50 / 32 / 24 | 7 h plateau |
| 4 — Mature | sunrise–sunset (fallback 09:00–16:30) | computed (fallback 45) | 70 / 60 / 38 / 30 | 7.5 h plateau |

Ratios are deliberate: white is the only dimming lever, and red/green/blue
track it at roughly 0.8 / 0.45 / 0.3. Chihiros' own default is blue at 0.8 of
white, which is most of why a new Pro fixture grows algae. Phase 2 (an
estimated 40–50 µmol/m²/s at the substrate) is the ceiling until CO2 runs;
Phases 3–4 are the CO2 ladder. See the DEFAULTS comment in
`packages/light_wrgb2.yaml` for the PAR each phase is sized to.

**The schedule still runs on the lamp.** A lit phase is pushed as an
auto-mode schedule (clear slots → schedule → auto → clock, the app's own
sequence — chihiros-esphome `ca8fc35`); the lamp then runs it off its RTC, so
the board or HA going down does not darken the tank. "Off (cycling)" is manual
mode at 0, which darkens it at once and does not relight itself. The board
re-pushes at 03:00 daily to resync the lamp's drifting clock, and on every
reconnect.

**The board checks the lamp.** `tank_lux` is lamp-only lux (daylight is
removed by its near-infrared signature on the AS7341). During a plateau the
board learns what "lit" reads; lit-when-it-should-be-dark or the reverse for
5 minutes triggers a re-push, at most one per 15 minutes, and after three that
do not take it raises Light Not Responding instead of hammering the radio.

### 75-gal CO2

Rebuilt in HA on 2026-10-06 to follow the light the board is actually
running, including the daily follow-the-sun times. The gas window is three
template sensors over the board's Light On Time / Off Time / Ramp; tune the
offsets in their `input_number` helpers, never in the automations:

| Helper | Value |
|---|---|
| `sensor.aquarium_75_co2_start` | light on + ramp − `input_number.aquarium_75_co2_lead` (90 min) |
| `sensor.aquarium_75_co2_stop` | light off − ramp − `input_number.aquarium_75_co2_stop_before_dusk` (90 min) |
| `sensor.aquarium_75_bubbler_start` | CO2 stop + `input_number.aquarium_75_bubbler_gap_after_co2` (180 min) |

All three go unknown when the board is offline, and an unknown time never
fires — gas does not start on a guess.

- **`automation.aquarium_75_co2_schedule`** — `switch.75g_co2` on at the start,
  off at the stop, again one hour after the stop (failsafe), and at **17:00
  absolute** (backstop that cannot be defeated by a blank sensor). The start is
  refused — with a notification — unless the light phase is not Off and the
  probe pH (`sensor.tank_monitor_75_gallon_water_ph`) is reporting and above the
  floor + 0.2.
- **`automation.aquarium_75_bubbler_schedule`** — `switch.75g_bubbler` off at the
  CO2 start, on at the bubbler start, and on at **22:00 absolute** as a
  backstop; every turn-on also forces CO2 off (gas yields to aeration, never
  the reverse).
- **`automation.aquarium_75_co2_ph_floor_cutoff`** — always enabled. Probe pH
  below `input_number.aquarium_75_ph_floor` (6.5) for 2 minutes while
  `switch.75g_co2` is on → gas off, bubbler on, persistent notification. It only
  ever turns gas off; the next scheduled start re-checks the floor.

The schedule and bubbler automations are **intentionally off** until the
November CO2 readiness gate; enable them together. Until then the airstone runs
around the clock. The old `input_datetime.aquarium_75_co2_on` / `_off` /
`_bubbler_on` fixed times were deleted.

The 75's manual pH helper (`input_number.aquarium_75_ph_manual`) is no longer
published to `tank-monitor-75g/chem/ph`: the 75 gal panel's pH now comes from
the controller's calibrated probe over BLE (v3 frame field 17).

> **`aquarium-dashboard.json` in this folder is stale.** It predates the two-tank
> restructure entirely — 4 nano-only sections, no visibility conditions, no tank
> selector header — while the live `aquarium-tank` dashboard has 7 sections, 6
> badges and the selector. Re-export before trusting this file again.
