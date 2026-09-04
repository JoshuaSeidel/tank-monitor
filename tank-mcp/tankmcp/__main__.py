"""Serve the MCP tools over streamable HTTP, behind a bearer token."""

from __future__ import annotations

import asyncio
import logging
import secrets
import sys

import uvicorn
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from . import config
from .server import TankServer

_LOGGER = logging.getLogger("tankmcp")

# Unauthenticated so an uptime check or a browser poking the port gets a
# straight answer without holding the API token.
OPEN_PATHS = ("/health",)


class BearerAuth:
    """Reject anything that does not carry the app's API token.

    The MCP endpoint is published on the LAN and has tools that change a
    setpoint and speak on a speaker, so it does not go out unauthenticated.
    """

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in OPEN_PATHS:
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        supplied = headers.get("authorization", "")
        prefix = "bearer "
        offered = supplied[len(prefix):] if supplied.lower().startswith(prefix) else ""

        if not secrets.compare_digest(offered, self.token):
            response = JSONResponse(
                {"error": "unauthorized", "detail": "Send Authorization: Bearer <api_token>"},
                status_code=401,
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


def main() -> int:
    cfg = config.load()
    logging.basicConfig(
        level=getattr(logging, cfg.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not cfg.ha_token:
        _LOGGER.error("No Home Assistant token in the environment; cannot start.")
        return 1

    server = TankServer(cfg)
    server.start()

    app = server.mcp.streamable_http_app()
    app.routes.append(
        Route("/health", lambda request: PlainTextResponse("ok"), methods=["GET"])
    )
    app.add_middleware(BearerAuth, token=cfg.api_token)

    _LOGGER.info("Tank MCP listening on http://0.0.0.0:%s/mcp", cfg.port)
    _LOGGER.info("API token: %s", cfg.api_token)
    _LOGGER.info("Controller: %s", cfg.device)

    try:
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=cfg.port,
            log_level=cfg.log_level.lower(),
            access_log=False,
        )
    finally:
        asyncio.run(server.aclose())
    return 0


if __name__ == "__main__":
    sys.exit(main())
