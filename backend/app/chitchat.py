"""Light conversational replies for greetings and meta questions."""

from __future__ import annotations

from typing import Any


def respond(text: str) -> dict[str, Any]:
    text = (text or "").strip().lower()
    if any(word in text for word in ("谢谢", "感谢", "多谢", "thanks")):
        reply = "不客气呀，能帮上忙就好。还有哪里不舒服，或者想聊点别的，都可以跟我说。"
    elif any(word in text for word in ("再见", "拜拜", "晚安", "bye")):
        reply = "好，记得好好吃饭、早点休息。有事随时叫我，我一直在。"
    elif any(word in text for word in ("你能做什么", "你会什么", "能干嘛", "有什么功能", "你是谁", "介绍一下自己")):
        reply = ("我是你的健康小助手，可以帮你：看身体不舒服、分析食物是否健康、"
                 "陪你聊心情、记录吃药并提醒你。你可以直接说哪里不舒服，或者发一张食物照片给我。")
    elif any(word in text for word in ("你好", "您好", "hi", "hello", "在吗", "嗨", "早上好", "晚上好", "下午好")):
        reply = "你好呀，我在。今天身体或心情怎么样？有哪里不舒服，或者想聊聊，都可以跟我说。"
    else:
        reply = ("我在听。你可以直接说哪里不舒服、最近心情怎么样，"
                 "也可以发一张食物照片，或者问我某种食物健不健康。")
    return {
        "kind": "chitchat",
        "reply": reply,
        "trace": [{"step": "chitchat", "agent": "闲聊 Agent", "title": "陪你聊两句",
                   "summary": "这不是医疗问题，先接住话头并引导你说出需求"}],
    }
