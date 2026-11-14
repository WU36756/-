"""Single-user health profile: age, sex, pregnancy, allergies, conditions."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "health.db"
LOCK = threading.Lock()

DEFAULT = {
    "age": None,
    "sex": "",
    "pregnant": False,
    "allergies": [],
    "conditions": [],
    "diet_pref": "",
    "avoid_foods": "",
    "meal_style": "",
    "activity_level": "",
    "updated_at": None,
}


def _connect() -> sqlite3.Connection:
    from . import db
    return db.connect(DB_PATH)


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Per-user databases can predate the profile-extras migration."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS profile (
               id INTEGER PRIMARY KEY CHECK (id = 1),
               age INTEGER, sex TEXT, pregnant INTEGER,
               allergies TEXT, conditions TEXT, updated_at TEXT,
               diet_pref TEXT, avoid_foods TEXT, meal_style TEXT,
               activity_level TEXT)"""
    )
    profile_columns = {row[1] for row in conn.execute("PRAGMA table_info(profile)").fetchall()}
    for column, ddl in (("diet_pref", "TEXT"), ("avoid_foods", "TEXT"),
                        ("meal_style", "TEXT"), ("activity_level", "TEXT")):
        if column not in profile_columns:
            conn.execute(f"ALTER TABLE profile ADD COLUMN {column} {ddl}")


def init() -> None:
    with LOCK, _connect() as conn:
        _ensure_columns(conn)


def get() -> dict[str, Any]:
    with _connect() as conn:
        _ensure_columns(conn)
        row = conn.execute("SELECT * FROM profile WHERE id = 1").fetchone()
    if row is None:
        return dict(DEFAULT)
    return {
        "age": row["age"],
        "sex": row["sex"] or "",
        "pregnant": bool(row["pregnant"]),
        "allergies": json.loads(row["allergies"] or "[]"),
        "conditions": json.loads(row["conditions"] or "[]"),
        "diet_pref": row["diet_pref"] or "",
        "avoid_foods": row["avoid_foods"] or "",
        "meal_style": row["meal_style"] or "",
        "activity_level": row["activity_level"] or "",
        "updated_at": row["updated_at"],
    }


def remove_fact(fact_type: str, value: str) -> dict[str, Any]:
    current = get()
    allergies = list(current.get("allergies") or [])
    conditions = list(current.get("conditions") or [])
    pregnant = bool(current.get("pregnant"))
    if fact_type == "allergy":
        allergies = [item for item in allergies if item != value]
    elif fact_type == "condition":
        conditions = [item for item in conditions if item != value]
    elif fact_type == "pregnancy":
        pregnant = False
    return update(current.get("age"), current.get("sex"), pregnant, allergies, conditions,
                  current.get("diet_pref", ""), current.get("avoid_foods", ""),
                  current.get("meal_style", ""), current.get("activity_level", ""))


def update(age: int | None, sex: str, pregnant: bool,
           allergies: list[str], conditions: list[str],
           diet_pref: str = "", avoid_foods: str = "",
           meal_style: str = "", activity_level: str = "") -> dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    with LOCK, _connect() as conn:
        _ensure_columns(conn)
        conn.execute(
            """INSERT INTO profile (id, age, sex, pregnant, allergies, conditions,
                   diet_pref, avoid_foods, meal_style, activity_level, updated_at)
               VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET age = excluded.age, sex = excluded.sex,
                   pregnant = excluded.pregnant, allergies = excluded.allergies,
                   conditions = excluded.conditions, diet_pref = excluded.diet_pref,
                   avoid_foods = excluded.avoid_foods, meal_style = excluded.meal_style,
                   activity_level = excluded.activity_level, updated_at = excluded.updated_at""",
            (age, sex, int(pregnant), json.dumps(allergies, ensure_ascii=False),
             json.dumps(conditions, ensure_ascii=False), diet_pref, avoid_foods,
             meal_style, activity_level, now),
        )
    return get()
