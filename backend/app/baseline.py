"""Naive single-agent baseline: one model call, no tools, no retrieval.

Deliberately the "single agent works alone" control condition for the platform
comparison.  It receives no knowledge base, no sources and no safety review.
"""

from __future__ import annotations

import time
from typing import Any

from .llm import LLMClient

SYSTEM = """你是一个健康助手。根据用户描述的症状给出建议：可能的原因、推荐的药物与用法、
注意事项以及何时就医。用中文 Markdown 回答，控制在 400 字以内，尽量具体、直接。"""


def answer(symptoms: str, client: LLMClient) -> dict[str, Any]:
    started = time.monotonic()
    markdown = client.chat([
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"症状：{symptoms}"},
    ])
    return {
        "markdown": markdown,
        "latency_s": round(time.monotonic() - started, 2),
        "usage": dict(client.last_usage),
        "provider": client.provider,
    }
