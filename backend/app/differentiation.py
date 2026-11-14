"""Distinguish wind-cold (风寒) vs wind-heat (风热) presentations.

Deterministic scoring from the patient's words and optional follow-up answers.
When the evidence is ambiguous the platform must NOT guess: it answers with two
branches and asks clarifying questions instead.
"""

from __future__ import annotations

from typing import Any

# Questions used to split cold vs heat. Option → (pattern, weight).
QUESTIONS: list[dict[str, Any]] = [
    {
        "id": "chills",
        "question": "你更怕冷（加衣也不缓解），还是更口干、想喝水？",
        "options": {
            "明显怕冷": ("cold", 2),
            "不怕冷，口干想喝水": ("heat", 2),
            "都不明显": (None, 0),
        },
    },
    {
        "id": "discharge",
        "question": "鼻涕或痰是什么样？",
        "options": {
            "清稀或白色": ("cold", 2),
            "黄稠": ("heat", 2),
            "干咳无痰": ("heat", 1),
            "没有鼻涕和痰": (None, 0),
        },
    },
    {
        "id": "throat",
        "question": "咽喉痛明显吗？",
        "options": {
            "明显疼痛": ("heat", 2),
            "轻微或不痛": ("cold", 1),
        },
    },
    {
        "id": "sweat",
        "question": "有出汗吗？",
        "options": {
            "不出汗": ("cold", 1),
            "容易出汗": ("heat", 1),
        },
    },
    {
        "id": "thirst",
        "question": "口渴吗？",
        "options": {
            "很口渴": ("heat", 1),
            "不渴": ("cold", 1),
        },
    },
]

# Words the patient may already have used, with weights (decisive signs weigh 2).
COLD_MARKERS = {
    "怕冷": 2, "畏寒": 2, "清涕": 2, "清鼻涕": 2, "清水鼻涕": 2, "流清涕": 2,
    "白痰": 2, "稀白痰": 2, "无汗": 1, "不出汗": 1, "鼻塞": 1,
}
HEAT_MARKERS = {
    "咽痛": 1, "咽喉痛": 1, "喉咙痛": 1, "黄痰": 2, "黄涕": 2,
    "口渴": 1, "口干": 1, "发热重": 1, "出汗": 1, "舌尖红": 1,
}

RESPIRATORY_MARKERS = ("感冒", "发热", "发烧", "咳嗽", "咽痛", "咽喉", "喉咙",
                      "鼻塞", "流鼻涕", "打喷嚏", "怕冷", "畏寒", "痰", "流涕")


def is_respiratory(text: str) -> bool:
    """Wind-cold/wind-heat differentiation only makes sense for these symptoms."""
    text = text or ""
    cold_like = any(marker in text for marker in ("发热", "发烧", "咽痛", "咳嗽", "怕冷", "畏寒"))
    allergy_like = any(marker in text for marker in ("鼻炎", "过敏", "花粉"))
    if allergy_like and not cold_like:
        return False
    return any(marker in text for marker in RESPIRATORY_MARKERS)


TAG_COLD = "风寒"
TAG_HEAT = "风热"


def score(symptoms: str, answers: dict[str, str] | None = None) -> dict[str, int]:
    scores = {"cold": 0, "heat": 0}
    text = symptoms or ""
    for marker, weight in COLD_MARKERS.items():
        if marker in text:
            scores["cold"] += weight
    for marker, weight in HEAT_MARKERS.items():
        if marker in text:
            scores["heat"] += weight
    for question in QUESTIONS:
        answer = (answers or {}).get(question["id"])
        if not answer:
            continue
        pattern, weight = question["options"].get(answer, (None, 0))
        if pattern:
            scores[pattern] += weight
    return scores


IMPLIED_ANSWERS = {
    "chills": ("\u6015\u51b7", "\u754f\u5bd2", "\u53e3\u5e72", "\u53e3\u6e34", "\u60f3\u559d\u6c34"),
    "discharge": ("\u9ec4\u75f0", "\u9ec4\u7a20", "\u6e05\u7a00", "\u767d\u75f0", "\u9f3b\u6d95", "\u75f0"),
    "throat": ("\u54bd\u75db", "\u55d3\u5b50", "\u5589\u5499", "\u54bd", "\u55d3\u5b50\u75bc", "\u55d3\u5b50\u75db", "\u5589\u5499\u75db", "\u54bd\u5589\u75db"),
    "sweat": ("\u51fa\u6c57", "\u76d7\u6c57", "\u4e0d\u51fa\u6c57"),
    "thirst": ("\u53e3\u6e34", "\u53e3\u5e72"),
}


def implied_answers(symptoms: str) -> dict[str, str]:
    text = symptoms or ""
    result = {}
    for question_id, cues in IMPLIED_ANSWERS.items():
        for cue in cues:
            if cue in text:
                result[question_id] = cue
                break
    return result


def differentiate(symptoms: str, answers: dict[str, str] | None = None) -> dict[str, Any]:
    """Return the pattern decision, scores, and the questions still worth asking."""
    scores = score(symptoms, answers)
    diff = scores["heat"] - scores["cold"]
    if diff >= 2:
        decision, tags = "heat", [TAG_HEAT]
    elif diff <= -2:
        decision, tags = "cold", [TAG_COLD]
    else:
        decision, tags = "ambiguous", [TAG_COLD, TAG_HEAT]
    answered = set((answers or {}).keys()) | set(implied_answers(symptoms).keys())
    followups = [q for q in QUESTIONS if q["id"] not in answered]
    return {
        "decision": decision,
        "scores": scores,
        "tags": tags,
        "followups": followups if decision == "ambiguous" else [],
        "reason": (
            None if decision == "ambiguous"
            else ("更符合风寒表现" if decision == "cold" else "更符合风热表现")
        ),
    }


def format_questions(questions: list[dict[str, Any]]) -> str:
    lines = []
    for question in questions:
        options = "；".join(question["options"].keys())
        lines.append(f"- {question['question']}（可选：{options}）")
    return "\n".join(lines)
