"""Post-generation verification. Deterministic checks that catch the most damaging errors cheaply."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.pipeline.context import Context
from app.pipeline.safety import LEAD_INS

MARKER = re.compile(r"\[(S\d+)\]")
NUMBER = re.compile(r"\d[\d,.\-/ ]*\d|\d")
URL_OR_EMAIL = re.compile(r"https?://\S+|[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
FORBIDDEN = re.compile(
    r"₹|\brs\.?\s*\d|\binr\b|\bper (hour|day|month|week)\b|\bguarantee[sd]?\b|\bwithin \d+ ?(minutes?|hours?|days?)\b",
    re.I)
SENTENCE = re.compile(r"(?<=[.!?।])\s+")


@dataclass
class VerifyResult:
    ok: bool
    failures: list[str] = field(default_factory=list)
    used_aliases: list[str] = field(default_factory=list)


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def verify_answer(answer: str, context: Context, language: str, *, strict_sentences: bool = False) -> VerifyResult:
    failures: list[str] = []
    aliases = context.by_alias()
    markers = MARKER.findall(answer)
    used = list(dict.fromkeys(markers))
    if not markers:
        failures.append("no_citation")
    for m in used:
        if m not in aliases:
            failures.append(f"unknown_citation:{m}")
    cited_text = " ".join(aliases[m].chunk.text for m in used if m in aliases)
    cited_low = cited_text.lower()
    body = MARKER.sub("", answer)
    for lead in LEAD_INS.values():
        body = body.replace(lead, "")
    # numbers / urls / emails / currency / promises must be supported by a cited source
    cited_digits = _digits(cited_text)
    for num in NUMBER.findall(body):
        d = _digits(num)
        if d and d not in cited_digits:
            failures.append(f"unsupported_number:{num.strip()}")
    for tok in URL_OR_EMAIL.findall(body):
        if tok.lower().rstrip(".,)") not in cited_low:
            failures.append(f"unsupported_token:{tok}")
    for m in FORBIDDEN.finditer(body):
        if m.group(0).lower() not in cited_low:
            failures.append(f"unsupported_claim:{m.group(0)}")
    if strict_sentences:
        for sent in SENTENCE.split(answer.strip()):
            if len(sent.split()) > 6 and not MARKER.search(sent):
                failures.append("uncited_sentence")
                break
    deva = len(re.findall(r"[ऀ-ॿ]", answer))
    letters = sum(c.isalpha() for c in answer) or 1
    if language == "hi" and deva / letters < 0.2 and not any(lead in answer for lead in LEAD_INS.values()):
        failures.append("language_mismatch")
    if "<<INSUFFICIENT>>" in answer or "<source" in answer or "<context" in answer:
        failures.append("leak")
    return VerifyResult(not failures, failures, used)
