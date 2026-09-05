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

### The TDS number is an hourly mean, and the mean is computed on the device

The analog TDS probe is honest about the trend and useless about any single
sample. Measured over a day of live data, the spread WITHIN one hour was a
median of 39 ppm and as much as 171 ppm — larger than any dose you would ever
make. That is what had this project explaining a "47 ppm overnight rise" that
was noise.

So the dashboard reads `sensor.tank_monitor_tds_1h_mean`. **That sensor is
computed on the ESP32, not here** — a 120-sample sliding window at 30 s,
republished every minute, defined in `packages/sensors.yaml`.

It was briefly an HA `statistics` helper instead, which was the wrong place.
A correction that only exists in Home Assistant is a correction the tank does
not have: the remote panel over ESP-NOW and the controller's own web page
would still have been showing the raw jittering value, and would have
disagreed with this dashboard by 15–40 ppm at any given moment. The same
argument applies to every calibration — see the note below.

The raw probe is still plotted on the Trends view underneath the mean,
deliberately: seeing the noise band around the mean is what stops the next
spike being read as an event.

### Calibration lives on the device, not here

Every probe correction — TDS K factor, pH two-point, temperature offset — is
a `restore_value` global on the ESP32, applied inside the sensor lambda
before anything is published. Home Assistant receives values that are already
correct; it is a consumer, not the correction.

The entities are exposed to HA for convenience, but the same controls exist
on the device's own web page at its IP address, which is what you use when
the broker is down or when you are standing at a sink with a wet probe. See
the root `README.md` for the procedure.

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
