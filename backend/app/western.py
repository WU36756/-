"""Curated Chinese-language OTC western-medicine knowledge base."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

KB_PATH = Path(__file__).resolve().parent / "data" / "western.json"


def load_kb() -> list[dict[str, Any]]:
    return json.loads(KB_PATH.read_text(encoding="utf-8"))


def for_terms(terms: list[str], limit: int = 2) -> list[dict[str, Any]]:
    """Pick at most ``limit`` OTC options matching the English symptom terms."""
    lowered = {term.lower() for term in terms}
    picked: list[dict[str, Any]] = []
    for item in load_kb():
        if lowered & {term.lower() for term in item.get("matched_terms", [])}:
            picked.append(item)
        if len(picked) >= limit:
            break
    return picked
