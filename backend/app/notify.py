"""Shared notification queue: page and background notifier both consume it."""

from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "health.db"
LOCK = threading.Lock()
_started = False


def _connect() -> sqlite3.Connection:
    from . import db
    return db.connect(DB_PATH)


def init() -> None:
    with LOCK, _connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS notifications (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   kind TEXT, title TEXT, body TEXT, payload TEXT,
                   created_at TEXT, read INTEGER DEFAULT 0)"""
        )


def enqueue(kind: str, title: str, body: str, payload: str = "") -> bool:
    with LOCK, _connect() as conn:
        exists = conn.execute(
            "SELECT 1 FROM notifications WHERE kind = ? AND body = ? AND read = 0",
            (kind, body),
        ).fetchone()
        if exists:
            return False
        conn.execute(
            "INSERT INTO notifications (kind, title, body, payload, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (kind, title, body, payload, datetime.now().isoformat(timespec="seconds")),
        )
    # 跨设备 / 关页推送
    try:
        from . import push as push_module

        push_module.send(title, body, tag=kind)
    except Exception:
        pass
    return True


def unread() -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM notifications WHERE read = 0 ORDER BY id"
        ).fetchall()
    return [dict(row) for row in rows]


def ack(ids: list[int]) -> int:
    if not ids:
        return 0
    placeholders = ",".join("?" for _ in ids)
    with LOCK, _connect() as conn:
        cursor = conn.execute(
            f"UPDATE notifications SET read = 1 WHERE id IN ({placeholders})", ids
        )
    return cursor.rowcount


def _scan() -> None:
    from . import crisis, meds, plan

    for item in meds.due():
        stage = item.get("stage", 1)
        dose = item.get("dose") or ""
        method = item.get("method") or ""
        prefix = "大郎，该吃药了！" if stage == 1 else "大郎，该吃药了！别忘了哦～"
        body = f"{prefix}{item['name']} {dose}，{method}".strip()
        enqueue(f"med:{item['id']}", "⏰ 该吃药了" if stage == 1 else "⏰ 第二次提醒",
                body, payload=str(stage))
    for item in plan.due():
        kind = item["kind"]
        if kind == "d3":
            enqueue("plan:d3", "🌱 康复计划",
                    "已经坚持 3 天啦，今天感觉怎么样？记得打卡。")
        elif kind == "d7_good":
            enqueue("plan:d7_good", "🌱 康复计划",
                    "一周有改善，已自动延长一周；继续保持，别松懈。")
        elif kind == "d7_review":
            enqueue("plan:d7_review", "🌱 康复计划",
                    "一周没有明显改善，建议复诊或咨询医生，不要硬扛。")
        elif kind == "d14":
            enqueue("plan:d14", "🌱 康复计划",
                    "两周了：恢复得怎么样？如果还没好，建议复诊收尾。")
    for item in crisis.due():
        enqueue("crisis", "💛 我在惦记你",
                "昨天你提到状态不太好，今天好一点了吗？不用急着回答，先照顾自己。")


def scan_session() -> None:
    """Run the notification scan inside the current browser session DB."""
    _scan()


def _scan_sessions() -> None:
    from . import db
    for db_file in db.USERS_DIR.glob("*.db"):
        token = db.CURRENT_USER.set(db_file.stem)
        try:
            _scan()
        except Exception:
            pass
        finally:
            db.CURRENT_USER.reset(token)


def start() -> None:
    """Background scanner so reminders exist even when the page is closed."""
    global _started
    if _started:
        return
    _started = True

    def loop() -> None:
        while True:
            try:
                _scan()
            except Exception:
                pass
            try:
                _scan_sessions()
            except Exception:
                pass
            time.sleep(15)

    threading.Thread(target=loop, daemon=True, name="notification-scanner").start()
