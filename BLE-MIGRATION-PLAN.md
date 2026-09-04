# BLE link migration plan

Goal: move the controller↔panel link from ESP-NOW to BLE, because ESP-NOW rides
the WiFi channel and loses it during exactly the outage the link exists to survive.
The CYD must speak **both** during the transition, so the existing C6 keeps working
until it is replaced.

Status: **plan only. Nothing built.**

---

## 1. Why BLE at all

ESP-NOW inherits the WiFi station channel. When the AP goes down, an ESPHome device
scans across channels to reconnect and ESP-NOW packets sent meanwhile are lost.

There is **no config-level fix**. ESPHome's own schema:

```python
cv.OnlyWithout(CONF_CHANNEL, CONF_WIFI): validate_channel
```

The ESP-NOW `channel:` option is only accepted on a device with **no WiFi component
at all**. Both boards need WiFi. So the channel cannot be pinned independently.

BLE has its own channel hopping and no dependency on the AP. Caveat worth keeping
in view: ESP32 WiFi and BLE **share one radio** and time-slice — BLE is not on
separate hardware. It is immune to the AP's channel, not to WiFi contention.

---

## 2. Measured feasibility

Every figure below is a real compile of this firmware, not an estimate.

| Board | Role | Transport | Flash | RAM |
|---|---|---|---|---|
| C6 | controller | ESP-NOW | 68.9% | 35.7% |
| C6 | controller | **+ BLE** | **97.8%** ❌ | 44.2% |
| WROOM-32 | controller | BLE | **73.9%** ✅ | 60.7% |
| **XIAO ESP32-S3** | controller | BLE | **33.7%** ✅ | 41.9% |
| CYD | panel | ESP-NOW | 69.1% | 31.6% |
| **CYD** | panel | **BLE + ESP-NOW** | **90.7%** ✅ | 64.7% |

Three things follow:

- **The C6 cannot take BLE.** 40 KB spare. It stays ESP-NOW for its remaining life,
  and is never reflashed for this work.
- **The CYD can carry both transports.** 90.7% flash — that figure already includes
  ESP-NOW, LVGL, the web UI and the chemistry mirror.
- **On WROOM-32 and CYD the binding constraint is RAM, not flash.** BLE reserves
  DRAM pools, cutting reportable RAM to ~124 KB total. Both land near 60–65% of it,
  so roughly 45 KB free. Watch this more closely than the flash bar.

The XIAO figure omits the web UI and ESP-NOW packages and carries no display fonts;
adding those is about one point on its 3.93 MB partition.

---

## 3. Link design

### One characteristic, not thirteen

The ESP-NOW link currently carries ~13 values. The obvious BLE translation is 13
characteristics. **Don't.**

- **Telemetry, controller → panel:** ONE notify characteristic carrying a compact
  delimited payload. The panel parses it in a lambda.
- **Commands, panel → controller:** ONE write characteristic, carrying the existing
  tiny text protocol unchanged (`SP <degF>`, `AL 0|1`).

Every lens agrees on this one. Fewer characteristics is less flash and less config;
a single payload is an **atomic snapshot**, where 13 independent characteristics
would let the panel show temperature from one moment beside TDS from three seconds
later; one payload has one age, which is better provenance; and a delimited string
is readable in a log where a UUID is not. It also matches the command protocol's
existing design rationale — text, so a firmware version skew between boards
degrades gracefully instead of misparsing a struct.

### Dual transport on the panel is additive, not a rewrite

The panel already caches every received value into a `restore_value` global with an
arrival timestamp, and the display reads the **globals**, never the transport. So a
second transport writes into the same globals and the entire LVGL layer is untouched.

- `Link Age` becomes age of the newest update from **either** transport.
- Add a `Link Source` text sensor — `espnow` / `ble` / `none`.
- Commands go out on whichever transport is currently live, decided by `Link Source`.

---

## 4. Phases

Each phase leaves a working tank.

| Phase | Change | C6 touched? |
|---|---|---|
| **0** | Today: C6 ↔ CYD over ESP-NOW | — |
| **1** | Add BLE client to the CYD **alongside** ESP-NOW. No peer yet, so it idles. Confirm nothing regresses | No |
| **2** | Build the new controller (XIAO S3 preferred, WROOM-32 viable) with BLE server. Bench it. Panel now has a live BLE peer **and** its ESP-NOW link to the C6 | No |
| **3** | Move probes and relays to the new controller. Seed the learned thermal model across via the existing `tank-seed/<device>/model` path. Retire the C6 | Retired |
| **4** | Optionally drop ESP-NOW from the CYD and recover the flash and RAM | — |

**Phase 1 is the only one that must come first.** 2 and 3 can wait for hardware.

---

## 5. Open risks — verify before building, not after

1. **Runtime coexistence.** WiFi + ESP-NOW + BLE all share one 2.4 GHz radio on the
   CYD. They *compile* together; that is not evidence they *work* together. This
   needs a bench test in phase 1 and is the single largest unknown.
2. **Payload length vs MTU.** Default BLE MTU is 23 bytes. A 13-value delimited
   payload is ~100. Needs MTU negotiation or a longer characteristic; confirm what
   ESPHome's `max_length` actually permits before committing to one characteristic.
3. **Reconnect behaviour.** Does `ble_client` re-establish cleanly after the
   controller reboots, without a panel restart? Untested.
4. **S3 ADC quality.** Not a BLE issue but it lands in the same build: the S3's
   internal ADC is likely not good enough for a ~100 MΩ pH electrode at ±0.1. An
   **ADS1115** on the existing I²C bus is the answer, and it should be decided
   *before* the board file is written, not bolted on after.
5. **Headless controller.** Neither the XIAO nor the WROOM-32 has a screen. The C6's
   display is currently the last readout standing when WiFi, HA and the panel are all
   down. A small I²C OLED restores that for a few dollars — decide in phase 2.

---

## 6. Provisional XIAO ESP32-S3 pin map

From the compiled probe build. ADC1 on the S3 is GPIO1–10 and the XIAO exposes
GPIO1–9, so **every broken-out pin is ADC-capable** — the opposite of the C6, where
GPIO0 was the last analog pin left.

| Function | Pin | Note |
|---|---|---|
| TDS | GPIO1 (A0) | ADC1 |
| pH | GPIO2 (A1) | ADC1 — or move to ADS1115, see risk 4 |
| DS18B20 | GPIO3 | 4.7 kΩ pull-up to 3V3 |
| I²C SDA / SCL | GPIO5 / GPIO6 | BH1750, plus ADS1115 and OLED if adopted |
| Heater relay | GPIO7 | |
| Fan relay | GPIO8 | |
| **Spare** | GPIO4, GPIO9 | both ADC1 — ORP fits here |

---

## 7. Not decided here

- XIAO ESP32-S3 vs WROOM-32 as the replacement controller. Both work; the XIAO has
  far more headroom, the WROOM-32 has more GPIO and is already in hand.
- Whether to add the ADS1115 and the OLED.
- Whether phase 4 ever happens, or the CYD keeps ESP-NOW permanently as a fallback.
