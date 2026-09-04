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

### Phase A — build the AMOLED panel on ESP-NOW

The new panel joins as a **second** display speaking the transport that
already works. Nothing else changes.

- New board file, new round UI (see §3)
- Reuses `packages/remote_display.yaml` **unchanged** — the ESP-NOW receive
  path, the cached globals, `Link Age`, `Link Source`
- **The CYD is untouched and keeps working.** Two panels showing the same
  tank, which is genuinely useful while the new UI is being built
- No controller change. No BLE. No new failure mode

This is the phase that can start the day the board arrives.

### Phase B — S3 controller, panel switches to BLE, CYD retires

- Build the S3 controller (XIAO ESP32-S3, measured at 33.7% flash with BLE)
- Panel swaps ESP-NOW for BLE **in one flash** — it never runs both
- Learned thermal model carries across via the existing
  `tank-seed/<device>/model` path
- C6 and CYD retire together

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
