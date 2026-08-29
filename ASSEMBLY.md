# Assembly

Two boards are covered here and they wire up differently:

- **[ESP32-C6 (`tank-monitor`)](#esp32-c6-tank-monitor)** — solder directly to
  the board's pads.
- **[CYD ESP32-2432S028R (`tank-monitor-v2`)](#cyd-esp32-2432s028r-tank-monitor-v2)** —
  display-only remote panel. No wiring at all.

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

## If you ever convert it back to a controller

The pin map that worked on this revision: TDS IO35, heater IO27, fan IO18,
DS18B20 IO19 with a 4.7 kΩ pull-up to 3V3, BH1750 SDA/SCL on IO1/IO3 powered
from the 3-pin header's **3.3V, not the UART header's 5V**. Not IO22 — this
revision doesn't break it out. Not the speaker header — IO26 reaches it
through the audio amplifier.
