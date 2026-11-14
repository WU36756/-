"""Small offline semantic fallback: TF-IDF over colloquial example phrases.

This is deliberately tiny (no downloads) and is only used when the keyword
router has no signal, so normal behaviour stays predictable.
"""

from __future__ import annotations

import math
import re
from typing import Iterable

CJK = re.compile(r"[\u4e00-\u9fff]+")
LATIN = re.compile(r"[a-zA-Z][a-zA-Z0-9\-]{2,}")


def _ngrams(text: str) -> list[str]:
    grams: list[str] = []
    lowered = (text or "").lower()
    for run in CJK.findall(lowered):
        for size in (2, 3, 4):
            for index in range(len(run) - size + 1):
                grams.append(run[index:index + size])
    for word in LATIN.findall(lowered):
        grams.append(word)
    return grams


class ExampleIndex:
    def __init__(self, examples: dict[str, Iterable[str]]) -> None:
        self.labels = list(examples)
        self.documents: dict[str, list[str]] = {
            label: [str(item) for item in items] for label, items in examples.items()
        }
        flat = [document for label in self.labels for document in self.documents[label]]
        vectors = self._fit(flat)
        self.vectors: dict[str, list[dict[str, float]]] = {}
        cursor = 0
        for label in self.labels:
            size = len(self.documents[label])
            self.vectors[label] = vectors[cursor:cursor + size]
            cursor += size

    @staticmethod
    def _fit(documents: list[str]) -> list[dict[str, float]]:
        tokenized = [_ngrams(document) for document in documents]
        df: dict[str, int] = {}
        for grams in tokenized:
            for gram in set(grams):
                df[gram] = df.get(gram, 0) + 1
        total = len(tokenized)
        idf = {gram: math.log((1 + total) / (1 + count)) + 1 for gram, count in df.items()}
        vectors = []
        for grams in tokenized:
            counts: dict[str, int] = {}
            for gram in grams:
                counts[gram] = counts.get(gram, 0) + 1
            vector = {gram: (1 + math.log(count)) * idf[gram] for gram, count in counts.items()}
            norm = math.sqrt(sum(value * value for value in vector.values())) or 1.0
            vectors.append({gram: value / norm for gram, value in vector.items()})
        return vectors

    def scores(self, text: str) -> list[tuple[str, float]]:
        grams = _ngrams(text)
        counts: dict[str, int] = {}
        for gram in grams:
            counts[gram] = counts.get(gram, 0) + 1
        vector = {gram: 1 + math.log(count) for gram, count in counts.items() if count}
        norm = math.sqrt(sum(value * value for value in vector.values())) or 1.0
        query = {gram: value / norm for gram, value in vector.items()}
        result = []
        for label in self.labels:
            best = 0.0
            for doc in self.vectors[label]:
                score = sum(value * doc.get(gram, 0.0) for gram, value in query.items())
                if score > best:
                    best = score
            result.append((label, best))
        result.sort(key=lambda pair: pair[1], reverse=True)
        return result


INTENT_EXAMPLES = {
    "medical": [
        "我头疼", "脑袋像要炸开", "太阳穴一跳一跳", "嗓子像吞刀片", "喉咙痛",
        "鼻子堵得慌", "咳嗽有黄痰", "发烧怕冷", "胸口闷", "喘不上气",
        "肚子绞着疼", "吃坏肚子了", "拉不出来", "胃胀反酸", "恶心呕吐",
        "腰像断了一样", "脖子落枕", "关节痛", "脚崴了", "膝盖肿了",
        "身上起红疹很痒", "脸上长痘", "眼睛干涩", "眼睛睁不开", "耳朵嗡嗡响",
        "牙床肿了", "口腔溃疡", "小便刺痛", "尿频尿急", "月经来了肚子疼",
        "浑身没劲", "手脚发麻", "站久了头晕", "血压有点高", "血糖高",
        "脑袋像被门夹了", "后脑勺一跳一跳", "肚子胀气老打嗝", "反酸水",
        "腰直不起来", "落枕了", "脚踝肿了", "手指发麻", "眼前发黑",
        "浑身像散了架", "手脚冰凉", "总觉得累",
    ],
    "psych": [
        "最近压力很大", "心里很烦", "提不起劲", "什么都不想做", "心情低落",
        "晚上睡不着胡思乱想", "很焦虑", "心慌坐不住", "想哭", "失恋了很难受",
        "和室友吵架", "觉得自己没用", "害怕考试", "不想社交", "很孤独",
        "精神内耗", "emo了", "被孤立", "烦躁", "心累", "撑不住了",
        "对什么都没兴趣", "总是自责", "害怕去人多的地方", "情绪忽上忽下",
        "烦心事", "脑子停不下来", "人生没意思", "感觉没意思",
        "容易发火", "不想说话", "莫名其妙想哭", "注意力不集中",
        "总觉得撑不住", "胸口像压了块石头", "心里有点累", "心里空落落",
    ],
    "food": [
        "炸鸡健康吗", "减脂早餐怎么吃", "吃这个会长胖吗", "热量高不高",
        "蛋白质多少", "这个能不能吃", "奶茶糖分高吗", "晚上吃水果会胖吗",
        "增肌怎么吃", "控糖饮食怎么安排", "外卖怎么选", "这个食物有营养吗",
        "减肥能吃吗", "一天吃几个鸡蛋", "喝牛奶还是豆浆", "碳水怎么分配",
        "低脂和全脂哪个好", "痛风能吃什么", "高血压饮食", "学生食堂怎么搭配",
        "减脂早餐咋吃", "这玩意儿吃了会胖吗", "晚上吃这个会不会长肉",
        "这个热量高吗", "能不能多吃", "增肌吃什么", "血糖高怎么吃",
    ],
}

DOMAIN_EXAMPLES = {
    "respiratory": ["咳嗽", "嗓子疼", "喉咙痛", "鼻塞流涕", "发烧怕冷", "咳黄痰"],
    "abdominal": ["肚子疼", "胃胀", "拉肚子", "便秘拉不出", "恶心反胃", "反酸烧心"],
    "headache": ["头疼", "脑袋发胀", "太阳穴跳", "头晕眼花", "偏头痛",
                    "后脑勺一跳一跳", "脑袋像被门夹"],
    "musculoskeletal": ["腰疼", "脖子落枕", "关节痛", "膝盖肿", "脚崴了", "肌肉酸痛"],
    "skin": ["起疹子", "很痒", "风团", "长痘", "皮肤脱皮"],
    "urinary": ["尿频", "小便刺痛", "尿不尽", "血尿", "腰酸水肿"],
    "gynecology": ["痛经", "月经不调", "大姨妈", "白带异常", "经期肚子疼"],
    "dental": ["牙疼", "牙龈肿", "口腔溃疡", "智齿疼"],
    "eye_ent": ["眼睛干", "眼屎多", "耳鸣", "耳朵疼", "流鼻血", "看东西模糊"],
    "systemic": ["发烧", "浑身没劲", "盗汗", "血压高", "上火", "湿气重",
                    "浑身像散了架", "手脚冰凉", "总觉得累"],
    "trauma": ["摔伤", "崴脚", "淤青", "扭伤", "闪腰", "撞伤"],
    "pediatrics": ["孩子发烧", "宝宝咳嗽", "小孩拉肚子", "婴儿起疹子"],
}

INTENT_INDEX = ExampleIndex(INTENT_EXAMPLES)
DOMAIN_INDEX = ExampleIndex(DOMAIN_EXAMPLES)


def infer_intent(text: str) -> tuple[str, float] | None:
    scores = INTENT_INDEX.scores(text)
    if not scores:
        return None
    best, score = scores[0]
    second = scores[1][1] if len(scores) > 1 else 0.0
    if score >= 0.10 and score - second >= 0.01:
        return best, score
    return None


def infer_domain(text: str) -> str | None:
    scores = DOMAIN_INDEX.scores(text)
    if not scores:
        return None
    best, score = scores[0]
    second = scores[1][1] if len(scores) > 1 else 0.0
    if score >= 0.08 and score - second >= 0.005:
        return best
    return None
