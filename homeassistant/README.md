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

### No probe cross-check any more

There used to be one here: the ESP32's DS18B20 was compared against a Seneye
Reef/Pond monitor, on the principle that two sensors in the same water should
agree. That monitor was returned on 2026-09-04 after its pH proved ~0.45 LOW
against an API liquid test — it had this project chasing a CO2 crisis and then
a KH crash, neither of which was real.

**So there is no second sensor now, and the gap is worth stating plainly:**
the controller drives the heater from the DS18B20 alone. If that probe reads
low, the controller will happily cook the tank while reporting the target, and
nothing in Home Assistant will notice. Check it against a reference
thermometer occasionally, by hand.

The lesson generalises past this one device. A continuous reading that cannot
be calibrated is not more trustworthy than an intermittent one that can — it
is less, because it is wrong more often and more confidently. That is why pH
is moving to a DFRobot glass electrode on the controller: it can be stood in
pH 7.00 buffer and proven right.

### The TDS number is an hourly mean, not a reading

The analog TDS probe is honest about the trend and useless about any single
sample. Measured over a day of live data, the within-hour spread was a median
of 39 ppm and as much as 171 ppm — so two readings taken minutes apart can
differ by more than any dose you would ever make. That is what had this
project explaining a "47 ppm overnight rise" that was noise.

So the dashboard reads `sensor.tank_monitor_tank_tds_hourly_mean` — a built-in
**statistics** helper over `sensor.tank_monitor_tds`, `state_characteristic:
mean`, `max_age: 1h`, `sampling_size: 500`, `keep_last_sample: true`. The raw
probe is still plotted on the Trends view underneath it, deliberately: seeing
the noise band around the mean is what stops anyone reading a spike as an
event.

Recreate it before importing the dashboard on a fresh install — the cards
reference it by entity id and will show "Entity not available" without it.

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
