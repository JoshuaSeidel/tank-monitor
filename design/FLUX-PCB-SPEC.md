# Tank-Monitor Carrier Board — flux.ai Build Instructions

A single custom PCB that replaces the XIAO-ESP32-S3 controller + separate BLE-bridge
ESP32 with one board carrying **two radios** (Wi-Fi/ESP-NOW chip + dedicated BLE chip),
all sensor front-end circuitry onboard, and screw-terminal connectors so bare
off-the-shelf probes (DS18B20, pH, TDS, BH1750, AS7341) plug straight in.
Multiple boards chain over an RS-485 expansion bus for multi-tank setups.

Target size: **55 × 60 mm (~2.2 × 2.4 in)**. Three things make this size
work: slim 12.7 mm-wide power relays instead of the classic G5LE cube, a
10440 (AAA-size) onboard backup cell with a BATT-EXT jack for a larger
case-mounted pack (§4b), and **double-sided assembly** — every small IC
(ADCs, charger, isolator, MOSFETs, shift register) lives on the back face;
the front face carries the two radio modules, relays, battery holder, and
all connectors. Sensor terminals are 2.54 mm push-in (§5). A placement
mockup lives at `design/carrier-v1-mockup.svg` (illustrative only —
flux.ai does the layout). 4-layer board
(SIG / GND / 3V3 / SIG) — flux.ai handles 4-layer fine and it makes the analog
isolation section much easier to route cleanly.

---

## 1. Architecture overview

```
                    ┌────────────────────────────────────────────┐
  USB-C 5V/3A ────► │ power-path/charger ──► 3V3 (digital)       │
                    │                └► isolated 3V3 (analog pH) │
                    │                                            │
                    │  ESP32-S3-WROOM-1-N16R8  ◄─UART2─►  ESP32-C3-MINI-1 │
                    │  (main: Wi-Fi + ESP-NOW)            (BLE only)      │
                    │        │                                            │
                    │   I²C bus ── ADS1115 ── isolated pH AFE             │
                    │        │        └────── TDS AFE                     │
                    │        ├── qwiic ×2 (BH1750 / AS7341 pods)          │
                    │   1-Wire ×2 (DS18B20 screw terminals)               │
                    │   Relay/SSR ×4 (heater A, heater B, fan, spare)     │
                    │   RS-485 expansion bus (2× USB-C LINK, daisy-chain) │
                    └────────────────────────────────────────────┘
```

Why two ESP32s instead of one ESP32 + nRF: the C3 runs the **existing
ESPHome BLE bridge firmware nearly unchanged** (Chihiros light control,
light-pod BLE link), keeping the whole repo single-toolchain. The S3 keeps
Wi-Fi + ESP-NOW, which we already know coexist; BLE moves off-chip, which is
exactly the coexistence limit that forced the two-board setup today.

## 2. Modules (use pre-certified modules, NOT bare chips)

| Ref | Part | Role |
|---|---|---|
| U1 | **ESP32-S3-WROOM-1-N16R8** | Main MCU. Wi-Fi STA + ESP-NOW broadcast. 16 MB flash / 8 MB PSRAM matches current firmware assumptions. |
| U2 | **ESP32-C3-MINI-1-N4** | BLE-only co-processor (Chihiros bridge, light-pod link). |
| U3 | **ADS1115IDGSR** | 16-bit ADC, addr 0x48 (ADDR→GND). pH on differential AIN0/AIN1, TDS on AIN2, AIN3 spare. |
| U4 | **DS18B20 front-end** | No IC — just 4.7 kΩ pull-ups to 3V3, one per bus. |
| U5 | pH AFE: **TLC2262 or LMP7721** ultra-high-input-impedance op-amp unity buffer + bias network | pH glass electrodes are ~10⁹ Ω sources; never feed an ADS1115 directly. |
| U6 | **ADuM1250 / ISO1541** I²C isolator + **B0303S-1WR3** isolated DC-DC | Galvanically isolates the pH section (see §4). |
| U7 | **THVD1450** RS-485 transceiver | Expansion/multi-tank bus. |
| U8 | USB-C power input: 5.1 kΩ CC pull-downs (advertises 5 V/3 A), polyfuse, TVS | No buck converter — the whole board runs from USB-C 5 V (~1 A worst case). |
| U9 | LDO: **AP2112K-3.3** ×2 | One per ESP32 (keeps C3 alive through S3 brownouts). Fed from the battery-backed rail (§4b). |
| U10 | **BQ25171-Q1** LiFePO₄ charger + power-path, 3.65 V | Battery backup charge/switchover (§4b). |
| U11 | **TPS63020** buck-boost 3V3 | Battery-backed system rail (§4b). |
| U12 | **74HC595** shift register | Sensor-status LEDs (§4c). |
| U13 | **LTC4311** I²C bus accelerator | Sits behind the Qwiic jacks so the BH1750/AS7341 breakouts work over 2–3 m of cable up at the light fixture. This is what makes the board all-in-one: light sensors are wired peripherals like the temp probes — no BLE light pod needed. |
| BT1 | 10440 LiFePO₄ cell (AAA-size, ~200 mAh) + holder + NTC | ~1–1.5 h onboard backup — rides out blips, always gets the mains-loss alert out. |
| J-BATT | JST-XH 3-pos (B+, TS, GND) | External case-mounted LiFePO₄ pack in parallel (e.g. 2× 18650 holder in the lid → 12 h+). |
| K1–K2 | **HF115F/005-1ZS3 slim power relays** (12.7 mm wide, 10 A) | Heater A / Heater B. 5 V coil fed from USB VBUS; AO3400 low-side MOSFET + flyback diode per coil, gated by the same 3.3 V GPIOs as today — the drive interface the firmware sees is unchanged. |
| K3–K4 | **HF32F/005-HSL3** slim 5 A relays | Fan, Spare (light loads). Same 5 V-coil MOSFET drive. |

**Relay notes:** the two 300 W heaters draw ~2.5 A each at 120 VAC; the
HF115F's 10 A contacts cover that with margin in a package half the G5LE's
width — that swap is what lets the board hit 55 × 60. Coils run from the
USB-C 5 V rail (VBUS), *not* the battery-backed 3V3: on mains loss the
coils lose power and every relay drops out by physics, no firmware needed
— the fail-safe is back in hardware. The GPIO→MOSFET drive is still 3.3 V
logic, so nothing changes for the firmware. `slow_pwm` at 20–60 s periods
keeps mechanical wear a non-issue; zero-cross isn't needed.

## 3. Pin map (mirror the existing firmware so YAML changes are minimal)

ESP32-S3 (U1):
- GPIO1 → 1-Wire bus B (cross-check probe), 4.7 kΩ to 3V3
- GPIO6 → 1-Wire bus A (control probe), 4.7 kΩ to 3V3
- GPIO43/44 → I²C SDA/SCL (main bus: ADS1115, qwiic connectors)
- GPIO7 → Heater A relay drive
- GPIO5 → Heater B relay drive
- GPIO8 → Fan relay drive
- GPIO9 → Spare relay drive
- GPIO17/18 → UART2 TX/RX ↔ C3 UART RX/TX (the S3↔C3 link)
- GPIO4 → battery voltage divider (ADC1); GPIO2 → charger PGOOD/AC-present (§4b)
- GPIO38/39/40 → 74HC595 (data/clock/latch) for status LEDs 6–10 (§4c)
- GPIO41, GPIO42 → spare screw terminal pair (float switch / leak sensor)
- GPIO47, GPIO48 → WIFI and ESPNOW status LEDs (direct drive)
- GPIO3 left unconnected (S3 strapping pin — firmware already treats it as forbidden)
- GPIO0 + EN → push buttons (BOOT/RESET) and to the USB-C/UART auto-program circuit
- RS-485: GPIO15 (TX), GPIO16 (RX), GPIO14 (DE/RE tied)

ESP32-C3 (U2):
- GPIO18/19 → native USB-serial-JTAG, to the shared USB-C via the S3/C3 slide switch (flashing/logs)
- GPIO6/7 → UART1 ↔ S3
- GPIO8 → status LED
- BOOT/RESET buttons

Both modules: keep-out zone under the antenna end — **antennas must overhang the
board edge or sit over a copper-free region ≥ 15 × 20 mm on all layers**, and
place them at opposite corners of the board.

## 4. Isolation (the part to get right)

1. **pH front-end — galvanic isolation.** Everything left of the isolation
   barrier: BNC jack (panel-mount, PTFE-insulated), guard ring driven by the
   buffer output around the BNC center trace, LMP7721 buffer, bias divider,
   ADS1115 differential input pair *or* better: put the pH channel on its own
   ADS1115 at 0x49 on the isolated side, crossing back through the ADuM1250
   I²C isolator, powered by the B0303S isolated DC-DC. ≥ 4 mm creepage slot
   milled under the barrier. This kills the classic "pH reads garbage when the
   TDS probe or heater is in the same water" ground-loop problem.
2. **TDS:** stays on the non-isolated ADS1115 (0x48) but drive the probe from a
   GPIO-switched excitation so it's only energized during sampling — reduces
   pH cross-talk and electrode plating.
3. **Mains section:** heater/fan relay contacts and their screw terminals in a
   fenced corner of the board: ≥ 6.4 mm creepage to everything low-voltage,
   milled slots between contact pads, no ground pour underneath, and a
   silkscreen box marked "⚡ 120 VAC". The relay coil itself is the
   isolation barrier (both relay families are rated 4 kV coil-to-contact);
   AO3400 MOSFET + flyback diode on the coil side.
4. **1-Wire probes** are submerged: add per-bus 100 Ω series resistor + TVS
   (SMAJ5.0A) + 470 pF to GND at the terminal — ESD/surge clamp for wet leads.
   (We've had probe water-ingress drag a bus low; series R keeps a shorted
   probe from latching the GPIO.)
5. **RS-485:** TVS array (SM712) + 120 Ω termination behind a DIP switch.

## 4b. Battery backup (onboard, power-path)

Goal: sensors, both radios, and alerting survive a wall-power outage; heaters
and fan do **not** run from battery (they're mains-side anyway — the relay
contacts just open when mains dies, which is the safe state).

- **Chemistry: LiFePO₄, 3.2 V nominal, single parallel group.** Chosen over
  Li-ion deliberately: this lives in a warm, humid cabinet 24/7 at float
  charge — LiFePO₄ tolerates continuous float, doesn't balloon, and its
  2000+ cycle life means you never think about it.
- **Onboard cell: 10440 (AAA-size, ~200 mAh)** in a board-mount holder —
  the size that lets the board hit 55 × 60 mm. Runs both ESP32s + sensors
  (~150 mA average with Wi-Fi) for **~1–1.5 h**: rides out typical blips
  and always gets the mains-loss alert sent. Anything longer is the
  external pack's job.
- **BATT-EXT (JST-XH 3-pos: B+, TS, GND):** an optional larger case-mounted
  LiFePO₄ pack wired in parallel with the onboard cell. Same chemistry and
  voltage, so the group self-balances and the one BQ25171 charges both —
  no second charger, no switching. A 2× 18650 holder velcroed in the case
  (cells in parallel, ~3000 mAh) takes total runtime past **12 h**. The
  external pack's NTC lands on TS alongside the onboard one (use the colder
  reading: two NTCs in parallel skews safe).
- **Charger/power-path: TI BQ25798 or simpler BQ25171-Q1 (LiFePO₄-aware,
  set to 3.65 V charge voltage)** fed from the 5 V buck. True power-path:
  the load is carried by the input while mains is present, battery is only
  a standby — seamless switchover, no reboot, no brownout on the C3.
- Battery rail → its own **TPS63020 buck-boost → 3V3** so the system rides
  the cell from 3.65 V down to 2.5 V cutoff. The two AP2112K LDOs in §2
  hang off this rail instead of directly off the 5 V buck.
- **Fuel/status sensing to firmware:** battery voltage via 1 % divider into
  S3 ADC (GPIO4 — it was spare), plus a `PGOOD`/`AC-present` digital signal
  from the charger into GPIO2. ESPHome exposes "on battery" + voltage %, HA
  alerts on mains loss — this is the actual payoff: **the tank texts you when
  the power goes out**, even though the router/HA may be down (queue the
  alert; also blink the PWR LED pattern, §4c).
- Protection: cell holder → 2 A polyfuse → charger; reverse-cell MOSFET;
  NTC pad on the holder wired to the charger's TS pin (charge inhibit
  outside 0–45 °C).
- Load shedding in firmware, not hardware: on battery, drop ESP-NOW
  broadcast rate and display links; keep 1-Wire/I²C sampling and MQTT.

## 4c. Status LEDs — case front panel

All LEDs on **one edge of the board in a single row on 5 mm pitch**, so a
straight strip of press-fit **light pipes (Bivar PLP2-500 series)** carries
them through the case wall. Rear-mount 0603 LEDs + light pipes beat
panel-mount wired LEDs: zero wiring, and the case drawing is just a row of
3 mm holes.

| # | Label | Color | Driven by | Meaning |
|---|---|---|---|---|
| 1 | PWR | Green | Hardware (3V3 rail) | Board powered |
| 2 | BATT | Amber | Charger STAT pin | Solid = charging, off = charged; firmware blinks it on mains-loss via a shared GPIO-OR |
| 3 | WIFI | Blue | S3 GPIO | Solid = connected, slow blink = connecting |
| 4 | ESPNOW | Blue | S3 GPIO | Blip on each broadcast — the "heartbeat" you can see across the room |
| 5 | BLE | Blue | C3 GPIO | Solid = Chihiros/pod connected, blink = scanning |
| 6 | TEMP-A | Green/Red bicolor | S3 GPIO ×2 | Green = probe reading sane; red = bus fault / value guard tripped |
| 7 | TEMP-B | Green/Red bicolor | S3 GPIO ×2 | Same, cross-check probe |
| 8 | CHEM | Green/Red bicolor | S3 GPIO ×2 | ADS1115/pH/TDS: green = I²C alive + values in band, red = missing device or wild reading |
| 9 | RS485 | Yellow | Transceiver activity (RX line via transistor) | Expansion bus traffic |
| 10 | FAULT | Red | S3 GPIO | Any alarm state (mirrors the existing on-device guards: dry TDS chamber, 1-Wire held low, heater disagreement) |

GPIO budget is tight on the S3 with bicolors — put LEDs 6–10 behind a
**74HC595 shift register** (3 GPIOs: GPIO15 is freed by moving RS-485 DE to
the '595 too, or just use GPIO38/39/40 which the WROOM module exposes and
the XIAO never had). LEDs 3–4 stay on direct GPIOs for zero-latency blips.
All firmware-driven: one ESPHome `status_led`-style interval block per LED,
fed from the exact template sensors that already exist (probe fault flags,
Wi-Fi/ESP-NOW state).

Silkscreen the labels on the board edge AND provide a printable front-panel
label strip in `case/`.

## 4d. Case mounting

- **M3 mounting holes at 4 corners**, 3.2 mm plated, 6 mm annular keep-out,
  positioned on a 5 mm grid so the case (FDM-printable, files to live in
  `case/carrier-v1/`) is trivial to model.
- All connectors on **two opposite edges only**: low-voltage screw
  terminals + Qwiic + BNC + all three USB-C (PWR, LINK ×2) on the "wet side" edge; mains relay
  terminals alone on the other edge, so mains and probe wiring
  never cross inside the case.
- LEDs + light pipes on a third (front) edge, DIP switch and BOOT/RESET
  buttons reachable through case cutouts.
- Component height limit 12 mm everywhere except the relay/battery zone
  (10440 holder ≈ 13 mm; HF115F ≈ 16 mm) — put the battery holder and relays in one
  "tall" corner so the case lid steps over a single region.
- Conformal-coat keep-out silkscreen around connectors; the case gets a
  drip loop note: probe cables must enter from below.

## 5. Connectors

Signal-level field wiring (22–28 AWG probe leads) uses **2.54 mm-pitch
push-in spring terminals (Phoenix PTSM 0,5 series or Wago 2060)** — tool-free,
and thin probe wire holds better in spring clamps than in screw barrels.
Only mains (5.08 mm — that pitch is the creepage) and the BNC stay large.

| Qty | Connector | Signal |
|---|---|---|
| 2 | 3-pos 2.54 mm push-in (PTSM) | DS18B20 A / B: 3V3, DATA, GND |
| 1 | Panel BNC (isolated section) | pH electrode |
| 1 | 3-pos 2.54 mm push-in (isolated GND ref) | pH temp-comp / spare isolated analog |
| 1 | 2-pos 2.54 mm push-in | TDS probe |
| 2 | JST-SH 4-pin **Qwiic** | BH1750 lux (0x23/0x5C — two fit one bus) and AS7341 spectral breakouts on cables up to the light fixture (2–3 m OK via the LTC4311 buffer). Buy Adafruit/SparkFun breakouts, no soldering. |
| 4 | 2-pos 5.08 mm screw terminal (rated 10 A / 300 V) | Relay outputs (dry contacts / SSR outputs) |
| 2 | USB-C **LINK** ports (paralleled, labeled LINK-IN / LINK-OUT) | RS-485 A/B on D+/D−, GND, +5 V pass-through on VBUS behind an ideal-diode OR (LM66100) so chained powered boards never back-feed each other. Daisy-chain tanks with ordinary USB-C 2.0 cables. Plugging a charger into a LINK port harmlessly powers the board. No CC logic — these are not USB ports, silkscreen them "LINK — NOT USB DATA". |
| 1 | USB-C (power + flash) + S3/C3 slide switch | Sole power input (5 V/3 A CC advertise) and shared flashing/log port; slide switch routes D+/D− to either module. VBUS → polyfuse → charger power-path, so flashing and powering are the same cable. |
| 1 | 4-pos 2.54 mm push-in | Spare GPIO41/GPIO42 + 3V3 + GND (float switches, leak sensor, etc.) |
| 10 | 0603 LEDs + Bivar PLP2 light pipes, one edge row, 5 mm pitch | Status panel (§4c) |
| 1 | Keystone 82 AAA/10440 holder (board-mount) | Onboard LiFePO₄ backup cell (§4b) |
| 1 | JST-XH 3-pos | BATT-EXT: external case-mounted LiFePO₄ pack (§4b) |

Every terminal gets silkscreen labels **with the signal name and the firmware
GPIO** (e.g. "TEMP-A GPIO6"), and polarity marks.

## 6. Multi-tank / expansion story

- Each board is a complete single-tank node (its own Wi-Fi connection to HA/MQTT
  — this is how the repo works today, so board #2 on a second tank needs zero
  new firmware).
- The RS-485 bus is the *optional* tie: extra sensor-only boards (a board
  populated without relays/second ESP32 — make U2, K1–K4 DNP variants in flux)
  can report to a head unit where Wi-Fi is weak, and +5 V pass-through on the
  LINK ports' VBUS powers a remote pod over a few meters of USB-C cable.
- DIP switch (4-pos) read on boot → node address 0–15, exposed to ESPHome.

## 7. What to type into flux.ai (step-by-step)

1. **New project** → "tank-monitor-carrier", 4-layer, 55 × 60 mm outline,
   double-sided assembly (small ICs on the back face).
2. Search flux's part library and drop in: `ESP32-S3-WROOM-1`, `ESP32-C3-MINI-1`,
   `ADS1115IDGSR` ×2, `ADuM1250ARZ`, `B0303S-1WR2`, `THVD1450DR`, `AP2112K-3.3TRG1` ×2, `LMP7721MA`, `USB4110-GF-A` ×3 (PWR + 2 LINK), `LM66100DCKR` ×2, `HF115F/005-1ZS3` ×2, `HF32F/005-HSL3` ×2,
   `AO3400A` ×4, `BQ25171-Q1`, `TPS63020DSJR`,
   `74HC595` (`SN74HC595DR`), `LTC4311CSC6`, Keystone `82` AAA holder, JST `B3B-XH-A`, screw terminals and
   Qwiic (`PRT-14417`) as above. Where flux lacks a part, import from SnapEDA/Ultra Librarian.
3. Use flux's **AI auto-connect prompts** per functional block, in this order,
   verifying each block's nets before the next: power tree (USB-C VBUS → charger
   power-path → buck-boost → LDOs) → S3 core
   (strapping resistors, 10 kΩ EN pull-up + 1 µF, boot/reset buttons, USB) →
   C3 core → UART cross-link → I²C bus + pull-ups (2× 4.7 kΩ) → ADS1115s →
   pH AFE → relay drivers → RS-485 → 74HC595 + LED row → terminals.
4. **Design rules:** set net classes — `MAINS` (clearance 6.4 mm),
   `PH_ISO` (own ground `AGND_ISO`, stitched nowhere), `RF` (antenna keep-out).
5. **Placement:** radios at top corners (antennas overhanging), power entry
   bottom-left, mains relay corner bottom-right, isolated pH strip along the
   left edge with the milled slot, all screw terminals on board edges.
6. Run flux's DRC + its AI review ("check my ESP32-S3 strapping pins,
   decoupling, and USB differential pair"), then export Gerbers/BOM/PnP for
   JLCPCB 4-layer with assembly.

## 8. Firmware deltas after the board exists

- New board file `boards/carrier-v1.yaml`: same pin substitutions as
  `xiao-esp32s3-lg-dual.yaml` except UART link to the C3 and the second
  ADS1115 at 0x49 for pH.
- C3 gets a trimmed variant of the BLE bridge config (`aquarium-ble-bridge`)
  with `uart` instead of Wi-Fi API as its transport to the S3 — or, simpler
  v1: give the C3 its own Wi-Fi API exactly like today's separate bridge
  board and use the UART link only for watchdog/heartbeat. Zero new code.
- ESP-NOW + Wi-Fi stay on the S3 (already proven to coexist); BLE lives
  entirely on the C3, so all three run simultaneously per the design goal.
