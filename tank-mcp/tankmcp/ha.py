"""Thin async client for the Home Assistant REST API."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

_LOGGER = logging.getLogger(__name__)

UNAVAILABLE = ("unknown", "unavailable", "none", "", None)


class HomeAssistantError(RuntimeError):
    """Raised when Home Assistant rejects a call or cannot be reached."""


class HomeAssistant:
    def __init__(self, base_url: str, token: str, timeout: float = 20.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=f"{base_url}/api",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as err:  # network, DNS, timeout
            raise HomeAssistantError(f"Home Assistant unreachable: {err}") from err
        if response.status_code >= 400:
            raise HomeAssistantError(
                f"Home Assistant returned {response.status_code} for {path}: "
                f"{response.text[:300]}"
            )
        if not response.content:
            return None
        return response.json()

    async def state(self, entity_id: str) -> dict[str, Any] | None:
        """Return the full state object, or None if the entity does not exist."""
        try:
            return await self._request("GET", f"/states/{entity_id}")
        except HomeAssistantError as err:
            if "returned 404" in str(err):
                return None
            raise

    async def states(self) -> list[dict[str, Any]]:
        """Return every entity state object."""
        return await self._request("GET", "/states") or []

    async def value(self, entity_id: str) -> str | None:
        """Return an entity's state string, or None when it has no usable value."""
        state = await self.state(entity_id)
        if state is None:
            return None
        raw = state.get("state")
        return None if raw in UNAVAILABLE else raw

    async def number(self, entity_id: str) -> float | None:
        raw = await self.value(entity_id)
        if raw is None:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    async def is_on(self, entity_id: str) -> bool | None:
        raw = await self.value(entity_id)
        if raw is None:
            return None
        return raw == "on"

    async def call(
        self, domain: str, service: str, data: dict[str, Any] | None = None
    ) -> Any:
        return await self._request("POST", f"/services/{domain}/{service}", json=data or {})

    async def history(self, entity_id: str, hours: float) -> list[dict[str, Any]]:
        """Return recorder history for one entity over the last `hours`."""
        start = datetime.now(timezone.utc) - timedelta(hours=hours)
        result = await self._request(
            "GET",
            f"/history/period/{start.isoformat()}",
            params={
                "filter_entity_id": entity_id,
                "minimal_response": "true",
                "no_attributes": "true",
            },
        )
        if not result:
            return []
        # The endpoint returns one list per requested entity.
        return result[0] if isinstance(result[0], list) else []
