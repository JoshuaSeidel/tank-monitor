"""Runtime configuration, read from the environment that run.sh exports."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    """Read an env var, treating bashio's "null" for an unset option as empty."""
    value = os.environ.get(name, default).strip()
    return "" if value == "null" else value


def _flag(name: str, default: bool) -> bool:
    value = _env(name)
    if not value:
        return default
    return value.lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Config:
    ha_url: str
    ha_token: str
    device: str
    seneye_prefix: str
    default_echo: str
    api_token: str
    port: int
    db_path: Path
    log_level: str
    publish_mqtt: bool
    mqtt_host: str
    mqtt_port: int
    mqtt_user: str
    mqtt_password: str

    @property
    def mqtt_enabled(self) -> bool:
        return self.publish_mqtt and bool(self.mqtt_host)


def _resolve_api_token() -> str:
    """Use the configured token, or mint and persist one on first start.

    Generating rather than refusing to boot keeps the app usable straight
    out of the store; the token is written to /data so it survives restarts
    and is logged once so it can be copied into an MCP client.
    """
    configured = _env("TANK_MCP_TOKEN")
    if configured:
        return configured

    token_file = Path(_env("TANK_MCP_TOKEN_FILE", "/data/api_token"))
    if token_file.exists():
        stored = token_file.read_text(encoding="utf-8").strip()
        if stored:
            return stored

    minted = secrets.token_urlsafe(32)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(minted + "\n", encoding="utf-8")
    token_file.chmod(0o600)
    return minted


def load() -> Config:
    return Config(
        ha_url=_env("TANK_MCP_HA_URL", "http://supervisor/core").rstrip("/"),
        ha_token=_env("TANK_MCP_HA_TOKEN"),
        device=_env("TANK_MCP_DEVICE", "tank_monitor"),
        seneye_prefix=_env("TANK_MCP_SENEYE_PREFIX", "seneye_spec_16"),
        default_echo=_env("TANK_MCP_DEFAULT_ECHO", "media_player.office"),
        api_token=_resolve_api_token(),
        port=int(_env("TANK_MCP_PORT", "8099")),
        db_path=Path(_env("TANK_MCP_DB", "/data/tank.db")),
        log_level=_env("TANK_MCP_LOG_LEVEL", "info").upper(),
        publish_mqtt=_flag("TANK_MCP_PUBLISH_MQTT", True),
        mqtt_host=_env("TANK_MCP_MQTT_HOST"),
        mqtt_port=int(_env("TANK_MCP_MQTT_PORT", "1883") or "1883"),
        mqtt_user=_env("TANK_MCP_MQTT_USER"),
        mqtt_password=_env("TANK_MCP_MQTT_PASSWORD"),
    )
