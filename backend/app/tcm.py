"""Curated OTC Chinese-patent-medicine knowledge base and matcher.

The model may only recommend medicines that exist in this file: it selects and
explains, it never invents a name, dose or price.  Entries are demo data with
source notes; real use must follow the current package insert (说明书).
"""

from __future__ import annotations

import json
from pathlib import Path

from .retrieval import search as semantic_search
from .symptoms import DOMAINS, expand as expand_symptoms
from typing import Any

KB_PATH = Path(__file__).resolve().parent / "data" / "tcm.json"

# 用户口语 → 知识库症状词，避免“肚子痛”在库里找不到对应药
SYMPTOM_SYNONYMS = {
    "肚子痛": "胃痛 腹痛", "肚子疼": "胃痛 腹痛", "肚痛": "胃痛 腹痛",
    "腹痛": "胃痛 腹痛", "小腹痛": "胃痛 腹痛", "胃疼": "胃痛",
    "拉肚子": "腹泻", "拉稀": "腹泻", "上吐下泻": "腹泻 呕吐",
    "嗓子疼": "咽痛", "嗓子痛": "咽痛", "喉咙痛": "咽痛",
    "鼻子不通": "鼻塞", "流鼻水": "流鼻涕",
    "绞痛": "腹痛", "隐痛": "腹痛", "胀痛": "腹痛", "烧灼痛": "腹痛",
    "小腹痛": "腹痛", "上腹痛": "腹痛", "肚脐周围": "腹痛", "肚子胀": "胃胀",
}


def load_kb() -> list[dict[str, Any]]:
    return json.loads(KB_PATH.read_text(encoding="utf-8"))


def _domain_counts(item: dict[str, Any]) -> dict[str, int]:
    keys = [str(key) for key in (item.get("symptom_keys") or [])]
    counts: dict[str, int] = {}
    for name, domain in DOMAINS.items():
        terms = set(domain["canonical"]) | set(domain["keywords"])
        counts[name] = sum(
            1 for key in keys
            if key in terms or any(len(term) >= 2 and term in key for term in terms)
        )
    return counts


def _domains_of(item: dict[str, Any]) -> set[str]:
    return {name for name, count in _domain_counts(item).items() if count}


def search_tcm(symptoms: str, limit: int = 3,
               domains: list[str] | None = None) -> list[dict[str, Any]]:
    """Match symptom text against the curated TCM knowledge base.

    Ranking: more matched symptom keys first, then cheaper (price_order) first.
    """
    text = expand_symptoms(symptoms or "")
    for spoken, standard in SYMPTOM_SYNONYMS.items():
        if spoken in text and standard not in text:
            text = f"{text} {standard}"
    scored: list[tuple[int, dict[str, Any], list[str]]] = []
    allowed = set(domains or [])
    if allowed:
        # 口语描述（"脑袋要炸""拉不出来"）没有原词命中时，用系统规范词补齐检索
        canonical: list[str] = []
        for name in allowed:
            terms = DOMAINS.get(name, {}).get("canonical", [])
            if any(term in text for term in terms):
                continue  # 已经明确是便秘/腹泻，就不要把同系统所有词都加进来
            canonical.extend(terms)
        if canonical:
            text = text + " " + " ".join(dict.fromkeys(canonical))

    def _allowed_entry(item: dict[str, Any]) -> bool:
        if not allowed:
            return True
        counts = _domain_counts(item)
        entry_domains = {name for name, count in counts.items() if count}
        if entry_domains and not (entry_domains & allowed):
            return False
        # 成人问诊不要推荐小儿专用药；只有明确提到孩子才放开
        if "pediatrics" in entry_domains and "pediatrics" not in allowed:
            return False
        best_allowed = max((counts.get(name, 0) for name in allowed), default=0)
        best_other = max(
            (count for name, count in counts.items() if name not in allowed),
            default=0,
        )
        return best_other <= best_allowed

    items = load_kb()
    by_key = {str(item.get("id") or item.get("name")): item for item in items}
    semantic_results = semantic_search(text, top_k=30)
    sims = {str(item.get("id") or item.get("name")): score
            for item, score in semantic_results}
    exact: dict[str, tuple[int, list[str]]] = {}
    for item in items:
        hits = [key for key in item.get("symptom_keys", []) if key and key in text]
        if hits and _allowed_entry(item):
            exact[str(item.get("id") or item.get("name"))] = (len(hits), hits)

    merged: list[tuple[float, dict[str, Any], list[str]]] = []
    for key, (hits, matched) in exact.items():
        merged.append((hits * 1.0 + sims.get(key, 0.0) * 2.5, by_key[key], matched))
    for item, score in semantic_results:
        key = str(item.get("id") or item.get("name"))
        if key in exact or score < 0.16 or not _allowed_entry(item):
            continue
        merged.append((score * 2.5, item, []))

    organ_terms = {"鼻": ("鼻", "鼻炎", "鼻窦"), "咽": ("咽", "喉", "声音"),
                   "耳": ("耳", "耳鸣"), "眼": ("眼", "目", "视物")}
    query_lower = (symptoms or "").lower()
    boosted = []
    for score, item, matched in merged:
        name = str(item.get("name") or "") + str(item.get("pattern") or "")
        for organ, terms in organ_terms.items():
            if organ in query_lower and any(term in name for term in terms):
                score += 0.6
                break
        boosted.append((score, item, matched))
    merged = boosted
    merged.sort(key=lambda row: (-row[0], row[1].get("price_order", 9)))
    selected = []
    for _, item, matched in merged[:limit]:
        entry = dict(item)
        entry["matched"] = matched
        selected.append(entry)
    return selected


def format_candidates(candidates: list[dict[str, Any]]) -> str:
    """Render candidates for a prompt or a CLI log."""
    lines = []
    for item in candidates:
        lines.append(
            f"- {item['name']}（{item['otc']}，{item['form']}，{item['price_range']}，"
            f"辨证：{item['pattern']}）主治：{'、'.join(item['indications'])}；"
            f"用法：{item['dosage']}；禁忌：{item['contraindications']}；"
            f"注意：{item['cautions']}"
        )
    return "\n".join(lines)

def by_pattern(tag: str, limit: int = 3) -> list[dict[str, Any]]:
    """Entries for one pattern tag, used when symptom keywords miss a branch."""
    items = [dict(item) for item in load_kb() if item.get("pattern_tag") == tag][:limit]
    for item in items:
        item.setdefault("matched", [])
    return items

def _kind(item: dict[str, Any], kind: str) -> bool:
    return item.get("kind", "patent") == kind


def recommend(symptoms: str, decision: str, tag: str | None = None,
              high_fever: bool = False, max_count: int = 5,
              domains: list[str] | None = None) -> list[dict[str, Any]]:
    """4-5 options per answer, mixing OTC patent medicines and herbs.

    ambiguous -> four per branch (2 patent + 2 herbs), so both branches are usable.
    """
    if high_fever:
        return []
    matched = search_tcm(symptoms, limit=20, domains=domains)
    if domains and "trauma" in domains:
        external_forms = ("气雾剂", "喷雾剂", "搽剂", "酊剂", "贴膏剂", "外用")
        external = [item for item in matched if item.get("form") in external_forms]
        internal = [item for item in matched if item not in external]
        matched = external + internal
    patents = [item for item in matched if _kind(item, "patent")]
    herbs = [item for item in matched if _kind(item, "herb")]

    if decision == "ambiguous":
        cold = [i for i in matched if i.get("pattern_tag") == "风寒"]
        heat = [i for i in matched if i.get("pattern_tag") == "风热"]
        focused = any(term in (symptoms or "") for term in
                      ("鼻", "耳", "眼", "孩子", "宝宝", "儿童", "小儿", "嗓"))
        # 经典感冒（风寒/风热都有信号）沿用两分支各 4 个；
        # 鼻、耳、眼、儿童等专项症状优先用检索相关性，避免全给感冒药。
        if not focused:
            # 辨证不明确：风寒、风热各给 2 个（一药一草），总数控制在 4–5 个
            selected: list[dict[str, Any]] = []
            extras: list[dict[str, Any]] = []
            for tag, base in (("风寒", cold), ("风热", heat)):
                group = base + [i for i in by_pattern(tag, 8)
                                if i.get("id") not in {x.get("id") for x in base}]
                chosen = ([i for i in group if _kind(i, "patent")][:1]
                          + [i for i in group if _kind(i, "herb")][:1])
                selected.extend(chosen)
                extras.extend(i for i in group if i not in chosen)
            for item in extras:
                if len(selected) >= 5:
                    break
                if item.get("id") not in {x.get("id") for x in selected}:
                    selected.append(item)
            return selected[:5]
        selected = patents[:3] + herbs[:2]
        if len(selected) < 4:
            for branch in ("风寒", "风热"):
                group = by_pattern(branch, 8)
                selected += [i for i in group if _kind(i, "patent")
                             and i.get("id") not in {x.get("id") for x in selected}][:2]
                selected += [i for i in group if _kind(i, "herb")
                             and i.get("id") not in {x.get("id") for x in selected}][:1]
        return selected[:max_count] or matched[:max_count]

    if decision == "not_applicable":
        selected = patents[:3] + herbs[:3]
        if len(selected) < 4:
            selected = matched[:max_count]
        return selected[:max_count] if selected else matched[:max_count]

    if tag is None:
        tag = "风寒"
    selected = [i for i in patents if i.get("pattern_tag") == tag][:3]
    selected += [i for i in herbs if i.get("pattern_tag") == tag][:3]
    if len(selected) < 4:
        group = by_pattern(tag, 8)
        selected += [i for i in group
                     if _kind(i, "patent") and i.get("id") not in {x.get("id") for x in selected}][:2]
        selected += [i for i in group
                     if _kind(i, "herb") and i.get("id") not in {x.get("id") for x in selected}][:2]
    return selected[:max_count]

