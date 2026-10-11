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
| `boards/xiao-esp32s3.yaml` | Seeed XIAO ESP32-S3 pins -- **the default** |
| `boards/xiao-esp32c3.yaml` | Seeed XIAO ESP32-C3 pins -- optional, same pads |

The repo's own `packages/base.yaml` supplies Wi-Fi, MQTT (with the
non-blocking `idf_send_async` publish), SNTP, OTA, the web page and the
diagnostics, so these boards use the same `secrets.yaml` keys as the tank
boards. Nothing from the tank controller is pulled in.

The remote wrappers build from GitHub `main` with `refresh: 0s`: a change
reaches a board only after it is pushed. To move a unit to the XIAO
ESP32-C3, change the last line of its wrapper's `files:` list to
`water-flow/boards/xiao-esp32c3.yaml`; the wiring lands on the same
D-numbered pads.

---

## Parts

### Both units

| Part | Notes |
|---|---|
| **Seeed XIAO ESP32-S3** (or XIAO ESP32-C3) | with its U.FL antenna attached -- there is no on-board antenna |
| 10 kΩ + 20 kΩ resistors, ¼ W | pulse-line divider, 5 V -> 3.3 V |
| 26-28 AWG silicone wire, heat shrink | |

### RO unit -- `water-flow-ro`

| Part | Notes |
|---|---|
| **uxcell 1/4" quick-connect hall flow sensor**, DC 5 V, 0.05-0.8 L/min | in the RO product line. A 100 GPD membrane makes ~0.26 L/min |
| USB-C 5 V wall adapter, ≥ 500 mA | preferred. The board and sensor draw ~60 mA |
| *or* USB-C power bank **with an always-on / low-current mode** | portable alternative. Most banks switch themselves off below a 50-100 mA load, which this unit sits right at; without that mode it will die mid-fill |

No boost board and no battery: on USB the XIAO's 5V pad is live and feeds
the sensor directly. This unit has no battery entities -- there is nothing
for them to measure.

### Change unit -- `water-flow-change` (sealed)

It lives beside a lot of moving water, so it is a closed box with one
cable gland and nothing to plug in during use.

| Part | Notes |
|---|---|
| **YF-S201-class 1/2" hall flow sensor**, 1-30 L/min | in the change hose |
| **MakerHawk 3.7 V 1000 mAh 1S LiPo, 102050** (10 × 20 × 50 mm) | dual protection board (PCM) on the cell -- **required**; never use an unprotected cell in a sealed box. JST-PH 2.0 plug |
| JST-PH 2.0 pigtail, mating the cell's plug | soldered to the XIAO's BAT+/BAT- pads so the cell can be unplugged and swapped |
| **Pololu U1V11F5** 5 V step-up | battery -> 5 V for the sensor. 0.5-5.5 V in, so it runs the whole LiPo range. EN left unconnected (on-board pull-up) |
| Waterproof on/off switch (IP67 panel-mount rocker or push-button, ≥ 1 A) | in the battery + line |
| 100 kΩ + 100 kΩ resistors, 100 nF ceramic | battery-voltage divider and its filter cap |
| **IP65 ABS enclosure, ~65 × 58 × 35 mm** | fits the cell (50 × 20 × 10), the XIAO (21 × 17.5), the U1V11F5 and the switch |
| PG7 cable gland | the sensor's three wires |
| Optional: IP67 capped USB-C panel jack | to charge and flash without opening the lid. Otherwise open the lid to reach the XIAO's USB-C |

---

## Wiring

Wire colours on both sensors: **red = +5 V, black = GND, yellow = pulse**.
GPIOs below are for the XIAO ESP32-S3; the XIAO ESP32-C3 uses the **same
pads** (D3 = GPIO5, D1 = GPIO3 there).

### The pulse-line divider (both units)

The hall sensor's output is pulled up to its own 5 V supply inside the
sensor. A 10 k (top) / 20 k (bottom) divider brings that to 3.3 V:

```
 sensor yellow ──[ 10 kΩ ]──┬── XIAO D3 (GPIO4)
                            │
                         [ 20 kΩ ]
                            │
                           GND
```

**Check it once with a meter before trusting the counts.** Turn the rotor
slowly by blowing through the sensor and read D3 to GND at the high level.
It must sit between **2.6 V and 3.4 V**. If the sensor's internal pull-up is
about 10 kΩ, the high level is only 5 × 20 / (10 + 10 + 20) = 2.5 V -- right
on the ESP32's 2.48 V input threshold, which counts erratically. In that
case replace the **10 kΩ top resistor with a wire**: the sensor's own
pull-up becomes the top leg and the pin sees 5 × 20 / 30 = 3.3 V. Do not
do that if the high level already reads above 3 V -- that sensor drives its
output hard, and without the top resistor the pin would see 5 V.

The 20 kΩ also holds the pin low with the sensor unplugged, so a missing
sensor reads as no flow rather than as noise.

### RO unit -- `water-flow-ro`

```
 POWER
  USB-C 5 V (wall adapter, or power bank in always-on mode) ── XIAO USB-C

 SENSOR (uxcell 1/4")
  XIAO 5V pad ────────────────── red      (VBUS: live because USB is plugged in)
  XIAO GND ───────────────────── black
  yellow ──[ 10 kΩ ]──┬───────── XIAO D3 (GPIO4)
                      └─[ 20 kΩ ]── GND

  D1 unused -- no battery on this unit. Status LED: GPIO21, on the board.
```

### Change unit -- `water-flow-change`

> **CHECK THE BATTERY PLUG POLARITY WITH A METER BEFORE CONNECTING IT.**
> JST-PH battery polarity is **not standardised** -- cells and pigtails from
> different makers are wired both ways round, and a reversed LiPo destroys
> the XIAO's charger instantly. Meter the cell's plug, then meter the
> pigtail once it is soldered: the cell's **red (+) must land on the XIAO's
> BAT+ pad** (through the switch). If they disagree, swap the pins in the
> pigtail's housing -- never the cell's.

```
 POWER
  LiPo + (red) ── JST-PH ── [ ON/OFF switch ] ──┬──── XIAO BAT+ pad (underside)
                                                 ├──── U1V11F5 VIN
                                                 └──── battery divider top (below)
  LiPo - (black) ─ JST-PH ───────────────────────┬──── XIAO BAT- pad = GND
                                                 └──── U1V11F5 GND

 SENSOR (YF-S201)
  U1V11F5 VOUT (5.0 V) ───────── red
  GND ────────────────────────── black
  yellow ──[ 10 kΩ ]──┬───────── XIAO D3 (GPIO4)
                      └─[ 20 kΩ ]── GND

 BATTERY SENSE
  switched BAT+ ──[ 100 kΩ ]──┬───────── XIAO D1 (GPIO2)
                              ├─[ 100 kΩ ]── GND
                              └─[ 100 nF ]── GND
```

* The divider's top leg takes the **switched** battery line, so nothing
  drains the cell while the box is off (the divider is ~20 µA when on).
* **Charging needs the switch ON** -- the switch is between the cell and
  the charger. Charge from USB-C with the switch on; the board runs and
  reports while it charges.
* The U1V11F5 is fixed at 5.0 V, so there is no output to set. (If an
  adjustable boost such as an MT3608 is ever substituted: set it to 5.0 V
  with no load **before** the sensor is connected.)
* Status LED: GPIO21, on the board -- blinking until online, then dark.

---

## Battery (change unit)

Estimated draw from the cell, XIAO ESP32-S3 on Wi-Fi with light modem
sleep:

| Load | mA from the cell |
|---|---|
| XIAO ESP32-S3, Wi-Fi connected, MQTT, power-save light | ~45-60 |
| YF-S201 (≤ 15 mA at 5 V) through the U1V11F5 (~85 %) | ~20-25 |
| dividers, status LED dark | < 0.1 |
| **total** | **~70 typical, ~110 worst** |

A 1000 mAh cell gives ~850 mAh before Low Battery (3.55 V), so roughly
**11-12 h on, ~8 h worst case**. A water change with the box on for 30-45
minutes (drain, refill, the waits between) uses 35-80 mAh: **about 10-15
changes per charge** -- call it 10 and charge when "Low Battery" comes on
or every couple of weeks, whichever is first.

The XIAO ESP32-S3's on-board charger runs at about **100 mA**, so a full
charge from empty takes **10+ hours -- charge overnight**. A top-up after
one change takes under an hour.

Low Battery turns on below 3.55 V under load (30 s debounce, so a Wi-Fi
transmit dip does not trip it). At that point there is enough left to
finish the change in progress, not to start another.

---

## Pin map

| Signal | XIAO pad | ESP32-S3 GPIO | ESP32-C3 GPIO | Why this pin |
|---|---|---|---|---|
| Flow pulse (divided) | D3 | GPIO4 | GPIO5 | plain interrupt input; not a strapping pin on either chip |
| Battery sense | D1 | GPIO2 | GPIO3 | ADC1 on both chips (ADC2 cannot read with Wi-Fi on) |
| Status LED | on-board | GPIO21 | -- (none) | |
| *never used* | D2 | GPIO3 (strap) | GPIO4 | S3 strapping pin |
| *never used* | D0, D8, D9 | | GPIO2/8/9 (strap) | C3 strapping pins |

---

## Operating procedure

**RO fill**

1. Plug the RO meter into USB-C. Wait for the status LED to stop blinking
   (~10 s) -- or for "Water Flow RO Status" to show online.
2. Set **Fill Target** in gallons if Home Assistant should stop the fill
   (0 = no target, measure only).
3. Turn the RO on (`switch.ro_water`). "Fill Volume" starts from 0 at the
   first flow after 2 minutes idle; **Reset Fill** zeroes it by hand.
4. When the fill is done, wait ~10 s after the water stops before
   unplugging: the volumes are written to flash when flow stops.

**Water change**

1. Switch the change meter on; wait for the LED to stop blinking.
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
