"""Per-user database routing: each login gets its own SQLite file."""

from __future__ import annotations

import contextvars
import shutil
import sqlite3
from pathlib import Path

CURRENT_USER = contextvars.ContextVar("current_user", default=None)
USERS_DIR = Path(__file__).resolve().parents[1] / "data" / "users"
TEMPLATE = Path(__file__).resolve().parents[1] / "data" / "health.db"


def set_user(user_id: str | None) -> None:
    CURRENT_USER.set(user_id)


def current() -> str | None:
    return CURRENT_USER.get()


def db_path(default: Path) -> Path:
    user = CURRENT_USER.get()
    if not user:
        return default
    USERS_DIR.mkdir(parents=True, exist_ok=True)
    return USERS_DIR / f"{user}.db"


class _ClosingConnection(sqlite3.Connection):
    """`with connect()` must release the file descriptor, not only commit."""

    def __exit__(self, exc_type, exc, tb):
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()


def connect(default: Path) -> sqlite3.Connection:
    path = db_path(default)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5, factory=_ClosingConnection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def seed(user_id: str) -> None:
    """First user gets the existing demo data so the demo is not empty."""
    target = USERS_DIR / f"{user_id}.db"
    if target.exists() or not TEMPLATE.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(TEMPLATE)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    # 只借主库的 schema，不把主库的测试对话/资料带进新评委空间
    token = CURRENT_USER.set(user_id)
    try:
        from . import demo_reset
        demo_reset.reset(seed=True)
    finally:
        CURRENT_USER.reset(token)
