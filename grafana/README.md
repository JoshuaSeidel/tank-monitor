# Grafana

Dashboard for the tank, querying InfluxDB 3 directly.

## 1. Add the datasource

In Grafana: **Connections → Add new connection → InfluxDB**.

| Field | Value |
|---|---|
| Query language | **SQL** |
| URL | `http://<home-assistant-ip>:8181` |
| Database | `homeassistant` |
| Token | your InfluxDB 3 API token |

Use the Home Assistant host's **IP address**, not `32b8266a-influxdb3` — that
hostname only resolves inside HA's container network, and Grafana is on
another box. Port 8181 is published on the HA host.

**Plain `http`, not `https`.** The App's config says `ssl: true`, but its
certificate files don't exist, so it serves plaintext. Pointing TLS at it
fails with `WRONG_VERSION_NUMBER`.

SQL, not InfluxQL or Flux: InfluxDB 3 is natively SQL, and Flux is not
supported at all on v3.

## 2. Import the dashboard

**Dashboards → New → Import → Upload JSON file** →
`tank-monitor-dashboard.json`, then pick the InfluxDB datasource when
prompted.

## How the data is shaped

The Home Assistant InfluxDB integration writes one **table per unit of
measurement**, not per entity:

| Table | Holds |
|---|---|
| `°F` | every Fahrenheit sensor in your house |
| `ppm` | TDS |
| `μS/cm` | conductivity |
| `%` | heater duty, fan duty, model confidence |
| `lx` | light level |

Each row carries `entity_id`, `domain`, `friendly_name`, and `value`. So every
query filters by `entity_id`, e.g.:

```sql
SELECT time, value FROM "°F"
WHERE entity_id = 'tank_monitor_water_temperature_f'
  AND $__timeFilter(time)
ORDER BY time
```

Note `entity_id` here is the **object id** — `tank_monitor_tds`, not
`sensor.tank_monitor_tds`.

## The panel that matters

**Temperature Swing (1h)** is the one to watch. It's peak-to-peak movement
over a rolling hour, computed on the ESP32. Starting around 3 °F and falling
toward 0.3 °F is the whole point of the build — the other panels explain
*why* it moved, but this one says whether it worked.

Give it a day before judging: the thermal model needs roughly that long to
train, which `Model Confidence` tracks.
