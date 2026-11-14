"""One-click demo reset: wipe test data and seed a clean story."""

from __future__ import annotations

import sqlite3

from datetime import date, timedelta
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "health.db"
TABLES = ("turns", "conversations", "medications", "plan_checkins", "plans",
          "memory_facts", "memory_notes", "notifications", "crisis_followups",
          "profile", "response_cache", "cabinet_items", "push_subscriptions")


def reset(seed: bool = True) -> dict[str, Any]:
    from . import conversations, meds, profile as profile_store

    from . import db
    with db.connect(DB_PATH) as conn:
        for table in TABLES:
            try:
                conn.execute(f"DELETE FROM {table}")
            except sqlite3.OperationalError:
                pass
        conn.commit()

    seeded: dict[str, Any] = {}
    if seed:
        profile_store.update(30, "female", False, [], [])
        first = meds.add("感冒颗粒", "一包", "温水冲服", "饭后", 8, 2, "08:00",
                         total_doses=6, stock_total=12, stock_unit="包",
                         expiry_date=(date.today() + timedelta(days=30)).isoformat())
        meds.add("丹参片", "2片", "口服", "饭后", 12, 2, "09:00",
                 total_doses=10, stock_total=20, stock_unit="片",
                 expiry_date=(date.today() + timedelta(days=90)).isoformat())
        seeded = {"profile": True, "medications": 2,
                  "first_medication": first["name"] if first else None}
    return {"reset": True, "seeded": seeded}
