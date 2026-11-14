"""Western-drug interaction lookup from openFDA labels, with a clear caveat.

RxNav's interaction endpoint is retired, so for pairs of western drugs we look up
the FDA label of the patient's medication and check whether it names the other
drug in its interactions/warnings sections. Chinese herbs are not covered here;
those rely on the small curated rules and are labelled as such.
"""

from __future__ import annotations

import json
import re
import threading
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

CACHE_PATH = Path(__file__).resolve().parents[1] / "out" / "drug-labels.json"
LOCK = threading.Lock()
_cache: dict[str, Any] = {}

MAP: dict[str, str] = {
    "布洛芬": "ibuprofen",
    "对乙酰氨基酚": "acetaminophen",
    "扑热息痛": "acetaminophen",
    "阿司匹林": "aspirin",
    "华法林": "warfarin",
    "氯吡格雷": "clopidogrel",
    "奥美拉唑": "omeprazole",
    "伪麻黄碱": "pseudoephedrine",
    "多潘立酮": "domperidone",
    "蒙脱石散": "diosmectite",
    "右美沙芬": "dextromethorphan",
    "氯雷他定": "loratadine",
    "西替利嗪": "cetirizine",
    "洛哌丁胺": "loperamide",
    "乳果糖": "lactulose",
    "特比萘芬": "terbinafine",
    "茶苯海明": "dimenhydrinate",
    "铝碳酸镁": "hydrotalcite",
    "氨溴索": "ambroxol",
    "阿莫西林": "amoxicillin",
    "二甲双胍": "metformin",
    "氨氯地平": "amlodipine",
    "缬沙坦": "valsartan",
    "辛伐他汀": "simvastatin",
    "左甲状腺素": "levothyroxine",
    "地高辛": "digoxin",
}


def map_drug(name: str) -> str | None:
    for key, english in MAP.items():
        if key and key in name:
            return english
    return None


def _load_cache() -> None:
    global _cache
    if _cache:
        return
    try:
        _cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        _cache = {}


def _save_cache() -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(_cache, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _label_text(english: str) -> str:
    _load_cache()
    if english in _cache:
        return _cache[english]
    query = urllib.parse.urlencode({
        "search": f'openfda.generic_name:"{english}"',
        "limit": 1,
    })
    url = f"https://api.fda.gov/drug/label.json?{query}"
    try:
        with urllib.request.urlopen(url, timeout=6) as response:
            data = json.loads(response.read().decode("utf-8"))
        result = (data.get("results") or [{}])[0]
        parts = []
        for field in ("drug_interactions", "warnings", "warnings_and_cautions"):
            parts.extend(result.get(field) or [])
        text = " ".join(str(part) for part in parts)
    except Exception:
        text = ""
    _cache[english] = text
    with LOCK:
        _save_cache()
    return text


def check(med_name: str, other_name: str) -> dict[str, Any] | None:
    """Return a warning if the FDA label of med_name mentions other_name."""
    med_en = map_drug(med_name)
    other_en = map_drug(other_name)
    if not med_en or not other_en or med_en == other_en:
        return None
    text = _label_text(med_en)
    if not text:
        return None
    lowered = text.lower()
    if other_en not in lowered:
        return None
    index = lowered.find(other_en)
    left = max(text.rfind(". ", 0, index), text.rfind("; ", 0, index))
    right = text.find(". ", index)
    start = left + 2 if left >= 0 else max(0, index - 100)
    end = right + 1 if right >= 0 else min(len(text), index + 140)
    snippet = text[start:end].replace("\n", " ").strip()[:240]
    return {
        "source": "openFDA 药品说明书",
        "text": snippet[:260],
        "med": med_name,
        "other": other_name,
    }
