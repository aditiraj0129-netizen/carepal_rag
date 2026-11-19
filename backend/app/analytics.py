"""Operations analytics computed from the prototype's own SQLite logs (demo/test traffic only; these are
not TheCarePal business statistics)."""
from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime, timedelta, timezone

from app import db
from app.config import Settings
from app.retrieval.tokenization import tokenize

IST = timezone(timedelta(hours=5, minutes=30))


def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    idx = min(len(s) - 1, max(0, round((p / 100) * (len(s) - 1))))
    return round(float(s[idx]), 1)


def _mask(phone: str) -> str:
    return "*" * max(len(phone) - 4, 0) + phone[-4:]


def overview(settings: Settings) -> dict:
    with db.session(settings.sqlite_path) as conn:
        q = lambda sql, *a: conn.execute(sql, a).fetchall()  # noqa: E731
        assistant = q("SELECT * FROM messages WHERE role='assistant'")
        total = len(assistant)
        outcomes = Counter(r["outcome"] for r in assistant)
        langs = Counter(r["language"] for r in assistant)
        routes = Counter(r["route"] for r in assistant)
        gaps = Counter(r["gap_reason"] for r in assistant if r["gap_reason"])
        ah = 0
        for r in assistant:
            try:
                h = datetime.fromisoformat(r["created_at"]).astimezone(IST).hour
                ah += int(h >= 22 or h < 6)
            except (TypeError, ValueError):
                pass
        lat = lambda col: [r[col] for r in assistant if r[col] is not None and r["outcome"] != "templated"]  # noqa: E731
        answered = outcomes.get("answered", 0) + outcomes.get("answered_low_confidence", 0)
        cited = q("SELECT c.url AS url, COUNT(*) AS n FROM message_citations mc JOIN chunks c ON c.chunk_id=mc.chunk_id "
                  "GROUP BY c.url ORDER BY n DESC")
        cited_urls = {r["url"] for r in cited}
        all_pages = [r["url"] for r in q("SELECT url FROM pages")]
        topics = q("SELECT p.title AS title, COUNT(DISTINCT mc.message_id) AS n FROM message_citations mc "
                   "JOIN chunks c ON c.chunk_id=mc.chunk_id JOIN pages p ON p.url=c.url "
                   "GROUP BY p.title ORDER BY n DESC LIMIT 10")
        retrieved = q("SELECT c.url AS url, MAX(c.page_title) AS title, COUNT(DISTINCT h.message_id) AS n "
                      "FROM retrieval_hits h JOIN chunks c ON c.chunk_id=h.chunk_id "
                      "WHERE h.used_in_context=1 GROUP BY c.url ORDER BY n DESC LIMIT 10")
        handoffs = q("SELECT reason, priority, status FROM handoffs")
        events = q("SELECT stage, error_type, COUNT(*) AS n FROM pipeline_events GROUP BY stage, error_type")
        fb = q("SELECT value, COUNT(*) AS n FROM feedback GROUP BY value")
        state = conn.execute("SELECT * FROM index_state WHERE id=1").fetchone()
        prov = q("SELECT provenance, COUNT(*) AS n FROM chunks GROUP BY provenance")
        return {
            "note": "Computed from this prototype's own logs; not TheCarePal business statistics.",
            "questions_total": total,
            "conversations": conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0],
            "outcomes": dict(outcomes),
            "answered": answered,
            "unanswered": total - answered - outcomes.get("templated", 0),
            "templated": outcomes.get("templated", 0),
            "common_topics": [{"topic": r["title"], "questions": r["n"]} for r in topics],
            "top_retrieved_pages": [{"url": r["url"], "title": r["title"], "questions": r["n"]} for r in retrieved],
            "answered_rate": round(answered / total, 3) if total else None,
            "abstain_rate": round((outcomes.get("abstained", 0) + outcomes.get("fallback", 0)) / total, 3) if total else None,
            "language_split": dict(langs),
            "routes": dict(routes),
            "gap_reasons": dict(gaps),
            "after_hours_share_ist": round(ah / total, 3) if total else None,
            "after_hours_definition": "22:00-06:00 IST",
            "latency_ms": {
                "retrieval_p50": _pct(lat("retrieval_ms"), 50), "retrieval_p95": _pct(lat("retrieval_ms"), 95),
                "generation_p50": _pct(lat("generation_ms"), 50), "generation_p95": _pct(lat("generation_ms"), 95),
                "total_p50": _pct(lat("total_ms"), 50), "total_p95": _pct(lat("total_ms"), 95),
            },
            "top_cited_pages": [{"url": r["url"], "citations": r["n"]} for r in cited[:10]],
            "never_cited_pages": sorted(set(all_pages) - cited_urls),
            "support_requests": {
                "total": len(handoffs),
                "by_reason": dict(Counter(r["reason"] for r in handoffs)),
                "by_priority": dict(Counter(r["priority"] for r in handoffs)),
                "by_status": dict(Counter(r["status"] for r in handoffs)),
            },
            "pipeline_events": [{"stage": r["stage"], "error_type": r["error_type"], "count": r["n"]} for r in events],
            "feedback": {("up" if r["value"] == 1 else "down"): r["n"] for r in fb},
            "index": None if state is None else {
                "embedding_model": state["embedding_model"], "chunks": state["chunk_count"],
                "updated_at": state["updated_at"]},
            "chunk_provenance": {r["provenance"]: r["n"] for r in prov},
        }


def unanswered_clusters(settings: Settings, status: str | None = None, limit: int = 50) -> list[dict]:
    """Group unanswered questions by shared English search terms (Jaccard >= 0.5), most frequent first."""
    with db.session(settings.sqlite_path) as conn:
        sql = "SELECT * FROM unanswered" + (" WHERE status=?" if status else "") + " ORDER BY created_at"
        rows = conn.execute(sql, (status,) if status else ()).fetchall()
    clusters: list[dict] = []
    for r in rows:
        terms = set(tokenize(r["english_query"] or r["question_redacted"] or ""))
        placed = False
        for c in clusters:
            union = c["terms"] | terms
            if union and len(c["terms"] & terms) / len(union) >= 0.5:
                c["rows"].append(r)
                c["terms"] |= terms
                placed = True
                break
        if not placed:
            clusters.append({"terms": set(terms), "rows": [r]})
    out = []
    for i, c in enumerate(clusters, 1):
        rows_ = c["rows"]
        qtext = Counter(r["question_redacted"] for r in rows_)
        out.append({
            "cluster_id": i,
            "label": qtext.most_common(1)[0][0],
            "count": len(rows_),
            "terms": sorted(c["terms"]),
            "languages": dict(Counter(r["language"] for r in rows_)),
            "reasons": dict(Counter(r["reason"] for r in rows_)),
            "statuses": dict(Counter(r["status"] for r in rows_)),
            "examples": list(qtext)[:5],
            "first_seen": min(r["created_at"] for r in rows_),
            "last_seen": max(r["created_at"] for r in rows_),
        })
    out.sort(key=lambda c: (-c["count"], c["last_seen"]), reverse=False)
    return out[:limit]


def support_requests(settings: Settings, *, mask: bool = False, limit: int = 100) -> list[dict]:
    with db.session(settings.sqlite_path) as conn:
        rows = conn.execute("SELECT * FROM handoffs ORDER BY CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 "
                            "ELSE 2 END, created_at DESC LIMIT ?", (limit,)).fetchall()
    return [{
        "request_id": r["id"], "name": r["name"], "phone": _mask(r["phone"]) if mask else r["phone"],
        "language": r["language"], "reason": r["reason"], "priority": r["priority"], "status": r["status"],
        "delivery": r["delivery"], "question_redacted": r["question_redacted"], "created_at": r["created_at"],
        "delete_after": r["delete_after"],
    } for r in rows]


__all__ = ["overview", "unanswered_clusters", "support_requests", "json", "UTC"]
