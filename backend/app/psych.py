"""Emotional support: warm responses, practical steps, and a crisis path."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DATA_PATH = Path(__file__).resolve().parent / "data" / "psych.json"

MEDICAL_WORDS = ("发烧", "发热", "咳嗽", "咽痛", "腹痛", "腹泻", "呕吐", "皮疹", "瘙痒",
                 "头痛", "头晕", "月经", "痛经", "血压", "血糖", "便秘", "药")

CRISIS_WORDS = ("自杀", "不想活", "活不下去", "自残", "割腕", "结束生命", "跳楼",
                "轻生", "伤害自己", "死了算了", "想死", "撑不下去", "活着没意义",
                "没希望", "想消失", "解脱", "不想醒", "活着好累", "没有意义")

HIGH_RISK = ("已经买了", "写好了", "遗书", "计划", "今晚", "马上", "站在", "楼顶",
             "割了", "吞了", "吃药自杀", "告别")
MEDIUM_RISK = ("想死", "不想活", "自杀", "自残", "割腕", "轻生", "结束生命",
               "伤害自己", "死了算了", "跳楼")
LOW_RISK = ("撑不下去", "活着没意义", "没希望", "想消失", "解脱", "不想醒",
            "活着好累", "没有意义")


def crisis_level(text: str) -> str:
    text = text or ""
    if any(word in text for word in HIGH_RISK):
        return "high"
    if any(word in text for word in MEDIUM_RISK):
        return "medium"
    if any(word in text for word in LOW_RISK):
        return "low"
    return "none"


def _data() -> dict[str, Any]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def sources() -> dict[str, Any]:
    return _data()["sources"]


def topics() -> list[dict[str, Any]]:
    return _data()["topics"]


def _topic_by_id(topic_id: str) -> dict[str, Any] | None:
    return next((item for item in topics() if item["id"] == topic_id), None)


def is_crisis(text: str) -> bool:
    return any(word in (text or "") for word in CRISIS_WORDS)


def _score(text: str, topic: dict[str, Any]) -> int:
    return sum(1 for word in topic.get("keywords", []) if word in text)


PRIORITY = {"crisis": 5, "bullying": 3}


def pick_topic(text: str) -> dict[str, Any] | None:
    text = text or ""
    best, best_score = None, 0
    for topic in topics():
        score = _score(text, topic) * PRIORITY.get(topic["id"], 1)
        if score > best_score:
            best, best_score = topic, score
    if best_score == 0:
        best = _topic_by_id("low_mood")
    return best


def should_route(text: str) -> bool:
    text = text or ""
    if is_crisis(text):
        return True
    if not pick_topic(text):
        return False
    if any(word in text for word in MEDICAL_WORDS):
        return False
    return any(word in text for topic in topics() for word in topic.get("keywords", []))


def respond(text: str) -> dict[str, Any] | None:
    text = text or ""
    if is_crisis(text):
        topic = _topic_by_id("crisis")
    else:
        topic = pick_topic(text)
    if topic is None:
        return None
    data_sources = sources()
    # rotate the warm opening line deterministically by input
    empathy_lines = topic.get("empathy", [])
    index = sum(ord(char) for char in text) % max(1, len(empathy_lines))
    ordered = empathy_lines[index:] + empathy_lines[:index]
    level = crisis_level(text) if topic["id"] == "crisis" else "none"
    suggestions = list(topic.get("suggestions", []))
    if topic["id"] == "crisis":
        if level == "high":
            suggestions = [
                "请立刻拨打 120 / 110，或让身边的人陪你去最近的急诊。",
                "把可能伤害自己的东西交给别人，不要一个人待着。",
            ] + suggestions
        elif level == "low":
            suggestions = [
                "先找个安全的地方坐下来，慢慢呼吸，给自己几分钟。",
                "如果这种想法变强，请拨打 12356 或告诉信任的人。",
            ] + suggestions
        from . import crisis as crisis_store

        try:
            crisis_store.init()
            crisis_store.record(level)
        except Exception:
            pass
    return {
        "kind": "psych",
        "topic": {"id": topic["id"], "name": topic["name"]},
        "risk_level": level,
        "hotlines": topic.get("hotlines", []),
        "empathy": ordered[:2],
        "suggestions": suggestions,
        "professional": topic.get("professional", []),
        "sources": [
            {"title": data_sources[key]["title"], "url": data_sources[key]["url"],
             "zh": data_sources[key]["zh"]}
            for key in topic.get("sources", []) if key in data_sources
        ],
        "crisis": topic["id"] == "crisis",
        "trace": [
            {"step": "psych", "agent": "心理支持 Agent", "title": "先接住情绪，再给办法",
             "summary": f"识别为「{topic['name']}」" + ("，启动危机支持" if topic["id"] == "crisis" else "")},
        ],
    }
