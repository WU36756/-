"""Profile-aware safety checks: allergies, pregnancy, conditions, interactions."""

from __future__ import annotations

from typing import Any

from . import drugdata

PREGNANCY_FORBIDDEN_HERBS = ("益母草", "红花", "桃仁", "三棱", "莪术", "水蛭", "麝香", "牛膝")
PREGNANCY_CAUTION_HERBS = ("当归", "川芎", "丹参", "桂枝", "牡丹皮", "肉桂", "附子")

CONDITION_RULES: dict[str, dict[str, Any]] = {
    "胃溃疡": {"drugs": ("布洛芬", "双氯芬酸"), "text": "可能增加胃肠道出血风险"},
    "胃病": {"drugs": ("布洛芬", "双氯芬酸"), "text": "可能刺激胃黏膜"},
    "高血压": {"drugs": ("伪麻黄碱",), "text": "可能升高血压"},
    "心脏病": {"drugs": ("伪麻黄碱", "多潘立酮"), "text": "可能增加心血管风险"},
    "肝病": {"drugs": ("对乙酰氨基酚",), "text": "可能增加肝脏负担"},
    "肾病": {"drugs": ("布洛芬", "双氯芬酸"), "text": "可能增加肾脏负担"},
}

INTERACTION_RULES: list[dict[str, Any]] = [
    {"meds": ("布洛芬", "双氯芬酸", "阿司匹林"), "herbs": ("丹参", "当归", "川芎", "益母草", "红花", "桃仁"),
     "text": "可能增加出血风险"},
    {"meds": ("布洛芬", "双氯芬酸"), "herbs": ("华法林", "氯吡格雷", "阿司匹林"),
     "text": "可能增加出血和胃损伤风险"},
    {"meds": ("对乙酰氨基酚",), "herbs": ("酒精", "酒"),
     "text": "饮酒可能增加肝损伤风险"},
    {"meds": ("奥美拉唑",), "herbs": ("氯吡格雷",),
     "text": "可能降低氯吡格雷的抗血小板效果"},
]


def _match(name: str, keys: tuple[str, ...] | list[str]) -> str | None:
    for key in keys:
        if key and key in name:
            return key
    return None


def apply(profile: dict[str, Any] | None,
          tcm: list[dict[str, Any]],
          western: list[dict[str, Any]],
          medications: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Filter unsafe options and return human-readable warnings."""
    profile = profile or {}
    warnings: list[str] = []
    excluded: list[str] = []
    allergies = [str(item) for item in profile.get("allergies") or []]
    conditions = [str(item) for item in profile.get("conditions") or []]
    pregnant = bool(profile.get("pregnant"))
    age = profile.get("age")

    def keep(item: dict[str, Any], kind: str) -> bool:
        name = str(item.get("name") or "")
        for allergy in allergies:
            if allergy and allergy in name:
                excluded.append(f"{name}（过敏史：{allergy}）")
                warnings.append(f"你记录了对「{allergy}」过敏，已排除 {name}。")
                return False
        if pregnant:
            text = str(item.get("contraindications") or "")
            if "孕妇禁用" in text or _match(name, PREGNANCY_FORBIDDEN_HERBS):
                excluded.append(f"{name}（孕期禁用）")
                warnings.append(f"{name} 孕期禁用，已排除。")
                return False
            if "孕妇慎用" in text or _match(name, PREGNANCY_CAUTION_HERBS):
                warnings.append(f"{name} 孕期需慎用，请先咨询医生。")
        return True

    safe_tcm = [item for item in tcm if keep(item, "tcm")]
    safe_western = [item for item in western if keep(item, "western")]

    if age is not None:
        if age < 18:
            warnings.append("未成年人用药剂量需按年龄/体重调整，请先咨询医生或药师。")
        elif age >= 65:
            warnings.append("老年人用药需注意剂量与药物相互作用，建议从低剂量开始。")
    if pregnant:
        warnings.append("已按孕期处理：禁用活血类中药，西药请先咨询产科医生。")

    for condition in conditions:
        rule = CONDITION_RULES.get(condition)
        if not rule:
            continue
        for item in safe_western:
            hit = _match(str(item.get("name") or ""), rule["drugs"])
            if hit:
                warnings.append(f"你有「{condition}」，{hit} {rule['text']}，请先咨询医生。")

    med_names = [str(item.get("name") or "") for item in (medications or [])]
    for rule in INTERACTION_RULES:
        for med in med_names:
            forward = bool(_match(med, rule["meds"]))
            backward = bool(_match(med, rule["herbs"]))
            if not (forward or backward):
                continue
            for item in safe_western + safe_tcm:
                name = str(item.get("name") or "")
                hit = (forward and _match(name, rule["herbs"])) or \
                      (backward and _match(name, rule["meds"]))
                if hit:
                    warnings.append(
                        f"你正在服用 {med}，与 {name} 同时使用：{rule['text']}，建议先咨询药师。")
    curated_pairs = set()
    for rule in INTERACTION_RULES:
        for med in med_names:
            forward = bool(_match(med, rule["meds"]))
            backward = bool(_match(med, rule["herbs"]))
            if not (forward or backward):
                continue
            for item in safe_western + safe_tcm:
                name = str(item.get("name") or "")
                if (forward and _match(name, rule["herbs"])) or \
                        (backward and _match(name, rule["meds"])):
                    curated_pairs.add((med, name))

    checked = 0
    for med in med_names:
        if checked >= 4:
            break
        for item in safe_western:
            name = str(item.get("name") or "")
            if (med, name) in curated_pairs:
                continue
            result = drugdata.check(med, name)
            if result:
                warnings.append(
                    f"你正在服用 {med}：{result['source']}提到与 {name} 的相互作用——"
                    f"“{result['text']}”")
            checked += 1
            if checked >= 4:
                break

    return {
        "tcm": safe_tcm,
        "western": safe_western,
        "warnings": list(dict.fromkeys(warnings)),
        "excluded": excluded,
        "coverage": "内置常见组合 + openFDA 说明书（仅西药）；中药相互作用未全面覆盖",
    }


def summary(profile: dict[str, Any] | None) -> list[str]:
    profile = profile or {}
    parts = []
    if profile.get("age"):
        parts.append(f"{profile['age']} 岁")
    if profile.get("sex") == "female":
        parts.append("女性" + ("，孕期" if profile.get("pregnant") else ""))
    elif profile.get("sex") == "male":
        parts.append("男性")
    if profile.get("allergies"):
        parts.append("过敏：" + "、".join(profile["allergies"]))
    if profile.get("conditions"):
        parts.append("慢病：" + "、".join(profile["conditions"]))
    return parts
