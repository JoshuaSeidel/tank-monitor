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
| `text…light_on_time` / `text…light_off_time` | Start and end of the photoperiod (HH:MM): sunrise / sunset on a sun-following phase |
| `number…light_ramp` | Dawn/dusk ramp, minutes (fixed phases). Sun curve: read-out of sunrise → bright window |
| `number…light_white` / `_red` / `_green` / `_blue` | Full brightness, % — the peak the day is shaped against |
| `number…light_full_brightness_hours` | The day's total light in hours at full brightness. >0 = this phase follows the sun (below); 0 = fixed times |
| `select…light_day_shape` | Sun curve (multi-point natural day, default) or Single fade (one scene). Sun-following phases only |
| `number…light_bright_threshold` | Share of the curve's peak that counts as "bright" (65 %, 50–90). Board-wide |
| `number…light_curve_step` | Minutes between the curve's points in the lamp (60; 30 if the lamp steps instead of fading) |
| `sensor…light_bright_start` / `…light_bright_end` | The bright window (HH:MM), `--:--` on the off phase. The CO2 schedule keys off these |
| `sensor…light_expected_level` | Brightness the lamp should be at now, % of the phase's full values |
| `sensor…light_expected_lux` | Learned lux × expected level: what lamp lux should read now |
| `sensor…light_daily_light` | Full-equivalent hours today actually delivers |
| `sensor…light_curve_peak` | Today's peak, % of full (under 100 when the target is below a full sine) |
| `button…push_light_phase_now` | Re-send the selected phase |
| `button…release_light_for_app_30_min` | Hands the lamp to the Chihiros app for 30 min, then takes it back and re-pushes |
| `button…reset_light_phase_to_defaults` | Restores the selected phase to the table below |
| `binary_sensor…light_linked` | The BLE link to the lamp is up |
| `binary_sensor…light_not_responding` | Three re-pushes did not make the lamp darker-than-schedule match |
| `binary_sensor…light_brighter_than_schedule` | Lit when it should be dark (5 % of full, floor 10 lx) or well above the sun curve, for 5 min. On the curve it also suspends the curve until midnight and pushes the single scene |
| `sensor…light_lamp_report` | The lamp's own stored-schedule snapshot after a push (points it says it holds) |
| `sensor…light_expected` | What the lamp should be doing now: lit (≥ half the peak) / ramping / dark / off phase |
| `sensor…light_learned_lux` | Lux at the phase's full values (curve: learned as lux / level above 70 % of the peak) |
| `sensor…light_link_drops`, `…light_link_uptime`, `…light_link_last_drop` | Link health and the radio's reason for the last drop |

The controls edit **the selected phase** and are stored in the board's flash,
so tuning never needs a reflash; pick another phase and they show its values.

**Follow the sun.** With Full Brightness Hours > 0 the board computes today's
sunrise and sunset at the tank (south-central Pennsylvania, from the board's own
clock — no HA needed) and spreads that many hours of full-equivalent light over
the day. It is recomputed after midnight and pushed while the lamp is dark. On
Time / Off Time / Ramp then show the computed values and refuse edits.

*Sun curve* (Light Day Shape default) — brightness follows the sun: 0 at
sunrise, a smooth rise to solar noon, a smooth fall to 0 at sunset, with the
phase's W/R/G/B ratio at every point. With x = (t − sunrise) / day:

    brightness = peak · sin(πx)^p   (fraction of the phase's full values)
    daily light = day · peak · M(p),   M(p) = ∫₀¹ sin(πx)^p dx,   M(1) = 2/π

A full-height sine delivers day · 2/π. A smaller target scales the peak down
(p = 1); a larger one keeps peak 100 % and widens the top with p < 1 (sin^p never
exceeds 1, so full is the cap). p is floored at 0.3 so dawn and dusk stay
gradual; on short winter days a target beyond that is out of reach and Light
Daily Light shows what the day delivers. The bright window (≥ threshold θ of the
peak) is closed form: x₀ = asin(θ^(1/p)) / π, window = [sunrise + x₀·day,
sunset − x₀·day]. Math: chihiros-esphome `components/chihiros_ble/sun_curve.h`.

2026-10-19 at the tank (board: sunrise 07:22, sunset 18:21, day 659 min, full
sine 6.99 h), Phase 1 W45/R36/G20/B14:

| Full Brightness Hours | Peak | p | Bright ≥65 % | CO2 on – off (lead 90, stop 90) |
|---|---|---|---|---|
| 6 (the value before this change) | 85.8 % | 1 | 09:50–15:53 | 08:20–14:23 |
| **7.5 (new Phase 1–2 default)** | 100 % | 0.786 | 09:31–16:12 | 08:01–14:42 |
| 8 (new Phase 3–4 default) | 100 % | 0.612 | 09:11–16:32 | 07:41–15:02 |

For scale, the single schedule it replaces (6 h plateau + two 150-min ramps)
was 8.5 h equivalent, and Phase 2's earlier 6.25 h was ~7.8 h at Phase 1
brightness. On first boot of this firmware every phase that already followed
the sun is re-seeded to the new default (the stored number used to mean the
plateau length), so Phase 1 reads 7.5.

*Single fade* — the older one scene: dose = plateau + ramp (two linear ramps
of R deliver R), ramp 15–150 min, span trimmed around solar noon when the
ramps hit 150. Same Full Brightness Hours, same bright window rule. It is also
the fallback if the lamp turns out not to run a curve.

Defaults (`light_seed_defaults` / `light_seed_sun` in
`packages/light_wrgb2.yaml` — what a fresh board and "Reset" write; the live
values are whatever has been tuned since):

| Phase | Window | Ramp | W / R / G / B | Follows the sun |
|---|---|---|---|---|
| Off (cycling) | — | — | 0 / 0 / 0 / 0 (manual mode, dark) | no |
| 1 — Plants in | sunrise–sunset (fallback 09:00–16:00) | computed (fallback 45) | 45 / 36 / 20 / 14 | 7.5 h daily light |
| 2 — Shrimp | sunrise–sunset (fallback 09:00–16:00) | computed (fallback 45) | 55 / 45 / 28 / 20 | 7.5 h daily light |
| 3 — Fish | sunrise–sunset (fallback 09:00–16:30) | computed (fallback 45) | 60 / 50 / 32 / 24 | 8 h daily light |
| 4 — Mature | sunrise–sunset (fallback 09:00–16:30) | computed (fallback 45) | 70 / 60 / 38 / 30 | 8 h daily light |

Ratios are deliberate: white is the only dimming lever, and red/green/blue
track it at roughly 0.8 / 0.45 / 0.3. Chihiros' own default is blue at 0.8 of
white, which is most of why a new Pro fixture grows algae. Phase 2 (an
estimated 40–50 µmol/m²/s at the substrate) is the ceiling until CO2 runs;
Phases 3–4 are the CO2 ladder. See the DEFAULTS comment in
`packages/light_wrgb2.yaml` for the PAR each phase is sized to.

**The schedule still runs on the lamp.** A fixed or Single-fade phase is
pushed as an auto-mode scene (switch to scenes → clear slots → schedule →
clock, the app's own sequence — chihiros-esphome `ca8fc35`). A Sun-curve phase
is pushed as a multi-point day into the lamp's custom-curve controller (curve
controller `5a/05 [03]` → clear it `[05]` → `[03]` → one `5a/06 [ch, hh, mm,
%]` frame per channel per point → clock → status query; chihiros-esphome `1e677ae`): sunrise
and sunset at 0 plus one point per hour on the clock, 13 points × 4 channels on
a 11 h day. Either way the lamp runs it off its RTC, so the board or HA going
down does not darken the tank or freeze it mid-day. "Off (cycling)" is manual
mode at 0, which darkens it at once and does not relight itself. The board
re-pushes at 03:00 daily to resync the lamp's drifting clock, and on every
reconnect.

**2026-10-19 field bug, fixed in chihiros-esphome `1e677ae` / this repo.** The
first Sun-curve day ran correctly except for a lamp-made bump to ~2.3× full
around 15:30 (NIR flat, so not daylight) and, after the 18:21 sunset point, a
slow relight (~1 lx/min, 30 lx by 18:58). Cause: `5a/05 [05]` clears the
*active* controller's settings; it was sent while the lamp was still in scene
mode, so the curve table kept points nobody had written that session. The
clear now follows `[03]`. Switching to Single fade at 18:58 darkened the lamp at
once (the scene path clears and runs the scenes). The relight also went
unflagged because "lit when dark" needed half the full lux; it is now 5 %.

**The board checks the lamp.** `tank_lux` is lamp-only lux (daylight is
removed by its near-infrared signature on the AS7341). The board learns the
lux at the phase's full values (a scene: on its plateau; the sun curve: lux /
level while above 70 % of the peak). Dark while the curve is above half its
peak (lux under a quarter of learned × level), or lit outside the photoperiod,
for 5 minutes triggers a re-push, at most one per 15 minutes, and after three that
do not take it raises Light Not Responding instead of hammering the radio.

### 75-gal CO2

Rebuilt in HA on 2026-10-06 to follow the light the board is actually
running; re-keyed on 2026-10-19 to the board's **bright window** (Light Bright
Start / End: the curve at or above Light Bright Threshold, 65 % of its peak).
Tune the offsets in their `input_number` helpers, never in the automations:

| Helper | Value |
|---|---|
| `sensor.aquarium_75_co2_start` | Light Bright Start − `input_number.aquarium_75_co2_lead` (90 min) |
| `sensor.aquarium_75_co2_stop` | Light Bright End − `input_number.aquarium_75_co2_stop_before_dusk` (90 min) |
| `sensor.aquarium_75_bubbler_start` | CO2 stop + `input_number.aquarium_75_bubbler_gap_after_co2` (180 min) |

Why these anchors. Dissolved CO2 lags the solenoid by an hour or two both ways.
Starting the lead before the bright window means the gas has built up by the
time the light is strong; below ~65 % of the peak photosynthesis is still
light-limited and CO2 demand is low, so gas in the dim dawn is wasted. Stopping
before the bright window *ends* (not before sunset) lets the residual carry
the rest of the bright stretch and be consumed rather than stripped, keeps the
gas window centred on the light, and has the water degassing in the dim tail
instead of entering the night — overnight CO2 on top of the pre-dawn oxygen
minimum is the failure that kills livestock. A stop measured from sunset would
inject into a dusk already below half brightness. Before the board runs this
firmware (no Bright Start/End yet) the helpers fall back to the old on + ramp /
off − ramp formula, which is the same window for a scene.

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
