"""Small response cache for repeated analyses (saves DeepSeek time/tokens)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "health.db"
LOCK = threading.Lock()
TTL = timedelta(minutes=10)


def _connect() -> sqlite3.Connection:
    from . import db

    return db.connect(DB_PATH)


def init() -> None:
    with LOCK, _connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS response_cache (
                   key TEXT PRIMARY KEY, result TEXT, created_at TEXT)"""
        )


def make_key(*parts: Any) -> str:
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def get(key: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT result, created_at FROM response_cache WHERE key = ?",
                           (key,)).fetchone()
    if row is None:
        return None
    try:
        created = datetime.fromisoformat(row["created_at"])
    except ValueError:
        return None
    if datetime.now() - created > TTL:
        return None
    return json.loads(row["result"])


def put(key: str, result: dict[str, Any]) -> None:
    with LOCK, _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO response_cache (key, result, created_at) VALUES (?, ?, ?)",
            (key, json.dumps(result, ensure_ascii=False),
             datetime.now().isoformat(timespec="seconds")),
        )
        conn.execute(
            "DELETE FROM response_cache WHERE key NOT IN"
            " (SELECT key FROM response_cache ORDER BY created_at DESC LIMIT 200)"
        )


def clear() -> int:
    with LOCK, _connect() as conn:
        cursor = conn.execute("DELETE FROM response_cache")
    return cursor.rowcount


def stats() -> dict[str, Any]:
    with _connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS total FROM response_cache").fetchone()
    return {"entries": int(row["total"] or 0), "ttl_seconds": int(TTL.total_seconds())}
