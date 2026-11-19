"""Human escalation: consent, validation, request IDs, storage.

HONESTY RULE: this prototype only *stores* a support request. There is no CRM or messaging integration,
so no response here may claim a team member was notified or contacted. `HandoffSink` is the seam where a
real integration could be added once TheCarePal specifies it; only the SQLite sink exists.
"""
from __future__ import annotations

import re
import secrets
import sqlite3
import string
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from app import db
from app.config import Settings
from app.observability.redaction import redact_pii

_DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_PHONE = re.compile(r"^(?:\+?91|0)?([6-9]\d{9})$")
_NAME_OK = re.compile(r"^[A-Za-zऀ-ॿ][A-Za-zऀ-ॿ .'\-]{1,79}$")
REASONS = {"unanswered", "low_confidence", "wants_human", "complaint", "emergency", "distress", "privacy", "other"}
PRIORITY = {"emergency": "urgent", "distress": "urgent", "complaint": "high"}


class EscalationError(ValueError):
    """Invalid or incomplete support request (safe to show to the user)."""


def normalize_phone(raw: str) -> str:
    cleaned = re.sub(r"[\s\-().]", "", raw.translate(_DEV_DIGITS))
    m = _PHONE.match(cleaned)
    if not m:
        raise EscalationError("Please enter a valid 10-digit Indian mobile number (starting with 6-9).")
    return f"+91{m.group(1)}"


def validate_name(raw: str) -> str:
    name = re.sub(r"\s+", " ", raw).strip()
    if not _NAME_OK.match(name):
        raise EscalationError("Please enter your name (letters only, 2-80 characters).")
    return name


def new_request_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return f"SR-{datetime.now(UTC):%Y%m%d}-" + "".join(secrets.choice(alphabet) for _ in range(6))


@dataclass
class SupportRequest:
    request_id: str
    status: str
    delivery: str
    notified_team: bool
    duplicate: bool = False


class HandoffSink(Protocol):
    def save(self, record: dict) -> SupportRequest: ...


class SqliteHandoffSink:
    delivery = "stored_locally"

    def __init__(self, settings: Settings):
        self.settings = settings

    def save(self, record: dict) -> SupportRequest:
        with db.session(self.settings.sqlite_path) as conn:
            # idempotency: the same phone + session within 10 minutes returns the existing request
            cutoff = (datetime.now(UTC) - timedelta(minutes=10)).isoformat(timespec="seconds")
            row = conn.execute(
                "SELECT id FROM handoffs WHERE phone=? AND conversation_id=? AND created_at>=? "
                "ORDER BY created_at DESC LIMIT 1", (record["phone"], record["conversation_id"], cutoff)).fetchone()
            if row:
                return SupportRequest(row["id"], "recorded", self.delivery, False, duplicate=True)
            conn.execute(
                "INSERT INTO handoffs(id,conversation_id,name,phone,consent,language,reason,priority,"
                "question_redacted,status,delivery,created_at,delete_after) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (record["id"], record["conversation_id"], record["name"], record["phone"], 1, record["language"],
                 record["reason"], record["priority"], record["question_redacted"], "new", self.delivery,
                 record["created_at"], record["delete_after"]))
        return SupportRequest(record["id"], "recorded", self.delivery, False)


def create_support_request(settings: Settings, sink: HandoffSink, *, conversation_id: str, name: str, phone: str,
                           consent: bool, reason: str, question: str | None, language: str,
                           honeypot: str = "") -> SupportRequest:
    if honeypot:
        raise EscalationError("Invalid request.")
    if not consent:
        raise EscalationError("Consent is required: please agree to be contacted on this number.")
    now = datetime.now(UTC)
    record = {
        "id": new_request_id(), "conversation_id": conversation_id, "name": validate_name(name),
        "phone": normalize_phone(phone), "language": language, "reason": reason if reason in REASONS else "other",
        "priority": PRIORITY.get(reason, "normal"), "question_redacted": redact_pii((question or "")[:500]),
        "created_at": now.isoformat(timespec="seconds"),
        "delete_after": (now + timedelta(days=settings.handoff_retention_days)).isoformat(timespec="seconds"),
    }
    return sink.save(record)


CONFIRMATION = {
    "en": "Your request {rid} has been saved. This prototype does not contact anyone automatically, so nobody has been notified yet; the team can follow up from the saved requests. You can also message TheCarePal on WhatsApp.",
    "hi": "आपका अनुरोध {rid} सहेज लिया गया है। यह प्रोटोटाइप अपने-आप किसी से संपर्क नहीं करता, इसलिए अभी किसी को सूचित नहीं किया गया है; टीम सहेजे गए अनुरोधों से संपर्क कर सकती है। आप WhatsApp पर भी संदेश भेज सकते हैं।",
    "hinglish": "Aapka request {rid} save ho gaya hai. Yeh prototype apne-aap kisi se contact nahi karta, isliye abhi kisi ko inform nahi kiya gaya hai; team saved requests se follow up kar sakti hai. Aap WhatsApp par bhi message kar sakte hain.",
}


def purge_expired(settings: Settings) -> int:
    with db.session(settings.sqlite_path) as conn:
        cur: sqlite3.Cursor = conn.execute("DELETE FROM handoffs WHERE delete_after < ?",
                                           (datetime.now(UTC).isoformat(timespec="seconds"),))
        return cur.rowcount
