"""Cross-session memory with negation handling and deletion."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "health.db"
LOCK = threading.Lock()

CONDITIONS = ("高血压", "糖尿病", "胃溃疡", "心脏病", "肝病", "肾病", "哮喘", "痛风", "甲状腺")
ALLERGY_PATTERN = re.compile(r"(?:对|对)([\u4e00-\u9fa5A-Za-z0-9]{2,12}?)(?:过敏|不耐受)")
PREGNANT_WORDS = ("怀孕", "孕期", "孕妇", "妊娠", "有了宝宝")
NEGATIONS = ("没有", "没", "不", "无", "并非", "否认", "别", "不是")


def _negated(text: str, index: int) -> bool:
    prefix = text[max(0, index - 8):index]
    return any(word in prefix for word in NEGATIONS)


def _connect() -> sqlite3.Connection:
    from . import db
    return db.connect(DB_PATH)


def init() -> None:
    with LOCK, _connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS memory_facts (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   fact_type TEXT, value TEXT, created_at TEXT,
                   UNIQUE(fact_type, value))"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS memory_notes (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   conversation_id TEXT, symptoms TEXT, summary TEXT, created_at TEXT)"""
        )


def _add_fact(fact_type: str, value: str) -> bool:
    with LOCK, _connect() as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO memory_facts (fact_type, value, created_at) VALUES (?, ?, ?)",
            (fact_type, value, datetime.now().isoformat(timespec="seconds")),
        )
    return cursor.rowcount > 0


def facts() -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, fact_type, value FROM memory_facts ORDER BY id"
        ).fetchall()
    return [dict(row) for row in rows]


def update_fact(fact_id: int, value: str) -> dict[str, Any] | None:
    value = (value or "").strip()[:40]
    if not value:
        return None
    with LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM memory_facts WHERE id = ?", (fact_id,)).fetchone()
        if row is None:
            return None
        try:
            conn.execute("UPDATE memory_facts SET value = ? WHERE id = ?", (value, fact_id))
        except sqlite3.IntegrityError:
            return None
    return {"id": fact_id, "fact_type": row["fact_type"], "value": value,
            "old_value": row["value"]}


def delete_fact(fact_id: int) -> dict[str, Any] | None:
    with LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM memory_facts WHERE id = ?", (fact_id,)).fetchone()
        if row is None:
            return None
        conn.execute("DELETE FROM memory_facts WHERE id = ?", (fact_id,))
    return dict(row)


def observe(text: str) -> dict[str, Any]:
    """Extract durable facts, skipping negated statements."""
    text = text or ""
    new: list[dict[str, str]] = []
    for match in ALLERGY_PATTERN.finditer(text):
        if _negated(text, match.start(1)):
            continue
        value = match.group(1).strip()
        if len(value) >= 2 and _add_fact("allergy", value):
            new.append({"type": "allergy", "value": value})
    for condition in CONDITIONS:
        index = text.find(condition)
        if index >= 0 and not _negated(text, index) and _add_fact("condition", condition):
            new.append({"type": "condition", "value": condition})
    for word in PREGNANT_WORDS:
        index = text.find(word)
        if index >= 0 and not _negated(text, index) and _add_fact("pregnancy", "孕期"):
            new.append({"type": "pregnancy", "value": "孕期"})
    return {"new": new}


def sync_profile(profile_module: Any) -> None:
    items = facts()
    allergies = [item["value"] for item in items if item["fact_type"] == "allergy"]
    conditions = [item["value"] for item in items if item["fact_type"] == "condition"]
    pregnancy = any(item["fact_type"] == "pregnancy" for item in items)
    if not (allergies or conditions or pregnancy):
        return
    current = profile_module.get()
    merged_allergies = list(dict.fromkeys((current.get("allergies") or []) + allergies))
    merged_conditions = list(dict.fromkeys((current.get("conditions") or []) + conditions))
    if (merged_allergies != (current.get("allergies") or [])
            or merged_conditions != (current.get("conditions") or [])
            or (pregnancy and not current.get("pregnant"))):
        profile_module.update(current.get("age"), current.get("sex"),
                              bool(current.get("pregnant") or pregnancy),
                              merged_allergies, merged_conditions)


def add_note(conversation_id: str | None, symptoms: str, summary: str) -> None:
    with LOCK, _connect() as conn:
        conn.execute(
            "INSERT INTO memory_notes (conversation_id, symptoms, summary, created_at) VALUES (?, ?, ?, ?)",
            (conversation_id or "", symptoms[:120], summary[:200],
             datetime.now().isoformat(timespec="seconds")),
        )


def clear_notes() -> int:
    with LOCK, _connect() as conn:
        cursor = conn.execute("DELETE FROM memory_notes")
    return cursor.rowcount


def recent_notes(limit: int = 3) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT symptoms, summary, created_at FROM memory_notes ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def context_text() -> str:
    lines = []
    for item in facts():
        if item["fact_type"] == "allergy":
            lines.append(f"过敏：{item['value']}")
        elif item["fact_type"] == "condition":
            lines.append(f"慢病：{item['value']}")
        elif item["fact_type"] == "pregnancy":
            lines.append("孕期")
    for note in recent_notes():
        lines.append(f"上次：{note['symptoms']} → {note['summary']}")
    return "；".join(lines)
