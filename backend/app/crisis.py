"""Crisis follow-up records: a gentle check-in 24 hours after a crisis reply."""

from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "health.db"
LOCK = threading.Lock()
CHECKIN_DELAY = timedelta(hours=24)


def _connect() -> sqlite3.Connection:
    from . import db
    return db.connect(DB_PATH)


def init() -> None:
    with LOCK, _connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS crisis_followups (
                   id TEXT PRIMARY KEY, created_at TEXT, due_at TEXT,
                   level TEXT, status TEXT DEFAULT 'open')"""
        )


def record(level: str) -> dict[str, Any]:
    now = datetime.now()
    item_id = uuid.uuid4().hex[:12]
    due = (now + CHECKIN_DELAY).isoformat(timespec="seconds")
    with LOCK, _connect() as conn:
        conn.execute("INSERT INTO crisis_followups VALUES (?, ?, ?, ?, 'open')",
                     (item_id, now.isoformat(timespec="seconds"), due, level))
    return {"id": item_id, "due_at": due, "level": level}


def due(now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or datetime.now()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM crisis_followups WHERE status = 'open' AND due_at <= ?",
            (now.isoformat(timespec="seconds"),),
        ).fetchall()
    return [dict(row) for row in rows]


def ack_all() -> int:
    """Mark every due/open follow-up as done (used when the toast is dismissed)."""
    with LOCK, _connect() as conn:
        cursor = conn.execute(
            "UPDATE crisis_followups SET status = 'done' WHERE status = 'open'"
        )
    return cursor.rowcount


def ack(followup_id: str) -> bool:
    with LOCK, _connect() as conn:
        cursor = conn.execute(
            "UPDATE crisis_followups SET status = 'done' WHERE id = ?", (followup_id,)
        )
    return cursor.rowcount > 0
