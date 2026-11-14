"""Food knowledge base, healthy/junk classification and image recognition."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DATA_PATH = Path(__file__).resolve().parent / "data" / "food.json"

RATING_LABEL = {
    "recommend": ("推荐", "ok"),
    "moderate": ("适量", "warn"),
    "limit": ("少吃 / 避免", "bad"),
}

QUESTION_WORDS = ("健康", "垃圾", "热量", "成分", "营养", "好处", "坏处", "能吃", "可以吃",
                  "减肥", "发胖", "蛋白", "脂肪", "糖", "盐", "卡路里")

_MODEL = None
_CATS: list[str] = []
_TRANSFORM = None


def _data() -> dict[str, Any]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def sources() -> dict[str, Any]:
    return _data()["sources"]


def foods() -> list[dict[str, Any]]:
    return _data()["foods"]


def _by_id() -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in foods()}


def _index() -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for item in foods():
        keys = [item["name"], *item.get("aliases", []), *item.get("english", [])]
        for key in keys:
            index[str(key).lower()] = item
    return index


def search(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Exact name/alias matches first, then prefix matches, then substrings."""
    query = (query or "").strip().lower()
    if not query:
        return []
    ranked: list[tuple[int, dict[str, Any]]] = []
    for item in foods():
        keys = [item["name"], *item.get("aliases", []), *item.get("english", [])]
        lowered = [str(key).lower() for key in keys]
        if any(key == query for key in lowered):
            ranked.append((0, item))
        elif any(key.startswith(query) for key in lowered):
            ranked.append((1, item))
        elif any(query in key for key in lowered):
            ranked.append((2, item))
    ranked.sort(key=lambda pair: pair[0])
    return [item for _, item in ranked[:limit]]


def detect(text: str) -> list[dict[str, Any]]:
    text = (text or "").lower()
    found: list[dict[str, Any]] = []
    for item in foods():
        keys = [item["name"], *item.get("aliases", []), *item.get("english", [])]
        if any(str(key).lower() in text for key in keys):
            found.append(item)
    return found


def is_food_question(text: str) -> bool:
    text = text or ""
    if detect(text):
        return True
    return False


MEDICAL_MARKERS = ("胃", "腹", "痛", "发烧", "发热", "咳", "咽", "鼻", "失眠", "便秘",
                   "腹泻", "头痛", "头晕", "月经", "痛经", "皮疹", "痒", "药", "感冒")


def should_route(text: str) -> bool:
    """Route food questions to the food engine, leave medical complaints alone."""
    text = text or ""
    if not detect(text):
        return False
    if any(marker in text for marker in MEDICAL_MARKERS):
        return False
    return len(text) <= 30 or any(word in text for word in QUESTION_WORDS)


def analyze(item: dict[str, Any]) -> dict[str, Any]:
    label, tone = RATING_LABEL.get(item.get("rating"), ("未知", "warn"))
    data_sources = sources()
    return {
        "id": item["id"],
        "name": item["name"],
        "aliases": item.get("aliases", []),
        "category": item.get("category", ""),
        "rating": item.get("rating"),
        "rating_label": label,
        "rating_tone": tone,
        "nutrition": item.get("nutrition", {}),
        "unit": item.get("nutrition", {}).get("unit", "每 100 g"),
        "benefits": item.get("benefits", []),
        "harms": item.get("harms", []),
        "tips": item.get("tips", ""),
        "sources": [
            {"title": data_sources[key]["title"], "url": data_sources[key]["url"],
             "zh": data_sources[key]["zh"]}
            for key in item.get("sources", []) if key in data_sources
        ],
    }


def answer(text: str) -> dict[str, Any] | None:
    items = detect(text)
    if not items:
        return None
    if len(items) == 1:
        return {"kind": "food", "analysis": analyze(items[0]), "items": []}
    return {"kind": "food", "analysis": None,
            "items": [analyze(item) for item in items[:6]]}


def _load_model() -> bool:
    global _MODEL, _CATS, _TRANSFORM
    if _MODEL is not None:
        return True
    try:
        import torch  # noqa: F401
        from torchvision import models, transforms
    except Exception:
        return False
    weights = models.MobileNet_V2_Weights.DEFAULT
    _MODEL = models.mobilenet_v2(weights=weights).eval()
    _CATS = list(weights.meta["categories"])
    _TRANSFORM = transforms.Compose([
        transforms.Resize(256),
        transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    ])
    return True


def predict(path: str, top_k: int = 5) -> dict[str, Any]:
    if not _load_model():
        return {"available": False, "predictions": [],
                "reason": "视觉模型未安装（torch/torchvision 不可用）"}
    try:
        import torch
        from PIL import Image
    except Exception:
        return {"available": False, "predictions": [], "reason": "缺少 Pillow"}
    image = Image.open(path).convert("RGB")
    tensor = _TRANSFORM(image).unsqueeze(0)
    with torch.no_grad():
        probabilities = torch.softmax(_MODEL(tensor)[0], dim=0)
    top = torch.topk(probabilities, top_k)
    index = _index()
    predictions = []
    for score, position in zip(top.values.tolist(), top.indices.tolist()):
        label = _CATS[position]
        item = index.get(label.lower())
        predictions.append({
            "label": label,
            "name": item["name"] if item else label,
            "food_id": item["id"] if item else None,
            "confidence": round(float(score), 3),
            "analysis": analyze(item) if item else None,
        })
    return {"available": True, "predictions": predictions}

def _guide_sources(*keys: str) -> list[dict[str, str]]:
    data = sources()
    return [{"title": data[key]["title"], "url": data[key]["url"], "zh": data[key]["zh"]}
            for key in keys if key in data]


def guide(text: str) -> dict[str, Any] | None:
    """Meal-plan advice: not a single food, so return a structured guide card."""
    lowered = (text or "").lower()
    if not any(word in lowered for word in (
            "怎么吃", "咋吃", "吃什么", "食谱", "搭配", "早餐", "午餐", "晚餐",
            "加餐", "三餐", "减脂", "减肥", "增肌", "练肌肉", "长肌肉",
            "健身", "饮食计划", "食谱", "控糖", "血糖", "糖尿病",
            "高血糖", "胰岛素抵抗", "多囊", "血压",
            "尿酸", "痛风", "饮食", "营养")):
        return None

    if any(word in lowered for word in ("减脂", "减肥", "瘦身", "掉秤")):
        title = "减脂期早餐怎么吃" if "早餐" in lowered else "减脂期怎么吃"
        sections = [
            {"heading": "核心原则",
             "items": ["每天制造约 300–500 kcal 的温和热量缺口，不极端节食",
                       "每餐先保证蛋白质：鸡蛋、无糖酸奶、牛奶、豆腐、鸡胸肉",
                       "主食选粗粮：燕麦、全麦面包、玉米、红薯，约 1 拳",
                       "蔬菜占一半盘子，水果每天 1–2 份，不喝含糖饮料"]},
            {"heading": "一份早餐参考（约 350–400 kcal）",
             "items": ["燕麦 40 g 或无糖酸奶 200 g",
                       "鸡蛋 1 个 / 豆浆 300 ml / 牛奶 250 ml（选一种）",
                       "蓝莓或番茄 1 小把",
                       "黑咖啡或茶，不加糖"]},
            {"heading": "尽量避开",
             "items": ["油条、手抓饼、蛋糕、含糖奶茶、果汁",
                       "只吃水果或只喝咖啡当早餐"]},
        ]
        tips = "减脂不是不吃早餐；上午容易饿可加无糖酸奶或一个鸡蛋。"
        source_keys = ("cns", "nhs")
    elif any(word in lowered for word in ("增肌", "长肌肉", "练肌肉", "健身")):
        title = "增肌期怎么吃"
        sections = [
            {"heading": "核心原则",
             "items": ["蛋白质每天约 1.2–1.6 g/kg 体重，分 3–4 餐",
                       "每餐一掌心优质蛋白：鸡蛋、奶、鱼、鸡胸肉、牛肉、豆腐",
                       "训练前后要有碳水，主食不要砍太狠",
                       "总热量略高于消耗，每周增重 0.25–0.5 kg 为宜"]},
            {"heading": "一日参考",
             "items": ["早餐：燕麦 + 牛奶 + 鸡蛋",
                       "午餐：米饭 1 拳 + 鸡胸肉/鱼 1 掌 + 蔬菜半盘",
                       "加餐：无糖酸奶 + 水果或一小把坚果",
                       "晚餐：红薯/糙米 + 豆腐/牛肉 + 蔬菜"]},
        ]
        tips = "优先从食物获取蛋白质；肾病或痛风者需医生个体化调整。"
        source_keys = ("cns", "who")
    elif any(word in lowered for word in ("控糖", "血糖", "糖尿病")):
        title = "控糖饮食怎么安排"
        sections = [
            {"heading": "吃饭顺序",
             "items": ["先吃蔬菜，再吃蛋白质，最后吃主食",
                       "主食选低 GI：糙米、燕麦、荞麦、豆类，粗细搭配",
                       "每餐主食约 1 拳，避免单独喝粥或吃软烂面条"]},
            {"heading": "注意",
             "items": ["水果放在两餐之间，一次 1 小份",
                       "不喝果汁和含糖饮料",
                       "用降糖药或胰岛素者，饮食调整要和医生商量"]},
        ]
        tips = "控糖饮食不能替代药物；心慌、出冷汗等低血糖表现要立刻处理。"
        source_keys = ("cns", "nhs")
    elif any(word in lowered for word in ("血压", "高血压", "降压")):
        title = "高血压饮食怎么吃"
        sections = [
            {"heading": "核心原则",
             "items": ["每天食盐不超过 5 g，少酱油、咸菜、加工肉",
                       "多吃蔬菜、水果、全谷物、豆类、低脂奶",
                       "少油炸和肥肉，适量鱼、禽、坚果",
                       "限制酒精和含糖饮料"]},
            {"heading": "实用做法",
             "items": ["用醋、柠檬、香辛料代替一部分盐",
                       "看包装营养成分表的钠含量",
                       "在外吃饭少喝汤、少蘸酱"]},
        ]
        tips = "肾功能不全或正在服用保钾利尿剂者，不要自行大量补钾。"
        source_keys = ("who", "nhs")
    elif any(word in lowered for word in ("尿酸", "痛风")):
        title = "高尿酸/痛风饮食怎么吃"
        sections = [
            {"heading": "核心原则",
             "items": ["多喝水，每天约 2000 ml（心肾功能不全者遵医嘱）",
                       "限制动物内脏、浓肉汤、海鲜、啤酒",
                       "少喝含果糖饮料和果汁",
                       "适量低脂奶、鸡蛋、蔬菜"]},
            {"heading": "注意",
             "items": ["急性发作期不要自行加药或停药",
                       "豆制品不必完全禁止，但不要一次吃太多"]},
        ]
        tips = "饮食只能辅助降尿酸；反复痛风或尿酸很高要就医。"
        source_keys = ("cns", "who")
    elif "早餐" in lowered:
        title = "早餐怎么搭配"
        sections = [
            {"heading": "早餐公式",
             "items": ["主食 1 拳：燕麦、全麦面包、玉米、红薯、杂粮粥",
                       "蛋白质 1 份：鸡蛋、牛奶、无糖酸奶、豆浆、豆腐",
                       "蔬果 1 小份：番茄、黄瓜、蓝莓、苹果"]},
            {"heading": "尽量避开",
             "items": ["油条、蛋糕、含糖奶茶、果汁",
                       "只喝咖啡或只吃水果"]},
        ]
        tips = "早餐尽量在起床后 1–2 小时内吃，别长期空腹。"
        source_keys = ("cns", "nhs")
    else:
        title = "一日三餐怎么搭配"
        sections = [
            {"heading": "餐盘模型",
             "items": ["一半盘子蔬菜",
                       "四分之一优质蛋白：鱼、禽、蛋、奶、豆、瘦肉",
                       "四分之一主食：优先全谷物和薯类",
                       "每天 1–2 份水果，少油少盐少糖"]},
            {"heading": "实用技巧",
             "items": ["先吃菜和蛋白，再吃主食，饱腹感更好",
                       "外卖选蒸煮炖，少选油炸和浓汤",
                       "含糖饮料换成白水、茶或无糖咖啡"]},
        ]
        tips = "糖尿病、肾病、痛风或怀孕者，饮食方案需要个体化。"
        source_keys = ("cns", "nhs", "who")

    return {"kind": "food_guide", "title": title, "sections": sections,
            "tips": tips, "sources": _guide_sources(*source_keys)}
