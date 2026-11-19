"""Unit tests: language, safety routing, redaction/tracing, escalation, verifier, LLM client."""
import pytest

from app import db
from app.config import Settings
from app.escalation import EscalationError, SqliteHandoffSink, create_support_request, normalize_phone, validate_name
from app.observability.redaction import redact_pii, sanitize_for_trace
from app.observability.tracing import configure_tracing, trace_span, tracing_enabled
from app.pipeline.language import detect_language
from app.retrieval.tokenization import tokenize
from tests.conftest import make_settings


def test_language_detection():
    assert detect_language("What is the refund policy?") == "en"
    assert detect_language("रिफंड पॉलिसी क्या है?") == "hi"
    assert detect_language("mere papa ko dementia hai, kya aap ghar par care dete ho?") == "hinglish"


def test_tokenizer_handles_exact_terms_and_hinglish_stopwords():
    assert tokenize("Telmideed 40") == tokenize("telmideed 40") and "40" in tokenize("Telmideed 40")
    assert tokenize("alzeihmer care") == tokenize("alzheimer care")
    assert "kitna" not in tokenize("refund kitna milega")


def test_redaction_removes_phone_email_and_names():
    t = redact_pii("Call me on +91 98765 43210 or a.b@x.com, my name is Ravi Kumar")
    assert "98765" not in t and "a.b@x.com" not in t and "Ravi" not in t
    assert sanitize_for_trace({"q": "9876543210"})["q"] != "9876543210"


def test_tracing_is_a_noop_when_disabled(tmp_path):
    s = make_settings(tmp_path)
    assert configure_tracing(s) is False and tracing_enabled() is False
    with trace_span("x", inputs={"a": 1}) as sp:
        sp.set(ok=True)


def test_phone_and_name_validation():
    assert normalize_phone("98765 43210") == "+919876543210"
    assert normalize_phone("+91-9876543210") == "+919876543210"
    for bad in ("12345", "5876543210", "abcdefghij"):
        with pytest.raises(EscalationError):
            normalize_phone(bad)
    with pytest.raises(EscalationError):
        validate_name("1")


def mk(settings, **kw):
    base = dict(conversation_id="c1", name="Asha Rao", phone="9876543210", consent=True, reason="wants_human",
                question=None, language="en", honeypot="")
    base.update(kw)
    return create_support_request(settings, SqliteHandoffSink(settings), **base)


def test_escalation_requires_consent_and_is_honest(tmp_path):
    s = make_settings(tmp_path)
    db.init_db(s.sqlite_path)
    with pytest.raises(EscalationError):
        mk(s, consent=False)
    with pytest.raises(EscalationError):
        mk(s, honeypot="bot")
    r = mk(s)
    assert r.request_id.startswith("SR-") and r.delivery == "stored_locally" and r.notified_team is False
    assert mk(s).duplicate is True and mk(s).request_id == r.request_id  # idempotent within window


def test_short_self_contained_question_does_not_inherit_previous_topic():
    from app.pipeline.rewrite import build_plan
    plan = build_plan("रिफंड पॉलिसी क्या है?", "hi", previous_question="father dementia home care")
    assert "dementia" not in plan.english_query and "refund" in plan.english_query
    follow = build_plan("and for babies?", "en", previous_question="Do you offer free consultation")
    assert follow.english_query.startswith("Do you offer free consultation")
