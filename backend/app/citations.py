"""Citation anchoring: does the cited source actually support the sentence?

The model is given numbered sources; this module checks the sentences that carry
the highest risk: those naming a TCM product or quoting a dosage.  Claims about
other topics, meta-commentary about the source list, headings and questions are
not judged here — the review already checks citation ranges, the disclaimer and
forbidden wording.

Support test: content tokens shared with the cited source, excluding tokens that
only repeat the source title (the product name).  Dosage numbers in the sentence
must also appear in the cited source.
"""

from __future__ import annotations

import re
from typing import Any

STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "have", "has", "are", "was",
    "were", "will", "can", "may", "you", "your", "not", "but", "its", "they", "their",
    "also", "than", "when", "what", "which", "how", "who", "use", "used", "using",
}

# Bigrams too generic to prove support.
GENERIC_BIGRAMS = {
    "建议", "使用", "可以", "可能", "注意", "如果", "需要", "出现", "症状", "以下",
    "以上", "本次", "参考", "说明", "一次", "一日", "每日", "服用", "口服", "本品",
    "以及", "或者", "所以", "因此", "进行", "选择", "情况", "时间", "医生", "药师",
}

# Structural / meta lines that are not factual claims.
SKIP_PREFIXES = ("#", "|", "[", ">", "- **参考价", "- **用法", "- **禁忌", "- **注意", "- **适用")
SKIP_WORDS = ("参考价", "辨证方向", "用法（按说明书）", "用法（照说明书）", "禁忌：", "注意：",
              "没有提供", "未提供", "题录", "说明书摘要", "无法判断", "不足以",
              "均为单药", "联合用药方案", "免责声明")

CITATION_RE = re.compile(r"\[(\d+)(?:\s*[-–]\s*(\d+))?\]")
SENTENCE_SPLIT = re.compile(r"(?<=[。！？；!?;])|\n")
DOSE_RE = re.compile(r"\d+\s*(?:mg|ml|毫升|毫克|g\b|袋|片|丸|粒|支|瓶|盒)", re.IGNORECASE)


def citation_numbers(text: str) -> set[int]:
    numbers: set[int] = set()
    for match in CITATION_RE.finditer(text):
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else start
        for number in range(min(start, end), max(start, end) + 1):
            numbers.add(number)
    return numbers


def strip_citations(text: str) -> str:
    return CITATION_RE.sub(" ", text)


def tokens(text: str) -> set[str]:
    lowered = text.lower()
    result = {word for word in re.findall(r"[a-z][a-z0-9\-]{3,}", lowered) if word not in STOPWORDS}
    for run in re.findall(r"[\u4e00-\u9fff]{2,}", lowered):
        for index in range(len(run) - 1):
            bigram = run[index:index + 2]
            if bigram not in GENERIC_BIGRAMS:
                result.add(bigram)
    return result


def source_text(source: dict[str, Any]) -> str:
    return " ".join(str(source.get(key) or "") for key in ("title", "snippet", "url"))


def product_names(sources: list[dict[str, Any]]) -> list[str]:
    names = []
    for source in sources:
        title = str(source.get("title") or "")
        name = re.split(r"[（(]", title)[0].strip()
        name = re.sub(r"说明书$", "", name).strip()
        if len(name) >= 3:
            names.append(name)
    return names


def is_high_risk_claim(claim: str, sources: list[dict[str, Any]]) -> bool:
    """Only drug/dose sentences are anchored; anything else is left to review."""
    if DOSE_RE.search(claim):
        return True
    return any(name in claim for name in product_names(sources))


def _drop_section(markdown: str, keyword: str) -> str:
    """Remove a whole section (e.g. the patient-supplied medication log) from anchoring."""
    kept: list[str] = []
    skipping = False
    for line in markdown.splitlines():
        if line.startswith("## "):
            skipping = keyword in line
        if not skipping:
            kept.append(line)
    return "\n".join(kept)


def sentences(markdown: str) -> list[str]:
    markdown = _drop_section(markdown, "正在用药")
    parts = [part.strip() for part in SENTENCE_SPLIT.split(markdown) if part and part.strip()]
    result = []
    for part in parts:
        if len(part) > 400 or part.startswith(SKIP_PREFIXES):
            continue
        if any(word in part for word in SKIP_WORDS):
            continue
        if part.rstrip().endswith("？"):
            continue
        result.append(part)
    return result


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", strip_citations(text)))


DOSAGE_VERBS = ("口服", "冲服", "煎服", "滴眼", "外用", "含服", "温水送服")


def _normalize_dose(text: str) -> str:
    cleaned = re.sub(r"[\s，,。；;：:]", "", text or "")
    return cleaned.replace("–", "-").replace("—", "-").replace("~", "-").replace("～", "-")


def _dose_phrase(text: str) -> str:
    for verb in DOSAGE_VERBS:
        index = text.find(verb)
        if index == -1:
            continue
        fragment = text[index:index + 60]
        fragment = re.split(r"[。；;]", fragment)[0]
        normalized = _normalize_dose(fragment)
        if len(normalized) >= 6 and re.search(r"\d", normalized):
            return normalized
    return ""


def dose_supported(claim: str, source_raw: str) -> bool:
    """Exact dose wording in the cited source is the strongest signal."""
    phrase = _dose_phrase(claim)
    return bool(phrase) and phrase in _normalize_dose(source_raw)


def verify_citations(markdown: str, sources: list[dict[str, Any]]) -> list[str]:
    findings: list[str] = []
    if not sources:
        return findings
    for sentence in sentences(markdown):
        cited = citation_numbers(sentence)
        if not cited:
            continue
        claim = strip_citations(sentence)
        if not is_high_risk_claim(claim, sources):
            continue
        if sum(1 for name in product_names(sources) if name in claim) >= 2:
            continue  # 一句里并列多个药的"参见"式提示，不做单条锚定
        recommendation = any(word in claim for word in
                             ("首选", "推荐", "可选", "替代", "优先", "考虑", "建议"))
        if (recommendation and len(claim) <= 45
                and any(name in claim for name in product_names(sources))):
            continue  # 只点名"首选/可选某药"的短句；疗效/禁忌等实质断言仍逐条锚定
        claim_tokens = tokens(claim)
        claim_numbers = _numbers(claim)
        for number in sorted(cited):
            if not 1 <= number <= len(sources):
                continue
            source = sources[number - 1]
            source_raw = source_text(source)
            claim_chinese = bool(re.search(r"[\u4e00-\u9fff]", claim))
            source_chinese = bool(re.search(r"[\u4e00-\u9fff]", source_raw))
            if claim_chinese != source_chinese:
                continue  # cross-language pair: cannot judge support automatically
            title_tokens = tokens(str(source.get("title") or ""))
            overlap = (claim_tokens & tokens(source_raw)) - title_tokens
            names_matched = bool(claim_tokens & title_tokens)
            numbers_in_source = _numbers(source_raw)
            numbers_matched = bool(claim_numbers & numbers_in_source) if claim_numbers else False
            product_ok = any(name in claim for name in product_names([source]))
            if product_ok and not claim_numbers:
                supported = True  # 药名层面的句子，cited 来源正是该药说明书
            # 产品名 + 同类字段（价格/禁忌/用法）也算有支撑，但不能只凭产品名
            fields = ("参考价", "价格", "禁忌", "注意", "用法", "剂量")
            field_ok = any(word in claim and word in source_raw for word in fields)
            dose_ok = dose_supported(claim, source_raw)
            supported = dose_ok or len(overlap) >= 2 or (product_ok and field_ok)
            if claim_numbers and not numbers_matched and not dose_ok:
                supported = False
            if claim_numbers and numbers_matched and product_ok:
                supported = True
            if not supported:
                findings.append(
                    f"引用 [{number}] 与其所在句子的内容不匹配：{claim[:50]}…"
                )
                break
    return findings
