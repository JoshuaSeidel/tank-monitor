# Tank MCP

An MCP server for the aquarium, running as a Home Assistant App. It gives an
AI assistant a set of tools for the tank specifically -- read the controller
and the Seneye, type in a test-kit result, keep a record of fish and shrimp
that have died, and say any of it out loud on an Echo.

It is not a general Home Assistant bridge. Every tool answers a tank question,
and answers it with a verdict attached: not "pH 7.33" but "pH 7.33, in range".

## Install

1. **Settings -> Apps -> Store -> ⋮ -> Repositories**, add
   `https://github.com/JoshuaSeidel/tank-monitor`.
2. Install **Tank MCP** from the store and start it.
3. Open the log. On first start it mints an API token and prints it:

   ```
   Tank MCP listening on http://0.0.0.0:8099/mcp
   API token: 3Qv…
   ```

   Copy that into your MCP client. To set your own instead, put it in the
   app's `api_token` option and restart.

The app talks to Home Assistant through the Supervisor proxy, so there is no
long-lived access token to create. It picks up the Mosquitto broker the same
way.

## Options

| Option | Default | What it does |
|---|---|---|
| `api_token` | *(generated)* | Bearer token MCP clients must send. Left empty, one is generated into `/data/api_token` and logged. |
| `device` | `tank_monitor` | Which controller the tools read and command — `tank_monitor` or `tank_monitor_v2`. |
| `seneye_prefix` | `seneye_spec_16` | Object-id prefix of the Seneye sensors. |
| `default_echo` | `media_player.office` | Echo used by `announce` when no target is given. |
| `publish_livestock_to_mqtt` | `true` | Mirror the livestock ledger into Home Assistant as sensors. |
| `log_level` | `info` | |

## Connecting a client

The endpoint is streamable HTTP at `http://<home-assistant-ip>:8099/mcp`,
with `Authorization: Bearer <api_token>`.

Claude Code:

```bash
claude mcp add --transport http tank \
  http://192.168.6.4:8099/mcp \
  --header "Authorization: Bearer <api_token>"
```

`GET /health` is unauthenticated and returns `ok`, for an uptime check.

## Tools

**Reading**

| Tool | Answers |
|---|---|
| `tank_report` | "How is the tank?" — everything, plus a ranked list of what is wrong. Start here. |
| `tank_status` | Temperature against setpoint, heater and fan duty, TDS, faults, probe cross-check. |
| `water_chemistry` | Every chemistry value with a verdict; GH/KH in both degrees and ppm. |
| `seneye_status` | Seneye readings, how stale they are, slide expiry. |
| `metric_history` | Min/max/mean of one metric over N hours. |
| `water_test_history` | Past manual tests recorded through this app. |

**Writing**

| Tool | Does |
|---|---|
| `log_water_test` | Writes the `input_number.aquarium_*` helpers, runs the existing log script, keeps its own copy. Accepts GH/KH as ppm *or* degrees. |
| `set_target_temperature` | Moves the setpoint. Refused outside 68–82 °F. |

**Livestock**

| Tool | Does |
|---|---|
| `add_livestock` | Records stock going in. |
| `log_loss` | Records a death, with a cause and a date. |
| `livestock_inventory` | What is alive, per species. |
| `loss_history` | Losses over N days, per species, with a per-week rate. |
| `stocking_history` | Every stocking event. |
| `delete_loss` | Undoes a mistaken entry. |

Species names are folded onto a canonical key, so "kuhlis", "Kuhli Loaches"
and "kuhli loach" all land on the same species rather than three.

**Alexa**

| Tool | Does |
|---|---|
| `announce` | Says arbitrary text on an Echo. |
| `speak_tank_report` | Says the current tank status. |
| `speak_livestock_report` | Says the inventory and recent losses. |
| `list_echo_speakers` | Lists usable targets. |

## Alexa

Two directions, and they work differently.

**Alexa tells you** — the `announce` and `speak_*` tools push through
`notify.alexa_media`, so an assistant can speak on any Echo on demand. Nothing
to set up beyond Alexa Media Player, which is already installed.

**You ask Alexa** — Alexa cannot call MCP, so the ask path is pure Home
Assistant. `script.aquarium_speak_status` builds the same spoken report from
Home Assistant state and announces it. To wire it to a phrase:

1. **Settings -> Home Assistant Cloud -> Alexa** and expose
   *Aquarium: speak status*. It appears to Alexa as a scene.
2. In the Alexa app: **More -> Routines -> +**, "When you say" →
   `tank report`, "Add action" → Smart Home → *Aquarium: speak status*.

Then "Alexa, tank report" gets the tank spoken back. The livestock lines in
that report come from the sensors below, so they appear once this app has run
at least once.

Water temperature is separately worth exposing to Alexa directly: it is a
native temperature sensor, so "Alexa, what's the tank temperature?" works with
no routine at all.

## What it publishes back to Home Assistant

With MQTT available, the ledger appears as real entities under an *Aquarium
Livestock* device — so dashboards and the spoken report can use them without
going through MCP:

- `sensor.aquarium_livestock_total`
- `sensor.aquarium_livestock_losses_7d`
- `sensor.aquarium_livestock_losses_30d`
- `sensor.aquarium_livestock_last_loss`
- `sensor.aquarium_livestock_days_since_loss`

Each carries the full per-species breakdown as attributes. All retained, so
they survive a broker restart.

## Data

The ledger is SQLite at `/data/tank.db` inside the app, which means it
survives restarts and updates and is included in Home Assistant backups.
Manual test values are *also* written to the existing Home Assistant helpers,
so the dashboard, the logbook entry, and the ESP32's own chemistry panel all
stay in sync — this app adds a record, it does not replace theirs.

## Thresholds

The verdicts are not generic. They are set for this tank's stock — soft-water
tetras, scaleless kuhli loaches, blue-eyes, and Neocaridina shrimp:

- Cold floor 73.4 °F, matching the ESP32's blue band and the Home Assistant
  cold-floor alarm.
- On-target means within 0.5 °F of the setpoint.
- Free ammonia: elevated at 0.02 mg/L, toxic at 0.05 (Seneye's own bands).
- pH 6.5–7.8.
- Nitrate good below 20 ppm, water change due above 40.
- GH and KH are read from the `input_number.aquarium_*_target_*` helpers
  rather than hard-coded, so moving the target moves the verdict.

They live in `tankmcp/entities.py`.

## Tests

`tests/smoke_test.py` runs the real server against a stand-in Home Assistant
and drives it through a real MCP client — auth, every tool, the unit
conversions, the alias folding, and the refusals:

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python tests/smoke_test.py
```
