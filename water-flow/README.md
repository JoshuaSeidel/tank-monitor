# Water flow meters

Two small ESPHome flow meters for the 75 gal tank (~62 gal / 235 L of real
water), so every water change and every RO fill is measured instead of
estimated: *how much water we take out during changes and fillings*.

| Unit | Device name | Line | Power | Measures |
|---|---|---|---|---|
| RO | `water-flow-ro` | 1/4" RO product line | USB-C 5 V | per-fill gallons, lifetime gallons, fill-to-target signal |
| Change | `water-flow-change` | 1/2" water-change hose, both directions | sealed 1S LiPo | gallons removed / added per change, % changed, net, lifetime |

Both report to Home Assistant over MQTT with discovery, like every other
board in this repo, and both count on the chip: a Wi-Fi or broker drop
costs the live view, never a pulse. Units are US gallons everywhere a person
reads them; litres appear only in the diagnostic flow rate and the
calibration constant, because that is how the sensor datasheets state them.

## Files

| File | What it is |
|---|---|
| `water-flow-ro-remote.yaml` | **deploy wrapper**, RO unit -- put this in the ESPHome dashboard |
| `water-flow-change-remote.yaml` | **deploy wrapper**, change unit |
| `local-water-flow-ro.yaml`, `local-water-flow-change.yaml` | dev wrappers: build from the working tree, `-test` device names |
| `packages/flow_meter.yaml` | shared core: pulse input, flow sessions, flow rate, persistence, network tuning |
| `packages/battery.yaml` | LiPo voltage / percent / low-battery (change unit only) |
| `packages/ro_fill.yaml` | RO unit logic |
| `packages/water_change.yaml` | change unit logic |
| `boards/esp32-lite.yaml` | AITRIP ESP32 Lite V1.0.0 (LOLIN32 Lite clone) -- **the default** |
| `boards/xiao-esp32s3.yaml` | Seeed XIAO ESP32-S3 -- alternative |
| `boards/xiao-esp32c3.yaml` | Seeed XIAO ESP32-C3 -- alternative, same pads as the S3 |

The repo's own `packages/base.yaml` supplies Wi-Fi, MQTT (with the
non-blocking `idf_send_async` publish), SNTP, OTA, the web page and the
diagnostics, so these boards use the same `secrets.yaml` keys as the tank
boards. Nothing from the tank controller is pulled in.

The remote wrappers build from GitHub `main` with `refresh: 0s`: a change
reaches a board only after it is pushed. To build a unit for a XIAO
instead, change the last line of its wrapper's `files:` list to
`water-flow/boards/xiao-esp32s3.yaml` (or `xiao-esp32c3.yaml`) and wire
per [Alternative board: Seeed XIAO](#alternative-board-seeed-xiao).

---

## The board: AITRIP ESP32 Lite V1.0.0

A WEMOS LOLIN32 Lite clone: ESP32-D0WDQ6 rev1, 4 MB flash, CH340 USB
serial on USB-C, ME6211 3.3 V LDO (500 mA), TP4054 LiPo charger (~500 mA)
with a JST-PH 2.0 battery socket, blue LED on GPIO22 (lit when low).

Two things it does **not** have, and the wiring is built around both:

* **No 5 V header pin.** On the LOLIN32 Lite, USB 5 V goes to the charger
  and the LDO and nowhere else -- there is no way to take 5 V off the
  header for a peripheral. (Some clone listings draw a "5V" pin; the
  design does not depend on one.) Both flow sensors need 5 V, so each
  unit has a **fixed-5 V synchronous boost module** (see Parts): the RO
  unit's runs from the **3V pin**, the change unit's straight from the
  **switched battery line**. Nobody has to cut a USB cable.
* **No battery sense.** Battery + is not on the header and is not divided
  to any GPIO. The change unit taps its battery lead into an external
  100k/100k divider on GPIO35.

LDO budget for the RO unit's boost on 3V3: the ESP32's Wi-Fi peaks at
~250-350 mA for microseconds; the boost draws ~26 mA from 3.3 V to give the
sensor 15 mA at 5 V (~88 % efficient) plus a few mA for its power LED.
All inside the ME6211's 500 mA.

Header pins are labelled with GPIO numbers. **3V, GND, 22, 27, 35** are the
only five this project uses.

---

## Parts

### Both units

| Part | Notes |
|---|---|
| **AITRIP ESP32 Lite V1.0.0** (LOLIN32 Lite clone, USB-C) | |
| **5 V synchronous boost module** -- the "DC-DC Step Up Board, 0.9/1.5/1.8/2.5/3/3.3/3.7/4.2 V to 5 V" 10-pack already on hand | powers the flow sensor. **Fixed 5 V output, 0.9-4.2 V input**, pads IN+ / IN- / OUT+ / OUT-; some have a USB-A socket and/or a power LED. No trim pot, nothing to set -- but **meter OUT+ to OUT- once: it must read 5.0 V (4.8-5.2) before the sensor is connected** |
| 10 kΩ + 20 kΩ resistors, ¼ W | pulse-line divider, 5 V -> 3.3 V |
| 26-28 AWG silicone wire, heat shrink | |

### RO unit -- `water-flow-ro`

| Part | Notes |
|---|---|
| **uxcell 1/4" quick-connect hall flow sensor**, DC 5 V, 0.05-0.8 L/min | in the RO product line. A 100 GPD membrane makes ~0.26 L/min |
| USB-C 5 V wall adapter, ≥ 500 mA | preferred. The unit draws ~100-130 mA |
| *or* USB-C power bank with an **always-on / low-current mode** | portable alternative. At ~100 mA this board stays above most banks' auto-off threshold, but the margin is small -- use the mode if the bank has one |

No battery: leave the JST socket empty. This unit publishes no battery
entities -- there is nothing for them to measure.

### Change unit -- `water-flow-change` (sealed)

It lives beside a lot of moving water, so it is a closed box with one
cable gland and nothing to plug in during use.

| Part | Notes |
|---|---|
| **YF-S201-class 1/2" hall flow sensor**, 1-30 L/min | in the change hose |
| **MakerHawk 3.7 V 1000 mAh 1S LiPo, 102050** (10 × 20 × 50 mm) | dual protection board (PCM) on the cell -- **required**, never an unprotected cell in a sealed box. JST-PH 2.0 plug, straight into the board's battery socket |
| JST-PH 2.0 male/female extension lead (or one plug + one socket pigtail) | carries the switch, the divider tap and the boost feed, so the cell stays unpluggable and neither it nor the board's socket is modified. (Cutting the cell's own + lead works too, but then the cell can't be swapped) |
| **12 mm IP67 metal latching (self-locking) push-button, WITHOUT LED** -- e.g. "Juasky 5pcs 12mm Latching Metal Switch, Waterproof Self-Locking Push Button, High Head" (Amazon B0DWHSG6YW) | the on/off switch, in series in the battery + lead. Get the **no-LED** version: the LED versions are rated 12-24 V and will not light at 3.7 V. Panel-mounts through a **12 mm (0.47") hole** in the enclosure wall, O-ring on the **outside** |
| 100 kΩ + 100 kΩ resistors, 100 nF ceramic | battery-voltage divider and its filter cap |
| **IP65 ABS enclosure, ~85 × 58 × 33 mm** | the board (~50 × 25 mm plus the USB-C plug), the cell (50 × 20 × 10), the boost module and the switch. A 65 × 58 × 35 mm box fits too, but tightly |
| PG7 cable gland | the sensor's three wires |
| Optional: IP67 capped USB-C panel jack | to charge and flash without opening the lid. Otherwise open the lid to reach the board's USB-C |

---

## Wiring

Wire colours on both sensors: **red = +5 V, black = GND, yellow = pulse**.
Pin names below are the ESP32 Lite's header labels.

### The pulse-line divider (both units)

The hall sensor's output is pulled up to its own 5 V supply inside the
sensor. A 10 k (top) / 20 k (bottom) divider brings that to 3.3 V:

```
 sensor yellow ──[ 10 kΩ ]──┬── header 27 (GPIO27)
                            │
                         [ 20 kΩ ]
                            │
                           GND
```

**Check it once with a meter before trusting the counts.** Turn the rotor
slowly by blowing through the sensor and read pin 27 to GND at the high
level. It must sit between **2.6 V and 3.4 V**. If the sensor's internal
pull-up is about 10 kΩ, the high level is only 5 × 20 / (10 + 10 + 20) =
2.5 V -- right on the ESP32's 2.48 V input threshold, which counts
erratically. In that case replace the **10 kΩ top resistor with a wire**:
the sensor's own pull-up becomes the top leg and the pin sees 5 × 20 / 30
= 3.3 V. Do not do that if the high level already reads above 3 V -- that
sensor drives its output hard, and without the top resistor the pin would
see 5 V.

The 20 kΩ also holds the pin low with the sensor unplugged, so a missing
sensor reads as no flow rather than as noise.

### Sensor power (both units)

The boost module's output is fixed at 5 V -- there is no voltage to set.
Still, **power the module once with nothing on OUT and meter OUT+ to OUT-:
it must read 5.0 V (4.8-5.2 V)** before the sensor goes on. A module from
a mixed batch, or one with a damaged regulator, can pass its input
straight through or sit well off 5 V, and a pulse divider sized for 5 V
then gives the wrong level at the pin.

IN- and OUT- are the same ground on these modules; the sensor's black
goes to OUT-, which is also the board's GND through IN-.

### RO unit -- `water-flow-ro`

```
 POWER
  USB-C 5 V (wall adapter, or power bank in always-on mode) ── board USB-C
  JST battery socket: empty

 SENSOR (uxcell 1/4")
  3V ──── boost IN+          boost OUT+ (5.0 V) ── red
  GND ─── boost IN-          boost OUT- ────────── black
  yellow ──[ 10 kΩ ]──┬───── 27
                      └─[ 20 kΩ ]── GND

  35 unused (no battery on this unit). Status LED: 22, on the board.
```

### Change unit -- `water-flow-change`

> **CHECK THE BATTERY PLUG POLARITY WITH A METER BEFORE CONNECTING IT.**
> JST-PH battery polarity is **not standardised** -- cells and boards from
> different makers are wired both ways round, and a reversed LiPo destroys
> the board's charger instantly. Meter the cell's plug and find which pin
> is +; it must mate with the pin marked **+** beside the board's JST
> socket. Check the extension lead the same way, end to end. If anything
> disagrees, re-pin the extension lead's housing -- never the cell's.

```
 POWER  (JST-PH extension lead between cell and board)
  cell plug + (red) ──[ 12 mm latching switch ]──┬─────── board JST socket +
                                                 ├─────── boost IN+
                                                 └─────── battery divider top (below)
  cell plug - (black) ─────────────────────────────┬───── board JST socket -
                                                   └───── boost IN-

 SENSOR (YF-S201)
  boost OUT+ (5.0 V) ── red
  boost OUT- ────────── black
  yellow ──[ 10 kΩ ]──┬───── 27
                      └─[ 20 kΩ ]── GND

 BATTERY SENSE
  switched + ──[ 100 kΩ ]──┬───────── 35
                           ├─[ 100 kΩ ]── GND
                           └─[ 100 nF ]── GND
```

* The switch is the 12 mm latching push-button, wired **in series in the +
  wire** of a short JST-PH male/female extension: cell plug -> switch ->
  board socket, with the boost IN+ and the divider tapped on the board side
  of the switch. Mount it through a 12 mm hole in the box wall, O-ring
  outside the wall so the seal is against the box. Press to latch on, press
  again to release off.
* The divider's top leg takes the **switched** battery line, so nothing
  drains the cell while the box is off (the divider is ~20 µA when on).
* **Charging needs the switch ON** -- the switch is between the cell and
  the charger. Charge from USB-C with the switch on; the board runs and
  reports while it charges.
* Why the change unit's boost runs from the battery and not from 3V: the
  switched + wire in the extension lead is already there for the divider,
  so it costs one more joint, and it skips a conversion -- the sensor's
  current no longer passes through the LDO first. The cell never exceeds
  the module's 4.2 V input limit (the charger stops at 4.2 V), and the
  module keeps making 5 V down to 0.9 V, far below where the board quits.
* The boost's own idle draw and power LED are behind the switch too: with
  the box off, nothing draws from the cell.
* Status LED: 22, on the board -- blinking until online, then dark.

---

## Battery (change unit)

Estimated draw from the cell. The LOLIN32 Lite is not a frugal board:
its CH340 and LDO run from the battery too, and it measures ~45 mA with
Wi-Fi off and ~130 mA with Wi-Fi on and no power saving.

| Load | mA from the cell |
|---|---|
| board + ESP32, Wi-Fi connected, MQTT, power-save light | ~70-90 |
| YF-S201 (≤ 15 mA at 5 V) via the boost from the cell (~88 %) | ~23 |
| boost module's own quiescent draw + its power LED, if fitted | ~1-3 |
| dividers, status LED dark | < 0.1 |
| **total** | **~95-115 typical, ~160 worst** |

The module's power LED is the one load that buys nothing inside a sealed
box; desoldering it (or cutting its trace) saves ~1-2 mA, worth about 2 %
of the runtime -- optional.

A 1000 mAh cell gives ~850 mAh before Low Battery (3.55 V): **about 7-9 h
on, ~5 h worst case.** A water change with the box on for 30-45 minutes
(drain, refill, the waits between) uses 50-120 mAh: **about 7-10 changes
per charge** -- plan on 7, and charge when "Low Battery" comes on or after
every few changes, whichever is first.

The board's TP4054 charges at ~500 mA, so a full charge from empty takes
**about 2.5-3 hours** (0.5 C, gentle for this cell). A top-up after one
change takes well under an hour.

Low Battery turns on below 3.55 V under load (30 s debounce, so a Wi-Fi
transmit dip does not trip it). At that point there is enough left to
finish the change in progress, not to start another.

---

## Pin map

| Signal | ESP32 Lite (default) | XIAO ESP32-S3 | XIAO ESP32-C3 |
|---|---|---|---|
| Flow pulse (divided) | GPIO27 | D3 = GPIO4 | D3 = GPIO5 |
| Battery sense (ADC1) | GPIO35 | D1 = GPIO2 | D1 = GPIO3 |
| Status LED | GPIO22 (on-board, active low) | GPIO21 (on-board) | none |
| Sensor 5 V | boost from 3V (RO) / switched battery (change) | see below | see below |

ESP32 Lite pins avoided: 0, 2, 5, 12, 15 (strapping), 6-11 (flash), 36/39
(spurious-interrupt erratum), and ADC2 (0, 2, 4, 12-15, 25-27) for
anything analog -- ADC2 cannot read while Wi-Fi is on. Full reasoning in
`boards/esp32-lite.yaml`.

### Alternative board: Seeed XIAO

Both XIAO board files work with the same packages. Wire by the D-labels
in the table (they are not GPIO numbers). Differences from the ESP32 Lite:

* The XIAO's 5V pad is VBUS -- live on USB. On the RO unit it can feed the
  sensor directly with no boost. On battery it is dead, so the change unit
  still needs the boost module, fed from the switched BAT+ line.
* The battery goes on the BAT+/BAT- pads under the board (no socket):
  solder a JST-PH pigtail there, with the same polarity check as above.
* Lower draw (~70 mA total on the change unit, ~10-15 changes per 1000
  mAh) but a ~100 mA charger: 10+ hours to charge from empty.
* The XIAO needs its U.FL antenna attached.

---

## Operating procedure

**RO fill**

1. Plug the RO meter into USB-C. Wait for the blue LED to stop blinking
   (~10 s) -- or for "Water Flow RO Status" to show online.
2. Set **Fill Target** in gallons if Home Assistant should stop the fill
   (0 = no target, measure only).
3. Turn the RO on (`switch.ro_water`). "Fill Volume" starts from 0 at the
   first flow after 2 minutes idle; **Reset Fill** zeroes it by hand.
4. When the fill is done, wait ~10 s after the water stops before
   unplugging: the volumes are written to flash when flow stops.

**Water change**

1. Switch the change meter on; wait for the blue LED to stop blinking.
2. Press **New Water Change** (zeroes Removed / Added for this change).
3. Set **Mode = Draining**, then drain. Every Brute-load is a step; "Step
   Volume" shows the current one, "Removed This Change" and "Percent
   Changed" the running total.
4. Set **Mode = Refilling** *before* the refill water starts, then refill.
   "Added This Change" climbs; "Net Change" is back to 0 when the tank is.
5. Wait ~10 s after the last water, then switch off.

The mode cannot be detected -- a paddle sensor pulses the same way in both
directions. Water counted in the wrong mode lands in the wrong column.

## First-run calibration

Neither constant can be trusted out of the box:

* **RO: 4560 pulses/L** (F = 76 × Q). uxcell publishes no constant for the
  0.05-0.8 L/min part; 76 Hz per L/min is the figure listed for uxcell's
  sibling 1/4" quick-connect sensor. Expect it to be off by tens of percent.
* **Change: 450 pulses/L** both directions (the YF-S201 datasheet's
  F = 7.5 × Q). Commonly 5-15 % off forwards and more in reverse.

Both are corrected on the device, once, against the Brute (Brute 2620, 20
gal) marked at a known volume -- measure a mark with a calibrated jug
rather than trusting the moulded lines.

**RO unit**

1. Fill the marked Brute (or any container of known volume) from the RO
   in one go, measured by this meter. Let flow stop.
2. Enter the gallons actually in the container in **Measured Fill**.
3. Press **Calibrate From Measured Fill**. The board divides the fill's
   pulses by the measured litres, stores the new "Calibration Pulses per
   Litre", and "Fill Volume" immediately reads the measured value.

**Change unit** -- once per direction:

1. Mode = Draining. Drain into the empty Brute up to the mark in one run.
   Enter the true gallons in **Measured Step**, press **Calibrate From
   Measured Step**. "Drain Pulses per Litre" is set; this change's Removed
   is restated to match.
2. Mode = Refilling. Pump exactly that marked volume back. Enter it in
   **Measured Step**, press calibrate again. "Refill Pulses per Litre" is
   set.

Calibration rejects nonsense (no measurement entered, < 100 pulses, or a
result outside the plausible range) and logs why. The lifetime totals are
never restated -- Home Assistant reads any decrease in a `total_increasing`
sensor as a meter reset -- so the one calibration run stays in them at the
old constant. Re-check a calibration after a few fills against the Brute
mark; repeat the same procedure if it drifts.

---

## What persists, and when

| Value | Persisted |
|---|---|
| calibration constants, fill target, tank volume, mode | yes |
| last fill / last step (as raw pulses), this change's removed / added | yes |
| lifetime totals | yes |
| live flow rate, Flowing, measured-gallons input | no |

Values go to flash every 30 s **while they are changing**, and immediately
when flow stops. The ESP32's flash layer compares each value with what is
already stored and skips identical writes, so an idle meter left on writes
nothing. A power cut mid-flow loses at most 30 s of counting; switching off
after the water has stopped loses nothing. A 5 h RO fill is ~600 small
writes, spread across the flash by wear levelling.

A reboot ends the current session (the next flow starts a new fill / step);
volumes already counted are kept. Wi-Fi and MQTT outages do **not** reboot
these boards -- the default 15-minute reboot is disabled so a router blip
cannot zero a fill.

---

## Home Assistant entities

Entity ids are what MQTT discovery creates from the friendly name plus the
entity name. Every unit also gets the repo-standard diagnostics from
`packages/base.yaml`: `sensor.<unit>_wi_fi_signal`, `_uptime`,
`_heap_free`, `_heap_max_block`, `_loop_time`, `_reset_reason`,
`_firmware_build`, `_ip_address`, `binary_sensor.<unit>_status`,
`button.<unit>_restart`.

### `water-flow-ro` (friendly name "Water Flow RO")

| Entity | Unit | Notes |
|---|---|---|
| `sensor.water_flow_ro_flow_rate` | gal/min | live |
| `sensor.water_flow_ro_flow_rate_litres_per_minute` | L/min | diagnostic |
| `binary_sensor.water_flow_ro_flowing` | | on while pulses arrive |
| `sensor.water_flow_ro_fill_volume` | gal | current / last fill |
| `sensor.water_flow_ro_total_produced` | gal | lifetime, `total_increasing`, `device_class: water` |
| `sensor.water_flow_ro_fill_pulses` | pulses | diagnostic |
| `number.water_flow_ro_fill_target` | gal | 0 = disabled |
| `binary_sensor.water_flow_ro_fill_target_reached` | | on when fill ≥ target |
| `button.water_flow_ro_reset_fill` | | |
| `number.water_flow_ro_calibration_pulses_per_litre` | | config |
| `number.water_flow_ro_measured_fill` | gal | config |
| `button.water_flow_ro_calibrate_from_measured_fill` | | config |

### `water-flow-change` (friendly name "Water Flow Change")

| Entity | Unit | Notes |
|---|---|---|
| `select.water_flow_change_mode` | | Draining / Refilling |
| `sensor.water_flow_change_flow_rate` | gal/min | live |
| `sensor.water_flow_change_flow_rate_litres_per_minute` | L/min | diagnostic |
| `binary_sensor.water_flow_change_flowing` | | |
| `sensor.water_flow_change_step_volume` | gal | current / last step |
| `sensor.water_flow_change_removed_this_change` | gal | |
| `sensor.water_flow_change_added_this_change` | gal | |
| `sensor.water_flow_change_net_change` | gal | added − removed |
| `sensor.water_flow_change_percent_changed` | % | removed ÷ tank volume |
| `sensor.water_flow_change_lifetime_removed` | gal | `total_increasing` |
| `sensor.water_flow_change_lifetime_added` | gal | `total_increasing` |
| `sensor.water_flow_change_step_pulses` | pulses | diagnostic |
| `button.water_flow_change_new_water_change` | | |
| `number.water_flow_change_tank_water_volume` | gal | config, default 62 |
| `number.water_flow_change_drain_pulses_per_litre` | | config |
| `number.water_flow_change_refill_pulses_per_litre` | | config |
| `number.water_flow_change_measured_step` | gal | config |
| `button.water_flow_change_calibrate_from_measured_step` | | config |
| `sensor.water_flow_change_battery_voltage` | V | diagnostic |
| `sensor.water_flow_change_battery` | % | |
| `binary_sensor.water_flow_change_low_battery` | | |

---

## Home Assistant side (configured separately, not in this folder)

The boards measure; Home Assistant acts. What will be added there:

* **Fill by volume.** Trigger: `binary_sensor.water_flow_ro_fill_target_reached`
  from `off` to `on`. Action: turn off `switch.ro_water`. The board cannot
  reach the Kasa plug itself. Triggering on the `off -> on` edge (not on
  "is on") keeps a board coming online from switching the RO off.
* **RO stall alert.** `switch.ro_water` on while
  `binary_sensor.water_flow_ro_flowing` is off for N minutes (and the RO
  meter is online) -> notify. This is how "flow below the sensor's
  minimum" is caught: under 0.05 L/min the rotor stops, no pulse arrives,
  and that is indistinguishable on the board from no water at all -- a
  fouled membrane, an empty feed, a closed valve, or the meter unplugged.
* **Daily / monthly RO usage.** `utility_meter` helpers (daily, monthly)
  on `sensor.water_flow_ro_total_produced`. Done in HA rather than on the
  board because the board is off most of the day; utility_meter gets
  midnight right regardless. The same works for the change unit's
  lifetime totals.
* **Salty Shrimp for the refill.** ~5.5 g raises the whole tank (62 gal) by
  1 dGH, i.e. ≈ 5.5 / 62 = 0.089 g per gallon per dGH. To bring RO refill
  water up to the tank's GH target before it goes in:
  grams ≈ 0.089 × target dGH × refill gallons -- with refill gallons from
  `sensor.water_flow_change_added_this_change` (or the planned volume from
  `removed_this_change`). Example: 15 gal at 8 dGH ≈ 10.6 g.
