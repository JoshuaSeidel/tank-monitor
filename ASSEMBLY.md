# Assembly

Two boards are covered here and they wire up differently:

- **[ESP32-C6 (`tank-monitor`)](#esp32-c6-tank-monitor)** — solder directly to
  the board's pads.
- **[CYD ESP32-2432S028R (`tank-monitor-v2`)](#cyd-esp32-2432s028r-tank-monitor-v2)** —
  everything lands on JST connectors, no soldering to the board at all.

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

Nothing solders to this board. Every wire lands on one of its JST connectors,
so the work is crimping or splicing onto JST pigtails rather than tinning pads.
Steps 2 (pre-tin), 6 (pull-up) and 8 (inspect) from the C6 build still apply to
the wire ends and the probe.

**Read the first-flash warning below before you plug anything into USB.**

## What you need

- JST 1.25 mm pigtails to match the board's connectors, or the ones it shipped with
- 4.7 kΩ resistor (1/4 W)
- A **separate 5 V supply** for the relay module — see step 4
- Multimeter

## 1. Why these pins

Almost every GPIO on this board is already used internally: 12–15 display,
25/32/33/36/39 touch, 5/18/19/23 microSD, 4/16/17 RGB LED, 21 backlight,
26 speaker, 34 onboard LDR. What is actually reachable on the connectors is
IO22, IO27 and IO35 (the "Expand Input" connectors), IO26 (speaker) and
IO1/IO3 (UART). That is exactly six usable lines, and the build needs six —
there is no spare, which is why the assignments below are not negotiable.

## 2. Signal wires

| Connector | Pin | Goes to |
|---|---|---|
| Expand Input | IO35 | TDS `A` |
| Expand Input | IO22 | DS18B20 yellow (DQ) |
| Expand Input | IO27 | Relay Ch1 `IN+` (heater) |
| Speaker header | IO26 | Relay Ch2 `IN+` (fan) |
| UART header | IO1 | BH1750 `SDA` |
| UART header | IO3 | BH1750 `SCL` |

Leave BH1750 `ADDR` unconnected — floating is address 0x23, which is what the
config expects.

IO35 is input-only and on ADC1. ADC2 cannot be read while Wi-Fi is on, so
32–39 is the only usable range for the TDS analog line and 35 is the only pin
free in it. Do not move it.

**Meter each connector before you trust the silkscreen.** Confirm which pin of
each JST is 3V3, which is GND and which is the signal, with the board powered
off. Continuity from the connector pin to a known GND point is the quick check.

## 3. The 4.7 kΩ pull-up

Same as the C6 build: between the **DQ line and 3V3**, at the board end of the
run, not out at the probe. Sleeve both legs. Without it the DS18B20 reads
nothing or garbage.

## 4. Relay power — this board has no 5 V output

Nothing on the CYD brings 5 V out to a connector, so the D-1584TL needs its own
5 V supply. Its inputs are optocoupled, which is what makes this fine: run the
separate supply to the module, and **tie its ground to the board's ground** so
the control signals share a reference.

IO27 and IO26 go to `IN+` on channels 1 and 2. `IN−` on both channels goes to
the shared ground.

Do not open the relay module or touch its mains side. It has its own cord.

**Route the TDS wire away from the relay's power cord.** High-impedance analog
next to a mains cable picks up 60 Hz hum, and you will chase a noisy reading
that is not a sensor fault.

## 5. Verify the fan line before you rely on it

IO26 is shared with the on-board speaker amplifier. Meter the speaker header
with the board off and confirm the pin connects **directly** to IO26 on the
ESP32, not to the amplifier's output. If it is post-amp it cannot drive a relay
input, and the fan has to move to **IO2 on the SPI header** instead — IO2 is a
strapping pin, so it then needs a pulldown to stay low at boot, and
`boards/cyd-esp32-2432s028r.yaml` has to change to match.

A fan line that silently does nothing looks exactly like a controller that
never calls for cooling, so confirm this now rather than during a heat spike.

## 6. First USB flash: unplug the BH1750

**This one bites.** IO1/IO3 are UART0 — the pins the on-board CH340 uses to
talk to the ESP32. With the BH1750 on them, USB flashing can fail or hang.

1. **Unplug the BH1750** from the UART header.
2. Flash over USB.
3. Plug the BH1750 back in.

After the first flash the device is OTA-only and the sensor stays connected.

The same collision is why serial logging is off (`baud_rate: 0`). There is no
USB console on this board, so if it ever fails to boot you have no serial
output to read — recovery is a USB re-flash with the sensor unplugged again.

## 7. Power up in stages

1. USB only, nothing connected to mains. The LCD should light and show the UI.
2. Check the device's web page at its IP — `Water Temperature`, `TDS`, and
   `Tank Light Level` should all be present. A missing BH1750 shows up as no
   light reading and an empty I²C scan.
3. Check the TDS voltage with the probe **dry** — should sit near 0 V.
4. Tap the nav buttons. Touch working confirms the display and touch panel
   agree, which is orientation-sensitive on this board.
5. Only now plug in the relay module. Confirm the heater outlet clicks when
   the controller calls for heat.
6. Wet the probes and confirm sensible readings before anything goes in the
   tank.

## 8. Before it goes near water

Same as the C6: strain-relieve every wire where it leaves the board, mount the
board **above** the water line, and put the whole thing on a GFCI outlet.
