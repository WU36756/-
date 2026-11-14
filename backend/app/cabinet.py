"""Medicine cabinet: dose counters with a dragon-ball progress meter."""

from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "health.db"
LOCK = threading.Lock()


def _connect() -> sqlite3.Connection:
    from . import db
    return db.connect(DB_PATH)


def init() -> None:
    with LOCK, _connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS cabinet_items (
                   id TEXT PRIMARY KEY, name TEXT, total INTEGER, taken INTEGER DEFAULT 0,
                   completed INTEGER DEFAULT 0, created_at TEXT)"""
        )


def _row(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    total = max(1, item["total"] or 1)
    item["balls"] = min(total, int(item["taken"] or 0))
    if item["completed"]:
        item["balls"] = total
    return item


def list_all() -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM cabinet_items ORDER BY created_at DESC"
        ).fetchall()
    return [_row(row) for row in rows]


def add(name: str, total: int) -> dict[str, Any]:
    item_id = uuid.uuid4().hex[:12]
    total = max(1, min(int(total), 999))
    with LOCK, _connect() as conn:
        conn.execute(
            "INSERT INTO cabinet_items (id, name, total, taken, completed, created_at)"
            " VALUES (?, ?, ?, 0, 0, ?)",
            (item_id, name.strip()[:60], total, datetime.now().isoformat(timespec="seconds")),
        )
        row = conn.execute("SELECT * FROM cabinet_items WHERE id = ?", (item_id,)).fetchone()
    return _row(row)


def take(item_id: str) -> dict[str, Any] | None:
    with LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM cabinet_items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            return None
        if row["completed"]:
            return _row(row)
        taken = min(row["taken"] + 1, row["total"])
        completed = 1 if taken >= row["total"] else 0
        conn.execute(
            "UPDATE cabinet_items SET taken = ?, completed = ? WHERE id = ?",
            (taken, completed, item_id),
        )
        row = conn.execute("SELECT * FROM cabinet_items WHERE id = ?", (item_id,)).fetchone()
    item = _row(row)
    item["just_completed"] = bool(completed)
    return item


def delete(item_id: str) -> bool:
    with LOCK, _connect() as conn:
        cursor = conn.execute("DELETE FROM cabinet_items WHERE id = ?", (item_id,))
    return cursor.rowcount > 0
