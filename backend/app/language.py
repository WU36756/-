"""Language retrieval/normalization agent.

Two layers, both deterministic and local:
1. exact colloquial/canonical substitutions (酸疼 -> 酸痛);
2. a char-ngram paraphrase index, so a differently worded expression
   ("脑袋像被门夹了") still retrieves the canonical symptom ("头痛").

The agent only adds canonical terms to the current message; it never rewrites
the user's history.
"""

from __future__ import annotations

import math
import re
from typing import Any

CJK = re.compile(r"[\u4e00-\u9fff]+")

SYNONYMS: list[tuple[str, str]] = [
    ("拉不出屎", "便秘"), ("拉不出来", "便秘"), ("好几天没拉", "便秘"),
    ("窜稀", "腹泻"), ("拉稀", "腹泻"), ("吃坏肚子", "腹泻"),
    ("大腿酸疼", "大腿酸痛"), ("小腿酸疼", "小腿酸痛"),
    ("膝盖酸疼", "膝盖酸痛"), ("腰酸疼", "腰酸痛"),
    ("酸疼", "酸痛"), ("刺疼", "刺痛"),
    ("肚子疼", "腹痛"), ("肚子痛", "腹痛"), ("小肚子疼", "下腹痛"),
    ("脑袋疼", "头痛"), ("脑袋痛", "头痛"), ("后脑勺疼", "头痛"),
    ("头有点晕", "头晕"), ("头很晕", "头晕"), ("头发晕", "头晕"),
    ("头有点昏", "头晕"), ("头昏昏", "头晕"), ("晕乎乎", "头晕"),
    ("晕得慌", "头晕"), ("脑袋嗡嗡", "头晕"), ("头昏", "头晕"),
    ("眼前发黑", "头晕"), ("心口疼", "胸痛"), ("心口痛", "胸痛"),
    ("胸口压石头", "胸闷"), ("胸口像压了块石头", "胸闷"),
    ("喘不上气", "呼吸困难"), ("喘不过气", "呼吸困难"),
    ("上不来气", "呼吸困难"), ("嗓子疼", "咽痛"), ("嗓子痛", "咽痛"),
    ("喉咙痛", "咽痛"), ("嗓子像吞刀片", "咽痛"), ("嗓子像冒火", "咽痛"),
    ("鼻子堵", "鼻塞"), ("鼻子不通气", "鼻塞"),
    ("大姨妈疼", "痛经"), ("来例假疼", "痛经"), ("月经疼", "痛经"),
    ("大姨妈", "月经"), ("来例假", "月经"), ("例假", "月经"),
    ("牙床肿", "牙龈肿痛"), ("牙床疼", "牙痛"),
    ("小便火辣辣", "尿痛"), ("老想上厕所", "尿频"), ("总想上厕所", "尿频"),
    ("浑身没劲", "乏力"), ("没力气", "乏力"), ("浑身没力气", "乏力"),
    ("眼睛干", "眼干"), ("眼睛涩", "眼干"), ("耳朵嗡嗡", "耳鸣"),
    ("血糖高", "高血糖"), ("血压高", "高血压"), ("尿酸高", "高尿酸"),
    ("膝盖摔了", "膝盖摔伤"), ("膝盖磕了", "膝盖撞伤"),
    ("摔了一跤", "摔伤"), ("摔了一交", "摔伤"), ("磕了一下", "撞伤"),
    ("崴了脚", "崴脚"), ("脚脖子崴了", "崴脚"), ("脚脖子", "脚踝"),
    ("大腿根", "髋部"),
    ("小腿肚", "小腿"), ("胳膊肘", "手肘"), ("脊梁", "脊柱"),
    ("后腰", "腰"), ("心口", "胸口"), ("牙床", "牙龈"),
    ("便密", "便秘"), ("腹泄", "腹泻"), ("头通", "头痛"),
    ("胃里反酸水", "反酸"), ("反酸水", "反酸"), ("烧心", "反酸"),
    ("老想跑厕所", "尿频"), ("总跑厕所", "尿频"), ("一直跑厕所", "尿频"),
    ("脚脖子崴了", "崴脚"), ("崴了脚脖子", "崴脚"),
    ("头像要炸开", "头痛"), ("头要炸了", "头痛"),
    ("嗓子像被掐住", "咽痛"), ("鼻涕流个不停", "流鼻涕"),
    ("胸口发紧", "胸闷"), ("吃坏肚子拉水", "腹泻"), ("大便干", "便秘"),
    ("翻来覆去睡不着", "失眠"), ("晚上睡不着", "失眠"), ("入睡困难", "失眠"),
    ("半夜总醒", "失眠"), ("早醒", "失眠"), ("腿像灌了铅", "乏力"),
    ("大姨妈疼", "痛经"), ("来例假疼", "痛经"), ("经期疼", "痛经"),
]

# Different wording, same meaning. The index retrieves these by char overlap,
# so the sentence does not need to be identical.
PARAPHRASES: dict[str, list[str]] = {
    "头痛": ["脑袋像被门夹了", "头像要炸开", "后脑勺一跳一跳", "太阳穴突突跳",
             "头像被箍住", "脑袋发沉", "头一抽一抽地疼", "偏头痛犯了"],
    "头晕": ["天旋地转", "眼前冒金星", "站不稳", "晕得不敢睁眼",
             "头像坐船一样晃", "脑袋昏昏沉沉", "蹲下起来就发晕"],
    "咽痛": ["嗓子像吞刀片", "喉咙像被掐住", "咽口水都疼", "嗓子像冒火",
             "喉咙火辣辣", "说话都扯着疼"],
    "鼻塞": ["鼻子像被堵住", "鼻子不通气", "闻不到味道", "只能张嘴呼吸"],
    "流鼻涕": ["鼻涕流个不停", "清水鼻涕止不住", "鼻涕倒流"],
    "胸闷": ["胸口像压了块石头", "胸口发紧", "胸口堵得慌", "喘气不顺"],
    "呼吸困难": ["喘不上气", "上不来气", "气不够用", "走两步就喘"],
    "胸痛": ["心口像针扎", "胸口一阵刺痛", "心口疼得不敢动"],
    "腹痛": ["肚子绞着疼", "肚子翻江倒海", "肚子一阵一阵疼", "小肚子坠着疼"],
    "腹泻": ["吃坏肚子", "一直跑厕所", "拉水样便", "肚子咕噜咕噜响"],
    "便秘": ["好几天没拉", "拉不出来", "大便干得像羊粪", "蹲半天没动静"],
    "反酸": ["胃里反酸水", "烧心", "酸水往上涌", "胸口烧得慌"],
    "恶心": ["恶心想吐", "翻胃", "闻到油味就想吐", "胃里往上顶"],
    "腰痛": ["腰像断了", "腰直不起来", "弯腰就疼", "腰酸得站不住"],
    "膝盖疼痛": ["膝盖一弯就疼", "上下楼膝盖疼", "膝盖发软", "蹲下起不来"],
    "崴脚": ["脚脖子崴了", "脚踝扭了", "脚一落地就疼", "脚背肿起来"],
    "全身酸痛": ["浑身像散了架", "像被车碾过", "全身骨头都疼", "肌肉酸得抬不起手"],
    "乏力": ["腿像灌了铅", "走两步就累", "一点劲都提不起来", "整个人发虚"],
    "眼干": ["眼睛干得睁不开", "眼睛像进了沙子", "看屏幕就流泪", "眼睛涩得慌"],
    "耳鸣": ["耳朵嗡嗡响", "耳朵里像有蝉叫", "听力忽大忽小"],
    "牙痛": ["牙床肿了", "牙龈鼓包", "一咬东西就疼", "智齿疼得张不开嘴"],
    "尿痛": ["小便火辣辣", "尿像刀割", "尿完还疼"],
    "尿频": ["老想跑厕所", "刚尿完又想尿", "一晚上起夜好几次"],
    "痛经": ["大姨妈疼得打滚", "来例假肚子坠疼", "经期疼得直不起腰"],
    "发热": ["烧得迷迷糊糊", "浑身发烫", "体温计一量发烧", "烧到三十九度"],
    "畏寒": ["冷得打寒战", "盖被子还觉得冷", "手脚冰凉怕冷"],
    "失眠": ["晚上翻来覆去睡不着", "躺下脑子停不下来", "半夜总是醒",
             "睡不踏实", "一有动静就醒"],
    "焦虑": ["心里七上八下", "总担心出事", "坐立不安", "脑子停不下来",
             "一点小事就紧张"],
    "情绪低落": ["心里空落落的", "提不起劲", "什么都不想做", "觉得没意思",
                 "心里堵得慌", "莫名想哭", "对什么都没兴趣"],
    "皮疹": ["身上起红疹", "起风团很痒", "一片一片起疙瘩", "皮肤痒得抓破"],
}


# Broad colloquial KB. Canonical labels are what the routing/TCM layer expects.
EXTRA_PARAPHRASES: dict[str, list[str]] = {
    "发热": ["烧起来了", "体温有点高", "浑身发烫", "低烧不退", "烧到三十九度",
             "忽冷忽热", "打寒战又发烧"],
    "畏寒": ["冷得发抖", "盖被子还觉得冷", "手脚冰凉", "怕冷得厉害"],
    "乏力": ["没精神", "浑身软绵绵", "提不起劲", "走两步就累", "整个人发虚",
             "懒得动", "容易疲劳"],
    "失眠": ["入睡困难", "躺下就清醒", "半夜总醒", "早醒", "整夜做梦",
             "睡不踏实", "一有动静就醒", "白天补觉晚上睡不着"],
    "焦虑": ["心里不踏实", "总往坏处想", "紧张得手心出汗", "坐不住",
             "心里发慌", "静不下来", "总担心出事"],
    "情绪低落": ["不开心", "心里难受", "莫名想哭", "觉得没意思", "什么都不想做",
                 "提不起兴趣", "心里空", "觉得自己没用", "不想见人"],
    "心悸": ["心跳得厉害", "心慌", "心脏怦怦跳", "心跳漏一拍"],
    "胸闷": ["胸口发闷", "胸口堵", "胸口压着", "喘气费劲"],
    "呼吸困难": ["气短", "吸不上气", "走两步就喘", "憋得慌"],
    "咳嗽": ["老咳", "干咳", "咳得胸口疼", "夜里咳", "一吹风就咳"],
    "咳痰": ["痰多", "黄痰", "白痰", "咳不出痰", "痰黏"],
    "咽痛": ["嗓子发炎", "喉咙肿", "咽口水疼", "嗓子哑", "喉咙干疼"],
    "鼻塞": ["鼻子不通", "闻不到味道", "只能张嘴呼吸"],
    "流鼻涕": ["清鼻涕", "鼻涕止不住", "鼻涕倒流"],
    "打喷嚏": ["喷嚏打个不停", "一遇冷就打喷嚏"],
    "耳鸣": ["耳朵响", "耳朵里蝉鸣", "听力忽大忽小"],
    "眼干": ["眼睛涩", "看屏幕流泪", "眼睛像进沙子", "眼睛干得睁不开"],
    "眼红": ["眼睛红", "眼屎多", "眼睛充血"],
    "牙痛": ["牙床肿", "咬东西疼", "智齿疼", "牙龈鼓包"],
    "口腔溃疡": ["嘴里长泡", "嘴烂", "口腔破了"],
    "恶心": ["想吐", "反胃", "闻到油味难受", "胃里往上顶"],
    "呕吐": ["吐了", "吐酸水", "吃什么吐什么"],
    "腹痛": ["肚子疼", "肚子绞着疼", "小腹坠", "肚子一阵一阵疼", "肚子翻江倒海"],
    "腹泻": ["拉肚子", "窜稀", "水样便", "一直跑厕所", "吃坏肚子"],
    "便秘": ["拉不出", "大便干", "几天没上", "蹲半天没动静", "像羊粪"],
    "反酸": ["烧心", "反酸水", "酸水往上涌", "胸口烧得慌"],
    "腹胀": ["肚子胀", "胀气", "肚子鼓", "吃一点就胀"],
    "食欲差": ["吃不下", "没胃口", "看到饭就饱", "食欲不好"],
    "腰痛": ["腰酸", "腰直不起来", "腰像断了", "弯腰就疼", "站久了腰疼"],
    "关节痛": ["关节酸", "阴天关节疼", "手腕疼", "肩膀抬不起来"],
    "肌肉酸痛": ["浑身酸", "肌肉疼", "运动后酸", "按着就疼"],
    "膝盖疼痛": ["膝盖一弯就疼", "上下楼膝盖疼", "膝盖发软", "蹲下起不来"],
    "崴脚": ["脚踝扭了", "脚脖子歪了", "脚一落地就疼", "脚背肿"],
    "摔伤": ["摔了一跤", "磕到了", "跌了一跤", "撞了一下", "摔得淤青"],
    "皮疹": ["起疹子", "起风团", "红疙瘩", "一片一片红", "皮肤起包"],
    "瘙痒": ["痒得抓破", "身上痒", "越挠越痒", "晚上痒得睡不着"],
    "尿痛": ["小便疼", "尿像刀割", "尿完还疼", "小便火辣辣"],
    "尿频": ["老跑厕所", "夜尿多", "刚尿完又想尿", "憋不住尿"],
    "血尿": ["尿血", "小便发红", "尿液有血"],
    "痛经": ["例假疼", "大姨妈疼", "经期肚子疼", "疼得直不起腰"],
    "月经不调": ["月经乱", "月经推迟", "月经提前", "几个月没来", "周期不准"],
    "高血压": ["血压高", "高压高", "低压高", "血压控制不好"],
    "高血糖": ["血糖高", "血糖控制不好", "空腹血糖高"],
    "高尿酸": ["尿酸高", "痛风又犯了", "脚趾关节红肿"],
    "中暑": ["热到了", "晒晕了", "高温下不舒服"],
    "晕车": ["坐车晕", "晕船", "一坐车就恶心"],
    "脱发": ["掉头发", "头发稀", "洗头掉一把"],
    "脚气": ["脚痒脱皮", "脚趾缝烂", "脚气犯了"],
    "贫血": ["贫血", "缺铁", "气血不足", "脸色白"],
    "过敏": ["过敏了", "吃了东西起疹", "接触后发痒"],
}

PARAPHRASES.update(EXTRA_PARAPHRASES)

# Generated body-part variants cover thousands of "部位 + 疼/痛/酸/胀" phrasings.
BODY_VARIANTS = {
    "头": "头痛", "脑袋": "头痛", "后脑勺": "头痛", "太阳穴": "头痛",
    "嗓子": "咽痛", "喉咙": "咽痛", "咽喉": "咽痛",
    "鼻子": "鼻塞", "胸口": "胸痛", "心口": "胸痛",
    "肚子": "腹痛", "腹部": "腹痛", "小肚子": "腹痛",
    "胃": "腹痛", "腰": "腰痛", "后背": "背痛", "背": "背痛",
    "肩膀": "肩痛", "脖子": "颈痛", "膝盖": "膝盖疼痛",
    "大腿": "大腿疼痛", "小腿": "小腿疼痛",
    "手腕": "关节痛", "关节": "关节痛",
    "牙": "牙痛", "牙龈": "牙痛",
}
for body, canonical in BODY_VARIANTS.items():
    variants = [body + suffix for suffix in
                ("疼", "痛", "有点疼", "有点痛", "一阵一阵疼", "酸", "酸痛", "胀痛")]
    PARAPHRASES.setdefault(canonical, []).extend(variants)


def _ngrams(text: str) -> list[str]:
    grams: list[str] = []
    for run in CJK.findall((text or "").lower()):
        for size in (2, 3, 4):
            for index in range(len(run) - size + 1):
                grams.append(run[index:index + size])
    return grams


class ParaphraseIndex:
    def __init__(self, examples: dict[str, list[str]]) -> None:
        self.labels = list(examples)
        self.vectors: dict[str, list[dict[str, float]]] = {}
        flat: list[tuple[str, str]] = []
        for label, phrases in examples.items():
            for phrase in phrases:
                flat.append((label, phrase))
        tokenized = [_ngrams(phrase) for _, phrase in flat]
        df: dict[str, int] = {}
        for grams in tokenized:
            for gram in set(grams):
                df[gram] = df.get(gram, 0) + 1
        total = len(tokenized)
        idf = {gram: math.log((1 + total) / (1 + count)) + 1
               for gram, count in df.items()}
        cursor = 0
        for label in self.labels:
            size = len(examples[label])
            docs = []
            for grams in tokenized[cursor:cursor + size]:
                counts: dict[str, int] = {}
                for gram in grams:
                    counts[gram] = counts.get(gram, 0) + 1
                vector = {gram: (1 + math.log(count)) * idf[gram]
                          for gram, count in counts.items()}
                norm = math.sqrt(sum(value * value for value in vector.values())) or 1.0
                docs.append({gram: value / norm for gram, value in vector.items()})
            self.vectors[label] = docs
            cursor += size
        self.idf = idf

    def scores(self, text: str) -> list[tuple[str, float]]:
        grams = _ngrams(text)
        counts: dict[str, int] = {}
        for gram in grams:
            counts[gram] = counts.get(gram, 0) + 1
        if not counts:
            return []
        vector = {gram: (1 + math.log(count)) * self.idf.get(gram, 1.0)
                  for gram, count in counts.items()}
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


INDEX = ParaphraseIndex(PARAPHRASES)


def normalize(text: str) -> tuple[str, list[str]]:
    normalized = (text or "").strip()
    matches: list[str] = []
    for source, target in SYNONYMS:
        if source in normalized:
            normalized = normalized.replace(source, target)
            if target not in matches:
                matches.append(target)
    return normalized, matches


def enrich(text: str) -> dict[str, Any]:
    normalized, matches = normalize(text)
    for canonical in list(matches):
        normalized = normalized.replace(canonical + canonical, canonical)
    retrieved: list[str] = []
    positive_or_negated = (
        "开心", "高兴", "心情好", "好多了", "缓解了", "不疼", "不痛", "不晕",
        "不烧", "不咳", "不拉", "不吐", "不痒", "没发烧", "没有发烧",
    )
    suppressed = (any(word in normalized for word in positive_or_negated)
                  and "不舒服" not in normalized)
    generic = (any(word in normalized for word in ("不舒服", "难受"))
               and len(normalized) <= 12)
    # exact synonym hits are high precision; don't dilute them with broad retrieval
    if not matches and not suppressed and not generic:
        scores = INDEX.scores(normalized)
        if scores:
            best, score = scores[0]
            second = scores[1][1] if len(scores) > 1 else 0.0
            pain_words = ("疼", "痛", "酸", "胀")
            if ("耳朵" in normalized and any(w in normalized for w in pain_words)
                    and best == "耳鸣"):
                best = ""
            if ("眼睛" in normalized and any(w in normalized for w in pain_words)
                    and best == "眼干"):
                best = ""
            if best and score >= 0.42 and score - second >= 0.02 and best not in normalized:
                retrieved.append(best)
    additions = list(dict.fromkeys(matches + retrieved))
    extra = [item for item in additions if item not in normalized]
    enriched = normalized
    if extra:
        enriched += "；" + "；".join(extra)
    return {
        "original": text,
        "normalized": normalized,
        "text": enriched,
        "matches": additions,
        "retrieved": retrieved,
    }
