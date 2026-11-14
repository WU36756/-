"""PubMed query construction, ranking and relevance filtering.

Pure functions so the ranking rules can be unit-tested without network access.

Why this exists: a bare ``esearch?term=headache`` returns whatever PubMed's
default best-match order gives, which for broad symptom words is dominated by
case reports and unrelated trials (vaccines, malaria, dengue).  We build a
field-tagged query, prefer guidelines / systematic reviews, filter by title
relevance, and fall back to a relaxed query when the strict one is too narrow.
"""

from __future__ import annotations

import re

# Publication types that count as high-confidence evidence for a symptom question.
GUIDELINE_TYPES = {"guideline", "practice guideline"}
REVIEW_TYPES = {"systematic review", "meta-analysis", "review"}

_STRICT_FILTER = (
    "guideline[pt] OR practice guideline[pt] OR systematic review[pt] "
    "OR meta-analysis[pt] OR review[pt]"
)

_STOPWORDS = {
    "and", "or", "not", "the", "a", "an", "of", "in", "for", "with", "to",
    "headache", "pain",  # kept so symptom words are not accidentally dropped
}


def keywords(term: str, limit: int = 4) -> list[str]:
    """Extract searchable keywords from free text (agent may pass a query)."""
    cleaned = re.sub(r"\[[^\]]*\]", " ", term)
    tokens = [t for t in re.split(r"[\s,;]+", cleaned) if t]
    result: list[str] = []
    for token in tokens:
        token = token.strip("()\"'.").lower()
        if not token or token in {"and", "or", "not"}:
            continue
        if token in _STOPWORDS and len(tokens) > 1:
            continue
        if token not in result:
            result.append(token)
        if len(result) >= limit:
            break
    return result or [term.strip().lower()]


def build_query(term: str, strict: bool = True, years: int = 10) -> str:
    """Build an esearch term: field-tagged keywords, optional review-type filter."""
    words = keywords(term)
    tagged = " OR ".join(f"{word}[tiab]" for word in words)
    if not strict:
        return tagged
    return f"({tagged}) AND ({_STRICT_FILTER})"


def _year(pubdate: str) -> int:
    match = re.match(r"(\d{4})", pubdate or "")
    return int(match.group(1)) if match else 0


def is_relevant(title: str, words: list[str]) -> bool:
    """A title is relevant when it mentions at least one keyword (stem match)."""
    text = (title or "").lower()
    if not text:
        return False
    for word in words:
        stem = word[:-1] if len(word) > 3 and word.endswith("s") else word
        if stem in text:
            return True
    return False


def rank(item: dict) -> tuple:
    """Sort key: guideline > systematic review > review > other, then newer."""
    types = {str(t).lower() for t in (item.get("pubtype") or [])}
    if types & GUIDELINE_TYPES:
        weight = 0
    elif types & {"systematic review", "meta-analysis"}:
        weight = 1
    elif "review" in types:
        weight = 2
    elif "case reports" in types:
        weight = 4
    else:
        weight = 3
    return (weight, -_year(item.get("pubdate") or ""))


def select(summaries: list[dict], words: list[str], limit: int) -> list[dict]:
    """Keep relevant titles, drop case reports when better evidence exists, rank."""
    relevant = [item for item in summaries if is_relevant(item.get("title") or "", words)]
    strong = [item for item in relevant if rank(item)[0] <= 2]
    pool = strong or relevant or summaries
    return sorted(pool, key=rank)[:limit]
