"""SQLite ledger for livestock, losses, and manual water tests.

Lives in /data, so it survives app restarts and updates and is picked up by
Home Assistant's backups. Home Assistant's own recorder is deliberately not
used for this: stocking and losses are events with narrative attached, not
sensor samples, and they need to stay readable years later.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS livestock (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    species     TEXT    NOT NULL,
    label       TEXT    NOT NULL,
    count       INTEGER NOT NULL,
    added_on    TEXT    NOT NULL,
    notes       TEXT,
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS losses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    species     TEXT    NOT NULL,
    label       TEXT    NOT NULL,
    count       INTEGER NOT NULL,
    occurred_on TEXT    NOT NULL,
    cause       TEXT,
    notes       TEXT,
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS water_tests (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tested_at     TEXT    NOT NULL,
    total_ammonia REAL,
    nitrite       REAL,
    nitrate       REAL,
    gh_dgh        REAL,
    kh_dkh        REAL,
    tds_ppm       REAL,
    ph            REAL,
    notes         TEXT
);

CREATE INDEX IF NOT EXISTS idx_losses_date ON losses (occurred_on);
CREATE INDEX IF NOT EXISTS idx_livestock_species ON livestock (species);
CREATE INDEX IF NOT EXISTS idx_tests_date ON water_tests (tested_at);
"""

# The tank's actual stock, so free-text from a voice or chat request lands on
# one canonical species instead of six near-misses.
ALIASES = {
    "neocaridina": "neocaridina shrimp",
    "neo": "neocaridina shrimp",
    "shrimp": "neocaridina shrimp",
    "cherry shrimp": "neocaridina shrimp",
    "red cherry shrimp": "neocaridina shrimp",
    "kuhli": "kuhli loach",
    "khuli": "kuhli loach",
    "kuhli loaches": "kuhli loach",
    "loach": "kuhli loach",
    "tetra": "tetra",
    "tetras": "tetra",
    "blue eye": "blue-eye rainbowfish",
    "blue eyes": "blue-eye rainbowfish",
    "blue-eye": "blue-eye rainbowfish",
    "blue-eyes": "blue-eye rainbowfish",
    "rainbowfish": "blue-eye rainbowfish",
}


def normalise_species(raw: str) -> str:
    """Fold a free-text species name onto a canonical key."""
    key = " ".join(raw.strip().lower().split())
    if not key:
        raise ValueError("species must not be empty")
    if key in ALIASES:
        return ALIASES[key]
    # "kuhli loaches" -> "kuhli loach" for anything not in the alias table.
    if key.endswith("es") and key[:-2] in ALIASES:
        return ALIASES[key[:-2]]
    if key.endswith("s") and key[:-1] in ALIASES:
        return ALIASES[key[:-1]]
    if key.endswith("s") and not key.endswith("ss"):
        key = key[:-1]
    return key


def parse_day(value: str | None) -> str:
    """Accept an ISO date (or datetime) and return YYYY-MM-DD; default today."""
    if not value:
        return date.today().isoformat()
    text = value.strip()
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError as err:
        raise ValueError(
            f"'{value}' is not an ISO date; use YYYY-MM-DD"
        ) from err


@dataclass(frozen=True)
class Inventory:
    species: str
    label: str
    added: int
    lost: int

    @property
    def alive(self) -> int:
        return max(self.added - self.lost, 0)


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # --- writes ----------------------------------------------------------

    def add_livestock(
        self, species: str, count: int, added_on: str | None, notes: str | None
    ) -> dict[str, Any]:
        if count < 1:
            raise ValueError("count must be at least 1")
        key = normalise_species(species)
        day = parse_day(added_on)
        cur = self._conn.execute(
            "INSERT INTO livestock (species, label, count, added_on, notes, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (key, species.strip(), count, day, notes, datetime.now().isoformat(timespec="seconds")),
        )
        self._conn.commit()
        return {"id": cur.lastrowid, "species": key, "count": count, "added_on": day}

    def log_loss(
        self,
        species: str,
        count: int,
        occurred_on: str | None,
        cause: str | None,
        notes: str | None,
    ) -> dict[str, Any]:
        if count < 1:
            raise ValueError("count must be at least 1")
        key = normalise_species(species)
        day = parse_day(occurred_on)
        cur = self._conn.execute(
            "INSERT INTO losses (species, label, count, occurred_on, cause, notes, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                key,
                species.strip(),
                count,
                day,
                cause,
                notes,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        self._conn.commit()
        return {
            "id": cur.lastrowid,
            "species": key,
            "count": count,
            "occurred_on": day,
            "cause": cause,
        }

    def record_water_test(self, tested_at: str, values: dict[str, float | None], notes: str | None) -> int:
        cur = self._conn.execute(
            "INSERT INTO water_tests"
            " (tested_at, total_ammonia, nitrite, nitrate, gh_dgh, kh_dkh, tds_ppm, ph, notes)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                tested_at,
                values.get("total_ammonia"),
                values.get("nitrite"),
                values.get("nitrate"),
                values.get("gh_dgh"),
                values.get("kh_dkh"),
                values.get("tds_ppm"),
                values.get("ph"),
                notes,
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def delete_loss(self, loss_id: int) -> bool:
        cur = self._conn.execute("DELETE FROM losses WHERE id = ?", (loss_id,))
        self._conn.commit()
        return cur.rowcount > 0

    # --- reads -----------------------------------------------------------

    def inventory(self) -> list[Inventory]:
        added = {
            row["species"]: (row["total"], row["label"])
            for row in self._conn.execute(
                "SELECT species, SUM(count) AS total, MAX(label) AS label"
                " FROM livestock GROUP BY species"
            )
        }
        lost = {
            row["species"]: row["total"]
            for row in self._conn.execute(
                "SELECT species, SUM(count) AS total FROM losses GROUP BY species"
            )
        }
        species = sorted(set(added) | set(lost))
        return [
            Inventory(
                species=key,
                label=added.get(key, (0, key))[1],
                added=added.get(key, (0, key))[0],
                lost=lost.get(key, 0),
            )
            for key in species
        ]

    def losses(self, since: str | None = None, species: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM losses"
        clauses: list[str] = []
        params: list[Any] = []
        if since:
            clauses.append("occurred_on >= ?")
            params.append(since)
        if species:
            clauses.append("species = ?")
            params.append(normalise_species(species))
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY occurred_on DESC, id DESC"
        return [dict(row) for row in self._conn.execute(sql, params)]

    def stockings(self, species: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM livestock"
        params: list[Any] = []
        if species:
            sql += " WHERE species = ?"
            params.append(normalise_species(species))
        sql += " ORDER BY added_on DESC, id DESC"
        return [dict(row) for row in self._conn.execute(sql, params)]

    def water_tests(self, limit: int = 20) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self._conn.execute(
                "SELECT * FROM water_tests ORDER BY tested_at DESC, id DESC LIMIT ?",
                (limit,),
            )
        ]

    def last_loss(self) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM losses ORDER BY occurred_on DESC, id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None
