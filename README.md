# Tank Monitor

An ESP32-C6 aquarium controller: water temperature, TDS, and light level, with a
**self-learning predictive thermostat** that drives a heater and a cooling fan.
Reports to Home Assistant over MQTT with auto-discovery.

The control loop runs entirely on the ESP32. Home Assistant gets the data and
a setpoint slider, but if HA reboots, updates, or falls off the network, the
tank keeps being regulated exactly as before.

---

## Why the temperature swings 73–76 °F

A stock aquarium heater is a bimetallic on/off switch with roughly 2 °F of
hysteresis. It heats until it's over target, shuts off, the tank coasts down
past target, and it kicks on again. Add the daylight/lights heat load on top
and you get the 3 °F band you're seeing.

Two things here fix that:

1. **Time-proportional output.** Instead of on/off, the heater is switched on
   for a fraction of the time — at a steady duty, that fraction of every 15
   minutes. 30% duty is 30% of full heater power, so the tank can sit *at*
   the setpoint instead of oscillating around it. The relay's on-time equals
   the commanded duty times elapsed time however the duty moves (see
   [The relay drive](#the-relay-drive)). (Set the heater's own thermostat
   dial to its maximum and let this control it — the heater becomes a dumb
   resistor.)

2. **Feed-forward from a learned model.** The controller knows how fast your
   specific tank heats, cools, and gains heat from the lights, so it backs the
   heater off *before* the lights warm the water rather than after.

Expect ±0.5 °F once the model has a day of data — or ±0.2 °F if you swap the
heater onto an SSR and shorten the window (see below).

---

## Board

Built for a **LAFVIN / Waveshare ESP32-C6-LCD-1.47** — ESP32-C6 with an
on-board 1.47" 172x320 ST7789V panel. ESPHome ships a preset for this exact
board (`model: WAVESHARE-ESP32-C6-LCD-1.47`), which supplies the panel's
CS/DC/reset pins, its 34 px column offset, and colour inversion.

The display driver is `mipi_spi`, not the older `st7789v` platform. With a
90 degree rotation the old driver wants a full framebuffer and the C6 — 512 KB
SRAM, no PSRAM — runs out of memory. Current build sits at **35% RAM, 66%
flash**, so there's headroom but not unlimited.

The screen shows water temperature, target, heater and fan duty bars, TDS,
light level, and controller state. It keeps working when Home Assistant
doesn't, which is the whole point of running the control loop on-device.

### Pins already taken by the board

The LAFVIN breaks out two header rows, and **only these pins are physically
available**:

| Edge | Pins |
|---|---|
| One long edge | `9, 18, 19, 20, 23, 22, 13, RX, TX` |
| Other long edge | `5, 4, 3, 2, 1, 0, 3V3, GND, 5V` |

**GPIO10 is not on the board** — anything assigned to it silently does
nothing. Avoid `22` as well (exposed, but it's also the LCD backlight net),
`13` (USB D+), and `9` (boot strapping pin). GPIO6/7 are the LCD SPI bus and
14/15/21 are its CS/DC/reset, none of which reach a header.

## Parts list

Manufacturer links are verified. Amazon entries are **searches**, not
specific listings — ASINs for commodity parts churn constantly and a dead
link is worse than none.

### Required — the controller

| Part | Notes | Where |
|---|---|---|
| **LAFVIN / Waveshare ESP32-C6-LCD-1.47** | the controller and its display. Any ESP32 works — see `boards/` | [search](https://www.amazon.com/s?k=ESP32-C6+1.47+inch+LCD+development+board) |
| **DS18B20 waterproof probe** | water temperature. The one measurement the whole control loop depends on | [search](https://www.amazon.com/s?k=DS18B20+waterproof+temperature+probe) |
| **CZH-Labs D-1584TL** | 2-channel relay outlet module, ~$49. Two *independently* switched outlets — a single-channel IoT Relay cannot run a heater and a fan | [Amazon](https://www.amazon.com/Two-Channel-Control-Module-Arduino-Raspberry/dp/B0GR85JF68) · [direct](https://czh-labs.com/products/ac-power-2-channel-iot-relay-outlet-module-din-rail-or-screw-mounting) |
| 26–28 AWG stranded wire | hookup, silicone jacket is easiest | [search](https://www.amazon.com/s?k=26+AWG+silicone+stranded+hookup+wire) |
| Heat shrink, 2 mm and 3 mm | joints and splices | [search](https://www.amazon.com/s?k=heat+shrink+tubing+assortment+2mm+3mm) |

### Strongly recommended — pH

The controller cannot regulate what it cannot measure, and pH is the number
that tells you whether CO₂ is safe. **Buy the industrial version**: the
standard Gravity kit's electrode is not rated for permanent immersion, which
DFRobot themselves will tell you if you ask.

| Part | Notes | Where |
|---|---|---|
| **DFRobot SEN0169-V2**, *wide voltage* edition | $64.90. 3.3–5.5 V supply and **0–3 V output** — the classic edition outputs 0–5 V and would damage an ESP32 ADC pin | [DFRobot](https://www.dfrobot.com/product-2069.html) · [wiki](https://wiki.dfrobot.com/sen0169-v2/) |
| **pH 4.00 / 6.86 / 9.18 buffer sachets** (the NIST set) | the sensor is meaningless uncalibrated. Calibrate on the two that bracket the tank (9.18 and 6.86), check against the third | [search](https://www.amazon.com/s?k=pH+4.00+6.86+9.18+calibration+buffer+solution+sachets) |
| **KCl storage solution** | the electrode must never dry out. A dried probe is a dead probe | [search](https://www.amazon.com/s?k=pH+probe+KCl+storage+solution) |
| Suction-cup probe holder | fixes angle and depth; the bulb must point down | [search](https://www.amazon.com/s?k=aquarium+pH+probe+holder+suction+cup) |

### Optional — the rest

| Part | What it buys you | Where |
|---|---|---|
| Keyestudio TDS meter | dissolved solids. Useful for *trend*, not absolute — it ships uncalibrated | [search](https://www.amazon.com/s?k=Keyestudio+TDS+meter+sensor) |
| GY-302 / BH1750 module | ambient light, which the model uses to pre-compensate for the lights' heat | [search](https://www.amazon.com/s?k=GY-302+BH1750+light+sensor+module) |
| ESP32-2432S028R "CYD" | a second board as a remote touch panel — see `boards/cyd-esp32-2432s028r.yaml` | [search](https://www.amazon.com/s?k=ESP32-2432S028R+CYD+2.8+inch+display) |
| Seachem Ammonia Alert | a passive colorimetric disc, ~$10, lasts a year. **The best value item on this page** — there is no usable electronic ammonia sensor for a tank | [search](https://www.amazon.com/s?k=Seachem+Ammonia+Alert) |
| TCS34725 colour sensor | reads that disc so the ESP32 can log and alarm on it | [search](https://www.amazon.com/s?k=TCS34725+RGB+color+sensor) |
| DFRobot ORP probe | oxidation-reduction potential — the only practical measure of dissolved organic load. `GPIO33` is reserved for it on the WROOM-32 board, `GPIO4` on the S3 | [DFRobot](https://www.dfrobot.com/product-1071.html) |

### Test kits you cannot skip

No electronic sensor replaces these, and this project has twice chased a
phantom because a continuous reading was trusted over a liquid test.

| Kit | For |
|---|---|
| **API Freshwater Master Test Kit** | pH (low **and** high range), ammonia, nitrite, nitrate |
| **API GH & KH Test Kit** | sold separately. KH is what makes CO₂ injection safe or unsafe |

Test strips read GH and KH low and cannot resolve the range that matters
here. Use the drop tests.

### About the 1-Wire pull-up: there isn't one

No board in this project has an external DS18B20 pull-up fitted, and none
needs one. ESPHome's `gpio` one_wire platform asserts the chip's own pull-up
on every bus reset and every bit read — `pin_mode(gpio::FLAG_INPUT |
gpio::FLAG_PULLUP)`, `components/gpio/one_wire/gpio_one_wire.cpp:11`, checked
against 2026.9.1. The bus is never floating, so there is nothing to add and
no `pullup:` to set; the driver owns the pin mode regardless of what the
config says.

Earlier revisions of this file called the resistor **required** and said the
bus "reads garbage without it". That was wrong, and the hardware had been
disproving it daily — the XIAO controller has read temperatures for months
with nothing fitted.

It is worth knowing the margin is thin: ~45 kΩ against the DS18B20
datasheet's 4.7 kΩ. One probe on a short lead tolerates it; a long cable in
electrical noise is where slow rise times turn into CRC errors. Two things
follow. First, on the Freenove all-in-one boards the probes sit on GPIO4/5,
whose camera-bus resistors (~10 kΩ) parallel the internal one for ~8 kΩ —
in spec, for free. Second, if a bus ever does go marginal, a resistor is the
*last* thing to suspect: it has never been the cause here, and
`1-Wire bus held low` means water in the probe, which no pull-up value fixes.

## Wiring

Everything runs at 3.3 V.

### DS18B20 water temperature — 1-Wire

| Probe wire  | ESP32  |
|-------------|--------|
| Red (VDD)   | 3V3    |
| Black (GND) | GND    |
| Yellow (DQ) | GPIO18 |

That is the whole connection. The bus is open-drain, but ESPHome pulls it up
from inside the chip — see *About the 1-Wire pull-up* above. No resistor.

### Keyestudio TDS meter — analog

| Board pin | ESP32  |
|-----------|--------|
| VCC       | 3V3    |
| GND       | GND    |
| A (out)   | GPIO1  |

Power the board at **3.3 V, not 5 V**. Feeding a 5 V-powered board's output
into a GPIO will damage the pin. If you must run it at 5 V, put a 10k/20k
divider on the output.

The C6 has a single ADC unit, so the classic ESP32 problem where ADC2 stops
working while Wi-Fi is up doesn't apply here. GPIO0 is the only other free
ADC pin — GPIO2 and GPIO3 now drive the relays, and the rest of the ADC
block (GPIO4-6) is taken by the microSD slot and LCD.

### GY-302 / BH1750 light sensor — I²C

| Module pin | ESP32   |
|------------|---------|
| VCC        | 3V3     |
| GND        | GND     |
| SDA        | GPIO19  |
| SCL        | GPIO20  |
| ADDR       | leave unconnected (address 0x23) |

Mount it where it sees the tank lighting *and* the room's daylight, but not
where it's shadowed by the hood at some hours and not others — the controller
learns a 24-hour light profile and a moving shadow shows up as fake noise.

Since your lights are touch-switched rather than scheduled, this sensor is
what tells the controller they're on. It learns their typical schedule too,
so it anticipates them; if you turn them on off-schedule, the live reading
still feeds the model within one control tick.

### Heater and fan — 2-channel relay outlet module

Built around the **CZH-Labs D-1584TL**, a 2-channel IoT relay outlet module
(~$49). Two optocoupled, electrically isolated control inputs, a NEMA 5-15P
cord, and a normally-off + normally-on NEMA 5-15R receptacle per channel.
10 A per outlet, 15 A total. No mains wiring on your part.

| Module terminal | ESP32  |
|-----------------|--------|
| Channel 1 IN+   | GPIO2 (heater)  |
| Channel 2 IN+   | GPIO3 (fan)     |
| IN− (both)      | GND    |

Plug the heater into channel 1's **normally-off** receptacle and the fan into
channel 2's normally-off receptacle. Inputs are active high, so no `inverted:`
in the pin config.

**Set the heater's own thermostat dial to maximum.** This controller replaces
it; the heater becomes a dumb resistive element. Leaving the dial at a
setpoint means the heater's 2 °F hysteresis is still in the loop.

Two caveats:

- **3.3 V is at the bottom edge of the module's 3–120 VDC input range.** It
  should latch fine, but there's little margin. If a channel chatters, drive
  the input from the ESP32's 5 V pin through a small NPN transistor instead of
  straight off the GPIO.
- **These are mechanical relays**, which is why the period is 900 s and not
  300 s. At 5-minute periods you'd spend ~288 contact cycles a day and wear
  them out in about a year; at 15 minutes it's at most ~96/day, so several
  years, and every run is at least 30 s. The controller doesn't cycle at all
  when duty is pinned at 0% or 100%.

**If you want the tighter ±0.2 °F band later:** move the heater to a
zero-crossing SSR (SSR-25DA class, 3–32 VDC control, ~$12) in a project box,
and set the heater relay output's `period` (in the board file) to `300s`. An SSR is silent, has no
contacts, and cycles indefinitely — but it's real mains wiring, so only take
that on if you're comfortable with it and feeding it from a GFCI outlet. You
want the tank on a GFCI regardless.

### Full wiring diagram

All three sensors need 3V3 and GND, and the relay needs ground too — seven
power wires converging on two pads. Everything solders directly to the board:
join the power wires in a splice off-board and run one pigtail to each pad.
See [ASSEMBLY.md](ASSEMBLY.md).

Total sensor draw is under 10 mA, so the board's own regulator powers
everything. No external supply.

**Power — one pigtail per pad, split at a soldered splice:**

```
   ESP32-C6-LCD-1.47                        ┌── DS18B20 red
   ┌─────────────┐                          │
   │             │            ╔═══════╗     ├── TDS VCC
   │        3V3 ●┼────────────╢ splice╟─────┤
   │             │            ╚═══════╝     └── BH1750 VCC
   │             │
   │             │            ╔═══════╗     ┌── DS18B20 black
   │        GND ●┼────────────╢ splice╟─────┤
   │             │            ╚═══════╝     ├── TDS GND
   └─────────────┘                          │
                                            ├── BH1750 GND
                                            │
                                            └── Relay IN- (both ch.)
```

**Signal — one wire each, straight to its GPIO:**

```
   ESP32-C6-LCD-1.47
   ┌─────────────┐
   │             │
   │      GPIO18 ●─────────────────────────► DS18B20  DQ   (yellow)
   │             │          (no pull-up resistor — the driver
   │             │           supplies the chip's own)
   │       GPIO1 ●─────────────────────────► TDS       A    (analog)
   │             │
   │      GPIO19 ●─────────────────────────► BH1750    SDA
   │      GPIO20 ●─────────────────────────► BH1750    SCL
   │             │                           BH1750    ADDR → leave open
   │             │
   │       GPIO2 ●─────────────────────────► D-1584TL  CH1 IN+  (heater)
   │       GPIO3 ●─────────────────────────► D-1584TL  CH2 IN+  (fan)
   │             │
   └─────────────┘
```

**Every wire, in one table:**

| From (ESP32-C6) | To | Notes |
|---|---|---|
| 3V3 | bus → DS18B20 red, TDS VCC, BH1750 VCC | TDS at 3.3 V, **never 5 V** |
| GND | bus → DS18B20 black, TDS GND, BH1750 GND, relay IN− ×2 | one common ground |
| GPIO18 | DS18B20 yellow (DQ) | one wire, no pull-up resistor |
| GPIO1 | TDS "A" | ADC-capable pin |
| GPIO19 | BH1750 SDA | |
| GPIO20 | BH1750 SCL | |
| GPIO2 | D-1584TL channel 1 IN+ | heater |
| GPIO3 | D-1584TL channel 2 IN+ | fan |

Not wired: BH1750 `ADDR` (leave floating for address 0x23), and the relay
module's mains side — it has its own NEMA 5-15P cord.

**Routing matters for one wire in particular.** The TDS line is a
high-impedance analog signal; run it alongside the relay module's power cord
and it will pick up 60 Hz hum. Keep those separated. If the BH1750 sits more
than roughly a foot from the board, add a 100 nF cap across its VCC/GND at
the sensor end.

## The display

**One screen. The temperature owns almost all of it.**

The panel is 1.47" diagonal at 320x172, which in landscape is about
**33 x 18 mm** — a pixel pitch of roughly 0.10 mm. To read a number at 8 ft
you need digits subtending ~15-20 arcminutes, which works out to **11 mm
tall**. That is nearly the full height of the panel, so the temperature gets
everything and nothing else competes with it.

The font is sized to that constraint, not to taste. At 150 px em, "74.5"
measures **306 px wide by 109 px tall** — the largest it can be and still fit
320 px across. 160 px overflows. 109 px is 11.2 mm, which subtends ~16
arcmin at 8 ft and ~25 arcmin at 5 ft.

```
┌────────────────────────────────────────────┐
│ LIGHT 820                       lights on  │  ← 26px, amber when lit
├────────────────────────────────────────────┤
│              74.5                          │  ← 9.7mm digits
│                                            │    background = status colour
│ STEADY            74-75 | sw 0.2 | heat 32%│  ← status row
├────────────────────────────────────────────┤
│ TDS 212                          TDS OK    │  ← 32px strip
└────────────────────────────────────────────┘
```

172 px of panel, divided: **26 light / 114 temperature / 32 TDS**.

**Every string is positioned by its baseline, not its top or bottom.** This
matters more than it sounds: ESPHome places text using the font's *line box*
— ascender to descender, 148 px at this size — while the digits themselves
are only 92 px of ink. Anchoring `TOP_CENTER` therefore drops the glyphs
~28 px lower than the coordinate suggests, which is exactly how the first
attempt ended up printing the temperature through the status row. The
baseline is where digits physically rest, so it's the one anchor that
doesn't depend on font metrics.

At 126 px em the digits occupy y 28–120, clear of the light strip above
(ends at 26) and the status row below (ink starts at 126).

**The light strip costs the temperature ~1 mm of digit height** — 11 mm down
to 9.7 mm, which is ~13 arcmin at 8 ft instead of ~16. Still readable at
that range, slightly less comfortable. Delete the strip and bump `font_huge`
back to 150 if you'd rather have the height.

The strip goes **amber when the tank lights are on** (above `light_on_lux`,
default 50 lx) and near-black when they're off. Since the controller
pre-compensates for the lights' heat load, seeing their real state next to
the temperature is worth the space.

**From across the room you read the background colour, not the text.** Green,
amber, red — that alone tells you whether the tank is holding. The digits are
readable at 5-8 ft. Everything else (target band, hourly swing, heater duty,
TDS status) is deliberately small: it's there when you walk up to it, and
it's on the Home Assistant dashboard when you want to actually study it.

Temperatures of 100 °F or above drop the decimal so the digits still fit. If
you ever see that, the decimal place is not your problem.

### Thresholds

Set to your targets. Green inside the band, amber just outside, red beyond:

| | Green | Amber | Red |
|---|---|---|---|
| **Temperature** | 74–75 °F **and** steady | 73.5–74, 75–75.5 °F, or `SWINGING` | below 73.5, above 75.5 |
| **TDS** | 180–250 ppm | 150–180, 250–300 ppm | below 150, above 300 |

**Green requires the tank to be steady, not just momentarily in band.** The
controller keeps an hour of temperature history and reports peak-to-peak
swing; if that exceeds `temp_swing_max` (0.5 °F) the screen shows amber and
`SWINGING` even when the current reading sits inside 74–75. A tank crossing
through the band on its way between 73 and 76 is not holding temperature, and
the display shouldn't claim it is.

Swing reads `--` for the first ten minutes after a boot, and doesn't block
green until there's enough history to mean something.

All six numbers are substitutions at the top of `packages/base.yaml`
(`temp_lo`, `temp_hi`, `temp_red_lo`, `temp_red_hi`, `tds_lo`, `tds_hi`,
`tds_red_lo`, `tds_red_hi`) — change them in one place and both the display
bands and the on-screen target text follow.

The control setpoint is **74.5 °F**, the centre of the 74–75 band,
so normal drift stays inside green in both directions.

### Not measured

Your target list also includes pH 7.2–7.5, GH 7–8, and KH 3–4. There's no
sensor for those in this build — GH and KH have no practical hobby-grade
probe and stay test-kit measurements. pH *is* addable (an analog probe on a
spare ADC pin, GPIO0/2/3 are free), but it needs two-point calibration and
the probe is a consumable that drifts and needs replacing every year or so.
Say the word if you want it.

## 3D printed case

**Nothing off the shelf fits this board.** The Waveshare-outline cases and
the generic MakerWorld ESP32-C6 enclosure both assume the LCD is centred with
USB on a long edge; the LAFVIN is a stick, with USB-C, BOOT and RESET all on
one short end.

So there's a purpose-built one in [`case/`](case/) — parametric OpenSCAD plus
ready STLs, with a cable exit for the eight wires this build has. Print the
fit-test coupon first: LAFVIN publishes no mechanical drawing, so the
dimensions came off photographs and are good to about ±1 mm.

See [case/README.md](case/README.md).

## Assembly

Step-by-step soldering instructions are in **[ASSEMBLY.md](ASSEMBLY.md)** —
build order, the pull-up resistor, the pre-power checks, and a staged
power-up sequence.

## Flashing

### Build straight from git (recommended)

Rather than pasting the config into the ESPHome dashboard and re-pasting it
after every change, put **`tank-monitor-remote.yaml`** there instead — a
short wrapper that pulls the whole config from this repo:

```yaml
packages:
  tank_monitor:
    url: https://github.com/JoshuaSeidel/tank-monitor
    ref: main
    files:
      - packages/base.yaml
      - packages/control.yaml
      - packages/sensors.yaml
      - boards/lafvin-esp32c6.yaml
    refresh: 0s
```

Save it in the dashboard as `tank-monitor.yaml`. After that, a push to
`main` is all it takes — the next install builds the new config.

That `files:` list *is* the configuration, and it is where you choose
hardware — see [Config layout](#config-layout) below.

**`refresh: 0s` is not optional.** The default is `1d`, so without it you
can push a fix and spend an afternoon flashing yesterday's config.

Only `secrets.yaml` stays local. `!secret` references inside the remote
file resolve against your local secrets, so nothing sensitive goes in git.

**Local overrides win over the package**, so device-specific tweaks don't
require forking. Adding this below the `packages:` block sets the target to
75 °F for this device only:

```yaml
substitutions:
  target_temp_f: "75.0"
```

The `tank_controller` component is fetched from git the same way, so this
builds in the **Home Assistant ESPHome add-on** with no local files at all.

Locally instead:

```sh
pip install esphome
cp secrets.yaml.example secrets.yaml   # then edit it
esphome run tank-monitor-remote.yaml
```

<a name="config-layout"></a>
### Config layout

The config is split so the board is the only thing that changes between
builds. Nothing under `packages/` names a GPIO; everything that does lives
in `boards/`.

| File | Holds |
| --- | --- |
| `packages/base.yaml` | Identity, Wi-Fi, OTA, MQTT, SNTP, the display palette, the tuning substitutions |
| `packages/control.yaml` | The `tank_controller` component and every entity derived from it |
| `packages/sensors.yaml` | DS18B20, BH1750 and the TDS maths — expressed without pins |
| `packages/ph.yaml` | The pH maths and its two-point calibration — also without pins |
| `boards/lafvin-esp32c6.yaml` | LAFVIN ESP32-C6, 1.47" 172×320 ST7789V |
| `boards/cyd-esp32-2432s028r.yaml` | "CYD" ESP32-2432S028R, 2.8" 240×320 ILI9341 + touch |
| `boards/esp32-wroom32.yaml` | Plain ESP32-WROOM-32 devkit, headless |
| `boards/esp32s3-mini.yaml` | ESP32-S3-Zero / "S3 SuperMini", headless, 23×18 mm |

The board file supplies the buses and ids the shared packages expect —
`tds_voltage`, `ph_voltage`, `heater_output`, `fan_output`, plus the
`one_wire` and `i2c` buses — so a new board is one new file in `boards/`
and one changed line in the wrapper. A change to the control loop lands on
every board from one push.

Files are merged in listed order and later entries win, so the board file
gets the last word. That is how the CYD file switches serial logging off
without `packages/base.yaml` knowing anything about it.

### Building for the CYD instead

`tank-monitor-cyd-remote.yaml` is the same wrapper with the last line
pointing at `boards/cyd-esp32-2432s028r.yaml`. That board is far more
pin-constrained than the C6 — the full reasoning and the wire-by-wire pin
budget are in the header comment of the board file. Two things worth
knowing before ordering parts:

- Its I²C runs on the UART pins, so the board is **OTA-only** (no serial
  console) and the **first USB flash must be done with the BH1750
  unplugged** — the CH340 talks to the ESP32 over those same pins.
- Nothing on the board brings 5 V out to a connector, so the relay module
  needs its own supply, sharing ground with the board. The D-1584TL's
  optocoupled inputs are designed for exactly that.
- **"CYD" is several different boards.** They differ in display controller,
  and the seller's listing is not reliable evidence. The board file uses
  ESPHome's `ESP32-2432S028` preset (ILI9341, what the listing claims); if
  the panel comes up blank, garbled or colour-inverted, swap that one string
  for `ESP32-2432S028-7789` (ST7789V) or `ESP32-2432S028-9342` (ILI9342).

It uses the `mipi_spi` driver rather than `ili9xxx`, which is a RAM decision
rather than a stylistic one. A full 320×240×2 = 154 kB framebuffer does not
fit on a no-PSRAM ESP32 once statics are placed — `ili9xxx` allocates it in
one shot with no partial-buffer mode, and on failure calls `mark_failed()`,
so the screen silently never appears while everything else runs. `mipi_spi`
renders in stripes at `buffer_size: 50%`, and makes the controller swap above
a one-line change.

### The 10.1" wall panel (both tanks)

`tank-monitor-p4-panel-remote.yaml` is one wall panel for both tanks and both
flow meters: an Elecrow CrowPanel Advanced 10.1" (ESP32-P4 + ESP32-C6,
1024×600, also sold as IDEAQUX). It replaces the 4.3" 75 gal panel, the round
AMOLED and the CYD. Retire those first: each controller has a BLE slot for
this panel only once the old panel has let go of it.

- **Tanks over BLE**, one `packages/panel_p4_tank.yaml` per tank with its own
  id prefix and MAC (`t75` payload v3, `t16` payload v2), so the tank numbers
  keep working with Home Assistant or the broker down. Setpoint and learning
  commands go back over the same link.
- **Everything else over MQTT** (`packages/panel_p4_feeds.yaml`): the two
  water-flow meters, the nano's pH, and two Home Assistant feeds:
  automation *Aquarium — publish panel state to MQTT* (CO2, bubbler, days
  since loss) and `script.aquarium_alert`, which mirrors every latched alert
  to `tank-monitor-panel/alert/<tag>`.
- **The UI** is `packages/panel_p4_ui.yaml`, generated by
  `tools/gen_panel_p4_ui.py` from the design in `design/p4-panel/`. Edit the
  generator, not the YAML. `tools/p4_preview.py` renders the real UI on a Mac
  through ESPHome's SDL host platform with sample data and saves screenshots
  to `design/p4-panel/firmware-shots/`.

Needs ESPHome 2026.10 or later. Check the board revision first: V1.0 has
the SDIO pins in the opposite order (see `boards/elecrow-crowpanel-p4-101.yaml`).
On first boot press **Install** on "C6 Radio Firmware" once, so the C6 runs
the exact ESP-Hosted build ESPHome's host library expects (2.12.13; Elecrow
ships 2.12.3, same series, Bluetooth already on).

### Web interface

Every build serves its own UI at the device's IP — no Home Assistant, no
internet, no CDN. ESPHome's page is only `<esp-app></esp-app>` plus one
script tag, so pointing `js_url` at the device's own `/tank.js` replaces its
CDN bundle and
`components/tank_webui/assets/tank.js` becomes the whole interface. State
arrives over `/events`; controls POST back to the REST endpoints
`web_server` already exposes, addressed by the id each entity reported on
`/events` — its display name, e.g. `/number/Cal%20pH%20High%20Value/set`.
Since ESPHome 2026.7 those routes match by name only; the old object-id form
(`/number/cal_ph_high_value/set`) returns 404. A control stays disabled until
its entity has reported, so a board without one (no backlight, no pH) never
posts to an address that does not exist.

**Nothing to copy.** The script and stylesheet live inside the
`tank_webui` external component, which git delivers in full — unlike
`js_include`, which reads from the ESPHome config directory and cannot be
supplied by a remote package. The component embeds them at build time and
serves them at `/tank.js` and `/tank.css`, so `js_url` points at the
device itself.

Push, rebuild, done — same as every other change here.

It shows temperature with the same band colours as the panels, the target
with steppers, heater and fan duty plus live relay state, swing, TDS, pH,
light, model confidence, and the water chemistry mirrored from Home
Assistant with its age. Controls: setpoint, adaptive learning, backlight,
restart, reset learning — **and the full calibration panel** (see below).

The chemistry card hides itself on boards that don't include
`packages/chemistry.yaml`, rather than showing six dashes; the pH and
calibration cards do the same on boards without `packages/ph.yaml` or
`packages/sensors.yaml`.

### Secrets

The add-on shares **one** `secrets.yaml` across every device, so anything
device-specific is prefixed to avoid collisions:

| Key | Scope |
|---|---|
| `wifi_ssid`, `wifi_password`, `mqtt_broker` | shared with your other devices |
| `tank_monitor_mqtt_username` | this device |
| `tank_monitor_mqtt_password` | this device |
| `tank_monitor_ota_password` | this device |
| `tank_monitor_ap_password` | this device |

Give this device its own MQTT user rather than reusing a shared one — it
keeps broker access auditable and makes the logs readable when something
misbehaves.

First flash over USB; after that `esphome run` uses OTA. Live values are at
`http://tank-monitor.local/`.

---

## How the learning works

The controller fits a five-parameter thermal model of your tank:

```
dT/dt  =  kh·heater  −  kf·fan  −  ka·(T − ref)  +  kl·light  +  c
```

**Everything you configure or read is Fahrenheit.** The model itself runs in
Celsius internally — not from preference, but because its priors, clamps and
residual guards are tuned in °C/min, and hand-converting those constants is
how a working controller quietly stops working. The component converts once
at its boundary; no Celsius value is published or configurable.

- `kh` — how fast your heater actually raises this volume of water
- `kf` — how much your fan's evaporative cooling pulls out
- `ka` — how fast the tank loses heat to the room per degree of difference
- `kl` — heat the lights add at full brightness
- `c`  — the drift at `ref` with nothing running

`ref` is the model's operating point, not a constant: the active setpoint, or
the room's air temperature when a room sensor is configured (the 75 uses its
office Zigbee sensor via `packages/ambient_zigbee.yaml`; Home Assistant is not
in that path). A fixed reference the tank sits away from makes `ka` and `c`
indistinguishable — that is what pinned the 75's Tank Time Constant on its
bound in October 2026. Moving `ref` re-expresses `c` so the prediction never
steps, and a model saved by older firmware is migrated on first boot.

The Zigbee room sensor must have **retain** enabled in Zigbee2MQTT (device >
Settings > retain). Without it the broker holds no last value, so after any
reboot the board waits up to ~2 h for the sensor's next report before it can
use the room. See the header of `packages/ambient_zigbee.yaml`.

Parameters are fit online with recursive least squares. `c` is modelled as a
random walk (process noise sized to a two-hour tracking time), because the
room it stands in for really does move — day and night, the heating season, the
sun. Bounds are enforced by a covariance-aware projection, so a parameter held
on its limit hands its share of a correction to the others instead of leaving
the model biased. `Model Health` is judged against the residual's measured
noise floor, and `Model Reference` shows what the model is centred on.

`ka` moves only when something actually excites it: a window where the water
sits at least 0.3 °F from the model's centre — a setpoint move, a water change,
a heater outage, or the room swinging. With a room sensor the centre is the
room plus a 12-hour average of how far above it the water sits, so the room's
*movement* teaches `ka` and its steady level belongs to `c`. On a quiet day
`Tank Time Constant` stays where it is. (It used to walk: 400 → 6000 min in an
hour on the 75 on 2026-10-14, with the room moving 0.2 °F.)

The heater and fan terms learn from how long the relays were actually closed
(`heater_relay` / `fan_relay`, wired in `control.yaml`), timed from the relay
entities' own transitions over each 5-minute step, not from the duty the
controller asked for. Until the relay drive below was fixed, on the 75 those
differed by 1.7× — its board restarted the 15-minute PWM window on every new
call for heat — and learning from commanded duty is what made its `Learned
Heater Power` read 4.97 °F/h for heaters that can physically give 1.98. They
now agree, and the model still learns from the measurement.

### The relay drive

Every controller board drives its heater and fan relays through
`components/time_proportioning`, not ESPHome's `slow_pwm`. The rule: a credit
accumulates commanded duty × elapsed time and pays out the time the relay is
closed. The relay closes when no heat is owed back and opens once it is
`period·d·(1−d)` in debt — one cycle per period at a steady duty `d`, closed
`d·900 s` and open `(1−d)·900 s`, same as before, but nothing ever restarts,
so **delivered on-time equals commanded duty × elapsed time** to within a few
minutes over any span. A new call for heat closes the relay at once unless heat
is owed back. `min_on_time` / `min_off_time` (default 30 s) floor each run for
relay life; what they stretch is carried in the credit, not lost.

Why: the 75's board restarted its 900 s `slow_pwm` window on every 0 → >0 edge
of the demand (so a call for heat closed the relays now rather than at the next
window), and near setpoint the demand toggled ~49% / 0 as the probe flipped one
0.1125 °F step across the sign guard. Each restart granted a fresh duty × 900 s:
over 17 days of Home Assistant history the relays were closed **21.7%** of the
time against **12.7%** commanded. `Heater Output` understated the heat by 1.7×,
the tank overshot, and learning from commanded duty learned a heater 1.7× too
strong.

The demand itself no longer toggles on a single probe step either. A DS18B20
reads in 0.1125 °F steps, and water sitting at a step boundary flips between
two of them; any threshold in between was crossed on every flip. So every
decision now has 1.5 steps of width: the sign guard is a latch centred on its
old 0.1 °F (heat forbidden from 0.18 °F above setpoint until back within
0.02 °F), the fan may start at `Fan Deadband` as before but stops only 0.17 °F
below it, and the proportional term sees the reading through a play operator
that ignores a one-step flip (it lags a real move by at most 0.08 °F). The
integral keeps the raw reading, which averages the flips.

`tools/thermal_model_sim.py --relay` runs the window logic before and after
(14 days, real office temperature, four setpoints a fraction of a probe step
apart, means; overshoot is the worst):

| Tank, drive | Commanded | Delivered | Delivered / commanded | Relay closures/day | Demand 0→on/day | Control RMS | Max overshoot | Model Health min |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 75 + room sensor, before (restart-on-demand `slow_pwm`) | 8.3% | 19.4% | 2.33× | 332 | 301 | 0.082 °F | +0.28 °F | 100% |
| 75 + room sensor, after | 19.2% | 19.2% | 1.00× | 77 | 3 | 0.040 °F | +0.25 °F | 100% |
| 75, before | 5.9% | 19.5% | 3.33× | 370 | 357 | 0.097 °F | +0.29 °F | 100% |
| 75, after | 19.2% | 19.2% | 1.00× | 76 | 4 | 0.040 °F | +0.22 °F | 100% |
| nano, before (free-running `slow_pwm`) | 1.2% | 1.7% | 1.41× | 47 | 146 | 0.136 °F | +0.35 °F | 100% |
| nano, after | 1.8% | 1.8% | 1.00× | 38 | 3 | 0.102 °F | +0.33 °F | 100% |

The simulated "before" overstates the real 1.7× (it depends on where the
setpoint falls on the probe's step grid), but the mechanism is the same. After
flashing, `Heater Output` averaged over an hour or more matches the share of
that time the `Heater` entity is on.

### Tank size, heater, cover and placement

Five settings tell the model what physics allows, so its priors and bounds
come from the tank instead of from a generic guess. Each is a YAML key on
`tank_controller:` (the first-boot default, set in the board file) and an
entity in Home Assistant (the controller persists what you set there):

| YAML key | Entity | Meaning |
| --- | --- | --- |
| `tank_volume` | Tank Volume (gal) | nominal size, US gallons — gives glass and water-surface area |
| `water_volume` | Water Volume (gal) | water actually in it after substrate and rock; 0 = 85% of Tank Volume — gives heat capacity |
| `heater_power` | Heater Power (W) | all heaters together at full power; 0 = unknown |
| `tank_cover` | Tank Cover | `open_top` / `lid` / `evaporation_cover` / `unknown` |
| `tank_placement` | Tank Placement | `open_room` / `enclosed_cabinet` |

From these the controller computes the time constant `m·c / UA`: the water's
heat capacity over how many watts the tank sheds per degree. The areas are a
standard rectangular tank of that volume; the heat-transfer coefficients are
3–10 W/m²·K for the glass, and for the top 10–25 open (radiation, convection
and the room-dependent part of evaporation), 3–8 under a lid, 2–5 with the
evaporation cover sealed. A closed stand puts the cabinet's own walls in
series. `Time Constant Band` and `Expected Time Constant` show the result, and
`Tank Time Constant` learns within that band. `Heater Power` gives the heater
gain outright (watts over heat capacity) and holds the learned value near it.

Changing any of them resets what it determines — the time constant for volume,
cover and placement; the heater gain for heater power and water volume — to the
new expected value, re-opens its uncertainty so it relearns, and adjusts `c` so
the 15-minute forecast does not jump. The log says what changed. **When you put
a lid on, change Tank Cover**: most of an open tank's evaporation is a steady
loss (the 75 open-top: about 0.16 °F/h, ~25 W), so the heater will work less,
and the time constant rises with it.

| Tank | Settings | Time constant band | Expected | Heater |
| --- | --- | --- | --- | --- |
| 75 gal | 75 gal, 62 gal water, 300 W, open top, room | 446–2042 min | 954 min | 1.98 °F/h |
| 75 gal | same, lid | 618–3077 min | 1379 min | |
| 75 gal | same, lid + evaporation cover | 663–3318 min | 1483 min | |
| nano | 16 gal, 150 W, lid, enclosed cabinet | 628–3444 min | 1471 min | 4.51 °F/h |

The 75's measured value, from 17 days of its own Home Assistant history (heat
balance with delivered heater power, `tools/thermal_model_sim.py --measure`):
**810 min, 90% range 680–1010**.

**Room sensor and an enclosed cabinet.** A tank inside a closed stand sheds
heat to the cabinet's air, and that air is warmed by the tank and its heater
far more than it follows the room. An office or room sensor outside the
cabinet does not measure it. With `enclosed_cabinet` and a room sensor
configured the controller logs a warning; the model still runs (`ka` is then
the loss through the cabinet to the room, and the room's swing reaches the
tank late and damped), but a sensor *inside* the cabinet is the right input.
The nano is in a cabinet and has no room sensor, so it centres on its setpoint.

`tools/thermal_model_sim.py` replays the model and control law, in float32,
against a simulated tank (the 75's real office temperature from Home Assistant,
heaters through `time_proportioning` — or the old `slow_pwm` windows,
including the 75's restart-on-demand one, for the before/after table — a minute
of heater lag, two quantised probes, a Zigbee room sensor, lids going on, the
nano in a cabinet) for the previous and current firmware, and replays 17 days
of the 75's real history (`tools/data/`) through the estimator. Run it after
changing any of the model's constants or the relay drive.

**Learning runs on 5-minute windows, not every tick.** A DS18B20 quantizes to
0.1125 °F; differentiating that every 30 s produces noise far larger than the
~2 °F/hour signal being measured. Averaging over 5 minutes brings it into
range.

Separately, a 96-slot (15-minute resolution) profile of normalized light level
is learned per time-of-day, so the controller can predict the light heat load
20 minutes ahead and pre-compensate.

Both the model and the light profile are saved to flash every 10 minutes and
restored on boot — a reboot doesn't cost you the learning.

### If the temperature stops updating

The 1-Wire bus is **scanned once, at boot**. If the DS18B20 isn't detected
during startup, ESPHome never retries — the probe stays dead until the next
reboot, even if you fix the wiring while it's running. Look for this in the
logs:

```
[W][gpio.one_wire]:   Found no devices!
[W][dallas.temp.sensor]:   Unable to select an address
```

versus a healthy boot, which prints the probe's 64-bit address.

Checks, with the board powered off:

| Measure | Expect |
|---|---|
| DQ (GPIO18) to 3V3 | open — there is no pull-up resistor to find |
| DQ to GND | open |
| 3V3 to GND | open |
| Probe VCC to 3V3 | ~0 Ω |

Then **reboot** — fixing the wiring alone won't bring it back.

Note that the `Temperature Fault` binary sensor and the on-device display
are the authoritative indicators. The temperature sensor itself simply stops
publishing, so anything reading it goes unavailable rather than showing a
stale number.

### What can go wrong, and what catches it

| Failure | Caught by | Response |
|---|---|---|
| Probe stops responding | controller, after 120 s | heater cut, `Temperature Fault`, HA alert |
| Probe reads wrong but plausible | **Nothing.** There is no second temperature probe — verify against a reference thermometer by hand | — |
| Heater dead, unplugged, or relay channel not wired | `Heater Not Responding`, after 45 min at full duty with no rise | HA alert; the tank is drifting cold |
| Heater stuck on | hard `max_temperature` cutout, then HA runaway alarm | heater off, fan full |
| Controller offline entirely | HA sees the MQTT status go offline | HA alert |
| Wi-Fi or HA down | nothing needed | control loop is on-device and unaffected |
| Learned model goes wrong | feedforward is weighted by confidence | falls back toward plain feedback |

`Heater Not Responding` is the one that would have caught the GPIO10
mistake — the fan channel was assigned to a pin that isn't broken out, so
it would have run at 0% forever with nothing to say so.

### Safety behavior

- Above `max_temperature` (82 °F): heater off, fan full, model ignored.
- Below `min_temperature` (68 °F): heater full.
- Temperature probe missing for 2 minutes: **heater cut off** and the
  `Temperature Fault` problem sensor trips. A slowly cooling tank is a much
  better failure than a cooked one.
- Residuals over 54 °F/hour are discarded rather than learned from — that's a
  water change or a bad read, not information about the tank.

---

## Long-term history and Grafana

Home Assistant records everything here to **InfluxDB 3** (the InfluxDB3 App,
Enterprise with a free At-Home licence). The integration is configured through
the UI — Settings → Devices & Services → InfluxDB — not YAML.

Settings that work with this App:

| Field | Value |
|---|---|
| API | v2 (`configure_v2` in the flow) |
| URL | `http://32b8266a-influxdb3:8181` |
| Verify SSL | off |
| Organization | anything — InfluxDB 3 requires the field but ignores it |
| Bucket | `homeassistant` — on v3 this is the *database* name |

**Use `http`, not `https`.** The App sets `ssl: true` by default but ships no
certificate files, so it serves plaintext; TLS fails with
`WRONG_VERSION_NUMBER`.

Grafana lives in [`grafana/`](grafana/) — an importable dashboard plus
datasource setup. See [grafana/README.md](grafana/README.md).

## Asking the tank questions (Tank MCP)

[`tank-mcp/`](tank-mcp/) is a Home Assistant App that serves an **MCP server**
for this tank: an AI assistant gets tools for the controller,
manual test entry, and a record of fish and shrimp lost — plus the ability to
say any of it out loud on an Echo.

It is deliberately not a general Home Assistant bridge. Every tool answers a
tank question and answers it with a verdict attached, using thresholds set for
*this* stock (73.4 °F cold floor for the loaches, 0.02 mg/L free ammonia,
GH/KH read live from the target helpers rather than hard-coded).

Install it by adding this repository under **Settings → Apps → Store → ⋮ →
Repositories**. Full documentation, tool list, and the Alexa routine setup are
in [tank-mcp/DOCS.md](tank-mcp/DOCS.md).

Two things it adds on the Home Assistant side:

- An **Aquarium Livestock** device, published over MQTT discovery — total
  alive, losses over 7 and 30 days, days since the last one, with the
  per-species breakdown as attributes.
- `script.aquarium_speak_status`, which builds the spoken report from Home
  Assistant state alone. That is the ask-out-loud path: Alexa cannot call MCP,
  so exposing this script to Alexa and pointing a routine at it is what makes
  "Alexa, tank report" work.

## Home Assistant entities

Under one `Tank Monitor` device:

**Controls** — `Target Temperature` (°F, 70–80), `Display Backlight`,
`Adaptive Learning` switch,
`Reset Learning` button, `Restart` button.

**Main** — `Water Temperature` (°F), `TDS` (ppm),
`Electrical Conductivity` (µS/cm), `Tank Light Level` (lx), `Heater Output`
(%), `Fan Output` (%), `Predicted Temperature (15 min)`, `Controller State`.

**Tank** (config) — `Tank Volume` (gal), `Water Volume` (gal), `Heater Power`
(W), `Tank Cover`, `Tank Placement`; see
[Tank size, heater, cover and placement](#tank-size-heater-cover-and-placement).

**Diagnostic** — `Model Confidence`, `Model Bias`, `Tank Time Constant`,
`Expected Time Constant`, `Time Constant Band`,
`Learned Heater Power`, `Learned Light Heat Gain`, `Predicted Light Load`,
`Learned Fan Power`, `Temperature Drift Rate`, `TDS Probe Voltage`,
`Temperature Fault`, `Heater Not Responding`, `Fan Not Responding`,
Wi-Fi signal, uptime, IP.

There is no `Target Temperature` *sensor* — the `Target Temperature` number
under Controls is the setpoint, and it is recorded to InfluxDB like any other
entity, so Grafana draws the setpoint line straight from
`number.tank_monitor_target_temperature`. A mirror sensor would have been a
second entity with the same name and the same value.

No entity name carries a `°F` suffix. Every temperature in this project is
Fahrenheit, so the unit is not a distinguishing feature — see
[Tuning](#tuning).

`Model Confidence` reaching 100% means roughly a day of learning steps have
accumulated. Watch `Heater Output` — once settled it should sit at a fairly
steady partial value, not flip between 0 and 100.

### `Heater Output` and `Fan Output` are commands, not measurements

Both are the controller reading back its own decision. There is no current
sensing on either channel and nothing confirms the relay closed, or that
anything is plugged into that outlet. `Fan Output: 100%` means "I intend to
hold Ch2 closed", nothing more. (What they *do* now match is the drive: over
an hour or more, the share of time the `Heater` / `Fan` entities are on equals
the mean of these — see [The relay drive](#the-relay-drive). That says the
relay was driven, not that heat arrived.) They
are standard controller-output terms, but they carry a `%` and a
`state_class: measurement`, so it is easy to read them as evidence.

They are not evidence, and this has already cost an evening: a heater that
had stopped delivering heat showed 90–97% on that graph the entire time it
was failing. What caught it was the water falling while the model said it
should be climbing.

The entities that actually reflect delivery are inferred from how the water
responded:

| Entity | Says |
| --- | --- |
| `Learned Heater Power` (°F/h) | how much the heater really adds at 100% |
| `Learned Fan Power` (°F/h) | the same for the fan; near its floor after real runtime means it is not cooling |
| `Heater Not Responding` | ≥90% commanded for 45 min with no rise |
| `Fan Not Responding` | ≥90% commanded for 45 min with no fall |

The two "Not Responding" checks are coarse — they catch an absent actuator,
not a weak one. Use the learned gains for that.

---

## Calibration

**Every correction lives on the device, in flash, and is applied before the
value is published.** Not in Home Assistant, and not in a substitution that
needs a reflash.

Both of those alternatives were tried and both were wrong. A substitution
means recalibrating is a config edit and a rebuild — precisely what you
cannot do standing at a sink with a wet probe. And a correction applied in
Home Assistant is a correction the tank does not have: the ESP-NOW panel and
this device's own web page would still be showing the uncorrected number, and
the three surfaces would disagree.

So the numbers are `restore_value` globals, they survive reboots and OTA
updates, and they are reachable **two** ways — Home Assistant, and the
device's own web page at its IP. The second one is the one that matters,
because it still works with the broker, the router and HA all down.

### TDS — single point

1. Bring the calibration solution **to tank temperature**. Conductivity moves
   about 2 %/°C, so a bottle straight off a cold shelf bakes several percent
   of error into K permanently, and it will read wrong ever after in a way
   that is very hard to trace back.
2. Set **Cal TDS Standard** to what the bottle says (342 ppm and 1000 ppm are
   the usual ones).
3. Stand the probe in it and watch **TDS** settle — the single sample
   Calibrate TDS solves against, which the device page shows as *Reading
   now*. Not `TDS 1h Mean`: that is still an hour of tank water.
4. Press **Calibrate TDS**.

It solves `k = k · standard / reading` and refuses any result outside
0.1–5.0, which is the range beyond which the probe, not the calibration, is
the problem. **Cal TDS K Factor** is also directly editable if you would
rather type a known value.

### pH — two point

The two points are named for their role, not a number: **Cal pH High Value**
and **Cal pH Low Value** hold what each buffer actually says. Choose a pair
that **brackets the tank**. A glass electrode is linear from about 4 to 10,
so a third point buys nothing — but a tank at 7.4 calibrated on 6.86 and 4.00
is extrapolated above its highest point, which is where slope error hurts
most. With the NIST set (4.00 / 6.86 / 9.18) that means calibrating on 9.18
and 6.86 and keeping 4.00 back as the check.

1. Set **Cal pH High Value** and **Cal pH Low Value** to what the two bottles
   say.
2. Rinse in distilled water and **blot** dry. Never wipe the glass bulb: it
   builds a static charge that takes minutes to bleed off, and the reading
   wanders the whole time.
3. Stand in the high buffer, wait two minutes, press **Capture High Point**.
4. Rinse, blot, stand in the low buffer, wait two minutes, press
   **Capture Low Point**.
5. Rinse, blot, stand in the third buffer and read **Water pH**. Within about
   0.1 means the electrode is linear and healthy. Never calibrate on the check
   buffer — that is what makes it independent evidence rather than a
   restatement of the calibration.

On the device's own page the capture buttons carry the configured value
(**Capture high 9.18**), so the bottle in your hand can be checked against the
label before anything is stored. **Cal pH High Voltage** and **Cal pH Low
Voltage** show what was captured — write them down, and a point that has
drifted is obvious next time.

**Cal pH Slope** is the check that matters. It reads negative on this board —
more volts, lower pH — and a healthy electrode sits near −0.177 V/pH (the
Nernst slope at 25 °C); the device's page shows the magnitude. Much below
about 0.150 in size and it is worn out — recalibrating a dead electrode just
moves where it is wrong.

The reading is temperature-corrected against the DS18B20 at runtime, so a
probe calibrated at room temperature still reads correctly at 74 °F.

### Temperature — offset

**Cal Temperature Offset**, in °F, against a reference thermometer. Worth
doing: this probe is the only one the control loop has, so if it reads low
the heater will happily cook the tank while reporting the target, and nothing
anywhere will notice.

The offset is applied to the internal Celsius sensor rather than the
published Fahrenheit one, deliberately — the controller reads the internal
one, so correcting anywhere else would leave the control loop working from
the uncorrected value while every display showed the corrected one.

## Tuning

At the top of `packages/base.yaml`:

- **`target_temp_f`** — the setpoint, in Fahrenheit. Everything you set or
  read is Fahrenheit; the controller converts to Celsius once, internally,
  because its priors and clamps are tuned in °C/min.
- **`tds_k_factor`** — put the TDS probe in a known standard (707 ppm /
  1413 µS/cm), let it settle, set this to `known_ppm / displayed_ppm`,
  re-flash. Check `TDS Probe Voltage` if a reading looks wrong; in air it
  should sit near 0 V.

In the `tank_controller:` block:

- **`response_time`** (default 30 min) — how hard the controller pushes to
  close an error. Shorten it if recovery from a water change is too sluggish;
  lengthen it if the heater output looks jumpy.
- **`full_scale_lux`** (default 3000) — set near the lux your sensor reads
  with the tank lights on at full.
- **`min_temperature` / `max_temperature`** — hard cutouts, not targets.

Press `Reset Learning` after anything that changes the tank's physics — new
heater, big volume change, moving the tank to another room.

## Notes on the TDS reading

**Read `TDS 1h Mean`, not `TDS`.** A single sample from this probe is honest
about nothing. Over a day of live data the spread *within one hour* had a
median of 39 ppm and a maximum of 171 ppm — bigger than any dose you would
ever make, which means two readings minutes apart can differ by more than a
water change does. This project spent real effort explaining a 47 ppm
"overnight rise" that was noise.

So `TDS 1h Mean` is a 120-sample sliding window at 30 s, republished every
minute, computed **on the device** so the panel, the web page and Home
Assistant all show the same number with no broker involved. `TDS` itself is
still published, and still worth plotting underneath the mean: seeing the
noise band is what stops the next spike reading as an event. `Electrical
Conductivity` follows the mean, since it is the same measurement × 2 and the
two disagreeing by 30 µS/cm would look like a fault.

Underneath that: the raw value is a median over 20 ADC samples, giving a new
voltage every 10 s, and it is temperature-compensated to 77 °F using the
DS18B20. The ppm curve is the DFRobot Gravity polynomial (the Keyestudio
board is a clone of it); µS/cm is derived as `ppm × 2`, not measured
independently.

The probe ships uncalibrated — see [Calibration](#calibration). It is also
not rated for permanent submersion, and biofilm reads as dissolved solids, so
pull and clean it periodically.
