"""SQLite storage for Daybook entries.

Plain synchronous code with no Home Assistant imports, so it can be tested on
its own. Home Assistant calls it from the executor.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from typing import Any

from .const import KINDS, STATUSES, STATUS_CONFIRMED

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    item TEXT,
    start_ts REAL NOT NULL,
    end_ts REAL,
    value TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'confirmed',
    source TEXT NOT NULL DEFAULT 'manual',
    note TEXT NOT NULL DEFAULT '',
    created_ts REAL NOT NULL,
    updated_ts REAL NOT NULL,
    deleted_ts REAL
);
CREATE INDEX IF NOT EXISTS idx_entries_start ON entries(start_ts);
CREATE INDEX IF NOT EXISTS idx_entries_kind ON entries(kind, start_ts);

-- Every change keeps the previous version, so an automatic detection and
-- the correction you made to it both survive. Later models learn from this.
CREATE TABLE IF NOT EXISTS entry_history (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id TEXT NOT NULL,
    changed_ts REAL NOT NULL,
    action TEXT NOT NULL,
    before TEXT
);
CREATE INDEX IF NOT EXISTS idx_history_entry ON entry_history(entry_id);

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_COLUMNS = (
    "id, kind, item, start_ts, end_ts, value, status, source, note, "
    "created_ts, updated_ts, deleted_ts"
)
_EDITABLE = ("kind", "item", "start", "end", "value", "status", "source", "note")


class StoreError(ValueError):
    """Raised for invalid entries."""


def _row_to_entry(row: sqlite3.Row | tuple) -> dict[str, Any]:
    (
        id_, kind, item, start, end, value, status, source, note,
        created, updated, deleted,
    ) = row
    return {
        "id": id_,
        "kind": kind,
        "item": item,
        "start": start,
        "end": end,
        "value": json.loads(value or "{}"),
        "status": status,
        "source": source,
        "note": note,
        "created": created,
        "updated": updated,
        "deleted": deleted,
    }


def _validate(entry: dict[str, Any]) -> None:
    if entry.get("kind") not in KINDS:
        raise StoreError(f"Unknown kind: {entry.get('kind')!r}")
    if entry.get("status", STATUS_CONFIRMED) not in STATUSES:
        raise StoreError(f"Unknown status: {entry.get('status')!r}")
    start = entry.get("start")
    if not isinstance(start, (int, float)):
        raise StoreError("start must be a timestamp")
    end = entry.get("end")
    if end is not None:
        if not isinstance(end, (int, float)):
            raise StoreError("end must be a timestamp")
        if end < start:
            raise StoreError("end is before start")
    if not isinstance(entry.get("value", {}), dict):
        raise StoreError("value must be an object")


class DaybookStore:
    """Thread-safe wrapper around one SQLite file."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    # -- lifecycle -----------------------------------------------------
    def open(self) -> None:
        with self._lock:
            if self._conn is not None:
                return
            conn = sqlite3.connect(self._path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.executescript(_SCHEMA)
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version < SCHEMA_VERSION:
                conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            conn.commit()
            self._conn = conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Store is not open")
        return self._conn

    # -- entries -------------------------------------------------------
    def add(self, entry: dict[str, Any], now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        data = {
            "id": entry.get("id") or uuid.uuid4().hex[:16],
            "kind": entry.get("kind"),
            "item": entry.get("item"),
            "start": entry.get("start", now),
            "end": entry.get("end"),
            "value": entry.get("value") or {},
            "status": entry.get("status") or STATUS_CONFIRMED,
            "source": entry.get("source") or "manual",
            "note": entry.get("note") or "",
        }
        _validate(data)
        with self._lock:
            self.conn.execute(
                f"INSERT INTO entries ({_COLUMNS}) VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL)",
                (
                    data["id"], data["kind"], data["item"], float(data["start"]),
                    None if data["end"] is None else float(data["end"]),
                    json.dumps(data["value"]), data["status"], data["source"],
                    data["note"], now, now,
                ),
            )
            self._history(data["id"], "create", None, now)
            self.conn.commit()
        return self.get(data["id"])  # type: ignore[return-value]

    def get(self, entry_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self.conn.execute(
                f"SELECT {_COLUMNS} FROM entries WHERE id=?", (entry_id,)
            ).fetchone()
        return _row_to_entry(row) if row else None

    def update(
        self, entry_id: str, changes: dict[str, Any], now: float | None = None
    ) -> dict[str, Any]:
        now = time.time() if now is None else now
        current = self.get(entry_id)
        if current is None or current["deleted"] is not None:
            raise StoreError(f"No entry {entry_id}")
        merged = dict(current)
        for key in _EDITABLE:
            if key in changes:
                merged[key] = changes[key]
        _validate(merged)
        with self._lock:
            self._history(entry_id, "update", current, now)
            self.conn.execute(
                "UPDATE entries SET kind=?, item=?, start_ts=?, end_ts=?, value=?, "
                "status=?, source=?, note=?, updated_ts=? WHERE id=?",
                (
                    merged["kind"], merged["item"], float(merged["start"]),
                    None if merged["end"] is None else float(merged["end"]),
                    json.dumps(merged["value"] or {}), merged["status"],
                    merged["source"], merged["note"] or "", now, entry_id,
                ),
            )
            self.conn.commit()
        return self.get(entry_id)  # type: ignore[return-value]

    def delete(self, entry_id: str, now: float | None = None) -> dict[str, Any]:
        """Soft delete, so it can be restored."""
        now = time.time() if now is None else now
        current = self.get(entry_id)
        if current is None or current["deleted"] is not None:
            raise StoreError(f"No entry {entry_id}")
        with self._lock:
            self._history(entry_id, "delete", current, now)
            self.conn.execute(
                "UPDATE entries SET deleted_ts=?, updated_ts=? WHERE id=?",
                (now, now, entry_id),
            )
            self.conn.commit()
        return self.get(entry_id)  # type: ignore[return-value]

    def restore(self, entry_id: str, now: float | None = None) -> dict[str, Any]:
        now = time.time() if now is None else now
        current = self.get(entry_id)
        if current is None:
            raise StoreError(f"No entry {entry_id}")
        with self._lock:
            self._history(entry_id, "restore", current, now)
            self.conn.execute(
                "UPDATE entries SET deleted_ts=NULL, updated_ts=? WHERE id=?",
                (now, entry_id),
            )
            self.conn.commit()
        return self.get(entry_id)  # type: ignore[return-value]

    def list(
        self,
        start: float | None = None,
        end: float | None = None,
        kinds: list[str] | None = None,
        include_deleted: bool = False,
    ) -> list[dict[str, Any]]:
        """Entries overlapping [start, end), ordered by start."""
        sql = f"SELECT {_COLUMNS} FROM entries WHERE 1=1"
        args: list[Any] = []
        if end is not None:
            sql += " AND start_ts < ?"
            args.append(float(end))
        if start is not None:
            sql += " AND COALESCE(end_ts, start_ts) >= ?"
            args.append(float(start))
        if kinds:
            sql += f" AND kind IN ({','.join('?' * len(kinds))})"
            args.extend(kinds)
        if not include_deleted:
            sql += " AND deleted_ts IS NULL"
        sql += " ORDER BY start_ts"
        with self._lock:
            rows = self.conn.execute(sql, args).fetchall()
        return [_row_to_entry(r) for r in rows]

    def last_by_source(self, source: str | None, since: float) -> dict[str, Any] | None:
        sql = f"SELECT {_COLUMNS} FROM entries WHERE deleted_ts IS NULL AND created_ts >= ?"
        args: list[Any] = [since]
        if source:
            sql += " AND source = ?"
            args.append(source)
        sql += " ORDER BY created_ts DESC LIMIT 1"
        with self._lock:
            row = self.conn.execute(sql, args).fetchone()
        return _row_to_entry(row) if row else None

    def history(self, entry_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT changed_ts, action, before FROM entry_history "
                "WHERE entry_id=? ORDER BY rowid",
                (entry_id,),
            ).fetchall()
        return [
            {"changed": r[0], "action": r[1], "before": json.loads(r[2]) if r[2] else None}
            for r in rows
        ]

    def _history(self, entry_id: str, action: str, before: dict | None, now: float) -> None:
        self.conn.execute(
            "INSERT INTO entry_history (entry_id, changed_ts, action, before) VALUES (?,?,?,?)",
            (entry_id, now, action, json.dumps(before) if before else None),
        )

    # -- key/value -----------------------------------------------------
    def kv_get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self.conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def kv_set(self, key: str, value: Any) -> None:
        with self._lock:
            if value is None:
                self.conn.execute("DELETE FROM kv WHERE key=?", (key,))
            else:
                self.conn.execute(
                    "INSERT INTO kv (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, json.dumps(value)),
                )
            self.conn.commit()
