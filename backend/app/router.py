"""Intent routing agent: decide medical / psych / food / chitchat."""

from __future__ import annotations

import json
import re
from typing import Any

from .symptoms import all_keywords
from .food import foods as _foods
from .semantics import infer_intent

MEDICAL_WORDS = ("发烧", "发热", "咳嗽", "咽痛", "咽喉", "鼻塞", "流鼻涕", "打喷嚏", "头痛", "头疼",
                 "头晕", "胃胀", "胃痛", "胃疼", "反酸", "便秘", "腹泻", "拉肚子", "拉稀",
                 "恶心", "呕吐", "上吐下泻", "腹痛", "肚子痛", "肚子疼", "肚痛", "肚子不舒服",
                 "胃不舒服", "痛经", "月经", "皮疹", "瘙痒", "湿疹", "荨麻疹", "痤疮", "牙痛",
                 "牙疼", "口腔溃疡", "耳鸣", "腰痛", "关节痛", "肌肉酸痛", "全身酸痛", "颈肩",
                 "失眠", "睡不着", "高血压", "血糖", "便血", "痔疮", "眼干", "眼睛干", "中暑",
                 "晕车", "尿频", "更年期", "脱发", "脚气", "乏力", "没力气", "心慌", "胸闷", "气短",
                 "糖尿病", "高血糖", "高血脂", "痛风", "高尿酸", "贫血", "胃炎", "胃溃疡")
MEDICAL_WORDS = tuple(dict.fromkeys(MEDICAL_WORDS + tuple(all_keywords())))

PSYCH_WORDS = ("吵架", "室友", "舍友", "心情", "难过", "焦虑", "压力", "孤独", "烦", "生气",
               "失恋", "分手", "抑郁", "自卑", "内疚", "自责", "社恐", "拖延", "倦怠",
               "霸凌", "排挤", "想家", "胡思乱想", "崩溃", "emo", "委屈", "害怕", "紧张",
               "提不起劲", "没意思", "不想动", "内耗", "想哭", "烦躁", "心累",
               "摆烂", "麻木", "空虚", "被孤立", "没动力", "兴趣",
               "心情不好", "心情差", "心情低落", "不开心", "烦死了", "没希望",
               "精神内耗", "情绪低落", "压力大", "撑不住", "心里堵",
               "心里难受", "憋得慌", "情绪", "一点就炸",
               "心里有点累", "心里累", "心里很累", "心累",
               "心里疲惫", "心里空", "心里苦")

FOOD_WORDS = ("西兰花", "菠菜", "黄瓜", "番茄", "西红柿", "香蕉", "苹果", "橙子", "鸡胸肉",
              "牛肉", "三文鱼", "鸡蛋", "豆腐", "燕麦", "米饭", "面条", "可乐", "薯片",
              "炸鸡", "汉堡", "蛋糕", "方便面", "香肠", "奶茶", "冰淇淋", "核桃", "花生",
              "香菇", "海带", "葡萄", "酸奶", "牛奶", "奶酪", "鱼", "虾", "蟹",
              "热量", "卡路里", "大卡", "长胖", "发胖", "长肉", "减肥", "减脂",
              "增肌", "练肌肉", "长肌肉", "健身", "蛋白粉", "饮食计划",
              "食谱", "健身餐", "增肌餐", "蛋白质", "营养", "能不能吃", "可以吃吗",
              ) + tuple(item["name"] for item in _foods())

GREETING = ("你好", "您好", "hi", "hello", "在吗", "嗨", "早上好", "晚上好", "下午好")
THANKS = ("谢谢", "感谢", "多谢", "thanks", "thank")
BYE = ("再见", "拜拜", "晚安", "bye")
ABILITY = ("你能做什么", "你会什么", "能干嘛", "有什么功能", "你是谁", "介绍一下自己")


def _hits(text: str, words: tuple[str, ...]) -> int:
    return sum(1 for word in words if word in text)


def rules(text: str) -> dict[str, Any]:
    text = (text or "").strip().lower()
    if any(word in text for word in ("自杀", "不想活", "活不下去", "自残", "割腕", "轻生",
                                     "想死", "结束生命", "伤害自己")):
        return {"intent": "psych", "confidence": 0.98, "reason": "出现危机相关表达"}
    if any(word in text for word in GREETING) and len(text) <= 12:
        return {"intent": "chitchat", "confidence": 0.9, "reason": "问候"}
    if any(word in text for word in THANKS) and len(text) <= 12:
        return {"intent": "chitchat", "confidence": 0.9, "reason": "道谢"}
    if any(word in text for word in BYE) and len(text) <= 12:
        return {"intent": "chitchat", "confidence": 0.9, "reason": "告别"}
    if any(word in text for word in ABILITY):
        return {"intent": "chitchat", "confidence": 0.9, "reason": "询问能力"}
    if "心里" in text and any(word in text for word in
                              ("累", "烦", "堵", "难受", "空", "委屈", "苦", "闷")):
        return {"intent": "psych", "confidence": 0.85,
                "reason": "在说心里的感受"}
    if any(word in text for word in ("心累", "心很累")):
        return {"intent": "psych", "confidence": 0.85,
                "reason": "在说心累"}
    if "累" in text and not any(word in text for word in
                                ("焦虑", "压力", "烦", "难过", "想哭", "心情", "内耗")):
        return {"intent": "medical", "confidence": 0.7,
                "reason": "在说身体疲劳"}
    diet_plan = ("饮食计划", "饮食安排", "食谱", "一日三餐", "增肌餐", "健身餐",
                 "减脂餐", "练肌肉", "增肌", "减脂", "健身",
                 "早餐吃", "午餐吃", "晚餐吃")
    if any(word in text for word in diet_plan):
        return {"intent": "food", "confidence": 0.9,
                "reason": "在问饮食计划/搭配"}

    medical = _hits(text, MEDICAL_WORDS)
    psych = _hits(text, PSYCH_WORDS)
    food = _hits(text, FOOD_WORDS)
    scores = {"medical": medical, "psych": psych, "food": food}
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        if "心里" in text and any(word in text for word in
                                  ("累", "烦", "堵", "难受", "空", "委屈", "苦", "闷")):
            return {"intent": "psych", "confidence": 0.75,
                    "reason": "在说心里的感受"}
        symptom_hints = ("痛", "疼", "不舒服", "难受", "晕", "吐", "泻", "胀", "痒",
                         "咳", "烧", "酸", "麻", "肿", "出血", "失眠", "睡不着",
                         "炸", "刀割", "像断", "堵", "撑得慌", "胃撑", "肚子撑", "没劲", "没力气", "发冷",
                         "拉不出", "跑厕所", "嗡嗡", "睁不开", "起疙瘩", "落枕",
                         "疲惫", "没精神", "血压高")
        if any(hint in text for hint in symptom_hints):
            return {"intent": "medical", "confidence": 0.6,
                    "reason": "在描述身体不适"}
        body_parts = ("脑袋", "脑壳", "嗓子", "喉咙", "鼻子", "肚子", "胃", "腰",
                      "腿", "脚", "眼睛", "耳朵", "牙", "皮肤", "关节", "脖子",
                      "肩膀", "背", "胸口", "小便", "月经", "大姨妈", "例假")
        if any(part in text for part in body_parts):
            return {"intent": "medical", "confidence": 0.55,
                    "reason": "提到了身体部位，按问诊理解"}
        food_cues = ("热量", "卡路里", "大卡", "长胖", "发胖", "长肉", "减肥",
                     "减脂", "增肌", "蛋白质", "营养", "能不能吃", "可以吃吗")
        if any(cue in text for cue in food_cues):
            return {"intent": "food", "confidence": 0.6,
                    "reason": "在问食物/营养"}
        if "药" in text and not any(word in text for word in
                                    ("药膳", "饮食", "食谱", "食材")):
            return {"intent": "medical", "confidence": 0.7,
                    "reason": "涉及用药，按问诊处理"}
        semantic = infer_intent(text)
        if semantic:
            return {"intent": semantic[0], "confidence": 0.55,
                    "reason": "换了个说法，按语义相近理解"}
        return {"intent": "clarify", "confidence": 0.4,
                "reason": "拿不准你想问哪方面，先确认一下",
                "options": [{"intent": "medical", "label": "身体不舒服 / 用药"},
                            {"intent": "psych", "label": "情绪 / 心理"},
                            {"intent": "food", "label": "食物营养"}]}
    # drug-related questions stay medical even if a symptom word also appears
    if any(word in text for word in DRUG_CONTEXT) and medical:
        return {"intent": "medical", "confidence": 0.9, "reason": "涉及用药，优先问诊"}
    food_question = any(cue in text for cue in
                        ("能吃", "可以吃", "怎么吃", "吃多少", "吃啥", "吃点", "能不能吃"))
    if food and food_question:
        best = "food"
    # 同时提到身体和情绪时不再反问；情绪明显更多才走心理，否则按身体处理
    elif psych and psych > medical:
        best = "psych"
    return {"intent": best, "confidence": min(0.95, 0.55 + 0.1 * scores[best]),
            "reason": f"关键词：问诊 {medical}、心理 {psych}、食物 {food}"}


DRUG_CONTEXT = ("吃药", "服药", "药物", "副作用", "这个药", "药后", "停药", "吃了药")
INTENT_LABEL = {"medical": "身体不舒服 / 用药问题", "psych": "情绪 / 心理",
                "food": "食物营养", "chitchat": "随便聊聊"}


def _mixed(scores: dict[str, int]) -> bool:
    ranked = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
    top, second = ranked[0], ranked[1]
    return top[1] >= 1 and second[1] >= 1 and top[1] - second[1] <= 1


ROUTER_PROMPT = """你是健康助手的意图路由。把用户这句话分到四类之一：
medical（身体症状/用药）、psych（情绪/心理）、food（食物/营养/食物图片）、chitchat（问候/闲聊/能力询问）。

用户常用口语、方言、比喻或错别字，不要因为说法不标准就判成 chitchat：
- "脑袋像要炸开""嗓子像吞刀片""腰像断了""拉不出来""鼻子堵得慌" → medical
- "提不起劲""内耗""想哭""啥都不想做" → psych
- "这玩意儿吃了会长肉吗""热量高不高" → food

只输出 JSON：{"intent": "...", "confidence": 0.0-1.0, "reason": "简短中文"}
不要解释，不要输出其他内容。"""


def _llm_route(text: str, client: Any) -> dict[str, Any] | None:
    try:
        reply = client.chat([
            {"role": "system", "content": ROUTER_PROMPT},
            {"role": "user", "content": text[:200]},
        ], max_tokens=120, temperature=0)
        match = re.search(r"\{.*\}", reply or "", re.S)
        if not match:
            return None
        data = json.loads(match.group(0))
        if data.get("intent") not in ("medical", "psych", "food", "chitchat"):
            return None
        return {"intent": data["intent"], "confidence": float(data.get("confidence", 0.6)),
                "reason": f"模型判断：{data.get('reason', '')[:40]}"}
    except Exception:
        return None


def route(text: str, client: Any = None) -> dict[str, Any]:
    """Rules first; ask the model only when the rules are not confident."""
    baseline = rules(text)
    if client is not None and baseline["confidence"] < 0.7:
        model_route = _llm_route(text, client)
        if model_route and model_route["confidence"] >= 0.6:
            return model_route
    return baseline
