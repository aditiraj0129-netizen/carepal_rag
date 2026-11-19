"""PII redaction applied before anything is logged, stored for analytics, traced, or sent to an LLM.

Handles Indian mobile numbers (including Devanagari digits), emails, Aadhaar-like 12-digit numbers and
self-introduced names in English, Hinglish and Hindi.
"""
from __future__ import annotations

import re
from typing import Any

_DEVANAGARI_DIGITS = str.maketrans("\u0966\u0967\u0968\u0969\u096a\u096b\u096c\u096d\u096e\u096f", "0123456789")

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("[EMAIL]", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("[ID]", re.compile(r"(?<!\d)\d{4}[\s-]?\d{4}[\s-]?\d{4}(?!\d)")),
    ("[PHONE]", re.compile(r"(?<![\w])(?:\+?91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?![\w])")),
]
_NAME_PATTERNS = [
    re.compile(r"(?i:\bmy name is|\bmera naam|\bi am|\bi'm|\bmain)\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)"),
    re.compile(r"(?:मेरा नाम|मैं)\s+([\u0900-\u097f]+(?:\s+[\u0900-\u097f]+)?)"),
]
# words that follow "I am" / "main" but are not names
_NOT_NAMES = {"Looking", "Worried", "Asking", "Writing", "Calling", "Trying", "Not", "Sure", "Here", "Very"}


def redact_pii(text: str) -> str:
    if not text:
        return text
    probe = text.translate(_DEVANAGARI_DIGITS)  # same length, so spans line up with `text`
    spans: list[tuple[int, int, str]] = []
    for label, pat in _PATTERNS:
        for m in pat.finditer(probe):
            spans.append((m.start(), m.end(), label))
    for pat in _NAME_PATTERNS:
        for m in pat.finditer(text):
            if m.group(1) not in _NOT_NAMES:
                spans.append((m.start(1), m.end(1), "[NAME]"))
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    out, pos = [], 0
    for start, end, label in spans:
        if start < pos:  # overlaps a span we already replaced
            continue
        out.append(text[pos:start])
        out.append(label)
        pos = end
    out.append(text[pos:])
    return "".join(out)


def sanitize_for_trace(obj: Any, max_len: int = 2000) -> Any:
    """Recursively redact strings and truncate before data leaves the process (e.g. to LangSmith)."""
    if isinstance(obj, str):
        r = redact_pii(obj)
        return r if len(r) <= max_len else r[:max_len] + "...[truncated]"
    if isinstance(obj, dict):
        return {k: sanitize_for_trace(v, max_len) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_for_trace(v, max_len) for v in obj]
    return obj
