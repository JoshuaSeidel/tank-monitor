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
| `text…light_on_time` / `text…light_off_time` | Start and end of the photoperiod (HH:MM): civil dawn / civil dusk on Daylight, sunrise-side / sunset-side scene edges on Single fade |
| `number…light_ramp` | Dawn/dusk ramp, minutes (fixed phases). Daylight: read-out of civil dawn → bright window |
| `number…light_white` / `_red` / `_green` / `_blue` | Full brightness, % — solar noon on Daylight |
| `switch…light_follows_sun` | The selected phase follows today's sun (on) or runs the fixed On/Off Time and Ramp (off) |
| `number…light_full_brightness_hours` | Optional CAP on the day's light, hours at full brightness. **0 = natural (default)**. Single fade uses it as its daily light |
| `select…light_day_shape` | Daylight (real outdoor light, multi-point, default) or Single fade (one scene). Sun-following phases only |
| `number…light_daylight_exponent` | level = (illuminance / noon)^this. 0.5 default; 1.0 = literal photometry. Board-wide |
| `number…light_dawn_warmth` | How far low sun shifts the mix toward golden white (100 % default, 0 = phase ratio all day). Board-wide |
| `number…light_bright_threshold` | Share of the curve's peak that counts as "bright" (65 %, 50–90). Board-wide |
| `number…light_curve_step` / `…light_curve_edge_step` | Point spacing through midday (60 min) and within 2 h of dawn/dusk (30 min); ≤ 24 points |
| `sensor…light_bright_start` / `…light_bright_end` | The bright window (HH:MM), `--:--` on the off phase. The CO2 schedule keys off these |
| `sensor…light_expected_level` | Brightness the lamp should be at now, % of the phase's full values |
| `sensor…light_settings_restored` | Boot check of the stored light settings: `ok`, or which ones came back as their defaults and why. Anything but `ok` after a flash = a setting was lost and replaced |
| `sensor…light_expected_lux` | Learned lux × expected level: what lamp lux should read now |
| `sensor…light_daily_light` | Full-equivalent hours of today's natural day |
| `sensor…light_curve_peak` | Today's peak, % of full (under 100 only when the cap bites) |
| `button…push_light_phase_now` | Re-send the selected phase |
| `button…release_light_for_app_30_min` | Hands the lamp to the Chihiros app for 30 min, then takes it back and re-pushes |
| `button…reset_light_phase_to_defaults` | Restores the selected phase to the table below |
| `binary_sensor…light_linked` | The BLE link to the lamp is up |
| `binary_sensor…light_not_responding` | Three re-pushes did not make the lamp darker-than-schedule match |
| `binary_sensor…light_brighter_than_schedule` | Lit when it should be dark (5 % of full, floor 10 lx) or well above the curve (1.5× + 5 %), for 5 min. On the curve it also suspends the curve until midnight and pushes the single scene |
| `binary_sensor…light_curve_rejected` | After a curve push the lamp listed a stored time the board did not send; curve suspended until midnight, single scene instead |
| `sensor…light_lamp_report` | The lamp's own stored-schedule snapshot after a push: `match` / `lists N of M` / `FOREIGN n`, then the points |
| `sensor…light_expected` | What the lamp should be doing now: lit (≥ half the peak) / ramping / dark / off phase |
| `sensor…light_learned_lux` | Lux at the phase's full values (curve: learned as lux / level above 70 % of the peak) |
| `sensor…light_link_drops`, `…light_link_uptime`, `…light_link_last_drop` | Link health and the radio's reason for the last drop |

The controls edit **the selected phase** and are stored in the board's flash,
so tuning never needs a reflash; pick another phase and they show its values.

**Follow the sun.** With Light Follows Sun on, the board computes today's sun
at the tank (39.8 N 76.7 W, NOAA low-precision ephemeris from its own clock — no
HA needed). It is recomputed after midnight and pushed while the lamp is dark.
On Time / Off Time / Ramp then show the computed values and refuse edits.

*Daylight* (Light Day Shape default, since 2026-10-20) — brightness follows
real outdoor light from civil dawn (sun −6°) to civil dusk. Clear-sky global
illuminance from the sun's elevation h (chihiros-esphome
`components/chihiros_ble/daylight.h`):

    h ≥ 0      E = 127.5 klx · e^(−0.21 m) · sin h  +  0.8 klx + 15.5 klx · √(sin h)
                   (IES RP-21 clear sky: direct + sky; m = Kasten–Young air mass)
    −6 ≤ h < 0 E = 800 lx · 10^(0.38 h)          (civil twilight, 4 lx at −6°)
    level      = (E / E_noon)^g                    of the phase's full W/R/G/B

**Why g = 0.5 and not 1.** Literal photometry (g = 1) is *dimmer* than a sine
for the first ~1.5 h (11 % at 08:00 against the sine's 18 %), and its twilight
sits far below the lamp's smallest step (one W step is 2.2 % of Phase 1 white),
so the lamp would light at sunrise, not at dawn. The tank looked "barely pink"
on the sine at 26 %; physics would have been darker. g compresses the range
the way vision does (lightness ≈ luminance^⅓–½), so g = 0.5 glows from civil
dawn (W1 at 06:58), reaches a third of full by 08:00, and runs flat through
midday. Plants respond to the linear photon dose, reported as Daily Light.

| g | 08:00 | 09:00 | 10:00 | daily light 10-20 | bright ≥65 % |
|---|---|---|---|---|---|
| 1.0 (photometry) | 11 % | 37 % | 63 % | 6.56 h | 10:04–15:38 |
| 0.75 | 19 % | 48 % | 71 % | 7.18 h | 09:43–15:59 |
| 0.6 | 27 % | 55 % | 76 % | 7.65 h | 09:26–16:17 |
| **0.5 (default)** | 33 % | 61 % | 80 % | 8.03 h | 09:12–16:31 |
| sine it replaced | 26 % | 53 % | 74 % | 7.50 h | 09:31–16:12 |

**Golden dawn.** At low sun the WRGB mix reads pink (red LEDs stay visible at
low PWM). Light Dawn Warmth (100 %) moves the mix toward warm white at the
horizon — W +35 %, G +10 %, R −40 %, B −70 % — fading back to the phase's
ratio by 12° elevation, with luminous output held (rough per-channel weights,
not measured) and every channel clamped at its full value. 0 % turns it off.
(Real civil twilight skylight is bluish; the golden shift is the requested
look, strongest right around sunrise and sunset.)

**Total light is natural.** No target: the day gives what the sun gives.
Light Full Brightness Hours is now an optional cap (0 = off, the default).
A lit phase follows the sun unless Follows Sun is turned off by hand; a
setting that fails to restore after a flash comes back as follows-sun /
uncapped and is named in Light Settings Restored. Natural totals at g 0.5, Phase-full equivalent:

| Day | Civil dawn – dusk | Lit | Noon sun | Daily light | Bright ≥65 % | CO2 (lead 90, stop 90) |
|---|---|---|---|---|---|---|
| 2026-10-20 | 06:56–18:47 | 11.85 h | 39.7° | 8.03 h | 09:12–16:31 | 07:42–15:01 |
| 2026-12-21 | 06:55–17:15 | 10.33 h | 26.8° | 6.88 h | 08:58–15:12 | 07:28–13:42 |
| 2027-03-20 | 06:44–19:45 | 13.0 h | 50° | 8.85 h | 09:12–17:17 | 07:42–15:47 |
| 2027-06-21 | 05:07–21:11 | 16.07 h | 73.6° | 10.75 h | 08:16–18:01 | 06:46–16:31 |

Each day is normalised to its own noon, so a December noon is as bright in the
tank as a June one; the seasons change the length and shape, not the peak.
From spring the natural total passes 9 h — set a cap (≈ 8 h) before then if the
CO2 phases should not track it.

Points: civil dawn, sunrise, sunset, civil dusk exactly; every 30 min within
2 h of dawn and dusk, hourly between; ≤ 24 per channel. 19 points on 10-20,
24 in June. Worst straight-line error between points ~4 % of full, for a few
minutes before sunset. The lamp holds ≥ 13 points per channel (confirmed
2026-10-19); no documented maximum for the Pro — the read-back reports it.

2026-10-20, Phase 1 (W45 R36 G20 B14), g 0.5, warmth 100 %:

| Point | Sun | Level | W | R | G | B | Expected lux* |
|---|---|---|---|---|---|---|---|
| 06:56 civil dawn | −5.8° | 1 % | 0 | 0 | 0 | 0 | 2 |
| 07:23 sunrise | −0.7° | 8 % | 4 | 1 | 1 | 0 | 22 |
| 08:00 | 6.1° | 33 % | 16 | 9 | 6 | 3 | 97 |
| 08:30 | 11.4° | 48 % | 22 | 17 | 10 | 7 | 140 |
| 09:00 | 16.6° | 61 % | 27 | 22 | 12 | 9 | 177 |
| 10:00 | 25.9° | 80 % | 36 | 29 | 16 | 11 | 231 |
| 11:00 | 33.5° | 92 % | 41 | 33 | 18 | 13 | 266 |
| 12:00 | 38.3° | 98 % | 44 | 35 | 20 | 14 | 285 |
| 13:00 | 39.6° | 100 % | 45 | 36 | 20 | 14 | 290 |
| 14:00 | 37.2° | 97 % | 44 | 35 | 19 | 14 | 281 |
| 15:00 | 31.5° | 89 % | 40 | 32 | 18 | 12 | 258 |
| 16:00 | 23.4° | 75 % | 34 | 27 | 15 | 11 | 218 |
| 16:30 | 18.7° | 66 % | 29 | 24 | 13 | 9 | 190 |
| 17:00 | 13.6° | 54 % | 24 | 19 | 11 | 8 | 156 |
| 17:30 | 8.4° | 40 % | 19 | 13 | 8 | 5 | 115 |
| 18:00 | 2.9° | 25 % | 13 | 5 | 5 | 1 | 73 |
| 18:20 sunset | −0.8° | 7 % | 4 | 1 | 1 | 0 | 21 |
| 18:30 | −2.7° | 3 % | 2 | 1 | 1 | 0 | 10 |
| 18:47 civil dusk | −5.9° | 1 % | 0 | 0 | 0 | 0 | 0 |

\* Learned lux at full ≈ 290 × level; below ~12° the warm shift moves the real
reading a little either way.

*Single fade* — one scene, sunrise to sunset: dose = plateau + ramp (two
linear ramps of R deliver R), ramp 15–150 min, span trimmed around solar noon
when the ramps hit 150. Its daily light is the cap if set, else the natural
day's. It is the automatic fallback for the rest of the day when the lamp goes
brighter than the curve or its read-back lists foreign points.

Defaults (`light_seed_defaults` / `light_seed_sun` in
`packages/light_wrgb2.yaml` — what a fresh board and "Reset" write; the live
values are whatever has been tuned since):

| Phase | Window | Ramp | W / R / G / B | Follows the sun |
|---|---|---|---|---|
| Off (cycling) | — | — | 0 / 0 / 0 / 0 (manual mode, dark) | no |
| 1 — Plants in | civil dawn–dusk (fallback 09:00–16:00) | computed (fallback 45) | 45 / 36 / 20 / 14 | yes, natural |
| 2 — Shrimp | civil dawn–dusk (fallback 09:00–16:00) | computed (fallback 45) | 55 / 45 / 28 / 20 | yes, natural |
| 3 — Fish | civil dawn–dusk (fallback 09:00–16:30) | computed (fallback 45) | 60 / 50 / 32 / 24 | yes, natural |
| 4 — Mature | civil dawn–dusk (fallback 09:00–16:30) | computed (fallback 45) | 70 / 60 / 38 / 30 | yes, natural |

Ratios are deliberate: white is the only dimming lever, and red/green/blue
track it at roughly 0.8 / 0.45 / 0.3. Chihiros' own default is blue at 0.8 of
white, which is most of why a new Pro fixture grows algae. Phase 2 (an
estimated 40–50 µmol/m²/s at the substrate) is the ceiling until CO2 runs;
Phases 3–4 are the CO2 ladder. See the DEFAULTS comment in
`packages/light_wrgb2.yaml` for the PAR each phase is sized to.

**The schedule still runs on the lamp.** A fixed or Single-fade phase is
pushed as an auto-mode scene (switch to scenes → clear slots → schedule →
clock, the app's own sequence — chihiros-esphome `ca8fc35`). A Daylight phase
is pushed as a multi-point day into the lamp's custom-curve controller (curve
controller `5a/05 [03]` → clear it `[05]` → `[03]` → one `5a/06 [ch, hh, mm,
%]` frame per channel per point → clock → status query; chihiros-esphome
`1e677ae`, `532ffa4`): 19 points × 4 channels on 2026-10-20. The lamp's answer
to the status query is checked: a stored time the board did not send raises
Light Curve Rejected and falls back to the single scene for the day. Either way the lamp runs it off its RTC, so the board or HA going
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
lux at the phase's full values (a scene: on its plateau; the daylight curve: lux /
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
