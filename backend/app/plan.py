"""One-week recovery plan: daily check-ins, adherence and follow-up reminders."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "health.db"
LOCK = threading.Lock()
PLAN_DAYS = 7


def _connect() -> sqlite3.Connection:
    from . import db
    return db.connect(DB_PATH)


def init() -> None:
    with LOCK, _connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS plans (
                   id TEXT PRIMARY KEY, symptoms TEXT, summary TEXT,
                   start_date TEXT, status TEXT DEFAULT 'active',
                   notified_d3 INTEGER DEFAULT 0, notified_d7 INTEGER DEFAULT 0,
                   notified_d14 INTEGER DEFAULT 0, phase INTEGER DEFAULT 1,
                   review_note TEXT, created_at TEXT)"""
        )
        plan_columns = {row[1] for row in conn.execute("PRAGMA table_info(plans)").fetchall()}
        for column, ddl in (("notified_d14", "INTEGER DEFAULT 0"),
                            ("phase", "INTEGER DEFAULT 1"), ("review_note", "TEXT"),
                            ("plan_json", "TEXT")):
            if column not in plan_columns:
                conn.execute(f"ALTER TABLE plans ADD COLUMN {column} {ddl}")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS plan_checkins (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   plan_id TEXT, check_date TEXT,
                   diet INTEGER DEFAULT 0, exercise INTEGER DEFAULT 0,
                   meds INTEGER DEFAULT 0, score INTEGER DEFAULT -1, note TEXT,
                   UNIQUE(plan_id, check_date))"""
        )
        checkin_columns = {row[1] for row in conn.execute("PRAGMA table_info(plan_checkins)").fetchall()}
        if "score" not in checkin_columns:
            conn.execute("ALTER TABLE plan_checkins ADD COLUMN score INTEGER DEFAULT -1")


def active() -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM plans WHERE status = 'active' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


THEME_LABELS = {
    "sleep": "睡眠恢复", "gi_upset": "胃肠恢复", "constipation": "排便调整",
    "diarrhea": "腹泻恢复", "fever": "发热恢复", "high_fever": "退热恢复",
    "cough": "咳嗽恢复", "sore_throat": "咽部恢复", "cold_recovery": "感冒恢复",
    "pain": "疼痛管理", "skin": "皮肤护理", "anxiety": "情绪调节",
    "hypertension": "血压管理", "diabetes": "血糖管理", "gout": "尿酸管理",
    "weight_loss": "减脂", "muscle_gain": "增肌", "anemia": "补铁",
    "menstrual": "经期照顾", "menstrual_irregular": "月经周期调理",
    "injury": "跌打恢复",
}


TAG_TASKS = {
    "sleep": ["固定起床时间（周末误差不超过 30 分钟）",
              "午睡不超过 20 分钟", "睡前 1 小时不刷手机",
              "记录昨晚入睡和醒来时间"],
    "hypertension": ["早晚各测一次血压并记录", "检查今天食盐不超过 5 g",
                     "快走 30 分钟，避免憋气用力"],
    "diabetes": ["记录空腹或餐后 2 小时血糖（有血糖仪时）",
                 "按蔬菜→蛋白→主食的顺序吃", "餐后散步 15 分钟",
                 "检查双脚有无破皮、水泡"],
    "gout": ["饮水达到 2000 ml", "记录今天是否吃了内脏、浓汤、海鲜或喝酒",
             "缓解期低冲击运动 20 分钟"],
    "gi_upset": ["记录三餐和腹胀/反酸评分", "每餐七分饱，饭后散步 10 分钟",
                 "睡前 3 小时不进食"],
    "constipation": ["记录排便次数和性状", "晨起一杯温水，纤维达到 25 g",
                     "快走 20 分钟或腹部按摩 5 分钟"],
    "diarrhea": ["少量多次口服补液盐", "记录腹泻次数和尿量",
                 "症状加重或便血时及时就医"],
    "fever": ["早晚各测一次体温", "分次补水 1500–2000 ml",
              "记录退热药使用时间和剂量"],
    "high_fever": ["每 4 小时测一次体温", "观察意识、呼吸和尿量",
                   "高热不退或精神差立即就医"],
    "cough": ["记录咳嗽频率和痰色", "缩唇呼吸 3 组",
              "避免冷空气和烟味"],
    "sore_throat": ["温盐水漱口 2 次", "少量多次喝温水",
                    "记录吞咽疼痛评分"],
    "injury": ["抬高患肢，观察肿胀和疼痛", "急性期冷敷 15 分钟（隔布）",
               "无痛范围内活动脚趾/关节"],
    "pain": ["记录疼痛评分和诱发动作", "温和拉伸 5 分钟",
             "疼痛加重时停止活动"],
    "skin": ["记录皮疹范围和瘙痒评分", "出汗后及时清洁并保湿",
             "避免抓挠和热水烫洗"],
    "menstrual": ["记录经量和疼痛评分", "热敷下腹 15 分钟",
                  "保证蛋白质和铁摄入"],
    "menstrual_irregular": ["记录月经日期和周期", "保证三餐和体重稳定",
                            "若停经超过 3 个月或伴异常出血，尽快妇科就诊"],
    "anemia": ["记录头晕、心慌发生时间", "富铁食物搭配维生素 C",
               "避免浓茶咖啡和铁剂同服"],
    "weight_loss": ["记录体重（每周同一时间）", "每餐一掌心蛋白质",
                    "快走或力量训练 30 分钟"],
    "muscle_gain": ["记录训练部位和重量", "每餐一掌心蛋白质",
                    "训练后补充碳水+蛋白"],
    "anxiety": ["4-7-8 呼吸 3 组", "记录焦虑评分和触发事件",
                "白天快走 20 分钟"],
}


def build_week(tags: list[str], diet: list[str], exercise: list[str],
               avoid: list[str], daily_actions: list[str] | None = None) -> dict[str, Any]:
    """Concrete 7-day schedule instead of generic '多喝水、多休息'."""
    tags = tags or []
    theme = THEME_LABELS.get(tags[0], "恢复") if tags else "恢复"
    diet = diet or []
    exercise = exercise or []
    avoid = avoid or []

    def diet_task(index: int) -> str:
        return diet[index % len(diet)] if diet else "按建议正常吃三餐，七分饱"

    def move_task(index: int) -> str:
        return exercise[index % len(exercise)] if exercise else "散步 10–15 分钟，以不疲劳为度"

    days = []
    plan = [
        (1, "记录基线", [f"记录今天的症状评分（0–10）", diet_task(0),
                        move_task(0) if exercise else "以休息为主，散步 10 分钟"]),
        (2, "稳定执行", [diet_task(1), "饮水 1500–2000 ml，分次喝",
                        move_task(0)]),
        (3, "小复盘", ["对比第 1 天和第 3 天评分",
                      f"饮食继续：{diet_task(2)}",
                      "活动增加 5 分钟；不适就停"]),
        (4, "巩固习惯", [diet_task(3), "保证一掌心蛋白质", move_task(1)]),
        (5, "查漏补缺", ["检查睡眠、饮水和用药是否规律", diet_task(4),
                        "睡前 1 小时不刷手机"]),
        (6, "准备复诊", ["记录 3 天平均评分和仍在的症状",
                        "整理正在吃的药和剂量", "必要时提前预约医生"]),
        (7, "一周总结", ["对比第 1 天与今天评分", "评分下降≥2 分：继续下一周",
                        "无改善、加重或出现红旗：复诊"]),
    ]
    extra = TAG_TASKS.get(tags[0], []) if tags else []
    personal = list(daily_actions or [])
    for day, focus, tasks in plan:
        daily = list(tasks)
        if extra:
            daily.append(extra[(day - 1) % len(extra)])
        if personal:
            daily.append(personal[(day - 1) % len(personal)])
        days.append({"day": day, "focus": focus,
                     "tasks": [item for item in daily if item]})
    red_flags = ["胸痛、呼吸困难、意识改变", "高热不退超过 3 天",
                 "症状明显加重或出现新的剧烈疼痛"]
    if "injury" in tags:
        red_flags.insert(0, "畸形、完全不能活动、伤口深或大出血")
    if "anxiety" in tags or "sleep" in tags:
        red_flags.insert(0, "出现伤害自己的想法，请立即联系身边人或拨打 12356/120")
    return {"theme": theme, "days": days, "avoid": avoid[:4],
            "red_flags": red_flags[:4],
            "review": "第 7 天：好转则延长一周；无改善或加重则复诊。"}


def ensure(symptoms: str, lifestyle: dict[str, Any] | None) -> dict[str, Any] | None:
    """Create a plan from the latest advice, or keep the current one."""
    plan = active()
    if plan:
        started = datetime.fromisoformat(plan["start_date"]).date()
        if (date.today() - started).days < PLAN_DAYS:
            return None
    if plan:
        finish(plan["id"])
    lifestyle = lifestyle or {}
    if not (lifestyle.get("diet") or lifestyle.get("exercise")):
        return None
    theme = THEME_LABELS.get((lifestyle.get("tags") or [""])[0], "恢复")
    summary = f"{theme}计划。饮食：" + "；".join((lifestyle.get("diet") or [])[:2])
    if lifestyle.get("exercise"):
        summary += "。运动：" + "；".join(lifestyle["exercise"][:2])
    if lifestyle.get("notes"):
        summary += "。个人提醒：" + "；".join(lifestyle["notes"][:3])
    week = build_week(lifestyle.get("tags") or [], lifestyle.get("diet") or [],
                      lifestyle.get("exercise") or [], lifestyle.get("avoid") or [],
                      lifestyle.get("daily_actions") or [])
    details = json.dumps({"week": week, "diet": lifestyle.get("diet") or [],
                          "exercise": lifestyle.get("exercise") or [],
                          "avoid": lifestyle.get("avoid") or [],
                          "daily_actions": lifestyle.get("daily_actions") or []},
                         ensure_ascii=False)
    plan_id = uuid.uuid4().hex[:12]
    with LOCK, _connect() as conn:
        conn.execute(
            "INSERT INTO plans (id, symptoms, summary, start_date, status, created_at, plan_json)"
            " VALUES (?, ?, ?, ?, 'active', ?, ?)",
            (plan_id, symptoms[:120], summary[:400], date.today().isoformat(),
             datetime.now().isoformat(timespec="seconds"), details),
        )
    return active()


def finish(plan_id: str) -> None:
    with LOCK, _connect() as conn:
        conn.execute("UPDATE plans SET status = 'done' WHERE id = ?", (plan_id,))


def checkin(plan_id: str, diet: bool, exercise: bool, meds: bool, note: str = "",
            score: int | None = None) -> dict[str, Any] | None:
    today = date.today().isoformat()
    score_value = -1 if score is None else max(0, min(10, int(score)))
    with LOCK, _connect() as conn:
        conn.execute(
            """INSERT INTO plan_checkins (plan_id, check_date, diet, exercise, meds, score, note)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(plan_id, check_date) DO UPDATE SET
                   diet = excluded.diet, exercise = excluded.exercise,
                   meds = excluded.meds, score = excluded.score, note = excluded.note""",
            (plan_id, today, int(diet), int(exercise), int(meds), score_value, note[:200]),
        )
    return detail(plan_id)


def checkins(plan_id: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM plan_checkins WHERE plan_id = ? ORDER BY check_date",
            (plan_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def trend(items: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [item for item in items if int(item.get("score", -1)) >= 0]
    if len(scored) < 2:
        return {"label": "还不够判断", "delta": 0, "scores": scored}
    first = int(scored[0]["score"])
    last = int(scored[-1]["score"])
    delta = last - first
    if delta <= -2:
        label = "在好转"
    elif delta >= 2:
        label = "变差了"
    else:
        label = "差不多"
    return {"label": label, "delta": delta, "scores": scored}


def detail(plan_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
    if row is None:
        return None
    plan = dict(row)
    week = None
    if plan.get("plan_json"):
        try:
            week = json.loads(plan["plan_json"]).get("week")
        except (TypeError, ValueError):
            week = None
    if not week:
        # Old plans created before the upgrade: build a fresh week from their symptoms.
        from . import lifestyle as lifestyle_store
        current = lifestyle_store.select(plan.get("symptoms") or "")
        week = build_week(current.get("tags") or [], current.get("diet") or [],
                          current.get("exercise") or [], current.get("avoid") or [])
    started = datetime.fromisoformat(plan["start_date"]).date()
    elapsed = (date.today() - started).days
    days = max(1, min(PLAN_DAYS, elapsed + 1))
    items = checkins(plan_id)
    today_item = next((item for item in items if item["check_date"] == date.today().isoformat()), None)
    done_days = sum(1 for item in items if item["diet"] and item["exercise"])
    trend_info = trend(items)
    return {
        "plan": plan,
        "days": days,
        "total_days": PLAN_DAYS,
        "checkins": items,
        "today": today_item,
        "adherence": round(done_days / PLAN_DAYS * 100),
        "finished": plan["status"] != "active",
        "trend": trend_info,
        "review_note": plan.get("review_note"),
        "phase": plan.get("phase") or 1,
        "week": week,
    }


def due(now: datetime | None = None) -> list[dict[str, Any]]:
    """Day-3 encouragement and day-7 follow-up reminder."""
    now = now or datetime.now()
    plan = active()
    if not plan:
        return []
    started = datetime.fromisoformat(plan["start_date"]).date()
    elapsed = (now.date() - started).days
    day = elapsed + 1
    fired: list[dict[str, Any]] = []
    with LOCK, _connect() as conn:
        if day >= 3 and not plan["notified_d3"]:
            conn.execute("UPDATE plans SET notified_d3 = 1 WHERE id = ?", (plan["id"],))
            fired.append({"plan_id": plan["id"], "kind": "d3", "day": day,
                          "symptoms": plan["symptoms"]})
        if day >= PLAN_DAYS and not plan["notified_d7"]:
            items = conn.execute(
                "SELECT score FROM plan_checkins WHERE plan_id = ? ORDER BY check_date",
                (plan["id"],)).fetchall()
            scored = [int(row["score"]) for row in items if int(row["score"]) >= 0]
            improved = len(scored) >= 2 and scored[-1] <= scored[0] - 2
            if improved:
                conn.execute(
                    "UPDATE plans SET notified_d7 = 1, notified_d14 = 0, phase = 2,"
                    " review_note = ? WHERE id = ?",
                    ("一周有改善，已自动延长一周；继续保持。", plan["id"]))
                fired.append({"plan_id": plan["id"], "kind": "d7_good", "day": day,
                              "symptoms": plan["symptoms"]})
            else:
                conn.execute(
                    "UPDATE plans SET notified_d7 = 1, notified_d14 = 1,"
                    " review_note = ? WHERE id = ?",
                    ("一周没有明显改善，建议复诊或咨询医生。", plan["id"]))
                fired.append({"plan_id": plan["id"], "kind": "d7_review", "day": day,
                              "symptoms": plan["symptoms"]})
        if day >= PLAN_DAYS * 2 and plan["phase"] == 2 and not plan["notified_d14"]:
            conn.execute("UPDATE plans SET notified_d14 = 1 WHERE id = ?", (plan["id"],))
            fired.append({"plan_id": plan["id"], "kind": "d14", "day": day,
                          "symptoms": plan["symptoms"]})
        conn.commit()
    return fired
