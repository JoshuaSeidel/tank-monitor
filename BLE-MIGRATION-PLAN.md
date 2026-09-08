# Panel and link migration plan

**Rewritten 2026-09-04** after the phase 1 coexistence test failed and a
Waveshare ESP32-S3 1.75" round AMOLED was ordered to replace the CYD. The
earlier version of this plan assumed the CYD would carry two transports at
once. It cannot, and it no longer needs to.

---

## 1. The one rule everything follows

**No device ever runs three radios.**

That is the whole lesson of phase 1. WiFi + ESP-NOW + BLE together on the CYD
killed the ESP-NOW link and then the web server. Every arrangement below keeps
each device to two.

| Device | Radios | Ever three? |
|---|---|---|
| C6 controller | WiFi + ESP-NOW | no |
| CYD panel (today) | WiFi + ESP-NOW | no |
| AMOLED panel (phase A) | WiFi + ESP-NOW | no |
| AMOLED panel (phase B) | WiFi + BLE | no |
| S3 controller (phase B) | WiFi + BLE | no |

The awkward transitional state is gone because **the new panel is a new
device**. It does not have to become BLE on the same day the controller does.

---

## 2. Phases

### Phase A — AMOLED panel on ESP-NOW — **DONE, and now ended (2026-09-08)**

The new panel joined as a second display speaking the transport that already
worked: new board file, new round UI, `packages/remote_display.yaml`
unchanged, CYD untouched. It did its job — the round UI was built and
debugged against live data while no S3 controller existed.

It is over. `tank-monitor-amoled-remote.yaml` no longer loads
`remote_display.yaml` and **cannot be pointed at the C6**. The panel pairs
with the S3 and nothing else.

### Phase B — panel switches to BLE — **BUILT, not yet deployed**

Done:

- `packages/ble_link.yaml` — controller side. BLE server, one telemetry
  characteristic (notify, 5 s) and one command characteristic.
- `packages/ble_link_panel.yaml` — panel side. `ble_client`, notify
  subscription, checked parser, the same ids the board files already read.
- Payload is at **v2**: v1 omitted the controller's hourly TDS mean, so the
  panel would have shown the raw value while the CYD showed the mean. v1
  shipped but nothing ever consumed it, so there was no debt to carry.
- The panel's `HEATING 42%` became `HEATING` / `COOLING` / `IDLE`. They are
  relays; there is no throughput to throttle.

Still required before it works:

1. **The S3's BLE MAC.** `ble_client` addresses peers only by MAC — no name
   or service lookup. It is in the S3's boot log as `ESP-IDF BLE MAC
   address:`, and it is *not* the WiFi MAC. Set `s3_ble_mac` in the wrapper;
   the shipped value is intentionally invalid so the build stops until you do.
2. **The S3 has to be running.** It is the only board that speaks BLE. As of
   2026-09-08 its 54 entities are registered in HA and all unavailable.
3. **MTU is verified at runtime, not assumed.** The payload is ~115 bytes
   against BLE's 23-byte default. The parser counts fields and checks the
   version; a short read publishes nothing and logs `bad payload: N of 15
   fields -- MTU too small?`. If that appears in the panel log, MTU
   negotiation is the cause.

Known gap: **the round UI is read-only.** It has no setpoint stepper and no
learning switch, so nothing on the panel writes to the command
characteristic. The CYD can do both. That gap has to close before the CYD
retires, or retiring it loses function.

Still open from the original Phase B: the learned thermal model carrying
across via `tank-seed/<device>/model`, and C6 + CYD retiring together.

---

## 3. The round UI is a redesign, not a port

466 × 466 on a **circular** face. The CYD layout is a rectangular grid — a
header bar with radio icons at its ends, cards left and right, nav buttons
along the bottom. **On a circle every one of those corners is physically
absent.** None of it survives.

That constraint pushes the design where it should have gone anyway:

- ~44.5 mm across at 466 px is a **0.095 mm pitch**, roughly twice as fine
  as the CYD
- A centred temperature at ~45% of the diameter is about **20 mm tall**,
  against 11 mm on the C6 and ~8 mm on the CYD. **Smaller panel, bigger
  number**, because a round face has no room for furniture
- AMOLED contrast beats the CYD's TN panel at a glance and off-axis, which
  matters as much as size for reading across a room
- The arc gauge already built for the CYD home page — temperature arc,
  value in the centre, colour through the band — was always wanting to be
  round. That concept ports; its coordinates do not

**Build it with proportional positioning, not absolute pixels.** The current
layout is hard-coded to 320×240 and that is why this is a rewrite rather than
a resize. Doing it again the same way just moves the debt.

---

## 4. On arrival — verify before designing

1. **PSRAM.** The preset carries `requires={"psram"}`; the framebuffer is
   466×466×2 = **424 KB** and cannot live in internal RAM. Confirm the board
   is the S3**R8** variant.
2. **Touch controller.** Probably FT3168 or CST816, but that is a guess, and
   guesses have cost real time in this project. Read it off the board or its
   docs before writing config.
3. **Round-safe bounds.** Nothing drawn outside the inscribed circle. Corner
   coordinates that compile fine are simply invisible.

Preset facts already confirmed from ESPHome:
`WAVESHARE-ESP32-S3-TOUCH-AMOLED-1.75`, CO5300 controller, 466×466, 16-bit,
`offset_width: 6`, `cs_pin: 12`, `reset_pin: 39`.

---

## 5. Phase 1's result, and what it still means

Recorded so it is not re-learned: **WiFi + ESP-NOW + BLE on the CYD fails.**
The panel lost ESP-NOW, then stopped answering HTTP entirely, at
1100ms/100ms passive scanning — already the gentlest useful setting.

A follow-up test (commit `5e02610`) disables the ESP-NOW radio to isolate
whether BLE or the ESP-NOW pairing was at fault.

**That test is now informative rather than blocking.** Under this plan no
device ever runs BLE and ESP-NOW together, so its answer no longer gates
anything. It is still worth knowing — a clean WiFi + BLE result on 2016
silicon makes phase B near-certain on the S3 — but the CYD can be reverted to
its working ESP-NOW build at any time without holding the plan up.

---

## 6. Still open

- Whether the S3 controller is the XIAO ESP32-S3 or the WROOM-32. Both
  measured and both fit; the XIAO has far more headroom, the WROOM-32 more
  GPIO and is already in hand.
- Whether to add an ADS1115 for pH, and a small OLED so the controller is
  not blind. Both should be decided **before** the controller board file is
  written rather than bolted on after.
