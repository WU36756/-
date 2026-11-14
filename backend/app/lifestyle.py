"""Diet and recovery-training plans selected from the patient's current state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DATA_PATH = Path(__file__).resolve().parent / "data" / "lifestyle.json"

TAG_RULES: list[tuple[tuple[str, ...], str]] = [
    (("高烧", "高热", "39 度", "39度"), "high_fever"),
    (("发热", "发烧", "低烧"), "fever"),
    (("咽痛", "咽喉痛", "嗓子疼", "嗓子痛", "喉咙痛"), "sore_throat"),
    (("咳嗽", "咳痰", "有痰", "干咳"), "cough"),
    (("感冒", "鼻塞", "流鼻涕", "打喷嚏"), "cold_recovery"),
    (("失眠", "睡不着", "多梦", "早醒"), "sleep"),
    (("焦虑", "紧张", "心慌", "压力大", "内耗"), "anxiety"),
    (("胃胀", "腹胀", "反酸", "胃痛", "胃疼", "恶心", "呕吐", "消化不良", "吃不下",
      "肚子痛", "肚子疼", "腹痛", "肚子不舒服", "肠胃不舒服"), "gi_upset"),
    (("便秘", "大便干", "拉不出来"), "constipation"),
    (("腹泻", "拉肚子", "窜稀"), "diarrhea"),
    (("月经推迟", "月经不调", "闭经", "周期乱", "几个月没来"), "menstrual_irregular"),
    (("痛经", "月经", "大姨妈", "经期"), "menstrual"),
    (("贫血", "缺铁", "补铁"), "anemia"),
    (("高血压", "血压高"), "hypertension"),
    (("糖尿病", "血糖高", "控糖"), "diabetes"),
    (("痛风", "尿酸高"), "gout"),
    (("减脂", "减肥", "瘦身", "掉秤"), "weight_loss"),
    (("增肌", "长肌肉"), "muscle_gain"),
    (("扭伤", "扭到", "扭了", "崴脚", "崴了", "崴到", "脚扭", "脚崴",
      "脚踝肿", "踝肿", "跌打", "摔伤", "摔了一跤", "拉伤", "闪腰",
      "撞伤", "撞到", "磕到", "淤青", "淤血", "骨折"), "injury"),
    (("痛经", "头痛", "关节痛", "腰痛", "肌肉酸痛", "疼痛"), "pain"),
    (("痤疮", "痘痘", "湿疹", "瘙痒", "荨麻疹", "皮疹", "皮肤"), "skin"),
]


def _load() -> dict[str, Any]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def select(symptoms: str, triage: Any = None) -> dict[str, Any]:
    data = _load()
    sources = data["sources"]
    plans = data["plans"]
    text = symptoms or ""

    tags: list[str] = []
    for markers, tag in TAG_RULES:
        if any(marker in text for marker in markers):
            tags.append(tag)

    urgent = bool(getattr(triage, "urgent", False))
    high_fever = bool(getattr(triage, "high_fever", False))
    if high_fever or urgent:
        tags = [tag for tag in tags if tag not in ("fever", "cold_recovery")] + ["high_fever"]

    tags = list(dict.fromkeys(tags))
    if "menstrual_irregular" in tags and "menstrual" in tags:
        tags.remove("menstrual")
    if high_fever or urgent:
        tags = [tag for tag in tags if tag not in ("fever", "cold_recovery")]
        if "high_fever" not in tags:
            tags.append("high_fever")
    # 有症状专项时不再混入通用建议，避免“胃痛也餐餐蔬菜水果”
    ordered = tags if tags else ["general"]

    diet: list[str] = []
    exercise: list[str] = []
    avoid: list[str] = []
    diet_keys: list[str] = []
    exercise_keys: list[str] = []
    source_keys: list[str] = []
    for tag in ordered:
        plan = plans.get(tag)
        if not plan:
            continue
        diet += [line for line in plan.get("diet", []) if line not in diet]
        exercise += [line for line in plan.get("exercise", []) if line not in exercise]
        avoid += [line for line in plan.get("avoid", []) if line not in avoid]
        for key in plan.get("diet_sources", []):
            if key not in diet_keys:
                diet_keys.append(key)
        for key in plan.get("exercise_sources", []):
            if key not in exercise_keys:
                exercise_keys.append(key)
    for key in diet_keys + exercise_keys:
        if key not in source_keys:
            source_keys.append(key)

    return {
        "tags": ordered,
        "diet": diet,
        "exercise": exercise,
        "avoid": avoid,
        "diet_sources": diet_keys,
        "exercise_sources": exercise_keys,
        "sources": [
            {"key": key, "title": sources[key]["title"], "url": sources[key]["url"],
             "zh": sources[key]["zh"]}
            for key in source_keys if key in sources
        ],
    }
