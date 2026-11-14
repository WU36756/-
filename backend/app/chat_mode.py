"""Health-only conversational layer.

The structured pipeline remains the single source of medical facts.  This module
adds a narrow, explicitly scoped chat surface: it classifies scope, formats the
local evidence for the model, and falls back to deterministic advice when the
model is unavailable.
"""

from __future__ import annotations

import json
from typing import Any

from . import router

HEALTH_CUES = (
    "痛", "疼", "病", "药", "医", "症", "咳", "烧", "吐", "泻", "晕", "肿",
    "血", "心理", "焦虑", "抑郁", "情绪", "压力", "失眠", "睡不着", "吃", "喝",
    "营养", "减肥", "减脂", "增肌", "饮食", "食物", "血糖", "血压", "康复",
    "运动", "伤", "骨", "胃", "肠", "肝", "肾", "肺", "心脏", "头", "脚",
    "手", "腰", "背", "胸", "腹", "月经", "怀孕", "过敏", "疫苗", "检查",
    "化验", "挂号", "医院", "疲劳", "乏力", "没劲", "不舒服", "难受",
)

OFF_TOPIC = (
    "代码", "编程", "python", "java", "作业", "论文", "翻译", "股票", "基金",
    "比特币", "政治", "新闻", "合同", "法律", "旅游", "电影", "游戏", "星座",
    "彩票", "英语", "数学", "物理", "化学", "写个程序", "帮我写", "做ppt",
    "做表格", "简历", "情书", "娱乐", "明星",
)

GREETING = ("你好", "您好", "hi", "hello", "在吗", "嗨", "早上好", "晚上好",
            "下午好", "谢谢", "感谢", "多谢", "再见", "拜拜", "晚安", "bye")

CHAT_SYSTEM = """你是「健康助手」的健康对话机器人，只服务三类话题：
1. 身体不适、疾病、用药、检查、就医；
2. 情绪与心理健康；
3. 营养、膳食、减重/增肌、康复运动。

规则（必须遵守）：
- 非上述话题，礼貌拒绝，并引导回健康问题；不要回答编程、作业、论文、股票、政治、娱乐等。
- 不做诊断、不开处方；不说“你就是某病”；不新增平台事实之外的药名、剂量、疗程。
- 平台事实中的红旗/危机信号优先：出现胸痛、呼吸困难、意识改变、自伤/自杀风险时，先建议立即就医/拨打急救或危机热线。
- 只使用「平台事实」中的药物、剂量、来源；引用来源时用 [1][2] 对应来源列表。
- 先自然回应用户，再给 2-4 条可执行建议；信息不足时最多追问 1 个关键问题（位置、持续时间、能否承重、伴随症状等）。
- 用户换部位/换话题时，不要沿用旧部位；以当前消息为准。
- 语气像真人健康助手，简洁、具体、有同理心；不要输出 JSON、大标题堆砌或无关免责声明。
- 不要使用 Markdown 加粗（**）、标题（#）或表格；用自然段落和短横线即可。
- 结尾用一句话说明“信息参考，不替代面诊”。"""


def scope(text: str, force_intent: str | None = None) -> dict[str, Any]:
    """Return allowed / clarify / refuse / smalltalk with a deterministic gate."""
    raw = (text or "").strip()
    low = raw.lower()
    if force_intent in ("medical", "psych", "food"):
        return {"action": "allowed", "intent": force_intent}
    decision = router.rules(raw)
    intent = decision.get("intent")
    health_hit = any(word in low for word in HEALTH_CUES)
    off_hit = any(word in low for word in OFF_TOPIC)
    if intent in ("medical", "psych", "food"):
        return {"action": "allowed", "intent": intent, "decision": decision}
    if intent == "chitchat":
        if any(word in low for word in GREETING):
            return {"action": "smalltalk", "intent": "chitchat", "decision": decision}
        if off_hit and not health_hit:
            return {"action": "refuse", "intent": "off_topic", "decision": decision}
        if health_hit:
            return {"action": "allowed", "intent": "medical", "decision": decision}
        return {"action": "refuse", "intent": "off_topic", "decision": decision}
    # clarify / unknown
    if health_hit and not off_hit:
        return {"action": "clarify", "intent": "clarify", "decision": decision}
    return {"action": "refuse", "intent": "off_topic", "decision": decision}


def refusal_text() -> str:
    return (
        "我主要处理三类问题：身体不舒服/用药、情绪心理、营养膳食。"
        "编程、作业、论文、股票、娱乐这类话题我不展开。"
        "你可以告诉我哪里不舒服、最近心情怎么样，或者想了解什么食物。"
    )


def clarify_text() -> str:
    return (
        "我可以帮你看身体、情绪或饮食。你是身体哪里不舒服（比如肚子、头、脚），"
        "还是最近情绪/压力方面想聊聊，或者想问题吃什么？"
    )


def smalltalk_text(base: dict[str, Any] | None) -> str:
    if base and base.get("reply"):
        return str(base["reply"])
    return "你好呀，我在。今天身体或心情怎么样？有哪里不舒服可以直接说。"


def _join(items: Any, limit: int = 6) -> str:
    values = [str(item).strip() for item in (items or []) if str(item).strip()]
    return "；".join(values[:limit])


def local_reply(base: dict[str, Any] | None) -> str:
    """Deterministic chat fallback built from the structured result."""
    if not base:
        return "我先确认一下：你是身体不舒服、情绪方面，还是饮食营养问题？"
    kind = base.get("kind")
    if kind == "chitchat":
        return smalltalk_text(base)
    if kind == "clarify":
        return clarify_text()
    if kind == "food":
        analysis = base.get("analysis") or {}
        items = base.get("items") or []
        if analysis:
            name = analysis.get("name") or "这种食物"
            label = analysis.get("rating_label") or ""
            return (f"{name}：{label}。{_join(analysis.get('benefits'))}。"
                    + (f"注意：{_join(analysis.get('harms'))}。" if analysis.get("harms") else "")
                    + "信息参考，不替代面诊。")
        if items:
            return "我识别到这些食物，可以先告诉我你最关心哪一种，或者一次吃多少。"
        guide = base.get("guide") or base.get("plan") or {}
        text = guide.get("summary") if isinstance(guide, dict) else ""
        return (text or "你想了解哪类食物、减脂还是增肌？告诉我目标，我按你的情况给建议。") + \
            " 信息参考，不替代面诊。"
    if kind == "psych":
        if base.get("crisis"):
            hotlines = base.get("hotlines") or []
            lines = "；".join(f"{h.get('name', '')} {h.get('number', '')}".strip()
                             for h in hotlines[:2])
            return ("我很在意你现在的安全。先不要一个人扛着，请联系身边可信任的人，"
                    "或立刻拨打当地急救/危机热线" + (f"：{lines}" if lines else "") + "。"
                    "如果手边有可能伤害自己的东西，先把它交给别人。")
        parts = []
        topic = (base.get("topic") or {}).get("name")
        if topic:
            parts.append(f"听起来你现在更像是「{topic}」的困扰，我先接住这一点。")
        if base.get("empathy"):
            parts.append(str(base["empathy"][0]))
        if base.get("suggestions"):
            parts.append("可以先试：" + "；".join(map(str, base["suggestions"][:3])) + "。")
        if base.get("professional"):
            parts.append("如果持续两周以上或影响睡眠/工作，建议找专业心理人员评估。")
        return " ".join(parts) + " 信息参考，不替代面诊。"
    # medical
    triage = base.get("triage") or {}
    if triage.get("urgent"):
        return ("你描述里有需要优先就医的信号：" + _join(triage.get("reasons"), 3)
                + "。请立即前往急诊或拨打急救电话，不要只在家观察。")
    parts = []
    if base.get("differentiation", {}).get("label"):
        parts.append(f"从平台辨证看，目前更偏向「{base['differentiation']['label']}」。")
    tcm = [item.get("name") for item in (base.get("tcm") or [])[:3] if item.get("name")]
    if tcm:
        parts.append("可参考的中药方向：" + "、".join(tcm) + "，但先核对禁忌和正在吃的药。")
    life = base.get("lifestyle") or {}
    if life.get("diet"):
        parts.append("饮食上：" + _join(life["diet"], 2) + "。")
    if life.get("exercise"):
        parts.append("活动上：" + _join(life["exercise"], 2) + "。")
    followups = [q.get("question") for q in (base.get("followups") or []) if q.get("question")]
    if followups:
        parts.append("为了更准确，想再确认：" + followups[0])
    return " ".join(parts) + " 信息参考，不替代面诊。"


def facts(base: dict[str, Any], profile: dict[str, Any], medications: list[dict[str, Any]],
          notes: list[Any] | None = None) -> str:
    """Compact, model-readable evidence.  Keep it factual and bounded."""
    kind = base.get("kind") or "medical"
    data: dict[str, Any] = {"kind": kind, "profile": profile,
                            "medications": medications, "memory": notes or []}
    if kind == "medical":
        data.update({
            "symptoms": base.get("symptoms"),
            "triage": base.get("triage"),
            "differentiation": base.get("differentiation"),
            "tcm": [
                {key: item.get(key) for key in ("name", "usage", "dosage", "contraindications",
                                                "cautions", "price_range", "tags")}
                for item in (base.get("tcm") or [])[:6]
            ],
            "western": [
                {key: item.get(key) for key in ("name", "dosage", "contraindications",
                                                "cautions", "price_range")}
                for item in (base.get("western") or [])[:4]
            ],
            "lifestyle": base.get("lifestyle"),
            "sources": [
                {key: item.get(key) for key in ("title", "url", "zh")}
                for item in (base.get("sources") or [])[:8]
            ],
            "followups": [q.get("question") for q in (base.get("followups") or [])[:4]],
        })
    elif kind == "psych":
        data.update({
            "topic": base.get("topic"),
            "crisis": base.get("crisis"),
            "hotlines": base.get("hotlines"),
            "empathy": base.get("empathy"),
            "suggestions": base.get("suggestions"),
            "professional": base.get("professional"),
            "sources": [
                {key: item.get(key) for key in ("title", "url", "zh")}
                for item in (base.get("sources") or [])[:6]
            ],
        })
    elif kind == "food":
        data.update({
            "analysis": base.get("analysis"),
            "items": base.get("items"),
            "guide": base.get("guide") or base.get("plan"),
        })
    text = json.dumps(data, ensure_ascii=False, default=str)
    return text[:9000]


def prompt_messages(user_text: str, base: dict[str, Any], history: list[dict[str, str]],
                    profile: dict[str, Any], medications: list[dict[str, Any]],
                    notes: list[Any] | None = None) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": CHAT_SYSTEM}]
    for turn in history[-8:]:
        role = turn.get("role")
        content = str(turn.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content[:1200]})
    messages.append({
        "role": "user",
        "content": (
            f"用户当前消息：{user_text}\n\n"
            f"平台事实（只能据此回答，不得新增药物/剂量）：\n{facts(base, profile, medications, notes)}\n\n"
            "请用自然中文回答；先接住问题，再给建议；需要时只问一个问题。"
        ),
    })
    return messages
