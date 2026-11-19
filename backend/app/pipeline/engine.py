"""The conversation pipeline. `ChatEngine.run` is a generator of events so the same logic serves both
/chat (collect events) and /chat/stream (forward events as SSE).

Order: input guard -> language -> safety route -> [templated reply]  or
       rewrite -> retrieval (dense || bm25 -> RRF) -> evidence gate -> context -> generation -> verification
       -> persist (messages, per-retriever hits, citations, unanswered) -> done
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from app import db
from app.config import Settings
from app.escalation import PRIORITY
from app.index import IndexBundle
from app.llm.base import LLMClient, LLMError
from app.observability.redaction import redact_pii
from app.observability.tracing import record_event, trace_span, tracing_enabled
from app.pipeline import safety
from app.pipeline.context import Context, build_context
from app.pipeline.gate import GateDecision, decide
from app.pipeline.generate import INSUFFICIENT, ExtractiveGenerator, LLMGenerator
from app.pipeline.language import detect_language
from app.pipeline.rewrite import build_plan, glossary_rewrite
from app.pipeline.verify import verify_answer
from app.retrieval.hybrid import QueryPlan, RetrievalError, RetrievalResult

log = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_input(text: str) -> str:
    return re.sub(r"\s+", " ", CONTROL.sub("", text)).strip()


def session_hash(session_id: str) -> str:
    return hashlib.sha256(f"carepal-assist|{session_id}".encode()).hexdigest()[:20]


def after_hours(now: datetime) -> bool:
    h = now.astimezone(IST).hour
    return h >= 22 or h < 6


@dataclass
class Turn:
    message_id: str
    conversation_id: str
    question: str
    language: str
    route: str = "in_scope"
    outcome: str = ""
    gap_reason: str | None = None
    answer: str = ""
    citations: list[dict] = field(default_factory=list)
    generator: str = "none"
    plan: QueryPlan | None = None
    result: RetrievalResult | None = None
    gate: GateDecision | None = None
    context: Context | None = None
    handoff_offer: dict | None = None
    related: list[dict] = field(default_factory=list)
    retrieval_ms: float = 0.0
    generation_ms: float = 0.0
    degraded: list[str] = field(default_factory=list)


def event(name: str, **data: Any) -> dict:
    return {"event": name, "data": data}


def offer(reason: str, priority: str = "normal") -> dict:
    return {"reason": reason, "priority": priority, "ask": ["name", "phone", "consent"],
            "whatsapp_url": safety.WHATSAPP_URL, "notifies_team_automatically": False}


def citation_dict(alias: str, src) -> dict:
    c = src.chunk
    snippet = c.text if len(c.text) <= 280 else c.text[:277] + "..."
    return {"alias": alias, "chunk_id": c.chunk_id, "title": c.page_title, "url": c.url,
            "section": c.section_path, "snippet": snippet, "provenance": c.provenance}


def debug_payload(result: RetrievalResult, plan: QueryPlan, gate: GateDecision | None) -> dict:
    return {
        "mode": result.mode,
        "query_plan": {"original_redacted": redact_pii(plan.original), "english_query": plan.english_query,
                       "language": plan.language, "source": plan.source, "glossary_hits": plan.glossary_hits},
        "rankings": {lst.name: [{"rank": h.rank, "chunk_id": h.chunk_id, "score": round(h.score, 4),
                                 "url": result.chunks[h.chunk_id].url if h.chunk_id in result.chunks else None,
                                 "section": result.chunks[h.chunk_id].section_path if h.chunk_id in result.chunks else None}
                                for h in lst.hits[:8]] for lst in result.lists},
        "fused": [{"fused_rank": f.fused_rank, "rrf_score": round(f.rrf_score, 5), "chunk_id": f.chunk_id,
                   "url": result.chunks[f.chunk_id].url, "section": result.chunks[f.chunk_id].section_path,
                   "per_list": {k: {"rank": r, "score": round(s, 4)} for k, (r, s) in f.contributions.items()}}
                  for f in result.fused[:8]],
        "gate": None if gate is None else {"action": gate.action, "reason": gate.reason, "signals": gate.signals},
        "timings_ms": {k: round(v, 2) for k, v in result.timings_ms.items()},
        "degraded": result.degraded,
    }


class ChatEngine:
    def __init__(self, settings: Settings, bundle: IndexBundle | None, llm: LLMClient | None = None):
        self.settings = settings
        self.llm = llm
        self.set_bundle(bundle)

    def set_bundle(self, bundle: IndexBundle | None) -> None:
        self.bundle = bundle
        self.extractive = ExtractiveGenerator(bundle.bm25_index) if bundle else None

    @property
    def ready(self) -> bool:
        return self.bundle is not None

    # ------------------------------------------------------------------ public
    def run(self, message: str, session_id: str, *, debug: bool = False, mode: str | None = None,
            persist: bool = True) -> Iterator[dict]:
        t0 = time.perf_counter()
        text = clean_input(message)
        language = detect_language(text)
        turn = Turn(uuid.uuid4().hex, session_hash(session_id), text, language)
        safety_res = safety.classify(text)
        turn.route = safety_res.route
        trace_run_id = None
        with trace_span("chat_turn", "chain", inputs={"question": text},
                        metadata={"language": language, "route": safety_res.route}) as root:
            trace_run_id = root.run_id
            yield event("meta", message_id=turn.message_id, language=language, route=turn.route)
            try:
                if safety_res.route in safety.ROUTES_TEMPLATED:
                    yield from self._templated(turn, safety_res)
                else:
                    yield from self._rag(turn, safety_res, debug, mode)
            except Exception as exc:  # last line of defence: never leak a stack trace to the user
                log.exception("pipeline failure")
                record_event(self.settings, level="error", stage="pipeline", error_type=exc.__class__.__name__,
                             message=str(exc), message_id=turn.message_id)
                turn.outcome, turn.gap_reason = "fallback", "pipeline_error"
                turn.answer = safety.template("abstain", language)
                turn.handoff_offer = offer("unanswered")
                yield event("token", text=turn.answer)
                yield event("handoff_offer", **turn.handoff_offer)
            total_ms = (time.perf_counter() - t0) * 1000
            root.set(outcome=turn.outcome, gap_reason=turn.gap_reason, answer=turn.answer,
                     retrieval_ms=round(turn.retrieval_ms, 1), generation_ms=round(turn.generation_ms, 1),
                     total_ms=round(total_ms, 1), generator=turn.generator)
        if persist:
            self._persist(turn, total_ms, trace_run_id)
        yield event("done", message_id=turn.message_id, outcome=turn.outcome, route=turn.route, language=language,
                    generator=turn.generator, gap_reason=turn.gap_reason, traced=tracing_enabled(),
                    timings_ms={"retrieval_ms": round(turn.retrieval_ms, 1), "generation_ms": round(turn.generation_ms, 1),
                                "total_ms": round(total_ms, 1)})

    # --------------------------------------------------------------- templated
    def _templated(self, turn: Turn, sr: safety.SafetyResult) -> Iterator[dict]:
        key = sr.route
        turn.outcome = "templated"
        turn.answer = safety.template(key, turn.language)
        turn.generator = "template"
        yield event("token", text=turn.answer)
        if key == "emergency":
            yield event("emergency", numbers=safety.EMERGENCY_NUMBERS)
        if key in ("emergency", "distress"):
            turn.handoff_offer = offer(key, PRIORITY[key])
        elif key == "complaint":
            turn.handoff_offer = offer("complaint", "high")
        elif key in ("wants_human", "medical_advice", "account_request"):
            turn.handoff_offer = offer("wants_human" if key == "wants_human" else "other")
        if turn.handoff_offer:
            yield event("handoff_offer", **turn.handoff_offer)

    # -------------------------------------------------------------------- rag
    def _rag(self, turn: Turn, sr: safety.SafetyResult, debug: bool, mode: str | None) -> Iterator[dict]:
        if self.bundle is None or self.extractive is None:
            turn.outcome, turn.gap_reason, turn.generator = "fallback", "index_unavailable", "none"
            turn.answer = safety.template("no_index", turn.language)
            yield event("token", text=turn.answer)
            return
        with db.session(self.settings.sqlite_path) as conn:
            prev = conn.execute("SELECT text_redacted FROM messages WHERE conversation_id=? AND role='user' "
                                "ORDER BY created_at DESC LIMIT 1", (turn.conversation_id,)).fetchone()
            prev_q = None
            if prev and prev["text_redacted"]:
                prev_q = glossary_rewrite(prev["text_redacted"], detect_language(prev["text_redacted"]))[0]
            plan = build_plan(turn.question, turn.language, prev_q, self.llm)
            turn.plan = plan

            t_r = time.perf_counter()
            with trace_span("retrieval", "retriever", inputs={"query": plan.english_query},
                            metadata={"mode": mode or self.settings.retrieval_mode}) as sp:
                try:
                    result = self.bundle.retriever.retrieve(plan, conn, mode)
                except RetrievalError as exc:
                    record_event(self.settings, level="error", stage="retrieval", error_type="RetrievalError",
                                 message=str(exc), message_id=turn.message_id)
                    turn.outcome, turn.gap_reason = "fallback", "retrieval_failed"
                    turn.answer = safety.template("abstain", turn.language)
                    turn.handoff_offer = offer("unanswered")
                    yield event("token", text=turn.answer)
                    yield event("handoff_offer", **turn.handoff_offer)
                    return
                sp.set(rankings={lst.name: [h.chunk_id for h in lst.hits[:5]] for lst in result.lists},
                       fused=[f.chunk_id for f in result.fused[:5]], timings_ms=result.timings_ms,
                       degraded=result.degraded)
            turn.retrieval_ms = (time.perf_counter() - t_r) * 1000
            turn.result = result
            for d in result.degraded:
                record_event(self.settings, level="warning", stage="retrieval", error_type="degraded", message=d,
                             message_id=turn.message_id, degraded=True)
            turn.degraded = result.degraded

            gate = decide(plan, result, self.bundle.bm25_index, self.settings, sr.topic)
            turn.gate = gate
            context = build_context(result, conn, self.settings)
            turn.context = context

        if debug:
            yield event("debug", **debug_payload(result, plan, gate))

        if gate.action == "abstain":
            yield from self._abstain(turn, gate.reason or "no_content", sr.topic)
            return

        t_g = time.perf_counter()
        yield from self._generate(turn, context, gate)
        turn.generation_ms = (time.perf_counter() - t_g) * 1000

        if sr.route == "privacy_request" and not turn.handoff_offer:
            turn.handoff_offer = offer("privacy")
        if turn.handoff_offer:
            yield event("handoff_offer", **turn.handoff_offer)

    def _related(self, turn: Turn, limit: int = 2) -> list[dict]:
        if turn.result is None:
            return []
        seen, out = set(), []
        for _, rec in turn.result.ordered():
            if rec.url not in seen:
                seen.add(rec.url)
                out.append({"title": rec.page_title, "url": rec.url, "provenance": rec.provenance})
            if len(out) >= limit:
                break
        return out

    def _abstain(self, turn: Turn, reason: str, topic: str | None) -> Iterator[dict]:
        turn.outcome, turn.gap_reason, turn.generator = "abstained", reason, "template"
        note = ""
        if reason == "unpublished" and topic in safety.TOPIC_NOTES:
            note = safety.TOPIC_NOTES[topic].get(turn.language) or safety.TOPIC_NOTES[topic]["en"]
            note += " "
        turn.answer = note + safety.template("abstain", turn.language)
        turn.related = self._related(turn)
        turn.handoff_offer = offer("unanswered")
        yield event("token", text=turn.answer)
        yield event("citations", citations=[])
        yield event("abstain", reason=reason)
        if turn.related:
            yield event("related", pages=turn.related, note="closest published pages (not evidence for an answer)")
        yield event("handoff_offer", **turn.handoff_offer)

    def _generate(self, turn: Turn, context: Context, gate: GateDecision) -> Iterator[dict]:
        assert turn.plan is not None
        plan = turn.plan
        low_conf = gate.action == "answer_low_confidence"
        if self.llm is None:
            with trace_span("generate", "llm", inputs={"question": plan.english_query},
                            metadata={"generator": "extractive"}) as sp:
                gen = self.extractive.generate(plan.english_query, turn.language, context)  # type: ignore[union-attr]
                sp.set(insufficient=gen.insufficient, answer=gen.text)
            turn.generator = "extractive"
            if gen.insufficient:
                yield from self._abstain(turn, "model_insufficient", None)
                return
            v = verify_answer(gen.text, context, turn.language)
            if not v.ok:
                record_event(self.settings, level="warning", stage="verify", error_type="verification_failed",
                             message=",".join(v.failures), message_id=turn.message_id)
                yield from self._abstain(turn, "verification_failed", None)
                return
            for sentence in re.split(r"(?<=[.!?।\]])\s+", gen.text):
                yield event("token", text=sentence + " ")
            self._finish_answer(turn, gen.text, v.used_aliases, context, low_conf)
            yield event("citations", citations=turn.citations)
            return

        # ---- LLM path: stream, then verify (a `replace` event swaps in a safe fallback if verification fails)
        turn.generator = "llm"
        generator = LLMGenerator(self.llm)
        buffer, emitted, parts = "", False, []
        try:
            with trace_span("generate", "llm", inputs={"question": plan.english_query},
                            metadata={"generator": "llm"}) as sp:
                for tok in generator.stream(plan.english_query if turn.language == "en" else turn.question,
                                            turn.language, context):
                    parts.append(tok)
                    if not emitted:
                        buffer += tok
                        if len(buffer) < len(INSUFFICIENT) and INSUFFICIENT.startswith(buffer.strip()):
                            continue
                        if buffer.strip().startswith(INSUFFICIENT):
                            break
                        emitted = True
                        yield event("token", text=buffer)
                    else:
                        yield event("token", text=tok)
                sp.set(answer="".join(parts))
        except LLMError as exc:
            record_event(self.settings, level="error", stage="generation", error_type="LLMError", message=str(exc),
                         message_id=turn.message_id, degraded=True)
            if not emitted:  # nothing shown yet: degrade gracefully to extractive mode
                turn.degraded.append("llm_failed")
                saved, self.llm = self.llm, None
                try:
                    yield from self._generate(turn, context, gate)
                finally:
                    self.llm = saved
                return
            fallback = safety.template("abstain", turn.language)
            turn.outcome, turn.gap_reason, turn.answer = "fallback", "llm_failed", fallback
            yield event("replace", text=fallback, reason="llm_failed")
            turn.handoff_offer = offer("unanswered")
            return
        answer = "".join(parts).strip()
        if answer.startswith(INSUFFICIENT) or not answer:
            yield from self._abstain(turn, "model_insufficient", None)
            return
        v = verify_answer(answer, context, turn.language, strict_sentences=True)
        if not v.ok:
            record_event(self.settings, level="warning", stage="verify", error_type="verification_failed",
                         message=",".join(v.failures), message_id=turn.message_id)
            fallback = safety.template("abstain", turn.language)
            turn.outcome, turn.gap_reason, turn.answer = "fallback", "verification_failed", fallback
            turn.related = self._related(turn)
            turn.handoff_offer = offer("unanswered")
            yield event("replace", text=fallback, reason="verification_failed")
            yield event("citations", citations=[])
            return
        self._finish_answer(turn, answer, v.used_aliases, context, low_conf)
        yield event("citations", citations=turn.citations)

    def _finish_answer(self, turn: Turn, answer: str, used: list[str], context: Context, low_conf: bool) -> None:
        by_alias = context.by_alias()
        turn.answer = answer
        turn.citations = [citation_dict(a, by_alias[a]) for a in used if a in by_alias]
        turn.outcome = "answered_low_confidence" if low_conf else "answered"
        if low_conf:
            turn.gap_reason = "low_confidence"
            turn.handoff_offer = offer("low_confidence")

    # ---------------------------------------------------------------- persist
    def _persist(self, turn: Turn, total_ms: float, trace_id: str | None) -> None:
        now = datetime.now(UTC)
        ts = now.isoformat(timespec="seconds")
        try:
            with db.session(self.settings.sqlite_path) as conn:
                conn.execute("INSERT OR IGNORE INTO conversations(id,session_hash,language,started_at,after_hours,turn_count)"
                             " VALUES (?,?,?,?,?,0)", (turn.conversation_id, turn.conversation_id, turn.language, ts,
                                                       int(after_hours(now))))
                conn.execute("UPDATE conversations SET turn_count=turn_count+1 WHERE id=?", (turn.conversation_id,))
                conn.execute("INSERT INTO messages(id,conversation_id,role,text_redacted,route,language,created_at) "
                             "VALUES (?,?,?,?,?,?,?)", (uuid.uuid4().hex, turn.conversation_id, "user",
                                                        redact_pii(turn.question), turn.route, turn.language, ts))
                conn.execute(
                    "INSERT INTO messages(id,conversation_id,role,text_redacted,route,outcome,gap_reason,language,generator,"
                    "retrieval_ms,generation_ms,total_ms,trace_id,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (turn.message_id, turn.conversation_id, "assistant", redact_pii(turn.answer), turn.route,
                     turn.outcome, turn.gap_reason, turn.language, turn.generator, int(turn.retrieval_ms),
                     int(turn.generation_ms), int(total_ms), trace_id, ts))
                if turn.result is not None:
                    used = {s.chunk.chunk_id for s in turn.context.sources} if turn.context else set()
                    fused = {f.chunk_id: f for f in turn.result.fused}
                    for lst in turn.result.lists:
                        for h in lst.hits:
                            f = fused.get(h.chunk_id)
                            conn.execute("INSERT INTO retrieval_hits VALUES (?,?,?,?,?,?,?,?)",
                                         (turn.message_id, h.chunk_id, lst.name, h.rank, h.score,
                                          f.fused_rank if f else None, f.rrf_score if f else None,
                                          int(h.chunk_id in used)))
                for pos, c in enumerate(turn.citations, 1):
                    conn.execute("INSERT INTO message_citations VALUES (?,?,?)", (turn.message_id, c["chunk_id"], pos))
                if turn.gap_reason and turn.outcome in ("abstained", "fallback", "answered_low_confidence"):
                    sig = turn.gate.signals if turn.gate else {}
                    conn.execute(
                        "INSERT INTO unanswered(id,message_id,question_redacted,english_query,language,reason,top_dense,"
                        "term_coverage,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (uuid.uuid4().hex, turn.message_id, redact_pii(turn.question),
                         redact_pii(turn.plan.english_query) if turn.plan else None, turn.language, turn.gap_reason,
                         sig.get("max_dense"), sig.get("term_coverage"), "new", ts))
        except Exception as exc:
            log.exception("persist failed")
            record_event(self.settings, level="error", stage="persist", error_type=exc.__class__.__name__,
                         message=str(exc), message_id=turn.message_id)
