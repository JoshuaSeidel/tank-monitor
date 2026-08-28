"""The MCP tool surface for the aquarium."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import entities as E
from . import readings, speech
from .config import Config
from .ha import HomeAssistant
from .mqtt import LivestockPublisher
from .store import Store, normalise_species

_LOGGER = logging.getLogger(__name__)

# Friendly names for metric_history, so callers do not have to know entity ids.
HISTORY_METRICS = {
    "temperature": "temperature",
    "target": "target_temperature",
    "tds": "tds",
    "conductivity": "conductivity",
    "light": "light",
    "heater_duty": "heater_output",
    "fan_duty": "fan_output",
    "swing": "swing_1h",
    "model_confidence": "model_confidence",
}

# A heater on a 45 litre tank of shrimp and scaleless loaches can kill in a
# few hours. Refuse setpoints outside a range no keeper would ask for.
TARGET_MIN_F = 68.0
TARGET_MAX_F = 82.0


class TankServer:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.ha = HomeAssistant(cfg.ha_url, cfg.ha_token)
        self.store = Store(cfg.db_path)
        self.tank = E.TankEntities(cfg.device)
        self.seneye = E.SeneyeEntities(cfg.seneye_prefix)
        self.publisher: LivestockPublisher | None = None
        if cfg.mqtt_enabled:
            self.publisher = LivestockPublisher(
                cfg.mqtt_host, cfg.mqtt_port, cfg.mqtt_user, cfg.mqtt_password
            )
        self.mcp = FastMCP("tank-monitor", host="0.0.0.0", port=cfg.port)
        self._register()

    # --- lifecycle -------------------------------------------------------

    def start(self) -> None:
        if self.publisher:
            self.publisher.start()
            self.publisher.publish(self.livestock_summary())

    async def aclose(self) -> None:
        if self.publisher:
            self.publisher.stop()
        self.store.close()
        await self.ha.aclose()

    # --- shared helpers --------------------------------------------------

    def livestock_summary(self) -> dict[str, Any]:
        inventory = self.store.inventory()
        today = date.today()
        cutoff_7 = (today - timedelta(days=7)).isoformat()
        cutoff_30 = (today - timedelta(days=30)).isoformat()

        last = self.store.last_loss()
        last_on = last["occurred_on"] if last else None
        days_since = (today - date.fromisoformat(last_on)).days if last_on else None

        return {
            "total_alive": sum(item.alive for item in inventory),
            "total_added": sum(item.added for item in inventory),
            "total_lost": sum(item.lost for item in inventory),
            "species": {item.species: item.alive for item in inventory if item.alive},
            "losses_7d": sum(row["count"] for row in self.store.losses(since=cutoff_7)),
            "losses_30d": sum(row["count"] for row in self.store.losses(since=cutoff_30)),
            "last_loss_on": last_on,
            "last_loss_species": last["species"] if last else None,
            "last_loss_cause": last["cause"] if last else None,
            "days_since_loss": days_since,
        }

    def _publish_livestock(self) -> dict[str, Any]:
        summary = self.livestock_summary()
        if self.publisher:
            self.publisher.publish(summary)
        return summary

    async def _announce(self, message: str, target: str | None) -> dict[str, Any]:
        speaker = (target or self.cfg.default_echo).strip()
        if not speaker:
            raise ValueError("No Echo given and no default_echo configured for this app.")
        await self.ha.call(
            "notify",
            "alexa_media",
            {"target": [speaker], "message": message, "data": {"type": "announce"}},
        )
        return {"spoken_on": speaker, "message": message}

    # --- tools -----------------------------------------------------------

    def _register(self) -> None:
        mcp = self.mcp

        @mcp.tool()
        async def tank_status() -> dict[str, Any]:
            """Live state of the aquarium controller.

            Water temperature against setpoint, what the heater and fan are
            doing, TDS and conductivity, light level, controller faults, and a
            cross-check of the controller's probe against the Seneye's.
            Temperatures are Fahrenheit.
            """
            return await readings.tank_status(self.ha, self.tank, self.seneye)

        @mcp.tool()
        async def water_chemistry() -> dict[str, Any]:
            """Every chemistry value the tank has, with a verdict on each.

            pH and free ammonia come from the Seneye. Total ammonia, nitrite,
            nitrate, GH, KH and TDS come from the last test kit entry. GH and
            KH are given in both degrees and ppm, and each is judged against
            the target range configured in Home Assistant.
            """
            return await readings.water_chemistry(self.ha, self.seneye)

        @mcp.tool()
        async def seneye_status() -> dict[str, Any]:
            """Seneye monitor readings, how stale they are, and slide expiry."""
            return await readings.seneye_status(self.ha, self.seneye)

        @mcp.tool()
        async def tank_report() -> dict[str, Any]:
            """One call answering "how is the tank?".

            Controller state, chemistry, livestock, and a ranked list of
            anything currently wrong. Use this rather than three separate
            calls when the question is general.
            """
            status = await readings.tank_status(self.ha, self.tank, self.seneye)
            chemistry = await readings.water_chemistry(self.ha, self.seneye)
            seneye = await readings.seneye_status(self.ha, self.seneye)
            problems = readings.concerns(status, chemistry, seneye)
            return {
                "healthy": not problems,
                "concerns": problems,
                "tank": status,
                "chemistry": chemistry,
                "seneye": seneye,
                "livestock": self.livestock_summary(),
                "spoken_summary": speech.tank_report(status, chemistry, seneye, problems),
            }

        @mcp.tool()
        async def metric_history(metric: str, hours: float = 24.0) -> dict[str, Any]:
            """History for one controller metric over the last N hours.

            Valid metrics: temperature, target, tds, conductivity, light,
            heater_duty, fan_duty, swing, model_confidence. Returns min, max,
            mean, first and last, plus the raw samples.
            """
            key = metric.strip().lower()
            if key not in HISTORY_METRICS:
                raise ValueError(
                    f"Unknown metric '{metric}'. Choose one of: "
                    + ", ".join(sorted(HISTORY_METRICS))
                )
            if hours <= 0 or hours > 24 * 90:
                raise ValueError("hours must be between 0 and 2160 (90 days)")

            entity_id = getattr(self.tank, HISTORY_METRICS[key])
            rows = await self.ha.history(entity_id, hours)

            samples: list[dict[str, Any]] = []
            for row in rows:
                raw = row.get("state")
                if raw in ("unknown", "unavailable", None, ""):
                    continue
                try:
                    value = float(raw)
                except ValueError:
                    continue
                samples.append(
                    {"at": row.get("last_changed") or row.get("last_updated"), "value": value}
                )

            if not samples:
                return {
                    "metric": key,
                    "entity_id": entity_id,
                    "hours": hours,
                    "samples": [],
                    "note": "No recorded values in that window.",
                }

            values = [s["value"] for s in samples]
            return {
                "metric": key,
                "entity_id": entity_id,
                "hours": hours,
                "count": len(values),
                "min": round(min(values), 3),
                "max": round(max(values), 3),
                "mean": round(sum(values) / len(values), 3),
                "range": round(max(values) - min(values), 3),
                "first": samples[0],
                "last": samples[-1],
                "samples": samples,
            }

        @mcp.tool()
        async def log_water_test(
            total_ammonia_ppm: float | None = None,
            nitrite_ppm: float | None = None,
            nitrate_ppm: float | None = None,
            gh_ppm: float | None = None,
            kh_ppm: float | None = None,
            gh_degrees: float | None = None,
            kh_degrees: float | None = None,
            tds_ppm: float | None = None,
            ph: float | None = None,
            notes: str | None = None,
        ) -> dict[str, Any]:
            """Record a manual test-kit or test-strip result.

            Writes the Home Assistant helpers the dashboard and the ESP32
            panel already read, stamps the test time, and keeps its own copy
            in the app's ledger. Only the values you pass are changed; the
            rest keep their previous reading.

            GH and KH accept either ppm (what test strips print) or degrees
            (what the Home Assistant target ranges use) -- give one or the
            other, not both.
            """
            if gh_ppm is not None and gh_degrees is not None:
                raise ValueError("Give GH as ppm or degrees, not both.")
            if kh_ppm is not None and kh_degrees is not None:
                raise ValueError("Give KH as ppm or degrees, not both.")

            gh = gh_degrees
            if gh is None and gh_ppm is not None:
                gh = round(gh_ppm / E.PPM_PER_DEGREE, 1)
            kh = kh_degrees
            if kh is None and kh_ppm is not None:
                kh = round(kh_ppm / E.PPM_PER_DEGREE, 1)

            writes = {
                "total_ammonia": total_ammonia_ppm,
                "nitrite": nitrite_ppm,
                "nitrate": nitrate_ppm,
                "gh": gh,
                "kh": kh,
                "tds": tds_ppm,
                "ph": ph,
            }
            written = {k: v for k, v in writes.items() if v is not None}
            if not written:
                raise ValueError("Pass at least one reading to record.")

            for key, value in written.items():
                await self.ha.call(
                    "input_number",
                    "set_value",
                    {"entity_id": E.MANUAL[key], "value": value},
                )

            # The existing script stamps the time, writes the permanent
            # logbook entry and raises the on-screen confirmation.
            await self.ha.call("script", "turn_on", {"entity_id": E.LOG_TEST_SCRIPT})

            tested_at = datetime.now().isoformat(timespec="seconds")
            row_id = self.store.record_water_test(
                tested_at,
                {
                    "total_ammonia": total_ammonia_ppm,
                    "nitrite": nitrite_ppm,
                    "nitrate": nitrate_ppm,
                    "gh_dgh": gh,
                    "kh_dkh": kh,
                    "tds_ppm": tds_ppm,
                    "ph": ph,
                },
                notes,
            )

            return {
                "recorded_at": tested_at,
                "ledger_id": row_id,
                "written": written,
                "unchanged": [k for k in writes if k not in written],
                "chemistry_now": await readings.water_chemistry(self.ha, self.seneye),
            }

        @mcp.tool()
        async def water_test_history(limit: int = 10) -> list[dict[str, Any]]:
            """Past manual test results recorded through this app, newest first."""
            return self.store.water_tests(max(1, min(limit, 200)))

        @mcp.tool()
        async def set_target_temperature(fahrenheit: float) -> dict[str, Any]:
            """Change the controller's temperature setpoint, in Fahrenheit.

            The control loop runs on the ESP32, so this survives Home
            Assistant restarting. Refused outside 68-82 F.
            """
            if not TARGET_MIN_F <= fahrenheit <= TARGET_MAX_F:
                raise ValueError(
                    f"{fahrenheit} F is outside the safe range "
                    f"{TARGET_MIN_F}-{TARGET_MAX_F} F for this tank's stock."
                )
            previous = await self.ha.number(self.tank.target_temperature)
            await self.ha.call(
                "number",
                "set_value",
                {"entity_id": self.tank.target_temperature, "value": fahrenheit},
            )
            return {
                "device": self.cfg.device,
                "previous_target_f": previous,
                "new_target_f": fahrenheit,
            }

        @mcp.tool()
        async def add_livestock(
            species: str,
            count: int,
            added_on: str | None = None,
            notes: str | None = None,
        ) -> dict[str, Any]:
            """Record livestock going into the tank.

            species is free text and is folded onto a canonical name, so
            "kuhlis", "kuhli loach" and "Kuhli Loaches" all land together.
            added_on is an ISO date and defaults to today.
            """
            result = self.store.add_livestock(species, count, added_on, notes)
            return {"added": result, "livestock": self._publish_livestock()}

        @mcp.tool()
        async def log_loss(
            species: str,
            count: int = 1,
            occurred_on: str | None = None,
            cause: str | None = None,
            notes: str | None = None,
        ) -> dict[str, Any]:
            """Record a dead or lost fish or shrimp.

            cause is free text -- "unknown", "columnaris", "jumped", whatever
            fits. occurred_on is an ISO date and defaults to today. The
            running totals are mirrored into Home Assistant.
            """
            result = self.store.log_loss(species, count, occurred_on, cause, notes)
            summary = self._publish_livestock()
            recent = self.store.losses(
                since=(date.today() - timedelta(days=30)).isoformat(),
                species=species,
            )
            return {
                "logged": result,
                "livestock": summary,
                "same_species_losses_30d": sum(row["count"] for row in recent),
            }

        @mcp.tool()
        async def livestock_inventory() -> dict[str, Any]:
            """What is alive in the tank, per species, with totals and losses."""
            inventory = self.store.inventory()
            summary = self.livestock_summary()
            return {
                "summary": summary,
                "species": [
                    {
                        "species": item.species,
                        "alive": item.alive,
                        "ever_added": item.added,
                        "ever_lost": item.lost,
                    }
                    for item in inventory
                ],
                "spoken_summary": speech.livestock_report(
                    inventory, summary["losses_30d"], summary["days_since_loss"]
                ),
            }

        @mcp.tool()
        async def loss_history(days: int = 90, species: str | None = None) -> dict[str, Any]:
            """Deaths and losses over the last N days, newest first.

            Includes a per-species tally and the rate per week, which is what
            tells an outbreak apart from ordinary attrition.
            """
            if days < 1:
                raise ValueError("days must be at least 1")
            since = (date.today() - timedelta(days=days)).isoformat()
            rows = self.store.losses(since=since, species=species)

            tally: dict[str, int] = {}
            for row in rows:
                tally[row["species"]] = tally.get(row["species"], 0) + row["count"]
            total = sum(tally.values())

            return {
                "since": since,
                "days": days,
                "species_filter": normalise_species(species) if species else None,
                "total_lost": total,
                "per_species": tally,
                "per_week": round(total / (days / 7), 2),
                "events": rows,
            }

        @mcp.tool()
        async def stocking_history(species: str | None = None) -> list[dict[str, Any]]:
            """Every recorded stocking event, newest first."""
            return self.store.stockings(species)

        @mcp.tool()
        async def delete_loss(loss_id: int) -> dict[str, Any]:
            """Remove a loss entry recorded by mistake."""
            if not self.store.delete_loss(loss_id):
                raise ValueError(f"No loss with id {loss_id}.")
            return {"deleted": loss_id, "livestock": self._publish_livestock()}

        @mcp.tool()
        async def list_echo_speakers() -> list[dict[str, str]]:
            """Echo devices that can be spoken to, for use as an announce target."""
            states = await self.ha.states()
            speakers = [
                {
                    "entity_id": state["entity_id"],
                    "name": state.get("attributes", {}).get(
                        "friendly_name", state["entity_id"]
                    ),
                    "state": state.get("state", "unknown"),
                }
                for state in states
                if state["entity_id"].startswith("media_player.")
            ]
            return sorted(speakers, key=lambda s: s["name"])

        @mcp.tool()
        async def announce(message: str, target: str | None = None) -> dict[str, Any]:
            """Say something on an Echo right now.

            target is a media_player entity id; omit it to use the app's
            configured default speaker.
            """
            if not message.strip():
                raise ValueError("message must not be empty")
            return await self._announce(message, target)

        @mcp.tool()
        async def speak_tank_report(target: str | None = None) -> dict[str, Any]:
            """Read the current tank status aloud on an Echo."""
            status = await readings.tank_status(self.ha, self.tank, self.seneye)
            chemistry = await readings.water_chemistry(self.ha, self.seneye)
            seneye = await readings.seneye_status(self.ha, self.seneye)
            problems = readings.concerns(status, chemistry, seneye)
            message = speech.tank_report(status, chemistry, seneye, problems)
            result = await self._announce(message, target)
            result["concerns"] = problems
            return result

        @mcp.tool()
        async def speak_livestock_report(target: str | None = None) -> dict[str, Any]:
            """Read the livestock inventory and recent losses aloud on an Echo."""
            summary = self.livestock_summary()
            message = speech.livestock_report(
                self.store.inventory(), summary["losses_30d"], summary["days_since_loss"]
            )
            return await self._announce(message, target)
