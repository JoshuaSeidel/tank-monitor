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
pH 7.00 buffer and proven right.

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

Lives on the **`dashboard-modern` → Aquarium** view (`/dashboard-modern/aquarium`),
as the **Light** section of the 75-gal block, between "Heaters and controller" and
"Trends". It is gated on `input_select.aquarium_tank` = `75 Gal` like every other
section there. This is *not* on the `aquarium-tank` dashboard that
`aquarium-dashboard.json` tracks.

| Object | What it is |
|---|---|
| `input_select.aquarium_75_light_phase` | The phase selector — five presets |
| `automation.aquarium_75_apply_light_phase` | Pushes the selected preset to the bridge |
| `number.olivers_room_aquarium_light_bridge_wrgb2_schedule_*` | The values the fixture is told to hold |
| `time.olivers_room_aquarium_light_bridge_photoperiod_start` / `_end` | The window |
| `button.olivers_room_aquarium_light_bridge_wrgb2_apply_schedule` | Push now, over BLE |

Note the bridge deployed as `aquarium-light-bridge` in the "Oliver's Room" area,
not as the `tank-monitor-lg-light` name in the repo wrapper — so every entity ID
carries an `olivers_room_aquarium_light_bridge` prefix. Same intentional
repo-name/deployed-name split as the 75-gal controller.

The phases (09:00 anchored, daytime — the tank is lit while someone is at the
desk, 07:00–17:00, not in the evening):

| Phase | Window | Ramp | W / R / G / B |
|---|---|---|---|
| Off (cycling) | 09:00–14:00 | 30 | 0 / 0 / 0 / 0 |
| 1 — Plants in | 09:00–14:00 | 30 | 25 / 20 / 12 / 8 |
| 2 — Shrimp | 09:00–15:00 | 30 | 30 / 25 / 14 / 9 |
| 3 — Fish | 09:00–15:00 | 45 | 35 / 28 / 16 / 10 |
| 4 — Mature | 09:00–16:00 | 45 | 45 / 36 / 20 / 14 |

**The schedule lives on the fixture, not here.** The bridge connects, pushes the
frame, and disconnects; the lamp then runs the photoperiod off its own RTC. Home
Assistant going down does not darken the tank, and neither does the bridge — the
same reasoning that keeps the CO2 failsafe on absolute times.

### Off is manual mode, not a zeroed schedule

Off switches the lamp to manual mode at 0, which darkens it at once. That
choice predates the bridge fix below and was kept because it is proven.

**The bridge fix (2026-09-26, chihiros-esphome `ca8fc35`).** Two symptoms
looked like lamp firmware limits and were not:

- 2026-09-23: an all-zero auto schedule left the tank lit.
- 2026-09-26: Off → Phase 1 at 09:41, inside a 09:00–14:00 window, stored the
  schedule but left the tank dark until the next on/off edge.

The bridge's own btsnoop notes record the app's auto sequence as
`MODE 0x12 → MODE 0x05 → SCHEDULE`, but `prepare()` sent
`MODE 0x07 → SCHEDULE → MODE 0x12`. `0x07` is a CO2 command; `0x05` — clear
the stored auto slots — was never sent, so schedules **accumulated** in the
lamp instead of replacing each other. That is why the zeroed schedule
"didn't darken" it: the Phase 1 slot was still stored beside it.

With the app's sequence restored, a phase change applies within seconds,
mid-window included. Confirmed on the lamp 2026-09-26: Off went dark, then
Phase 1 came back on at once.

So "Off (cycling)" takes the other path in `WRGB2Device::prepare()`:

```cpp
if (auto_mode) {                        // lit phases
    push(reset_schedule(seq()));
    push(wrgb_schedule(..., r, g, b, w, seq()));
    push(reset_auto(seq()));
    push(rtc_packet(time, seq()));      // "triggers lamp schedule evaluation"
} else {                                // Off — immediate, and it works
    push(wrgb_channel(WRGB_R, r, seq()));
    ...
}
```

The automation sets the five numbers to 0 **first**, then turns the auto-mode
switch off. Order matters: in manual mode the bridge sends the same
`schedule_*` numbers as per-channel brightness, so they have to be 0 before the
mode flips. The manual `wrgb2_red/green/blue/white` numbers are never sent —
`on_connect` always passes the `schedule_*` ones to `prepare()`, which looks
like an upstream bug in the fork, but is harmless here.

Trade-off worth knowing: in Off, the lamp is in manual mode and no longer
running a schedule, so it will not light itself at 09:00. That is the desired
behaviour while cycling, and the stored schedule is zeroed anyway.

Ratios are deliberate: white is the only dimming lever, and red/green/blue track
it at 0.8 / 0.45 / 0.3. Chihiros' own default is blue at 0.8 of white, which is
most of why a new Pro fixture grows algae. There is no CO2 on this tank, so
carbon — not light — caps plant growth, and every watt past that cap feeds algae.
W 45 is the ceiling until CO2 exists.

The automation sets the five numbers and both times, waits 10 s, then presses
apply. The wait is not padding: changing a photoperiod time makes the bridge push
on its own after a 1.5 s debounce, and the Chihiros bridge firmware crashes on
overlapping BLE connections. Serialising is the point, and `mode: queued` keeps
two rapid selections from interleaving.

### Two gaps worth knowing

**Nothing verifies the fixture.** The 75-gal's two BH1750 runs are still disabled
(they shorted the 3V3 rail), so no lux sensor confirms the lamp does what the
dashboard says. If they are ever revived, the `light_on_lux` threshold cannot be
copied from the nano's 18 — a 09:00–16:00 photoperiod overlaps room daylight,
which alone would clear it.

**Selecting the phase already showing does nothing.** It is a state trigger, so
re-picking the current option is not a change. Use *Push to fixture* to re-send.

> **`aquarium-dashboard.json` in this folder is stale.** It predates the two-tank
> restructure entirely — 4 nano-only sections, no visibility conditions, no tank
> selector header — while the live `aquarium-tank` dashboard has 7 sections, 6
> badges and the selector. Re-export before trusting this file again.
