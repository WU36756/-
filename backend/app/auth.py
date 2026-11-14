"""Local accounts, sessions and DeepSeek consent."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "auth.db"
SESSION_DAYS = 7


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    with _connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS users (
                   id TEXT PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT,
                   created_at TEXT, consent INTEGER DEFAULT 0, consent_at TEXT)"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS sessions (
                   token TEXT PRIMARY KEY, user_id TEXT, created_at TEXT, expires_at TEXT)"""
        )


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()


def register(username: str, password: str) -> dict[str, Any]:
    username = username.strip()
    if len(username) < 2 or len(password) < 4:
        return {"error": "用户名至少 2 位，密码至少 4 位"}
    user_id = uuid.uuid4().hex[:12]
    salt = secrets.token_hex(16)
    with _connect() as conn:
        try:
            conn.execute(
                "INSERT INTO users (id, username, password_hash, created_at)"
                " VALUES (?, ?, ?, ?)",
                (user_id, username, f"{salt}${_hash(password, salt)}",
                 datetime.now().isoformat(timespec="seconds")),
            )
        except sqlite3.IntegrityError:
            return {"error": "用户名已存在"}
    return {"user": {"id": user_id, "username": username, "consent": False}}


def authenticate(username: str, password: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()
    if row is None:
        return None
    salt, digest = (row["password_hash"] or "").split("$", 1)
    if not secrets.compare_digest(_hash(password, salt), digest):
        return None
    return {"id": row["id"], "username": row["username"], "consent": bool(row["consent"])}


def create_session(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, now.isoformat(timespec="seconds"),
             (now + timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds")),
        )
    return token


def user_for_token(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    with _connect() as conn:
        row = conn.execute(
            "SELECT s.user_id, s.expires_at, u.username, u.consent FROM sessions s"
            " JOIN users u ON u.id = s.user_id WHERE s.token = ?", (token,)).fetchone()
    if row is None:
        return None
    if row["expires_at"] < datetime.now().isoformat(timespec="seconds"):
        return None
    return {"id": row["user_id"], "username": row["username"], "consent": bool(row["consent"])}


def destroy_session(token: str | None) -> None:
    if not token:
        return
    with _connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def set_consent(user_id: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE users SET consent = 1, consent_at = ? WHERE id = ?",
                     (datetime.now().isoformat(timespec="seconds"), user_id))


def has_consent(user_id: str) -> bool:
    with _connect() as conn:
        row = conn.execute("SELECT consent FROM users WHERE id = ?", (user_id,)).fetchone()
    return bool(row and row["consent"])
