"""Deterministic red-flag triage. Safety-critical rules do not use the model."""

from dataclasses import dataclass, field

from .symptoms import red_flags as ontology_flags

# Phrases that always route the user to urgent care. Matched literally.
RED_FLAGS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("胸痛或胸闷持续不缓解", ("胸痛", "胸口痛", "胸闷不缓解")),
    ("呼吸困难或喘不上气", ("呼吸困难", "喘不上", "窒息")),
    ("意识改变、昏厥或抽搐", ("意识不清", "昏迷", "昏厥", "抽搐", "惊厥")),
    ("大出血或呕血、黑便", ("大出血", "大量便血", "呕血", "黑便")),
    ("孕产期异常", ("孕妇", "怀孕", "孕晚期", "产后出血")),
    ("婴儿高热或精神差", ("婴儿", "新生儿", "3个月", "两个月")),
    ("剧烈头痛伴颈部僵硬", ("颈部僵硬", "脖子硬")),
    ("自伤或伤害他人风险", ("自杀", "自伤", "轻生")),
    ("急腹症表现", ("板状腹", "肚子硬", "肚子像木板", "一按就疼", "按压痛",
                    "右下腹", "持续剧痛", "疼得直不起腰", "疼得打滚", "绞痛不止", "便血")),
) + tuple(ontology_flags())

# Groups that make dose advice unsafe without a clinician.
SENSITIVE_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("儿童/婴幼儿", ("儿童", "孩子", "宝宝", "婴儿", "幼儿")),
    ("孕期或哺乳期", ("孕", "哺乳")),
    ("慢病或长期用药", ("高血压", "糖尿病", "心脏病", "肾", "肝", "长期服药", "抗凝")),
)

# High fever changes the recommendation: assess first, do not self-stack drugs.
HIGH_FEVER_MARKERS: tuple[str, ...] = ("高烧", "高热", "39℃", "39度", "39.5", "40度", "38.5")


@dataclass
class Triage:
    urgent: bool
    reasons: list[str] = field(default_factory=list)
    sensitive: list[str] = field(default_factory=list)
    high_fever: bool = False


def triage(symptoms: str) -> Triage:
    text = symptoms.lower()
    reasons: list[str] = []
    for reason, phrases in RED_FLAGS:
        if any(phrase.lower() in text for phrase in phrases):
            reasons.append(reason)
    sensitive: list[str] = []
    for group, phrases in SENSITIVE_GROUPS:
        if any(phrase.lower() in text for phrase in phrases):
            sensitive.append(group)
    high_fever = any(marker.lower() in text for marker in HIGH_FEVER_MARKERS)
    abdominal = any(word in text for word in ("腹痛", "肚子痛", "肚子疼", "肚痛", "小腹痛"))
    fever = any(word in text for word in ("发烧", "发热", "高烧", "高热"))
    vomiting = any(word in text for word in ("呕吐", "吐了", "想吐", "上吐下泻"))
    if abdominal and fever and vomiting and "腹痛伴发热呕吐" not in reasons:
        reasons.append("腹痛伴发热呕吐")
    return Triage(urgent=bool(reasons), reasons=reasons, sensitive=sensitive, high_fever=high_fever)
