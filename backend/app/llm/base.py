"""LLM provider interface. The pipeline works without any LLM (extractive mode)."""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Protocol


class LLMError(Exception):
    """Provider call failed (network, auth, quota, malformed output)."""


class LLMClient(Protocol):
    name: str

    def complete_json(self, messages: list[dict[str, str]]) -> dict[str, Any]: ...
    def stream_text(self, messages: list[dict[str, str]]) -> Iterator[str]: ...
