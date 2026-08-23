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
   for a fraction of each 15-minute window. 30% duty is 30% of full heater
   power, so the tank can sit *at* the setpoint instead of oscillating around
   it. (Set the heater's own thermostat dial to its maximum and let this
   control it — the heater becomes a dumb resistor.)

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

GPIO6/7 (SPI), 14 (LCD CS), 15 (LCD DC), 21 (LCD reset), 22 (backlight),
8 (RGB LED), 4/5 (microSD). GPIO12/13 are USB and 24-30 are flash. That
leaves GPIO0-3 (the only ADC-capable pins left), 9-11, 18-20, and 23.

## Wiring

Everything runs at 3.3 V.

### DS18B20 water temperature — 1-Wire

| Probe wire  | ESP32  |
|-------------|--------|
| Red (VDD)   | 3V3    |
| Black (GND) | GND    |
| Yellow (DQ) | GPIO18 |

Add a **4.7 kΩ resistor between DQ and 3V3**. Not optional — the bus is
open-drain and reads garbage without it.

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
working while Wi-Fi is up doesn't apply here. Any of GPIO0-3 would do; the
rest of the ADC block (GPIO4-6) is taken by the microSD slot and LCD.

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
| Channel 1 IN+   | GPIO23 (heater) |
| Channel 2 IN+   | GPIO10 (fan)    |
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
- **These are mechanical relays**, which is why the window is 900 s and not
  300 s. At 5-minute windows you'd spend ~288 contact cycles a day and wear
  them out in about a year; at 15 minutes it's ~96/day, so several years. The
  controller doesn't cycle at all when duty is pinned at 0% or 100%.

**If you want the tighter ±0.2 °F band later:** move the heater to a
zero-crossing SSR (SSR-25DA class, 3–32 VDC control, ~$12) in a project box,
and set `heater_output`'s `period` back to `300s`. An SSR is silent, has no
contacts, and cycles indefinitely — but it's real mains wiring, so only take
that on if you're comfortable with it and feeding it from a GFCI outlet. You
want the tank on a GFCI regardless.

### Full wiring diagram

All three sensors need 3V3 and GND, which is six wires converging on two
pins. Land power on a small bus (screw-terminal breakout, Qwiic/Grove hub
used purely for power, or a scrap of perfboard) and run only the signal
wires back to the GPIOs.

Total sensor draw is under 10 mA, so the board's own regulator powers
everything. No external supply.

**Power — one pair of wires from the board, fanned out:**

```
   ESP32-C6-LCD-1.47
   ┌─────────────┐
   │             │        ┌──────────── 3V3 RAIL ────────────┐
   │        3V3 ●┼────────┤                                  │
   │             │        │      │            │           │  │
   │        GND ●┼───┐    │     VCC          VCC         VCC │
   │             │   │    │   DS18B20        TDS        BH1750
   └─────────────┘   │    │     GND          GND         GND │
                     │    │      │            │           │  │
                     └────┤                                  │
                          └──────────── GND RAIL ────────────┘
                                             │
                                             └──── Relay IN- (both ch.)
```

**Signal — one wire each, straight to its GPIO:**

```
   ESP32-C6-LCD-1.47
   ┌─────────────┐
   │             │
   │      GPIO18 ●──────────┬──────────────► DS18B20  DQ   (yellow)
   │             │          │
   │             │         ┌┴┐
   │             │         │ │ 4.7k  pull-up, at the BOARD end
   │             │         └┬┘        not out at the probe
   │        3V3 ─┼──────────┘
   │             │
   │       GPIO1 ●─────────────────────────► TDS       A    (analog)
   │             │
   │      GPIO19 ●─────────────────────────► BH1750    SDA
   │      GPIO20 ●─────────────────────────► BH1750    SCL
   │             │                           BH1750    ADDR → leave open
   │             │
   │      GPIO23 ●─────────────────────────► D-1584TL  CH1 IN+  (heater)
   │      GPIO10 ●─────────────────────────► D-1584TL  CH2 IN+  (fan)
   │             │
   └─────────────┘
```

**Every wire, in one table:**

| From (ESP32-C6) | To | Notes |
|---|---|---|
| 3V3 | bus → DS18B20 red, TDS VCC, BH1750 VCC | TDS at 3.3 V, **never 5 V** |
| GND | bus → DS18B20 black, TDS GND, BH1750 GND, relay IN− ×2 | one common ground |
| GPIO18 | DS18B20 yellow (DQ) | + 4.7 kΩ from DQ to 3V3 |
| GPIO1 | TDS "A" | ADC-capable pin |
| GPIO19 | BH1750 SDA | |
| GPIO20 | BH1750 SCL | |
| GPIO23 | D-1584TL channel 1 IN+ | heater |
| GPIO10 | D-1584TL channel 2 IN+ | fan |

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
│                              74-75 °F      │
│                              sw 0.2        │
│              74.5                          │  ← 11mm digits, whole panel
│                                            │    background = status colour
│                          STEADY  32%       │
├────────────────────────────────────────────┤
│ TDS 212                          TDS OK    │  ← 34px strip
└────────────────────────────────────────────┘
```

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

All six numbers are substitutions at the top of `tank-monitor.yaml`
(`temp_lo`, `temp_hi`, `temp_red_lo`, `temp_red_hi`, `tds_lo`, `tds_hi`,
`tds_red_lo`, `tds_red_hi`) — change them in one place and both the display
bands and the on-screen target text follow.

The control setpoint is **23.6 °C / 74.5 °F**, the centre of the 74–75 band,
so normal drift stays inside green in both directions.

### Not measured

Your target list also includes pH 7.2–7.5, GH 7–8, and KH 3–4. There's no
sensor for those in this build — GH and KH have no practical hobby-grade
probe and stay test-kit measurements. pH *is* addable (an analog probe on a
spare ADC pin, GPIO0/2/3 are free), but it needs two-point calibration and
the probe is a consumable that drifts and needs replacing every year or so.
Say the word if you want it.

## 3D printed case

Your LAFVIN board is a clone of the Waveshare ESP32-C6-LCD-1.47, so cases cut
for the Waveshare fit. Free options:

- **[Case for ESP32-C6-LCD-1.47](https://www.printables.com/model/1601229-case-for-esp32-c6-lcd-147)** by Dicson (Printables) — updated Feb 2026
- **[ESP32-C6 1.47inch Display Enclosure](https://www.printables.com/model/1365867-esp32-c6-147inch-display-enclosure)** by Jonathan Senkerik (Printables) — snap-on lid
- **[ESP32-C6-1.47-LCD](https://www.printables.com/model/1472316-esp32-c6-147-lcd)** by By_ISIK (Printables)
- **[ESP32-LCD-1.47 Case](https://makerworld.com/en/models/1301018-esp32-lcd-1-47-case)** by Sedikit (MakerWorld) — two halves, needs gluing
- **[Clip-in case](https://www.thingiverse.com/thing:7065147)** by amduck (Thingiverse) — prints without supports, but cut for the **Touch** variant, so check the front face

If you want to design your own, there's an
**[accurate reference CAD model](https://www.printables.com/model/1633740-esp32-c6-lcd-147-reference-cad-model)**
by x_giedrius_x.

**One thing every one of these will be wrong about:** they're designed around a
bare dev board with a USB-C port and nothing else. You have eight wires leaving
the board — power bus, three sensors, two relay channels. Expect to cut or model
a cable exit on whichever you pick. The reference CAD model is the honest
starting point if you'd rather do it properly than take a knife to a print.

Print in PETG rather than PLA if the case will sit on the tank rim — PLA
softens in warm humid air and creeps over time.

---

## Assembly

Step-by-step soldering instructions are in **[ASSEMBLY.md](ASSEMBLY.md)** —
build order, the pull-up resistor, the pre-power checks, and a staged
power-up sequence.

## Flashing

```sh
pip install esphome
cp secrets.yaml.example secrets.yaml   # then edit it
esphome run tank-monitor.yaml
```

First flash over USB; after that `esphome run` uses OTA. Live values are at
`http://tank-monitor.local/`.

---

## How the learning works

The controller fits a five-parameter thermal model of your tank:

```
dT/dt  =  kh·heater  −  kf·fan  −  ka·(T − 25)  +  kl·light  +  c    [°C/min]
```

- `kh` — how fast your heater actually raises this volume of water
- `kf` — how much your fan's evaporative cooling pulls out
- `ka` — how fast the tank loses heat to the room per degree of difference
- `kl` — heat the lights add at full brightness
- `c`  — residual constant drift

Parameters are fit online with recursive least squares (forgetting factor
0.9995 — it adapts over days, not minutes) and clamped to physically plausible
ranges, which is what keeps closed-loop identification from wandering off
during long stretches where nothing much is changing.

**Learning runs on 5-minute windows, not every tick.** A DS18B20 quantizes to
0.0625 °C; differentiating that every 30 s produces noise far larger than the
~0.02 °C/min signal being measured. Averaging over 5 minutes brings it into
range.

Separately, a 96-slot (15-minute resolution) profile of normalized light level
is learned per time-of-day, so the controller can predict the light heat load
20 minutes ahead and pre-compensate.

Both the model and the light profile are saved to flash every 10 minutes and
restored on boot — a reboot doesn't cost you the learning.

### Safety behavior

- Above `max_temperature` (27 °C): heater off, fan full, model ignored.
- Below `min_temperature` (21 °C): heater full.
- Temperature probe missing for 2 minutes: **heater cut off** and the
  `Temperature Fault` problem sensor trips. A slowly cooling tank is a much
  better failure than a cooked one.
- Residuals over 0.5 °C/min are discarded rather than learned from — that's a
  water change or a bad read, not information about the tank.

---

## Home Assistant entities

Under one `Tank Monitor` device:

**Controls** — `Target Temperature` (°C, 21–27), `Display Backlight`,
`Adaptive Learning` switch,
`Reset Learning` button, `Restart` button.

**Main** — `Water Temperature` (°C), `Water Temperature F` (°F), `TDS` (ppm),
`Electrical Conductivity` (µS/cm), `Tank Light Level` (lx), `Heater Output`
(%), `Fan Output` (%), `Predicted Temperature (15 min)`, `Controller State`.

**Diagnostic** — `Model Confidence`, `Tank Time Constant`, `Learned Heater
Power`, `Learned Light Heat Gain`, `Predicted Light Load`, `Temperature Drift
Rate`, `TDS Probe Voltage`, `Temperature Fault`, Wi-Fi signal, uptime, IP.

`Model Confidence` reaching 100% means roughly a day of learning steps have
accumulated. Watch `Heater Output` — once settled it should sit at a fairly
steady partial value, not flip between 0 and 100.

---

## Tuning

At the top of `tank-monitor.yaml`:

- **`target_temp`** — setpoint in °C. 24.0 °C = 75.2 °F. Also adjustable live
  from HA; the slider value persists across reboots.
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

The published value is a median over 20 ADC samples every 2 s; the probe is
AC-excited and raw readings jump by tens of ppm. It's temperature-compensated
to 25 °C using the DS18B20. The ppm curve is the DFRobot Gravity polynomial
(the Keyestudio board is a clone of it); µS/cm is derived as `ppm × 2`, not
measured independently.

The TDS probe is not rated for permanent submersion and biofilm reads as
dissolved solids — pull and clean it periodically.
