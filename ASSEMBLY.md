# Assembly

Four boards are covered here and they wire up differently:

- **[ESP32-C6 (`tank-monitor`)](#esp32-c6-tank-monitor)** — solder directly to
  the board's pads.
- **[CYD ESP32-2432S028R (`tank-monitor-v2`)](#cyd-esp32-2432s028r-tank-monitor-v2)** —
  display-only remote panel. No wiring at all.
- **[ESP32-WROOM-32 (`tank-monitor-w32`)](#esp32-wroom-32-tank-monitor-w32)** —
  headless controller. Same wiring as the C6 on different pins.
- **[ESP32-S3 mini (`tank-monitor-s3`)](#esp32-s3-mini-tank-monitor-s3)** —
  headless controller in 23 × 18 mm. Solder directly to the board.
- **[XIAO ESP32-S3, large tank (`tank-monitor-75-gallon`)](#xiao-esp32-s3-large-tank-tank-monitor-75-gallon)** —
  headless controller, two of everything. Sensors on an ADS1115, three relay
  channels, two 1-Wire buses. Needs a power rail, not a splice.

Build order matters on both: power bus first, sensors one at a time, relay
last. That way if something is wrong you know which step caused it.

# ESP32-C6 (`tank-monitor`)

**Nothing is plugged in — no USB, no mains — until step 8.**

## What you need

- 26–28 AWG stranded hookup wire (silicone jacket is easiest to work with)
- 4.7 kΩ resistor (1/4 W)
- Heat shrink, 2 mm and 3 mm
- Soldering iron ~625 °F (330 °C), thin rosin-core solder
- Multimeter

Everything solders directly to the ESP32-C6 board. No breakout, no perfboard.

## 1. Prep the board

Identify the pads by the silkscreen labels on the back: `3V3`, `GND`, and the
GPIO numbers you need — **1, 10, 18, 19, 20**.

Tin each pad: touch the iron to the pad, feed a small amount of solder, remove.
You want a shiny dome, not a blob. Two seconds per pad — the C6 is fine but
don't dwell.

## 2. Pre-tin every wire end

Every wire, both ends, including the sensor pigtails. Twist the strands, tin
them, then trim to ~3 mm. Untinned stranded wire fans out and bridges
neighbouring pads, which is the single most common way this build goes wrong.

**Slide heat shrink onto the wire before you solder it.** You will forget at
least once. Everyone does.

## 3. Splice the power wires

There is one `3V3` pad and one `GND` pad, but three sensors need power and
four wires need ground. You can't stack that many wires on a single pad and
get a joint that survives being moved.

So join them **off the board** and run a single pigtail to each pad.

**3V3 splice — three wires plus a pigtail:**

```
   DS18B20 red   ─┐
   TDS VCC       ─┼──[ twist + solder + heat shrink ]──── pigtail ──► 3V3 pad
   BH1750 VCC    ─┘
```

**GND splice — four wires plus a pigtail:**

```
   DS18B20 black ─┐
   TDS GND       ─┤
   BH1750 GND    ─┼──[ twist + solder + heat shrink ]──── pigtail ──► GND pad
   Relay IN− ×2  ─┘
```

For each splice: strip ~10 mm on every wire including the pigtail, twist all
the conductors together into one bundle, flow solder through until it wicks
right through, then cover the whole thing with 3 mm heat shrink. Slide the
shrink on first.

The two relay `IN−` terminals can share one wire — jumper between them at the
module and run a single lead back to the splice.

**Solder the two pigtails to the board first**, then check with a multimeter
that there is **no continuity between 3V3 and GND**. Find a short now, not
after everything else is attached.

## 4. Sensor power

Already done — it's in the splices from step 3. Just confirm each sensor is on
the right one:

| Sensor | 3V3 splice | GND splice |
|---|---|---|
| DS18B20 | red | black |
| TDS board | VCC | GND |
| BH1750 | VCC | GND |

**TDS goes to 3.3 V, never 5 V.** 5 V on its output will destroy GPIO1.

## 5. Signal wires

One at a time, board pad → sensor:

| Board pad | Goes to |
|---|---|
| GPIO18 | DS18B20 yellow (DQ) |
| GPIO1 | TDS `A` |
| GPIO19 | BH1750 `SDA` |
| GPIO20 | BH1750 `SCL` |

Leave BH1750 `ADDR` unconnected — floating is address 0x23, which is what the
config expects.

Shrink each joint as you go.

## 6. The 4.7 kΩ pull-up

Solder it between the **DQ line and 3V3**, at the *board* end of the run —
not out at the probe. Easiest way: include one resistor leg in the 3V3 splice
when you make it in step 3, and solder the other leg onto the GPIO18 wire
where it leaves the board.

Sleeve both legs with heat shrink. Bare resistor legs near a tank are a short
waiting to happen.

Without this resistor the DS18B20 reads nothing or garbage. Any value from
2.2 kΩ to 10 kΩ will do — 4.7 kΩ is convention, not a requirement.

If you don't have one yet, the README covers switching to the C6's internal
pull-up as a bench-test stopgap. It is not a permanent substitute.

## 7. Relay control pair

Two signal wires plus one ground, to the D-1584TL's **low-voltage terminals
only**:

| Board pad | D-1584TL |
|---|---|
| GPIO2 | Channel 1 `IN+` (heater) |
| GPIO3 | Channel 2 `IN+` (fan) |
| GND splice | `IN−`, both channels (jumpered together) |

Do not open the relay module or touch its mains side. It has its own cord.

**Route the TDS signal wire away from the relay's power cord.** High-impedance
analog next to a mains cable picks up 60 Hz hum, and you'll chase a noisy
reading that isn't a sensor fault.

## 8. Inspect before powering

1. Look at every joint under decent light, splices included. Shiny and concave is good; dull,
   cracked, or ball-shaped means reheat it.
2. Multimeter continuity, **3V3 to GND: must be open.**
3. Tug each wire gently. Anything that moves gets resoldered.

## 9. Power up in stages

1. USB-C only, nothing else connected to mains. The LCD should light.
2. `esphome logs tank-monitor-remote.yaml`. Look for the DS18B20 address and a
   BH1750 found at 0x23 in the I²C scan.
3. Check the TDS voltage reading with the probe **dry** — should sit near 0 V.
4. Only now plug in the relay module. Confirm the heater outlet clicks when
   `Heater Output` goes above 0%.
5. Wet the probes and confirm sensible readings before putting anything in
   the tank.

## 10. Before it goes near water

- Strain-relieve every wire where it leaves the board — a dab of hot glue or
  a zip tie to the case is enough. Vibration and cable weight break solder
  joints, not the wire.
- Mount the board **above** the water line. Condensation runs downhill.
- Put the whole thing on a GFCI outlet. This is an aquarium; the fish are the
  reason but you are the other reason.


# CYD ESP32-2432S028R (`tank-monitor-v2`)

**There is no wiring.** This board is display-only: it subscribes to the C6's
values over the network and draws them. No probe, no TDS meter, no light
sensor, no relays, no pull-up resistor — nothing lands on its connectors.

That is deliberate. This board spends nearly every GPIO on its own screen and
touch panel, so making it a controller meant repurposing the microSD bus,
hanging the light sensor off the pins the USB bridge uses to flash the chip,
and metering the speaker header to learn whether it reached a pin or an
amplifier. The C6 already has a probe bolted to the tank and a control loop
that has been running it for weeks. Splitting the roles removes the whole
class of problem.

## Setup

1. Flash it. The wrapper loads `packages/remote_display.yaml` in place of
   `control.yaml` and `sensors.yaml`.
2. Power it by USB anywhere on your Wi-Fi. It does not need to be near the
   tank — that is the point of a remote panel.
3. Confirm it works: temperature, TDS and light should populate within a few
   seconds, and the `Link Age` entity should read a few seconds rather than
   `no data`.

`Link Age` is the one to watch. The panel is only ever as current as its last
message, and a frozen screen showing plausible numbers is the failure worth
making visible.

## Controlling from the panel

The setpoint buttons and the Adaptive Learning switch publish commands to the
C6's MQTT topics; the C6 remains the authority and its state topic corrects
the panel a moment later. So the panel changes the tank, but it never holds an
opinion the controller doesn't share.

## The microSD slot

Free again, since nothing uses IO18/19/23 now. ESPHome has no SD component in
core, so using it needs an external component — worth doing for local logging
(the Home Assistant host has no UPS, and that is what corrupts InfluxDB), but
it is not part of this build.

## The ESP-NOW link

The panel gets its data straight from the controller over ESP-NOW — peer to
peer, no router and no MQTT broker. Since the broker runs on Home Assistant,
this is what lets the panel keep working with Home Assistant down.

Two things have to be true:

**`espnow_key` in `secrets.yaml`, identical on both boards.** Any string. A
missing value fails the build, which is deliberate — an unencrypted link would
work perfectly and silently accept a setpoint command from anyone in range.

**The router's 2.4 GHz channel must be pinned.** ESP-NOW shares one radio with
Wi-Fi and can only work on the channel the station is already associated on —
ESPHome enforces this by rejecting a `channel:` setting whenever the wifi
component is present. Both boards land on the AP's channel, so they can hear
each other. **If the AP is ever set back to "auto" and moves, the link stops
with no error on either board:** packets go out on a channel nobody is
listening to. `Link Age` on the panel is what makes that visible.

Home Assistant is unaffected. Every entity still publishes over MQTT exactly as
before — this is a second path for one consumer, not a replacement. Chemistry
still arrives by MQTT too, because it originates in Home Assistant; with HA
down it goes stale and the panel says so.

## Battery (optional)

The BAT connector feeds the charger. On this revision nothing routes battery
voltage to an ADC, so the panel cannot read the pack without a divider — two
resistors from BAT+ to **IO35**, which is free now that this board runs no
sensors:

```
BAT+ ---[ R1 ]---+--- IO35
                 |
                [ R2 ]
                 |
BAT- / GND ------+
```

100 kΩ / 100 kΩ gives a ratio of 2.0, halving 4.2 V to 2.1 V — inside ADC1's
range at 12 db. Equal resistors also mean the divider draws only ~20 µA, so it
won't meaningfully flatten the cell while the panel is off.

**Fit the divider before trusting the reading.** IO35 is input-only with no
internal pulldown, so an unwired pin floats and can report anything. With the
divider fitted and no pack attached it reads near zero through R2, which is how
the indicator knows to hide itself.

**Calibrate once:** meter the pack, compare against the `Battery Voltage`
sensor, and adjust `battery_divider` by the ratio between them. Resistor
tolerance is essentially the whole error.

**Before connecting a LiPo:** confirm this board actually charges the pack
rather than just drawing from it, and use a cell with a protection circuit.
An unprotected LiPo on a board that doesn't manage it is a fire risk, not a
runtime feature.

The indicator sits bottom-right, over every page:

| Shows | Meaning |
|---|---|
| `84% 3h` | Discharging, about 3 hours left |
| `84%` | Discharging, not enough readings yet for an estimate |
| `84% CHG` (blue) | Charging |
| `FULL` (blue) | Charged |
| hidden | No pack detected, or no divider fitted |

The runtime needs about 20 minutes of readings before it appears — it's a
measured discharge slope, not a nameplate figure, so it reflects your actual
brightness and Wi-Fi use.

Charging is detected by trend, not by a status pin — this board doesn't break
one out. The panel samples every five minutes and looks at which way the pack
is moving, so expect up to ten minutes before the label catches up after you
plug in or unplug. `binary_sensor.tank_monitor_v2_battery_charging` reports the
same thing to Home Assistant.

## If you ever convert it back to a controller

The pin map that worked on this revision: TDS IO35, heater IO27, fan IO18,
DS18B20 IO19 with a 4.7 kΩ pull-up to 3V3, BH1750 SDA/SCL on IO1/IO3 powered
from the 3-pin header's **3.3V, not the UART header's 5V**. Not IO22 — this
revision doesn't break it out. Not the speaker header — IO26 reaches it
through the audio amplifier.

# ESP32-WROOM-32 (`tank-monitor-w32`)

A controller with no screen — the same job as the C6, on a plain devkit.
Everything solders to the board's own header pins; there is no breakout.

Follow the C6 build above for technique: steps 2 (pre-tin), 3 (power splices),
6 (the pull-up), 8 (inspect) and 10 (before it goes near water) apply
unchanged. Only the pin numbers differ.

## Pin map

| Board pin | Goes to |
|---|---|
| GPIO34 | TDS `A` |
| GPIO4 | DS18B20 yellow (DQ), with the 4.7 kΩ pull-up to 3V3 |
| GPIO21 | BH1750 `SDA` |
| GPIO22 | BH1750 `SCL` |
| GPIO26 | Relay Ch1 `IN+` (heater) |
| GPIO27 | Relay Ch2 `IN+` (fan) |
| GND | `IN−` both channels, and every sensor ground |
| 3V3 | every sensor VCC |

Leave BH1750 `ADDR` unconnected — floating is 0x23, which the config expects.

## Why these pins, and which ones to avoid

This board has pins to spare, so the choices are about which are *safe*:

- **GPIO6–11** are the flash. Using them prevents boot.
- **GPIO0, 2, 12, 15** are strapping pins. A pull-up or pull-down at boot
  changes boot mode — a 4.7 kΩ probe pull-up on GPIO12 stops some boards
  booting at all, which is why the DS18B20 is on GPIO4.
- **GPIO34–39 are input only** with no internal pull-ups. Right for the TDS
  analog line, useless for a relay or a 1-Wire bus.
- **ADC2 cannot be read while Wi-Fi is on.** Any analog input must be on
  ADC1 (32–39). That is not a preference; ADC2 simply returns garbage.

GPIO25, 32 and 33 are left free on purpose — 32 and 33 are the remaining ADC1
pins, which is what a second analog probe (pH, ORP) would need.

## Differences from the C6

**It keeps a USB console.** The CYD has to disable serial because its I²C sits
on the UART pins; nothing here touches GPIO1/GPIO3, so this is the easiest of
the three boards to diagnose with `esphome logs`.

**No display, no backlight.** Home Assistant, the web UI at its own IP, and the
remote panel are the interfaces.

**Give it a different `device_name`** if it runs alongside the C6. That name
sets the MQTT topic prefix, discovery object ids, mDNS hostname and fallback AP
name at once — two boards answering to the same name overwrite each other's
entities as fast as they appear.

To let a remote panel read this board instead of the C6, uncomment
`packages/espnow_link.yaml` in the wrapper **and** point that panel's
`source_device` substitution at this device's name. The panel selects its
source by provider name, so two controllers can broadcast at once without
colliding — but a panel only listens to the one it was told about.


# ESP32-S3 mini (`tank-monitor-s3`)

A controller with no screen, on a board the size of a postage stamp. Covers
both the **Waveshare ESP32-S3-Zero** (23.5 × 18 mm) and the generic
**"ESP32-S3 SuperMini"** (22.5 × 18 mm) — same chip, same pin map, one
config in `boards/esp32s3-mini.yaml`.

Follow the C6 build above for technique: steps 2 (pre-tin), 3 (power
splices), 6 (the pull-up), 8 (inspect) and 10 (before it goes near water)
apply unchanged. Only the pin numbers and the two extra parts differ.

## Two parts the other boards do not need

| Part | Why |
|---|---|
| 100 µF electrolytic + 100 nF ceramic | across `3V3` and `GND`, as close to the board as they will sit. These boards brown out and reboot under Wi-Fi transmit load; this is the fix |
| 31 mm of 1.0 mm silver-plated wire | *optional* antenna mod — see below. Skip it until you have measured RSSI |

## Pin map

| Board pin | Goes to |
|---|---|
| GPIO1 | TDS `A` |
| GPIO2 | pH board analog out (blue on the Gravity cable) |
| GPIO5 | DS18B20 yellow (DQ), with the 4.7 kΩ pull-up to 3V3 |
| GPIO6 | BH1750 `SDA` |
| GPIO7 | BH1750 `SCL` |
| GPIO8 | Relay Ch1 `IN+` (heater) |
| GPIO9 | Relay Ch2 `IN+` (fan) |
| GND | `IN−` both channels, every sensor ground, and the caps |
| 3V3 | every sensor VCC, and the caps |

Leave BH1750 `ADDR` unconnected — floating is 0x23, which the config expects.

`GPIO4` is left free on purpose: it is the reserved ADC1 pin for an ORP
probe. `GPIO10` is the last ADC1 pin after that, then 11–13 for digital.

That is four wires on the 3V3 splice and six on GND — one more of each than
the C6 build, because of the pH board and the decoupling caps. Ten
conductors is past what one twisted joint holds reliably, so make it two
splices per rail joined by a short link, not one bundle.

**The pH board goes to 3V3, not 5V.** The SEN0169-**V2** is the
wide-voltage edition and outputs 0–3 V. The classic SEN0169 outputs 0–5 V
and will damage GPIO2. Check the board you actually received.

## Why these pins, and which ones to avoid

Only GPIO1–13 are used, because that is the range *both* boards break out.
The Zero also exposes 15–18, 21 and 43/44; the SuperMini does not.

Which pins are safe comes from ESPHome's validator (`gpio_esp32_s3.py`),
not from seller pinout diagrams:

- **GPIO26–32** are the in-package flash and PSRAM. ESPHome rejects them
  outright. No mini board breaks them out, which is why.
- **GPIO0, 3, 45, 46** are strapping. Only GPIO3 is on this header, so it
  is the one pin in 1–13 left alone. GPIO0 is the BOOT button.
- **GPIO19, 20** are USB-Serial-JTAG, which is this board's only console.
- **GPIO22–25** are not in the IO mux at all. Unusable on any S3.
- **ADC2 (GPIO11–20) cannot be read while Wi-Fi is on.** Every analog
  probe must be on ADC1, which is GPIO1–10. Not a preference — ADC2
  returns garbage.

**GPIO9–14 are ordinary GPIOs.** Several widely-copied pinout guides label
them "flash-dedicated"; that is carried over from octal-PSRAM S3 modules
and is wrong for the FH4R2. The fan relay sits on GPIO9.

The relays are deliberately **not** on GPIO43/44. Those are free now that
the console is on USB, but the ROM bootloader prints on TX at every reset,
and a few milliseconds of that on an optocoupled relay input is an audible
click of the heater on every boot.

## The antenna, which is the weak part

Both boards use a small 2.4 GHz ceramic antenna with a documented history
of short range and dropped links. On the S3-Zero, a paired-RSSI test
against an unmodified board measured **at least +10 dB** from a wire
antenna — roughly double the usable range — and thermal imaging showed the
stock regulator running hot from reflected power. SuperMini units have
also been reported shipping with the ceramic antenna mounted backwards.

This board is the ESP-NOW provider for the remote panel, and ESP-NOW
follows the Wi-Fi association, so a marginal link degrades the panel and
MQTT together. The control loop itself is unaffected — it runs on-device
and keeps regulating with the network down. Brownout *reboots* are the
real cost: the model, light profile and setpoint all persist, but each
reboot restarts the 900 s heater window mid-cycle and blanks the hourly
swing history for ten minutes.

So: fit the caps always, and check RSSI once the board is where the tank
is. Below about −70 dBm, do the wire mod — a 5 mm loop at the bottom of a
31 mm length, the loop fitted around both ends of the original antenna.

If neither appeals, a **XIAO ESP32-S3** is smaller again (21 × 17.5 mm) and
has a U.FL connector with an external antenna in the box, which removes the
problem rather than mitigating it. It breaks out 11 GPIO against the eight
used here, so it fits — with no room for a second I²C device that does not
share the bus.

## Differences from the C6

**No USB-UART bridge.** The USB-C port is wired straight to the S3's
USB-Serial-JTAG peripheral, so the board file sets
`logger: hardware_uart: USB_SERIAL_JTAG`. Without it the console would go
out on GPIO43/44 where nothing is listening — an open port and no output.
If the dashboard does not offer the port on first flash, hold BOOT while
plugging it in.

**Recalibrate pH and TDS.** `ph_v_neutral` and `ph_v_acid` are volts
measured through *this board's* ADC, and the S3's converter is not the
C6's. Copying the numbers from another wrapper gives a wrong reading that
looks right — which is the exact failure that made the old monitor
useless. Redo the two-point calibration against pH 7.00 and 4.00 buffer,
and recheck the TDS `k_factor` the same way.

**No display, no backlight.** Home Assistant, the web UI at its own IP, and
the remote panel are the interfaces.

**Give it a different `device_name`** if it runs alongside the C6. That
name sets the MQTT topic prefix, discovery object ids, mDNS hostname and
fallback AP name at once — two boards answering to the same name overwrite
each other's entities as fast as they appear.

To let a remote panel read this board instead of the C6, uncomment
`packages/espnow_link.yaml` in the wrapper **and** point that panel's
`source_device` substitution at this device's name.


# XIAO ESP32-S3, large tank (`tank-monitor-75-gallon`)

The second tank's controller. Same silicon as the 12-gal XIAO, a different
wet side: **two DS18B20 probes, two BH1750 light sensors, pH and TDS on an
ADS1115, and three relay channels** — heater A, heater B, fan. Config is
`boards/xiao-esp32s3-lg-dual.yaml`; wrapper is `tank-monitor-lg-remote.yaml`.

Follow the C6 build for technique: steps 2 (pre-tin), 8 (inspect) and 10
(before it goes near water) apply unchanged. The power step is **different**
— see below — because this board has roughly twice the conductors of any
other in this file.

## What you need

- The XIAO ESP32-S3 (8 MB flash / 8 MB PSRAM — check the label, the S3 mini
  is a different board and a different config)
- ADS1115 breakout (16-bit, 4-channel, I2C)
- 2 × DS18B20 waterproof probes
- 2 × BH1750 breakouts
- DFRobot Gravity TDS board (SEN0244) + probe
- DFRobot Gravity pH board **SEN0169-V2** + BNC probe — the V2 specifically,
  it outputs 0–3 V. The classic SEN0169 outputs 0–5 V and will damage the
  ADS1115 at the 3.3 V rail it must run on
- D-1585TL 4-channel IoT relay outlet (the 4-outlet sibling of the D-1584TL
  you already run)
- 2 × 4.7 kΩ resistors, 1/4 W
- A scrap of perfboard, ~20 × 40 mm, for the power rails
- 26–28 AWG silicone hookup wire, heat shrink, iron, multimeter — as for the C6

Optional: 100 µF electrolytic + 100 nF ceramic across 3V3/GND at the rail.
The XIAO regulates better than the S3 mini and the 12-gal XIAO has run
without them; cheap insurance if you have them in the drawer.

## Read this before you pick up the iron

**The pad labels are not GPIO numbers.** The XIAO is silkscreened `D0`–`D10`
and those are *not* the GPIOs the config uses — `D3` is GPIO4, `D8` is GPIO7.
Wiring to the pad whose printed number matches a GPIO lands on the wrong pin,
and every symptom of that is silent: a probe on the wrong bus reports "No
devices", an analog input on the wrong pad reads plausible nonsense. **Wire
by the `D` column of the table below and nothing else.**

**`D2` stays empty.** It is GPIO3, an S3 strapping pin. Nothing may hold it
at a level during boot.

**Ignore the small alternate-function labels.** Next to the `D` numbers the
silkscreen also prints `SDA` beside `D4` and `SCL` beside `D5` — the chip's
*default* I2C pair — and `TX`/`RX` beside `D6`/`D7`. This config does **not**
use them that way: I2C is on `D6`/`D7`, `D4` is a relay, `D5` is a probe.
Wire I2C to the pads marked `SDA`/`SCL` and you have put the light sensors
on the heater-B relay line. Follow the `D` number, nothing else.

**The ADS1115 runs from 3V3, not 5V.** Its I2C logic threshold is 0.7 × VDD:
at 5 V that is 3.5 V, and the XIAO drives 3.3 V, so highs are marginal and it
fails intermittently. Its absolute-max analog input is VDD + 0.3 V, so the
3.3 V rail also caps what the Gravity boards may feed it.

## Pin map

Top view, USB-C at the top. Left column `D0`–`D6` top to bottom; right column
`5V`, `GND`, `3V3`, `D10`, `D9`, `D8`, `D7` top to bottom.

| Pad | GPIO | Goes to |
|---|---|---|
| `D0` | 1 | DS18B20 **B** yellow (DQ) — cross-check probe, bus B |
| `D1` | 2 | *spare* (ADC1) |
| `D2` | 3 | **nothing — strapping pin** |
| `D3` | 4 | *spare* (ADC1) |
| `D4` | 5 | Relay Ch2 `IN+` — **heater B** |
| `D5` | 6 | DS18B20 **A** yellow (DQ) — control probe, bus A |
| `D6` | 43 | I2C `SDA` — ADS1115, both BH1750s |
| `D7` | 44 | I2C `SCL` — ADS1115, both BH1750s |
| `D8` | 7 | Relay Ch1 `IN+` — **heater A** |
| `D9` | 8 | Relay Ch3 `IN+` — **fan(s)** |
| `D10` | 9 | *spare* (ADC1) |
| `3V3` | — | the 3V3 rail (one pigtail) |
| `GND` | — | the GND rail (one pigtail) |
| `5V` | — | unused |

Heater A and probe A are the **same half of the tank**; B and B the other.
That pairing is a wiring fact the firmware cannot verify, and if it is
backwards every gradient reading points at the wrong end. Label the probe
leads before they go in the water.

I2C is on `D6`/`D7` = GPIO43/44, which are also UART0. That is fine: the
XIAO's console is native USB, so UART0 is free. It is why the **relays are
not** on those pads — the ROM bootloader prints on TX at every reset, and a
few milliseconds of that on an optocoupled relay input is an audible click
of the heater on every boot.

## Power distribution — build a rail, do not splice

Count the conductors:

| Rail | Wires |
|---|---|
| 3V3 | DS18B20 A, DS18B20 B, BH1750 A, BH1750 B, BH1750 B `ADDR`, ADS1115 `VDD`, TDS board, pH board, pull-up A, pull-up B — **10** |
| GND | DS18B20 A, DS18B20 B, BH1750 A, BH1750 B, ADS1115 `GND`, ADS1115 `ADDR`, TDS board, pH board, relay `IN−` — **9** |

Twenty conductors. The C6 section says ten is past what one twisted joint
holds; this is twice that. So: **perfboard**.

Take the scrap of perfboard. Pick two rows a few holes apart and bridge each
row with a run of solder or a length of bare bus wire — that gives you a
3V3 rail and a GND rail, each with a dozen tinned holes. Solder one pigtail
from each rail to the XIAO's `3V3` and `GND` pads. Every sensor's power lead
then goes to a hole on the appropriate rail, one wire per hole, each with
its own joint.

Mark which rail is which with a permanent marker before the first wire goes
on. A 3V3/GND swap on a rail takes every sensor with it.

If you are using the decoupling caps, they go across the two rails on the
perfboard, right where the XIAO pigtails land.

## 1. Prep and pre-tin

C6 steps 1–2. Tin only the pads in the table: `D0`, `D4`, `D5`, `D6`, `D7`,
`D8`, `D9`, `3V3`, `GND`. Leave `D2` untouched — bare, untinned, nothing
near it.

## 2. Build the rails

As above. Pigtails to the XIAO first, then check continuity from each rail
to its pad with the meter. Then nothing else on the rails until step 3.

## 3. The ADS1115 — first on the bus, closest to the board

This is the one I2C device that carries analog signals, so it sits **as
close to the XIAO as the wiring allows** — a few centimetres of `SDA`/`SCL`,
not a run.

| ADS1115 pin | Goes to |
|---|---|
| `VDD` | 3V3 rail |
| `GND` | GND rail |
| `SDA` | `D6` |
| `SCL` | `D7` |
| `ADDR` | GND rail — **explicitly**, not floating. 0x48 |
| `ALRT` | unconnected |
| `A0` | TDS board signal (step 4) |
| `A1` | pH board signal (step 4) |
| `A2`, `A3` | unconnected |

Two more wires now go to `D6` and `D7` later (the BH1750s). Leave enough
tinned pad to land them, or better, bring `SDA` and `SCL` from the XIAO to
two more perfboard holes and fan out from there — same idea as the rails.

## 4. pH and TDS into the ADS1115

Both Gravity boards run from the **3V3 rail**. The TDS board (SEN0244)
outputs 0–2.3 V; the pH board (SEN0169-V2) outputs 0–3.0 V. Both sit under
the ADS1115's 3.6 V ceiling. Confirm you have the V2 before this step.

| Board | Wire | Goes to |
|---|---|---|
| TDS | red / `+` | 3V3 rail |
| TDS | black / `−` | GND rail |
| TDS | `A` | ADS1115 `A0` |
| pH | red | 3V3 rail |
| pH | black | GND rail |
| pH | blue (analog out) | ADS1115 `A1` |

**Route both signal wires away from the relay module's mains cord**, and
from each other's power leads where you can. The pH signal in particular is
the one that will pick up 60 Hz hum and give you a wandering reading that
is not a probe fault.

## 5. The two BH1750s and their addresses

They share the I2C bus with the ADS1115 and tell themselves apart by the
`ADDR` pin. **This is the whole trick** — two identical boards, one address
pin each, wired opposite:

| | `VCC` | `GND` | `SDA` | `SCL` | `ADDR` | Address |
|---|---|---|---|---|---|---|
| BH1750 **A** | 3V3 rail | GND rail | `D6` | `D7` | **unconnected** | 0x23 |
| BH1750 **B** | 3V3 rail | GND rail | `D6` | `D7` | **3V3 rail** | 0x5C |

Get both `ADDR` pins the same way round and the I2C scan shows one device
where you expect two — and the config's second sensor never publishes.

These two sit at opposite ends of a 48" tank, so each `SDA`/`SCL` pair is a
4–5 ft run. I2C is not built for that; the board file already runs the bus
at **10 kHz** (down from the 50 kHz default) to buy the capacitance margin
a run that long needs. Your side of the bargain:

- **Twisted pair** for `SDA`/`SCL` on each run (a pair pulled from Cat5 is
  ideal), with `GND` alongside. Not a flat ribbon, not two loose wires.
- **Route it away from the heater cords and the relay module.** A slow clock
  buys capacitance margin, not noise immunity; a relay snapping next to an
  unshielded I2C pair is a corrupted lux reading, not an error.
- The GY-302 breakouts carry their own pull-ups, so add none. If the scan
  is intermittent, 2.2 kΩ from `SDA` and `SCL` to 3V3 at the *board* end.

If one sensor still comes and goes in the log after that, the fix is a
differential I2C extender — a PCA9615 board (SparkFun QwiicBus) at the XIAO
and one at each sensor, which carries I2C over ordinary twisted pair for
tens of metres. Do not chase it with thicker wire or a faster clock.

## 6. Two 1-Wire buses, two pull-ups

Two probes, and they are **deliberately on separate buses** so neither
needs an address in the config and a flooded probe takes down only itself.
Each bus is exactly the C6's step 6, done twice:

| Probe | Red | Black | Yellow (DQ) | 4.7 kΩ |
|---|---|---|---|---|
| DS18B20 **A** (control, heater-A half) | 3V3 rail | GND rail | `D5` | between `D5` and the 3V3 rail |
| DS18B20 **B** (cross-check, heater-B half) | 3V3 rail | GND rail | `D0` | between `D0` and the 3V3 rail |

Pull-up at the *board* end, not out at the probe. Sleeve both resistor legs.
Without it that bus reports "No devices, can't auto-select address", which
is indistinguishable from the probe being on the wrong pad.

Label the probe leads **A** and **B** now, at the board, before they are
routed. Once they are in the tank they look identical.

## 7. Relay control, three channels

Low-voltage terminals only. Do not open the module or touch its mains side
— it has its own cord. The D-1585TL takes 3–120 V DC on its control
terminals and is **active-high**, so the XIAO's 3.3 V drives it directly.

| XIAO pad | D-1585TL |
|---|---|
| `D8` | Channel 1 `IN+` — **heater A** |
| `D4` | Channel 2 `IN+` — **heater B** |
| `D9` | Channel 3 `IN+` — **fan(s)**, all in parallel on this one outlet |
| GND rail | `IN−` on channels 1, 2 and 3, jumpered together |
| — | Channel 4 — spare, nothing connected |

Note `D4` for heater B, not `D3` — `D3` is a spare ADC pin and `D4` is
GPIO5. Easy to land one pad over.

3.3 V is the **bottom** of the module's 3–120 V control range. It works —
your 2-channel D-1584TL runs on it today — but it means the internal opto
LED is at minimum forward current. If a channel ever latches on and will not
release, that is the symptom, and the fix is feeding that `IN+` through the
GPIO from the XIAO's `5V` pad rather than 3.3 V. Not a reason to change
anything now.

## 8. Inspect

C6 step 8. Then three checks specific to this build, all with the board
**unpowered**:

- Meter from `D2` to everything. It should be open to all of it.
- Meter from the 3V3 rail to the GND rail. Open. If it beeps, one of the
  twenty wires is on the wrong rail — find it now, not with smoke.
- Meter from BH1750 A's `ADDR` to BH1750 B's `ADDR`. Open. If they are
  connected, they are on the same address.

## 9. Power up in stages — what the log should say

USB-C from a wall adapter. Flash `tank-monitor-lg-remote.yaml` and watch the
serial log. In order:

**I2C scan** — the first thing you want to see, and it names all three:

```
[I][i2c.idf]: Found i2c device at address 0x23
[I][i2c.idf]: Found i2c device at address 0x48
[I][i2c.idf]: Found i2c device at address 0x5C
```

One missing is a wiring fault on that device. `0x23` present and `0x5C`
absent is BH1750 B's `ADDR` not reaching 3V3. `0x48` absent is the ADS1115
— check its `VDD` is on 3V3 and `ADDR` is actually tied to GND.

**Two 1-Wire buses**, each reporting one device:

```
[I][one_wire.gpio]: Found devices:
[I][one_wire.gpio]:   0x...   (bus on GPIO6)
[I][one_wire.gpio]: Found devices:
[I][one_wire.gpio]:   0x...   (bus on GPIO1)
```

"No devices" on one bus and not the other is that bus's pull-up or its
yellow wire on the wrong pad.

**Then** check Home Assistant: `Water Temperature` and `Water Temperature B`
both reporting and roughly agreeing, `TDS` and `pH` present and not NaN,
both light levels present, and — the one people forget — the relay
binary sensors present and **off**: `Heater` (the pair), `Heater Left`,
`Heater Right` and `Fan`. The side names come from `side_a_name` /
`side_b_name` in the wrapper; if you changed those, the entities follow.

**Then** the relays. From HA, raise the setpoint a few degrees above the
water temperature and watch `Heater Left` and `Heater Right` go on
**together** — both, at the same moment. They share one duty and one
phase-locked window. If only one goes, its `IN+` is on the wrong pad.

**This can take up to fifteen minutes.** The heaters are driven by a
time-proportional window of 900 s, and a duty change is picked up at the
next window boundary, not instantly. Wait it out before deciding something
is wrong — and listen for the relay click, which is unmistakable. Then drop
the setpoint and watch both release, again within a window.

## 10. Before it goes near water

C6 step 10, then two things this board needs that the others did not:

**Cross-calibrate the probes in one cup.** Two DS18B20 are ±0.5 °C absolute
and can read nearly a degree apart in identical water. Put both in the same
glass, wait ten minutes, and set `Cal Temp Offset B` until they agree. Every
gradient reading on this tank is downstream of that number, and the
`Probe Disagreement` alarm fires off it.

**Recalibrate pH and TDS.** The stored calibration in NVS is in volts read by
a *different* ADC, and it survives a flash. The C6 → S3 swap moved TDS by
~30 % for exactly this reason. Both calibration procedures are in the
README; do them before believing any chemistry number this board reports.

Then set `side_a_name` / `side_b_name` in the wrapper to match how you
actually mounted things, and label the outside of the tank to match.
