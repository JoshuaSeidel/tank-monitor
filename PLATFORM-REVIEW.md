# Platform review — 2026-09-04

Written after four unit-mislabel bugs surfaced in a single day. None of them were
new; all four had existed for weeks, and each had survived a previous "fix" that
touched one representation of the value and left the others alone.

This document is the holistic pass. It is deliberately not a patch list.

---

## 1. The structural problem

**A single quantity is represented in up to eleven places, and nothing checks that
they agree.** GH is the worst case:

| # | Surface | What it holds |
|---|---|---|
| 1 | `input_number.aquarium_gh` | the value |
| 2 | `input_number.aquarium_gh_target_min` / `_max` | the target band |
| 3 | `sensor.aquarium_gh_log` | a template sensor with its own unit attribute |
| 4 | dashboard-modern → Aquarium, section 2 card 13 | verdict logic + unit label |
| 5 | dashboard-modern → Aquarium, section 6 card 4 | the saved-test summary |
| 6 | `/aquarium-tank` Tank view | targets table |
| 7 | `homeassistant/aquarium-dashboard.json` | a hand-maintained repo snapshot |
| 8 | `tank-mcp/tankmcp/entities.py` | `MANUAL` and `TARGETS` maps |
| 9 | `tank-mcp/tankmcp/readings.py` | verdict + unit conversion |
| 10 | `script.aquarium_log_manual_test` | the permanent logbook line |
| 11 | `packages/chemistry.yaml` + board files | MQTT mirror to the ESP32 panel |

Changing the unit in one place changes nothing anywhere else, and **no surface
declares its unit in a way another surface can read**. The unit lives in a display
attribute (invisible to templates), in prose, and in Python string keys.

That is why patching kept producing the next bug.

---

## 2. Findings

Severity is about **how wrong a decision it can cause**, not how ugly it is.

### 🔴 Live and wrong

**F1 — A dashboard card still instructs entering degrees.**
`dashboard-modern` → Aquarium, section 2 card 13 reads *"Enter them below in **dGH /
dKH**, not the ppm printed on test strips — divide the strip's ppm by 17.9"* and
renders `GH {{ gh }} dGH`. The helper is ppm. Following that card's instruction
today would enter a value ~18× too small into a ppm field. This card was missed by
every pass so far, including today's.

**F2 — The compiled temperature setpoint is 76.0 °F.**
`packages/base.yaml` `target_temp_f: "76.0"` → `packages/control.yaml`
`setpoint: ${target_temp_f}`. The live value is 74.0 and survives because the number
entity has `restore_value: true`. **A fresh flash, or any board whose NVS is cleared,
boots the tank at 76 °F** — 2 °F above where it should be, with shrimp in it.

**F3 — Two different cold floors.**
`tank-mcp` `TEMP_COLD_FLOOR_F = 73.4` vs the Home Assistant alarm's 73.0. The spoken
report says "below the cold floor for the loaches" at a temperature the alarm does
not consider cold.

### 🟠 Disagreeing, consequence bounded

**F4 — Four different pH upper bounds.**
`aquarium_ph_out_of_range` says 8.0 · `tank-mcp` `PH_MAX` says 7.8 · the targets card
says 7.5 · nothing reads a helper. The *lower* bounds (7.0 cutoff, 6.8 alarm) are
deliberate tiering and are fine; the upper bounds are drift.

**F5 — Only GH and KH have target helpers.**
Nitrate, nitrite, ammonia and pH bands are hard-coded in the MCP app, the automations
and the dashboard cards independently. There is no single place to change "what good
looks like" for four of the six chemistry values.

**F6 — `homeassistant/aquarium-dashboard.json` is a hand-maintained duplicate.**
It has been edited separately from the live dashboard twice today. It will drift
again; it is a snapshot pretending to be a source.

### 🟡 Known, accepted, or already tracked

**F7 — `tds_k_factor: "1.0"`.** The TDS probe has never been calibrated. Tracked on
the new Sensor verification card; the 342 ppm / 700 µS standard is on order.

**F8 — No second temperature probe.** Accepted deliberately after the Seneye was
returned. Recorded in `homeassistant/README.md` and the alarm's own description.

**F9 — `PPM_PER_DEGREE = 17.9` survives in `tank-mcp`.** Now used only to *derive*
a degrees figure for display, which is correct — but it is the constant that caused
the ×18 bug and deserves the comment it now has.

---

## 3. Target architecture

Three rules, in priority order.

### Rule 1 — The unit belongs in the identifier, not an attribute

`input_number.aquarium_kh_ppm`, not `input_number.aquarium_kh` with a `ppm` unit
attribute. A template that reads the wrong thing then *looks* wrong at every call
site, in every surface, without running anything.

This is the only change that makes the class of bug visible rather than latent.

### Rule 2 — One source of truth per quantity, read everywhere else

Every band gets a helper, and every consumer reads it. No hard-coded thresholds in
dashboard cards, MCP constants or automation triggers where a helper could be read.

The exception worth keeping: **deliberate tiering.** The CO2 cutoff at 7.0 and the
alarm at 6.8 are supposed to differ. Tiering should be expressed as an offset from
the helper, not as a second independent number.

### Rule 3 — Generated artifacts are generated, not hand-edited

`homeassistant/aquarium-dashboard.json` should be exported from the live dashboard by
a script, never edited directly. Otherwise it is a third copy of the truth.

---

## 4. Migration order

Sequenced so each step leaves the system working.

| Step | Change | Why this order |
|---|---|---|
| 1 | Fix **F1** and **F2** | Both can cause a wrong action today; neither depends on the rest |
| 2 | Add target helpers for pH, nitrate, nitrite, ammonia | Creates the sources of truth Rule 2 needs |
| 3 | Repoint every consumer at the helpers (cards, MCP, automations) | Removes the hard-coded copies |
| 4 | Rename GH/KH/TDS helpers to `_ppm` | The big one. Do it *after* step 3 so there are fewer consumers to update |
| 5 | Reconcile F3 and F4 to single values | Trivial once the helpers exist |
| 6 | Replace the dashboard JSON snapshot with an export script | Stops the duplicate re-forming |

**Step 4 is the rename that was started and stopped.** Nothing was written; the
consumer search is in the session log. It is deliberately sequenced last because
doing it first means renaming entities that a dozen hard-coded card templates still
reference.

---

## 5. What this review does not cover

- The ESPHome control loop and learning model, reviewed separately on 2026-09-03
- `tank-mcp`'s livestock ledger
- Grafana dashboards in `grafana/`
- Whether the KH *target* should be 54–72 ppm or 90–125 ppm. That is a fishkeeping
  decision, not an architecture one, and it is still open.
