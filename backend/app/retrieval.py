"""Vector retrieval for the knowledge base.

Default: local TF-IDF over character n-grams (works offline, no downloads).
Optional: set EMBEDDING_MODEL_PATH to a local sentence-transformers model
directory and the same interface uses real embeddings instead.

The KB is small (138 entries), so the index is rebuilt in memory on first use
and cached by file mtime.
"""

from __future__ import annotations

import math
import os
import re
from pathlib import Path
from typing import Any

import numpy as np

DATA_PATH = Path(__file__).resolve().parent / "data" / "tcm.json"
_MODEL = None
_INDEX: dict[str, Any] = {}
_CACHE_KEY: tuple[float, str] | None = None

CJK = re.compile(r"[\u4e00-\u9fff]+")
LATIN = re.compile(r"[a-zA-Z][a-zA-Z0-9\-]{2,}")


def _ngrams(text: str) -> list[str]:
    grams: list[str] = []
    lowered = (text or "").lower()
    for run in CJK.findall(lowered):
        for size in (1, 2, 3):
            for index in range(len(run) - size + 1):
                grams.append(f"{size}:{run[index:index + size]}")
    for word in LATIN.findall(lowered):
        grams.append(f"w:{word}")
    return grams


def _doc_text(item: dict[str, Any]) -> str:
    parts = [
        str(item.get("name") or ""),
        " ".join(item.get("symptom_keys") or []),
        " ".join(item.get("indications") or []),
        str(item.get("pattern") or ""),
        str(item.get("cautions") or ""),
        str(item.get("contraindications") or ""),
    ]
    return " ".join(part for part in parts if part)


def _neural_available() -> bool:
    return bool(os.environ.get("EMBEDDING_MODEL_PATH"))


def _neural_encode(texts: list[str]) -> np.ndarray:
    global _MODEL
    if _MODEL is None:
        from sentence_transformers import SentenceTransformer

        _MODEL = SentenceTransformer(os.environ["EMBEDDING_MODEL_PATH"], device="cpu")
    return np.asarray(_MODEL.encode(texts, normalize_embeddings=True))


def _build() -> dict[str, Any]:
    import json

    items = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    texts = [_doc_text(item) for item in items]
    if _neural_available():
        matrix = _neural_encode(texts)
        return {"items": items, "texts": texts, "matrix": matrix, "mode": "neural"}

    tokenized = [_ngrams(text) for text in texts]
    df: dict[str, int] = {}
    for grams in tokenized:
        for gram in set(grams):
            df[gram] = df.get(gram, 0) + 1
    total = len(tokenized)
    idf = {gram: math.log((1 + total) / (1 + count)) + 1 for gram, count in df.items()}
    matrix = []
    for grams in tokenized:
        counts: dict[str, int] = {}
        for gram in grams:
            counts[gram] = counts.get(gram, 0) + 1
        vector = {gram: (1 + math.log(count)) * idf[gram] for gram, count in counts.items()}
        norm = math.sqrt(sum(value * value for value in vector.values())) or 1.0
        matrix.append({gram: value / norm for gram, value in vector.items()})
    return {"items": items, "texts": texts, "matrix": matrix, "idf": idf,
            "mode": "tfidf"}


def index() -> dict[str, Any]:
    global _INDEX, _CACHE_KEY
    stat = DATA_PATH.stat()
    key = (stat.st_mtime, DATA_PATH.name)
    if _INDEX and _CACHE_KEY == key:
        return _INDEX
    _INDEX = _build()
    _CACHE_KEY = key
    return _INDEX


def _query_vector(query: str) -> Any:
    data = index()
    if data["mode"] == "neural":
        return _neural_encode([query])[0]
    counts: dict[str, int] = {}
    grams = _ngrams(query)
    for gram in grams:
        counts[gram] = counts.get(gram, 0) + 1
    idf = data["idf"]
    vector = {gram: (1 + math.log(count)) * idf[gram]
              for gram, count in counts.items() if gram in idf}
    norm = math.sqrt(sum(value * value for value in vector.values())) or 1.0
    return {gram: value / norm for gram, value in vector.items()}


def search(query: str, top_k: int = 20) -> list[tuple[dict[str, Any], float]]:
    """Return (item, similarity) sorted by cosine similarity."""
    data = index()
    query = (query or "").strip()
    if not query:
        return []
    vector = _query_vector(query)
    scores: list[tuple[dict[str, Any], float]] = []
    if data["mode"] == "neural":
        sims = np.dot(data["matrix"], vector)
        for item, score in zip(data["items"], sims):
            scores.append((item, float(score)))
    else:
        for item, doc_vector in zip(data["items"], data["matrix"]):
            score = sum(value * doc_vector.get(gram, 0.0) for gram, value in vector.items())
            scores.append((item, float(score)))
    scores.sort(key=lambda pair: pair[1], reverse=True)
    return scores[:top_k]


def mode() -> str:
    return index()["mode"]
