"""Medications: reminders + course progress + stock/expiry in one record."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "health.db"
LOCK = threading.Lock()
GRACE = timedelta(hours=2)
FOLLOWUP = timedelta(minutes=3)


def _connect() -> sqlite3.Connection:
    from . import db
    return db.connect(DB_PATH)


def init() -> None:
    with LOCK, _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS medications (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                dose TEXT,
                method TEXT,
                times TEXT,
                note TEXT,
                active INTEGER DEFAULT 1,
                created_at TEXT,
                last_fired TEXT,
                interval_hours REAL,
                doses_per_day INTEGER,
                start_time TEXT,
                pending_at TEXT,
                pending_stage INTEGER,
                paused_until TEXT,
                total_doses INTEGER,
                taken INTEGER DEFAULT 0,
                completed INTEGER DEFAULT 0,
                stock_total REAL,
                stock_unit TEXT,
                stock_remaining REAL,
                expiry_date TEXT
            )
            """
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(medications)").fetchall()}
        for column, ddl in (
            ("interval_hours", "REAL"), ("doses_per_day", "INTEGER"),
            ("start_time", "TEXT"), ("pending_at", "TEXT"), ("pending_stage", "INTEGER"),
            ("paused_until", "TEXT"), ("total_doses", "INTEGER"), ("taken", "INTEGER DEFAULT 0"),
            ("completed", "INTEGER DEFAULT 0"), ("stock_total", "REAL"), ("stock_unit", "TEXT"),
            ("stock_remaining", "REAL"), ("expiry_date", "TEXT"),
        ):
            if column not in columns:
                conn.execute(f"ALTER TABLE medications ADD COLUMN {column} {ddl}")
        # migrate legacy time-only rows
        rows = conn.execute(
            "SELECT id, times, start_time FROM medications WHERE start_time IS NULL"
        ).fetchall()
        for row in rows:
            try:
                slots = json.loads(row["times"] or "[]")
            except json.JSONDecodeError:
                slots = []
            if slots:
                doses = max(1, min(len(slots), 12))
                conn.execute(
                    "UPDATE medications SET start_time = ?, doses_per_day = ?, interval_hours = ?"
                    " WHERE id = ?", (slots[0], doses, round(24 / doses, 2), row["id"]))
        # merge any old cabinet items into the unified table, then clear them
        try:
            cabinet_rows = conn.execute("SELECT name, total, taken FROM cabinet_items").fetchall()
        except sqlite3.OperationalError:
            cabinet_rows = []
        for row in cabinet_rows:
            existing = conn.execute(
                "SELECT id FROM medications WHERE name = ? ORDER BY created_at LIMIT 1",
                (row["name"],)).fetchone()
            if existing:
                conn.execute(
                    "UPDATE medications SET total_doses = ?, taken = ?,"
                    " completed = ? WHERE id = ?",
                    (row["total"], row["taken"], int(row["taken"] >= row["total"]),
                     existing["id"]))
            else:
                conn.execute(
                    "INSERT INTO medications (id, name, dose, method, times, note, active,"
                    " created_at, interval_hours, doses_per_day, start_time, total_doses,"
                    " taken, completed) VALUES (?, ?, '', '', '[]', '', 1, ?, 8, 1, '08:00', ?, ?, ?)",
                    (uuid.uuid4().hex[:12], row["name"],
                     datetime.now().isoformat(timespec="seconds"), row["total"], row["taken"],
                     int(row["taken"] >= row["total"])))
        if cabinet_rows:
            conn.execute("DELETE FROM cabinet_items")
        conn.commit()


def _row(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["times"] = json.loads(item.get("times") or "[]")
    item["active"] = bool(item.get("active"))
    item["completed"] = bool(item.get("completed"))
    item["taken"] = int(item.get("taken") or 0)
    total = item.get("total_doses")
    item["balls"] = min(total, item["taken"]) if total else 0
    if item["completed"] and total:
        item["balls"] = total
    item["days_to_expiry"] = None
    if item.get("expiry_date"):
        try:
            item["days_to_expiry"] = (date.fromisoformat(item["expiry_date"]) - date.today()).days
        except ValueError:
            item["days_to_expiry"] = None
    return item


def _clean_start(value: str) -> str | None:
    try:
        hour, minute = str(value).strip().split(":")[:2]
        return f"{int(hour):02d}:{int(minute):02d}"
    except (ValueError, AttributeError):
        return None


def schedule(item: dict[str, Any]) -> list[str]:
    start = _clean_start(item.get("start_time") or "")
    interval = float(item.get("interval_hours") or 0)
    doses = int(item.get("doses_per_day") or 0)
    if not start or interval <= 0 or doses <= 0:
        return []
    hour, minute = (int(part) for part in start.split(":"))
    base = datetime.combine(date.today(), time(hour, minute))
    times = []
    for index in range(min(doses, 12)):
        moment = base + timedelta(hours=interval * index)
        times.append(moment.strftime("%H:%M") + ("（次日）" if moment.date() != date.today() else ""))
    return times


def add(name: str, dose: str = "", method: str = "", note: str = "",
        interval_hours: float = 8, doses_per_day: int = 2, start_time: str = "08:00",
        total_doses: int | None = None, stock_total: float | None = None,
        stock_unit: str = "盒", expiry_date: str = "") -> dict[str, Any] | None:
    start = _clean_start(start_time)
    try:
        interval = float(interval_hours)
        doses = int(doses_per_day)
    except (TypeError, ValueError):
        return None
    if not start or not 0.5 <= interval <= 24 or not 1 <= doses <= 12:
        return None
    item_id = uuid.uuid4().hex[:12]
    total = int(total_doses) if total_doses else None
    stock = float(stock_total) if stock_total is not None else None
    with LOCK, _connect() as conn:
        conn.execute(
            "INSERT INTO medications (id, name, dose, method, times, note, active, created_at,"
            " interval_hours, doses_per_day, start_time, total_doses, taken, completed,"
            " stock_total, stock_unit, stock_remaining, expiry_date)"
            " VALUES (?, ?, ?, ?, '[]', ?, 1, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?)",
            (item_id, name.strip(), dose.strip(), method.strip(), note.strip(),
             datetime.now().isoformat(timespec="seconds"), interval, doses, start,
             total, stock, stock_unit.strip() or "盒", stock, expiry_date or None),
        )
        row = conn.execute("SELECT * FROM medications WHERE id = ?", (item_id,)).fetchone()
    return _row(row)


def update(item_id: str, **fields: Any) -> dict[str, Any] | None:
    allowed = {"name", "dose", "method", "note", "interval_hours", "doses_per_day",
               "start_time", "total_doses", "stock_total", "stock_unit",
               "stock_remaining", "expiry_date"}
    clean = {key: value for key, value in fields.items() if key in allowed}
    if not clean:
        return None
    if "start_time" in clean:
        start = _clean_start(str(clean["start_time"]))
        if not start:
            return None
        clean["start_time"] = start
    assignments = ", ".join(f"{key} = ?" for key in clean)
    with LOCK, _connect() as conn:
        cursor = conn.execute(
            f"UPDATE medications SET {assignments} WHERE id = ?",
            [*clean.values(), item_id])
    if cursor.rowcount == 0:
        return None
    with _connect() as conn:
        row = conn.execute("SELECT * FROM medications WHERE id = ?", (item_id,)).fetchone()
    return _row(row)


def list_all() -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM medications ORDER BY created_at DESC").fetchall()
    return [_row(row) for row in rows]


def list_active() -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM medications WHERE active = 1").fetchall()
    return [_row(row) for row in rows]


def delete(item_id: str) -> bool:
    with LOCK, _connect() as conn:
        cursor = conn.execute("DELETE FROM medications WHERE id = ?", (item_id,))
    return cursor.rowcount > 0


def take(item_id: str) -> dict[str, Any] | None:
    """Record one dose: progress + stock, clear the pending reminder."""
    with LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM medications WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            return None
        item = _row(row)
        taken = item["taken"] + 1
        total = item.get("total_doses")
        completed = int(bool(total) and taken >= total)
        if total:
            taken = min(taken, total)
        stock = item.get("stock_remaining")
        if stock is not None:
            stock = max(0.0, float(stock) - 1)
        conn.execute(
            "UPDATE medications SET taken = ?, completed = ?, stock_remaining = ?,"
            " pending_at = NULL, pending_stage = NULL WHERE id = ?",
            (taken, completed, stock, item_id),
        )
        row = conn.execute("SELECT * FROM medications WHERE id = ?", (item_id,)).fetchone()
    result = _row(row)
    result["just_completed"] = bool(completed and not item["completed"])
    return result


def due(now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or datetime.now()
    fired: list[dict[str, Any]] = []
    with LOCK, _connect() as conn:
        now_text = now.isoformat(timespec="seconds")
        conn.execute("UPDATE medications SET paused_until = NULL WHERE paused_until <= ?",
                     (now_text,))
        pending = conn.execute(
            "SELECT * FROM medications WHERE pending_at IS NOT NULL AND pending_at <= ?",
            (now_text,)).fetchall()
        for row in pending:
            item = _row(row)
            item["stage"] = 2
            item["due_time"] = (item.get("pending_at") or "")[11:16]
            conn.execute("UPDATE medications SET pending_at = NULL, pending_stage = NULL"
                         " WHERE id = ?", (item["id"],))
            fired.append(item)
        rows = conn.execute(
            "SELECT * FROM medications WHERE active = 1"
            " AND (paused_until IS NULL OR paused_until <= ?)", (now_text,)).fetchall()
        for row in rows:
            item = _row(row)
            start = _clean_start(item.get("start_time") or "")
            try:
                interval = float(item.get("interval_hours") or 0)
                doses = int(item.get("doses_per_day") or 0)
            except (TypeError, ValueError):
                continue
            if not start or interval <= 0 or doses <= 0:
                continue
            hour, minute = (int(part) for part in start.split(":"))
            for day_offset in (-1, 0):
                base_date = (now + timedelta(days=day_offset)).date()
                base = datetime.combine(base_date, time(hour, minute))
                for index in range(min(doses, 12)):
                    target = base + timedelta(hours=interval * index)
                    key = f"{target.date().isoformat()}#{index}"
                    if item.get("last_fired") == key:
                        continue
                    if now < target or now - target > GRACE:
                        continue
                    pending_at = (now + FOLLOWUP).isoformat(timespec="seconds")
                    conn.execute(
                        "UPDATE medications SET last_fired = ?, pending_at = ?, pending_stage = 1"
                        " WHERE id = ?", (key, pending_at, item["id"]))
                    item["due_time"] = target.strftime("%H:%M")
                    item["last_fired"] = key
                    item["stage"] = 1
                    fired.append(dict(item))
                    break
                else:
                    continue
                break
        conn.commit()
    return fired


def pause(item_id: str, minutes: int = 30) -> bool:
    until = (datetime.now() + timedelta(minutes=max(1, minutes))).isoformat(timespec="seconds")
    with LOCK, _connect() as conn:
        cursor = conn.execute(
            "UPDATE medications SET paused_until = ?, pending_at = NULL, pending_stage = NULL"
            " WHERE id = ?", (until, item_id))
    return cursor.rowcount > 0


def skip(item_id: str) -> bool:
    with _connect() as conn:
        row = conn.execute("SELECT interval_hours FROM medications WHERE id = ?",
                           (item_id,)).fetchone()
    hours = float(row["interval_hours"] or 1) if row else 1
    return pause(item_id, int(hours * 60))


def ack(item_id: str) -> bool:
    with LOCK, _connect() as conn:
        cursor = conn.execute(
            "UPDATE medications SET pending_at = NULL, pending_stage = NULL WHERE id = ?",
            (item_id,))
    return cursor.rowcount > 0


def fire_now(item_id: str) -> dict[str, Any] | None:
    with LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM medications WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            return None
        pending_at = (datetime.now() + FOLLOWUP).isoformat(timespec="seconds")
        conn.execute("UPDATE medications SET pending_at = ?, pending_stage = 1 WHERE id = ?",
                     (pending_at, item_id))
    item = _row(row)
    item["stage"] = 1
    return item
