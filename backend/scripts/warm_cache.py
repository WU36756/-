#!/usr/bin/env python3
"""Warm the offline evidence cache for the demo symptom sets."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipeline import analyze  # noqa: E402

SYMPTOMS = [
    "发烧，咽喉痛，有点怕冷",
    "咳嗽三天，有黄痰",
    "高烧39度，头痛",
    "胃胀，反酸，吃不下饭",
    "失眠，多梦，白天乏力",
    "痛经，有血块",
]

for symptoms in SYMPTOMS:
    result = analyze(symptoms, provider="mock")
    print(f"{symptoms}: evidence={len(result['evidence'])} trace={len(result['trace'])}")
