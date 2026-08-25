# Home Assistant

## Aquarium dashboard

Live at **Settings → Dashboards → Aquarium**, or `/aquarium-tank`.
`aquarium-dashboard.json` is the config, kept here for version control.

Three views:

| View | Purpose |
|---|---|
| **Tank** | Live state — temperature, controller, water quality, health |
| **Manual tests** | Type test-kit results, press one button to log them |
| **Trends** | History: is the swing actually falling? |

### The probe cross-check

The Tank view compares the ESP32's DS18B20 against the Seneye's own
temperature probe. Two independent sensors in the same water should agree;
when they don't, one has drifted or failed.

- **≤ 0.5 °F apart** — agree
- **0.5–1.5 °F** — drifting
- **> 1.5 °F** — one has failed

This matters more than it looks: the controller drives the heater from the
DS18B20 alone. If that probe reads low, the controller happily cooks the
tank while reporting the target. The Seneye is the only independent check
on it.

### Manual entry

Uses the existing `input_number.aquarium_*` helpers and
`script.aquarium_log_manual_test` rather than duplicating them. GH and KH
have no hobby-grade probe, so they stay test-kit values — the Tank view's
target table reads them from the `*_log` sensors so they sit alongside the
measured parameters.

### Rebuilding

`aquarium-dashboard.json` is the source of truth here; the dashboard was
created from it via the HA config API, not hand-edited in the UI. If you
edit it in the UI, export it back to this file.
