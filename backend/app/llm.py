"""LLM client: OpenAI-compatible or Anthropic-compatible endpoints, mock offline."""

from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx

from .config import settings


USAGE_TOTALS = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def reset_usage() -> None:
    for key in USAGE_TOTALS:
        USAGE_TOTALS[key] = 0


def usage_totals() -> dict[str, int]:
    return dict(USAGE_TOTALS)


class LLMUnavailable(RuntimeError):
    """The model could not be reached; callers should fall back to templates."""


class LLMClient:
    def __init__(self, provider: str | None = None, api_key: str | None = None,
                 base_url: str | None = None, model: str | None = None,
                 models: list[str] | None = None, api_format: str = "openai") -> None:
        self.provider = provider or settings.llm_provider
        self.last_usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self.api_key = (
            api_key
            or settings.custom_api_key
            or settings.deepseek_api_key
            or os.environ.get("DEEPSEEK_API_KEY", "")
        )
        raw_base = (base_url or settings.deepseek_base_url or "").rstrip("/")
        for suffix in ("/chat/completions", "/completions", "/messages", "/responses"):
            if raw_base.endswith(suffix):
                raw_base = raw_base[: -len(suffix)].rstrip("/")
                break
        if raw_base and "://" in raw_base and raw_base.split("://", 1)[1].count("/") == 0:
            raw_base += "/v1"
        self.base_url = raw_base
        self.model = model or settings.model
        self.models = [item for item in (models or []) if item] or [self.model]
        self.api_format = (api_format or "openai").lower()

    @property
    def live(self) -> bool:
        return (self.provider in ("deepseek", "custom")
                and bool(self.api_key) and bool(self.base_url) and bool(self.models))

    def _call_openai(self, model: str, messages: list[dict[str, str]],
                     json_mode: bool) -> tuple[str, dict[str, Any]]:
        # 自定义网关常有推理模型：把预算放大，避免思考 token 把正文挤空
        max_tokens = 6000 if self.provider == "custom" else settings.max_tokens
        payload: dict = {
            "model": model,
            "messages": messages,
            "temperature": settings.temperature,
            "max_tokens": max_tokens,
        }
        if self.provider == "deepseek" and settings.reasoning_effort:
            payload["reasoning_effort"] = settings.reasoning_effort
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        with httpx.Client(timeout=httpx.Timeout(settings.timeout_seconds, connect=8.0)) as client:
            response = client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Content-Type": "application/json"},
                json=payload,
            )
            if response.status_code == 400 and "response_format" in payload:
                payload.pop("response_format", None)
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}",
                             "Content-Type": "application/json"},
                    json=payload,
                )
            response.raise_for_status()
            data = response.json()
        choices = data.get("choices") or [{}]
        message = (choices[0] or {}).get("message") or {}
        content = (message.get("content") or "").strip()
        usage = data.get("usage") or {}
        return content, usage

    def _call_anthropic(self, model: str, messages: list[dict[str, str]],
                        json_mode: bool) -> tuple[str, dict[str, Any]]:
        system = " ".join(item["content"] for item in messages if item["role"] == "system")
        chat_messages = [item for item in messages if item["role"] != "system"]
        payload: dict = {
            "model": model,
            "max_tokens": settings.max_tokens,
            "temperature": settings.temperature,
            "messages": chat_messages,
        }
        if system:
            payload["system"] = system
        with httpx.Client(timeout=httpx.Timeout(settings.timeout_seconds, connect=8.0)) as client:
            response = client.post(
                f"{self.base_url}/messages",
                headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                         "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        blocks = data.get("content") or []
        content = "".join(str(block.get("text") or "") for block in blocks
                          if isinstance(block, dict)).strip()
        usage = data.get("usage") or {}
        return content, usage

    def _call(self, model: str, messages: list[dict[str, str]],
              json_mode: bool) -> tuple[str, dict[str, Any]]:
        if self.api_format == "anthropic":
            return self._call_anthropic(model, messages, json_mode)
        return self._call_openai(model, messages, json_mode)

    def chat(self, messages: list[dict[str, str]], json_mode: bool = False) -> str:
        if not self.live:
            raise RuntimeError("mock mode: the LLM is not called")
        last_error: Exception | None = None
        attempts = 2 if self.provider == "deepseek" else 1
        for model in self.models:
            for attempt in range(attempts):
                try:
                    content, usage = self._call(model, messages, json_mode)
                    self.last_usage = {
                        "prompt_tokens": int(usage.get("prompt_tokens") or
                                             usage.get("input_tokens") or 0),
                        "completion_tokens": int(usage.get("completion_tokens") or
                                                 usage.get("output_tokens") or 0),
                        "total_tokens": int(usage.get("total_tokens") or
                                            (int(usage.get("input_tokens") or 0) +
                                             int(usage.get("output_tokens") or 0))),
                    }
                    for key in USAGE_TOTALS:
                        USAGE_TOTALS[key] += self.last_usage.get(key, 0)
                    if content:
                        return content
                    finish = (data.get("choices") or [{}])[0].get("finish_reason") \
                        if "data" in locals() else "unknown"
                    last_error = ValueError(
                        f"empty content (finish={finish}, completion_tokens="
                        f"{usage.get('completion_tokens', 0)})")
                    break
                except (httpx.HTTPError, KeyError, IndexError, ValueError) as error:
                    last_error = error
                    break
        raise LLMUnavailable(
            f"model unreachable after {len(self.models)} model(s): {last_error}") from last_error


def parse_json_object(text: str) -> dict:
    """Parse the first JSON object in a model reply, tolerating fences."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON object in reply: {text[:200]}")
    return json.loads(cleaned[start:end + 1])
