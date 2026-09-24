# Tank-Monitor Carrier Board — flux.ai Build Instructions

A single custom PCB that replaces the XIAO-ESP32-S3 controller + separate BLE-bridge
ESP32 with one board carrying **two radios** (Wi-Fi/ESP-NOW chip + dedicated BLE chip),
all sensor front-end circuitry onboard, and screw-terminal connectors so bare
off-the-shelf probes (DS18B20, pH, TDS, BH1750, AS7341) plug straight in.
Multiple boards chain over an RS-485 expansion bus for multi-tank setups.

Target size: **≤ 100 × 100 mm (4 × 4 in); aim for 80 × 80 mm.** 4-layer board
(SIG / GND / 3V3 / SIG) — flux.ai handles 4-layer fine and it makes the analog
isolation section much easier to route cleanly.

---

## 1. Architecture overview

```
                    ┌────────────────────────────────────────────┐
 12 V DC barrel ──► │ Buck 12V→5V ──► LDO 5V→3V3 (digital)       │
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
                    │   RS-485 expansion bus (2× RJ45, daisy-chain)       │
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
| U8 | Buck: **TPS54331** or module **K7805-1000R3** (12 V→5 V, 1 A) | Main rail. |
| U9 | LDO: **AMS1117-3.3** or better **AP2112K-3.3** ×2 | One per ESP32 (keeps C3 alive through S3 brownouts). |
| K1–K4 | **G3MB-202P** solid-state relays (or HF115F 10 A mechanical for heaters — see note) | Heater A, Heater B, Fan, Spare. Driven via NPN/MOSFET + opto already inside the SSR. |

**Heater relay note:** the two 300 W heaters draw ~2.5 A each at 120 VAC. G3MB-202P
is rated 2 A — use **G3MC-202P (2 A)** only for the fan/spare and put **10 A
HF115F mechanical relays** (or panel-mount SSRs off-board) on the two heater
channels, with proper creepage (§4). Firmware uses `slow_pwm` with 20–60 s
periods, so mechanical relay wear is acceptable and zero-cross isn't needed.

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
- GPIO2, GPIO4 → broken out to a spare screw terminal pair (ADC1-capable)
- GPIO3 left unconnected (S3 strapping pin — firmware already treats it as forbidden)
- GPIO0 + EN → push buttons (BOOT/RESET) and to the USB-C/UART auto-program circuit
- RS-485: GPIO15 (TX), GPIO16 (RX), GPIO14 (DE/RE tied)

ESP32-C3 (U2):
- GPIO20/21 → UART0 (native USB-serial-JTAG also broken out to its own USB-C for flashing)
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
   silkscreen box marked "⚡ 120 VAC". Optocoupled drive (built into SSRs;
   for mechanical relays add PC817 + flyback diode + driver transistor).
4. **1-Wire probes** are submerged: add per-bus 100 Ω series resistor + TVS
   (SMAJ5.0A) + 470 pF to GND at the terminal — ESD/surge clamp for wet leads.
   (We've had probe water-ingress drag a bus low; series R keeps a shorted
   probe from latching the GPIO.)
5. **RS-485:** TVS array (SM712) + 120 Ω termination behind a DIP switch.

## 5. Connectors

| Qty | Connector | Signal |
|---|---|---|
| 2 | 3-pos 3.5 mm screw terminal (Phoenix 1984617 style) | DS18B20 A / B: 3V3, DATA, GND |
| 1 | Panel BNC (isolated section) | pH electrode |
| 1 | 3-pos screw terminal (isolated GND ref) | pH temp-comp / spare isolated analog |
| 1 | 2-pos screw terminal | TDS probe |
| 2 | JST-SH 4-pin **Qwiic** | I²C pods: BH1750 (0x23/0x5C), AS7341 — buy Adafruit/SparkFun breakouts, no soldering |
| 4 | 2-pos 5.08 mm screw terminal (rated 10 A / 300 V) | Relay outputs (dry contacts / SSR outputs) |
| 2 | RJ45 (paralleled) | RS-485 expansion: A, B, GND, +12 V pass-through — daisy-chain boards tank-to-tank with ordinary Ethernet cable |
| 1 | 2.1 mm barrel jack + 2-pos screw terminal alt | 12 V DC in, reverse-polarity MOSFET |
| 2 | USB-C | S3 flashing/logs; C3 flashing/logs |
| 1 | 4-pos screw terminal | Spare GPIO2/GPIO4 + 3V3 + GND (float switches, leak sensor, etc.) |

Every terminal gets silkscreen labels **with the signal name and the firmware
GPIO** (e.g. "TEMP-A GPIO6"), and polarity marks.

## 6. Multi-tank / expansion story

- Each board is a complete single-tank node (its own Wi-Fi connection to HA/MQTT
  — this is how the repo works today, so board #2 on a second tank needs zero
  new firmware).
- The RS-485 bus is the *optional* tie: extra sensor-only boards (a board
  populated without relays/second ESP32 — make U2, K1–K4 DNP variants in flux)
  can report to a head unit where Wi-Fi is weak, and +12 V pass-through on the
  RJ45 pairs powers a remote pod up to ~10 m.
- DIP switch (4-pos) read on boot → node address 0–15, exposed to ESPHome.

## 7. What to type into flux.ai (step-by-step)

1. **New project** → "tank-monitor-carrier", 4-layer, 90 × 90 mm outline.
2. Search flux's part library and drop in: `ESP32-S3-WROOM-1`, `ESP32-C3-MINI-1`,
   `ADS1115IDGSR` ×2, `ADuM1250ARZ`, `B0303S-1WR2`, `THVD1450DR`, `TPS54331DR`
   (+ its inductor/diode/caps — accept flux's suggested reference design),
   `AP2112K-3.3TRG1` ×2, `LMP7721MA`, `USB4110-GF-A` ×2, `G3MC-202P` ×2,
   `HF115F/012-1ZS3` ×2, `PC817` ×2, screw terminals and Qwiic (`PRT-14417`)
   as above. Where flux lacks a part, import from SnapEDA/Ultra Librarian.
3. Use flux's **AI auto-connect prompts** per functional block, in this order,
   verifying each block's nets before the next: power tree → S3 core
   (strapping resistors, 10 kΩ EN pull-up + 1 µF, boot/reset buttons, USB) →
   C3 core → UART cross-link → I²C bus + pull-ups (2× 4.7 kΩ) → ADS1115s →
   pH AFE → relay drivers → RS-485 → terminals.
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
