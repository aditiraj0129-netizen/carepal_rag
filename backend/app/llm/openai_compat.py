"""Client for any OpenAI-compatible /chat/completions endpoint (OpenAI, Groq, Gemini's OpenAI-compatible
URL, a local server...). Configure LLM_BASE_URL / LLM_MODEL / LLM_API_KEY; nothing is hardcoded."""
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx

from app.config import Settings
from app.llm.base import LLMClient, LLMError


class OpenAICompatClient:
    name = "openai_compat"

    def __init__(self, base_url: str, model: str, api_key: str | None, timeout: float = 30.0,
                 transport: httpx.BaseTransport | None = None):
        if not base_url or not model:
            raise LLMError("LLM_BASE_URL and LLM_MODEL must be set for the openai_compat provider")
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.Client(base_url=base_url.rstrip("/"), headers=headers, timeout=timeout,
                                    transport=transport)
        self.model = model

    def _payload(self, messages: list[dict[str, str]], stream: bool) -> dict[str, Any]:
        return {"model": self.model, "messages": messages, "temperature": 0.1, "stream": stream}

    def complete_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        try:
            resp = self._client.post("/chat/completions", json=self._payload(messages, False))
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            start, end = content.find("{"), content.rfind("}")
            return json.loads(content[start:end + 1])
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"completion failed: {exc.__class__.__name__}") from exc

    def stream_text(self, messages: list[dict[str, str]]) -> Iterator[str]:
        try:
            with self._client.stream("POST", "/chat/completions", json=self._payload(messages, True)) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    try:
                        delta = json.loads(data)["choices"][0].get("delta", {}).get("content")
                    except (ValueError, KeyError, IndexError):
                        continue
                    if delta:
                        yield delta
        except httpx.HTTPError as exc:
            raise LLMError(f"stream failed: {exc.__class__.__name__}") from exc


def build_llm(settings: Settings) -> LLMClient | None:
    """None means extractive mode (no LLM)."""
    if settings.llm_provider == "extractive":
        return None
    key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else None
    return OpenAICompatClient(settings.llm_base_url or "", settings.llm_model, key, settings.llm_timeout_seconds)
