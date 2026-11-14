"""Conversation history store (SQLite, same health.db as medications)."""

from __future__ import annotations

import json
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
            """CREATE TABLE IF NOT EXISTS conversations (
                   id TEXT PRIMARY KEY, title TEXT, created_at TEXT, updated_at TEXT)"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS turns (
                   id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT,
                   user_text TEXT, result_json TEXT, created_at TEXT)"""
        )


def create(title: str = "新会话") -> dict[str, Any]:
    item_id = uuid.uuid4().hex[:12]
    now = datetime.now().isoformat(timespec="seconds")
    with LOCK, _connect() as conn:
        conn.execute("INSERT INTO conversations VALUES (?, ?, ?, ?)", (item_id, title, now, now))
    return {"id": item_id, "title": title, "created_at": now, "updated_at": now}


def list_all(query: str = "") -> list[dict[str, Any]]:
    query = (query or "").strip()
    with _connect() as conn:
        if query:
            like = f"%{query}%"
            rows = conn.execute(
                """SELECT DISTINCT c.id, c.title, c.created_at, c.updated_at
                   FROM conversations c LEFT JOIN turns t ON t.conversation_id = c.id
                   WHERE c.title LIKE ? OR t.user_text LIKE ?
                   ORDER BY c.updated_at DESC""",
                (like, like),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, title, created_at, updated_at FROM conversations ORDER BY updated_at DESC"
            ).fetchall()
    return [dict(row) for row in rows]


def rename(conversation_id: str, title: str) -> bool:
    title = (title or "").strip()[:40]
    if not title:
        return False
    with LOCK, _connect() as conn:
        cursor = conn.execute(
            "UPDATE conversations SET title = ? WHERE id = ?", (title, conversation_id)
        )
    return cursor.rowcount > 0


def get(conversation_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        if row is None:
            return None
        turns = conn.execute(
            "SELECT user_text, result_json, created_at FROM turns WHERE conversation_id = ? ORDER BY id",
            (conversation_id,),
        ).fetchall()
    return {
        "conversation": dict(row),
        "turns": [
            {"user_text": turn["user_text"],
             "result": json.loads(turn["result_json"]),
             "created_at": turn["created_at"]}
            for turn in turns
        ],
    }


def add_turn(conversation_id: str, user_text: str, result: dict[str, Any]) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    with LOCK, _connect() as conn:
        conn.execute(
            "INSERT INTO turns (conversation_id, user_text, result_json, created_at) VALUES (?, ?, ?, ?)",
            (conversation_id, user_text, json.dumps(result, ensure_ascii=False), now),
        )
        row = conn.execute("SELECT title FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        title = (row["title"] if row else "") or ""
        if title == "新会话":
            title = user_text.strip()[:24] or "新会话"
            conn.execute("UPDATE conversations SET title = ? WHERE id = ?", (title, conversation_id))
        conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))


def delete(conversation_id: str) -> bool:
    with LOCK, _connect() as conn:
        conn.execute("DELETE FROM turns WHERE conversation_id = ?", (conversation_id,))
        cursor = conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
    return cursor.rowcount > 0


def recent_user_texts(conversation_id: str, limit: int = 3) -> list[str]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT user_text FROM turns WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
            (conversation_id, limit),
        ).fetchall()
    return [row["user_text"] for row in reversed(rows) if row["user_text"]]


def recent_dialogue(conversation_id: str, limit: int = 8) -> list[dict[str, str]]:
    """Return recent user/assistant turns for the conversational layer."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT user_text, result_json FROM turns WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
            (conversation_id, limit),
        ).fetchall()
    dialogue: list[dict[str, str]] = []
    for row in reversed(rows):
        user_text = (row["user_text"] or "").strip()
        if user_text:
            dialogue.append({"role": "user", "content": user_text[:800]})
        try:
            result = json.loads(row["result_json"] or "{}")
        except (TypeError, ValueError):
            result = {}
        assistant = (result.get("chat_reply") or result.get("report_markdown")
                     or result.get("message") or result.get("reply") or "")
        if assistant:
            dialogue.append({"role": "assistant", "content": str(assistant)[:1200]})
    return dialogue[-limit:]


def recent_answers(conversation_id: str, limit: int = 3) -> dict[str, str]:
    """Merge follow-up answers from recent medical turns in this conversation."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT result_json FROM turns WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
            (conversation_id, limit),
        ).fetchall()
    merged: dict[str, str] = {}
    for row in reversed(rows):
        try:
            result = json.loads(row["result_json"] or "{}")
        except (TypeError, ValueError):
            continue
        if result.get("kind") not in (None, "medical"):
            continue
        answers = result.get("answers") or {}
        if isinstance(answers, dict):
            merged.update({str(key): str(value) for key, value in answers.items()})
    return merged
