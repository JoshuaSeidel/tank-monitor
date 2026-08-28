"""End-to-end check: real MCP client -> real server -> stand-in Home Assistant.

Run from the tank-mcp directory:  python tests/smoke_test.py
Exits non-zero on the first failed expectation.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn
from starlette.routing import Route
from starlette.responses import PlainTextResponse

import fake_ha  # noqa: E402  (path set above)

HA_PORT = 18123
MCP_PORT = 18099
TOKEN = "smoke-test-token"

failures: list[str] = []


def check(label: str, condition: bool, detail: object = "") -> None:
    if condition:
        print(f"  ok    {label}")
    else:
        print(f"  FAIL  {label}  {detail}")
        failures.append(label)


async def serve(app, port: int, ready: asyncio.Event) -> None:
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)

    async def watch() -> None:
        while not server.started:
            await asyncio.sleep(0.05)
        ready.set()

    asyncio.create_task(watch())
    await server.serve()


def payload(result) -> object:
    """Unwrap an MCP tool result into plain Python."""
    if getattr(result, "structuredContent", None):
        content = result.structuredContent
        # FastMCP wraps non-dict returns under "result".
        return content.get("result", content) if isinstance(content, dict) else content
    return json.loads(result.content[0].text)


async def main() -> int:
    workdir = tempfile.mkdtemp(prefix="tankmcp-smoke-")
    os.environ.update(
        TANK_MCP_HA_URL=f"http://127.0.0.1:{HA_PORT}",
        TANK_MCP_HA_TOKEN="fake-token",
        TANK_MCP_DEVICE="tank_monitor",
        TANK_MCP_SENEYE_PREFIX="seneye_spec_16",
        TANK_MCP_DEFAULT_ECHO="media_player.office",
        TANK_MCP_TOKEN=TOKEN,
        TANK_MCP_TOKEN_FILE=f"{workdir}/api_token",
        TANK_MCP_DB=f"{workdir}/tank.db",
        TANK_MCP_PORT=str(MCP_PORT),
        TANK_MCP_PUBLISH_MQTT="false",
        TANK_MCP_LOG_LEVEL="warning",
    )

    from tankmcp import config as app_config
    from tankmcp.__main__ import BearerAuth
    from tankmcp.server import TankServer

    cfg = app_config.load()
    server = TankServer(cfg)

    app = server.mcp.streamable_http_app()
    app.routes.append(Route("/health", lambda r: PlainTextResponse("ok"), methods=["GET"]))
    app.add_middleware(BearerAuth, token=cfg.api_token)

    ha_ready, mcp_ready = asyncio.Event(), asyncio.Event()
    tasks = [
        asyncio.create_task(serve(fake_ha.build(), HA_PORT, ha_ready)),
        asyncio.create_task(serve(app, MCP_PORT, mcp_ready)),
    ]
    await asyncio.wait_for(asyncio.gather(ha_ready.wait(), mcp_ready.wait()), timeout=20)

    try:
        await run_checks()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await server.aclose()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
        return 1
    print("all checks passed")
    return 0


async def run_checks() -> None:
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    url = f"http://127.0.0.1:{MCP_PORT}/mcp"

    print("\nauth")
    async with httpx.AsyncClient() as client:
        health = await client.get(f"http://127.0.0.1:{MCP_PORT}/health")
        check("health endpoint is open", health.status_code == 200, health.status_code)
        anon = await client.post(
            url, json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
            headers={"Accept": "application/json, text/event-stream"},
        )
        check("unauthenticated request is rejected", anon.status_code == 401, anon.status_code)
        wrong = await client.post(
            url, json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
            headers={"Authorization": "Bearer nope", "Accept": "application/json, text/event-stream"},
        )
        check("wrong token is rejected", wrong.status_code == 401, wrong.status_code)

    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with streamablehttp_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            print("\ntool registration")
            tools = {tool.name for tool in (await session.list_tools()).tools}
            expected = {
                "tank_status", "water_chemistry", "seneye_status", "tank_report",
                "metric_history", "log_water_test", "water_test_history",
                "set_target_temperature", "add_livestock", "log_loss",
                "livestock_inventory", "loss_history", "stocking_history",
                "delete_loss", "list_echo_speakers", "announce",
                "speak_tank_report", "speak_livestock_report",
            }
            check("all tools registered", expected <= tools, sorted(expected - tools))
            check("every tool is described", all(t.description for t in (await session.list_tools()).tools))

            print("\nreads")
            status = payload(await session.call_tool("tank_status", {}))
            check("temperature read", status["temperature_f"] == 74.53, status.get("temperature_f"))
            check("target read", status["target_f"] == 74.3, status.get("target_f"))
            check("on target verdict", status["verdict"] == "on target", status.get("verdict"))
            check("probes agree", status["probe_cross_check"]["verdict"] == "agree", status["probe_cross_check"])
            check("device online", status["online"] is True)
            check("heater duty read", status["heater_duty_percent"] == 0.0)

            seneye = payload(await session.call_tool("seneye_status", {}))
            check("seneye pH", seneye["ph"] == 7.33, seneye.get("ph"))
            check("free ammonia safe", seneye["free_ammonia_verdict"] == "safe", seneye)
            check("seneye not stale", seneye["stale"] is False, seneye.get("reading_age_hours"))
            check("slide ok", seneye["slide_verdict"] == "ok", seneye.get("slide_days_remaining"))

            chem = payload(await session.call_tool("water_chemistry", {}))
            kit = chem["from_test_kit"]
            check("nitrate verdict", kit["nitrate_verdict"] == "good", kit.get("nitrate_ppm"))
            check("nitrite zero", kit["nitrite_verdict"] == "zero", kit.get("nitrite_ppm"))
            check("GH flagged below target", kit["gh_verdict"] == "below target", kit.get("gh_dgh"))
            check("GH target read from HA", kit["gh_target_dgh"] == [6.0, 8.0], kit.get("gh_target_dgh"))

            report = payload(await session.call_tool("tank_report", {}))
            check("report flags GH and KH", not report["healthy"] and len(report["concerns"]) >= 2, report["concerns"])
            check("spoken summary is plain text", "°" not in report["spoken_summary"] and "/" not in report["spoken_summary"])
            check("spoken summary mentions temperature", "74.5 degrees" in report["spoken_summary"], report["spoken_summary"])

            history = payload(await session.call_tool("metric_history", {"metric": "temperature", "hours": 6}))
            check("history parsed", history["count"] == 4, history.get("count"))
            check("history skips unavailable", history["max"] == 74.73, history.get("max"))
            bad = await session.call_tool("metric_history", {"metric": "nonsense"})
            check("unknown metric rejected", bad.isError, bad)

            print("\nwrites")
            logged = payload(await session.call_tool("log_water_test", {
                "nitrate_ppm": 15, "gh_ppm": 125, "kh_ppm": 54, "notes": "strip test",
            }))
            check("only given values written", set(logged["written"]) == {"nitrate", "gh", "kh"}, logged["written"])
            check("ppm converted to degrees", logged["written"]["gh"] == 7.0, logged["written"])
            check("KH ppm converted", logged["written"]["kh"] == 3.0, logged["written"])
            check("GH now in range", logged["chemistry_now"]["from_test_kit"]["gh_verdict"] == "in range")
            check("log script was run", any(
                c["domain"] == "script" and c["service"] == "turn_on" for c in fake_ha.CALLS))
            empty = await session.call_tool("log_water_test", {})
            check("empty test rejected", empty.isError)
            both = await session.call_tool("log_water_test", {"gh_ppm": 125, "gh_degrees": 7})
            check("ppm and degrees together rejected", both.isError)

            tests = payload(await session.call_tool("water_test_history", {"limit": 5}))
            check("test kept in ledger", len(tests) == 1 and tests[0]["notes"] == "strip test", tests)

            setpoint = payload(await session.call_tool("set_target_temperature", {"fahrenheit": 74.0}))
            check("setpoint changed", setpoint["new_target_f"] == 74.0, setpoint)
            unsafe = await session.call_tool("set_target_temperature", {"fahrenheit": 95})
            check("unsafe setpoint refused", unsafe.isError)

            print("\nlivestock")
            await session.call_tool("add_livestock", {"species": "Kuhli Loaches", "count": 6, "added_on": "2026-06-01"})
            await session.call_tool("add_livestock", {"species": "neocaridina", "count": 20, "added_on": "2026-07-15"})
            added = payload(await session.call_tool("add_livestock", {"species": "tetras", "count": 8}))
            check("stocking recorded", added["livestock"]["total_alive"] == 34, added["livestock"])

            loss = payload(await session.call_tool("log_loss", {
                "species": "kuhli", "count": 2, "occurred_on": "2026-08-26", "cause": "suspected columnaris",
            }))
            check("aliases fold together", loss["logged"]["species"] == "kuhli loach", loss["logged"])
            check("inventory reduced", loss["livestock"]["total_alive"] == 32, loss["livestock"])
            check("30d loss tally", loss["same_species_losses_30d"] == 2, loss)

            inventory = payload(await session.call_tool("livestock_inventory", {}))
            species = {row["species"]: row for row in inventory["species"]}
            check("kuhli count after loss", species["kuhli loach"]["alive"] == 4, species.get("kuhli loach"))
            check("shrimp alias canonical", "neocaridina shrimp" in species, list(species))
            check("spoken livestock summary", "32 animals" in inventory["spoken_summary"], inventory["spoken_summary"])

            hist = payload(await session.call_tool("loss_history", {"days": 30}))
            check("loss history totals", hist["total_lost"] == 2, hist)
            check("loss rate per week", hist["per_week"] == 0.47, hist.get("per_week"))
            filtered = payload(await session.call_tool("loss_history", {"days": 30, "species": "shrimp"}))
            check("species filter works", filtered["total_lost"] == 0, filtered)

            removed = payload(await session.call_tool("delete_loss", {"loss_id": loss["logged"]["id"]}))
            check("loss deleted", removed["livestock"]["total_alive"] == 34, removed["livestock"])
            missing = await session.call_tool("delete_loss", {"loss_id": 999})
            check("deleting a missing loss errors", missing.isError)

            print("\nalexa")
            speakers = payload(await session.call_tool("list_echo_speakers", {}))
            check("speakers listed", {s["entity_id"] for s in speakers} == {
                "media_player.office", "media_player.master_bedroom"}, speakers)

            spoken = payload(await session.call_tool("announce", {"message": "Tank check"}))
            check("default speaker used", spoken["spoken_on"] == "media_player.office", spoken)
            notify = [c for c in fake_ha.CALLS if c["domain"] == "notify"]
            check("notify.alexa_media called", notify and notify[-1]["service"] == "alexa_media", notify[-1:])
            check("announce type set", notify[-1]["data"]["data"]["type"] == "announce", notify[-1])
            check("targets the media player", notify[-1]["data"]["target"] == ["media_player.office"], notify[-1])

            blank = await session.call_tool("announce", {"message": "   "})
            check("empty announcement rejected", blank.isError)

            said = payload(await session.call_tool("speak_tank_report", {"target": "media_player.master_bedroom"}))
            check("report spoken on chosen echo", said["spoken_on"] == "media_player.master_bedroom", said)
            check("spoken report is non-trivial", len(said["message"]) > 80, said["message"])


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
