"""Evidence cache for offline demos (original module, restored).

`DEMO_OFFLINE=1` makes the pipeline prefer cached evidence instead of network.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

CACHE_PATH = Path(__file__).resolve().parents[1] / "data" / "evidence_cache.json"


def _key(symptoms: str) -> str:
    return hashlib.sha256((symptoms or "").strip().lower().encode()).hexdigest()[:24]


def offline_only() -> bool:
    return os.environ.get("DEMO_OFFLINE") == "1"


def _load_all() -> dict[str, Any]:
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load(symptoms: str) -> dict[str, Any] | None:
    data = _load_all()
    entry = data.get(_key(symptoms))
    if isinstance(entry, dict):
        return entry.get("evidence")
    return None


def save(symptoms: str, evidence: Any) -> None:
    data = _load_all()
    data[_key(symptoms)] = {"symptoms": symptoms, "evidence": evidence}
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
