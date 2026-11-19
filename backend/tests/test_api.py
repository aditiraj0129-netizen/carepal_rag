"""API + end-to-end tests through the real FastAPI app (real index, real retrieval, real SQLite)."""
import json

import pytest
from fastapi.testclient import TestClient

from app import db
from app.api.main import create_app
from app.ingestion.pipeline import run_ingest
from tests.conftest import make_settings

SID = "session-abcdef12"
ADMIN = {"Authorization": "Bearer test-admin-key"}


@pytest.fixture
def client(ingested):
    with TestClient(create_app(ingested)) as c:
        yield c


def chat(client, msg, debug=False, sid=SID):
    r = client.post("/chat", json={"session_id": sid, "message": msg, "debug": debug})
    assert r.status_code == 200, r.text
    return r.json()


def test_health(client):
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["index_ready"] and h["chunks"] > 50 and h["generator"] == "extractive"
    assert h["embedding_semantic"] is False  # honest: offline hashing embedder
    assert "x-request-id" in client.get("/health").headers


def test_refund_question_retrieves_real_chunk_and_returns_its_source_url(client):
    r = chat(client, "What is CarePal's refund policy?", debug=True)
    assert r["outcome"].startswith("answered") and r["citations"]
    top = r["citations"][0]
    assert top["url"] == "https://www.thecarepal.com/refund" and top["provenance"] == "research_summary"
    assert "non-refundable" in top["snippet"].lower() or "refund" in top["snippet"].lower()
    dbg = r["retrieval_debug"]
    assert {"dense_en", "bm25"} <= set(dbg["rankings"]) and dbg["rankings"]["bm25"][0]["url"].endswith("/refund")
    assert dbg["fused"][0]["url"].endswith("/refund")


def test_unpublished_price_abstains_without_inventing_numbers(client):
    r = chat(client, "How much does elderly care cost per month?")
    assert r["outcome"] in {"abstained", "abstain"} or r["abstain_reason"]
    assert r["abstain_reason"] == "unpublished" and "₹" not in r["answer"] and "Rs" not in r["answer"] and r["handoff_offer"]


def test_emergency_is_templated_with_numbers_and_no_retrieval(client):
    r = chat(client, "my father is not breathing and has chest pain")
    assert r["route"] == "emergency" and "112" in (r["emergency_numbers"] or []) and not r["citations"]


def test_hinglish_question_cites_dementia_page(client):
    r = chat(client, "mere papa ko dementia hai, kya aap ghar par care dete ho?")
    assert r["language"] == "hinglish" and any("/dementia" in c["url"] for c in r["citations"])


def test_stream_emits_events_and_done(client):
    with client.stream("POST", "/chat/stream", json={"session_id": SID, "message": "refund policy"}) as r:
        body = "".join(r.iter_text())
    events = [ln[7:] for ln in body.splitlines() if ln.startswith("event: ")]
    assert "meta" in events and "token" in events and "citations" in events and events[-1] == "done"


def test_feedback_ok_and_unknown_message(client):
    mid = chat(client, "refund policy")["message_id"]
    assert client.post("/feedback", json={"message_id": mid, "value": 1}).status_code == 200
    assert client.post("/feedback", json={"message_id": "nope-nope-nope", "value": 1}).status_code == 404


def test_escalation_flow_is_honest_and_pii_not_stored_in_messages(client, ingested):
    chat(client, "I want to talk to a person, my number is 9123456789", sid="session-esc00001")
    r = client.post("/support/escalate", json={"session_id": "session-esc00001", "name": "Asha Rao", "phone": "9123456789",
                                               "consent": True, "reason": "wants_human"})
    j = r.json()
    assert r.status_code == 200 and j["request_id"].startswith("SR-") and j["notified_team"] is False
    assert j["delivery"] == "stored_locally"
    with db.session(ingested.sqlite_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM messages WHERE text_redacted LIKE '%9123456789%'").fetchone()[0] == 0
    bad = client.post("/support/escalate", json={"session_id": SID, "name": "Asha Rao", "phone": "123", "consent": True})
    assert bad.status_code in (400, 422)
    nocons = client.post("/support/escalate", json={"session_id": SID, "name": "Asha Rao", "phone": "9123456780", "consent": False})
    assert nocons.status_code in (400, 422)


def test_admin_auth_and_analytics(client):
    assert client.get("/admin/analytics").status_code == 401
    assert client.get("/admin/analytics", headers={"Authorization": "Bearer wrong"}).status_code in (401, 403)
    chat(client, "What is the CEO's salary?")
    a = client.get("/admin/analytics", headers=ADMIN)
    assert a.status_code == 200 and a.json()
    u = client.get("/admin/unanswered", headers=ADMIN).json()
    assert isinstance(u["clusters"], list) and u["clusters"]


def test_admin_disabled_without_key(ingested):
    s = make_settings(ingested.data_dir, admin_api_key=None)
    with TestClient(create_app(s)) as c:
        assert c.get("/admin/analytics").status_code == 503


def test_admin_ingest_snapshots_and_evaluation_run(client):
    r = client.post("/admin/ingest", headers=ADMIN, json={"source": "snapshots"})
    assert r.status_code == 200 and r.json()["chunks_new"] == 0  # incremental: nothing changed
    ev = client.post("/evaluation/run", headers=ADMIN, json={"split": "dev", "modes": ["dense", "bm25", "hybrid"]})
    assert ev.status_code == 200, ev.text
    j = ev.json()
    assert set(j["retrieval"]["modes"]) == {"dense", "bm25", "hybrid"} and j["caveats"]


def test_validation_and_rate_limit(ingested):
    with TestClient(create_app(ingested)) as c:
        assert c.post("/chat", json={"session_id": "x", "message": "hi"}).status_code == 422
        assert c.post("/chat", json={"session_id": SID, "message": ""}).status_code == 422
    s = make_settings(ingested.data_dir, rate_limit_per_minute=2)
    with TestClient(create_app(s)) as c:
        codes = [c.post("/chat", json={"session_id": SID, "message": "refund"}).status_code for _ in range(4)]
    assert 429 in codes


def test_503_when_index_missing(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as c:
        assert c.get("/health").json()["status"] == "degraded"
        assert c.post("/chat", json={"session_id": SID, "message": "hi"}).status_code == 503


def test_at_home_care_question_is_not_mistaken_for_a_city_question(client):
    r = chat(client, "Do you provide dementia care at home?")
    assert r["outcome"].startswith("answered") and any("/dementia" in c["url"] for c in r["citations"])
    # a genuine city question is still withheld
    assert chat(client, "Do you provide care in Pune?")["abstain_reason"] == "unpublished"
