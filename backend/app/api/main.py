"""FastAPI application factory. Endpoints: /health, /chat, /chat/stream, /feedback, /support/escalate,
/admin/analytics, /admin/unanswered, /admin/ingest, /evaluation/run (+ /admin/support-requests so staff can
actually see stored requests)."""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import queue
import threading
import time
import uuid
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from app import analytics, db
from app.config import Settings, get_settings
from app.escalation import CONFIRMATION, EscalationError, SqliteHandoffSink, create_support_request, purge_expired
from app.index import IndexNotReady, load_index
from app.ingestion.fetch import CrawlBlocked
from app.ingestion.pipeline import IngestError, run_ingest
from app.llm.openai_compat import build_llm
from app.observability.redaction import redact_pii
from app.observability.tracing import configure_tracing, tracing_enabled
from app.pipeline.engine import ChatEngine, session_hash
from app.retrieval.embeddings import build_embedder
from app.schemas import (
    ChatRequest, ChatResponse, EscalateRequest, EscalateResponse, EvalRequest, FeedbackRequest, IngestRequest,
)

log = logging.getLogger("carepal")
VERSION = "0.1.0"


class RateLimiter:
    """Small in-memory sliding-window limiter (single-process prototype)."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.hits: dict[str, deque[float]] = defaultdict(deque)
        self.lock = threading.Lock()

    def check(self, key: str) -> bool:
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_minute:
                return False
            q.append(now)
            return True


def collect(events: Iterator[dict], debug: bool) -> ChatResponse:
    r: dict[str, Any] = {"citations": [], "related_pages": [], "degraded": [], "answer": ""}
    for ev in events:
        n, d = ev["event"], ev["data"]
        if n == "meta":
            r.update(message_id=d["message_id"], language=d["language"], route=d["route"])
        elif n == "token":
            r["answer"] += d["text"]
        elif n == "replace":
            r["answer"] = d["text"]
        elif n == "citations":
            r["citations"] = d["citations"]
        elif n == "abstain":
            r["abstain_reason"] = d["reason"]
        elif n == "emergency":
            r["emergency_numbers"] = d["numbers"]
        elif n == "related":
            r["related_pages"] = d["pages"]
        elif n == "handoff_offer":
            r["handoff_offer"] = d
        elif n == "debug" and debug:
            r["retrieval_debug"] = d
        elif n == "done":
            r.update(outcome=d["outcome"], generator=d["generator"], timings_ms=d["timings_ms"])
    r["answer"] = r["answer"].strip()
    return ChatResponse(**r)


async def aiter_events(gen: Iterator[dict]) -> AsyncIterator[dict]:
    """Run the (blocking) pipeline generator in one worker thread and hand events to the event loop, so
    tracing context stays in a single thread and the loop is never blocked."""
    q: queue.Queue = queue.Queue()
    sentinel = object()

    def worker() -> None:
        try:
            for ev in gen:
                q.put(ev)
        except Exception as exc:  # surfaced to the client as a safe error event
            log.exception("stream failure")
            q.put({"event": "error", "data": {"code": "internal_error", "request_id": None, "type": exc.__class__.__name__}})
        finally:
            q.put(sentinel)

    threading.Thread(target=worker, daemon=True).start()
    while True:
        item = await asyncio.to_thread(q.get)
        if item is sentinel:
            return
        yield item


def sse(ev: dict) -> str:
    return f"event: {ev['event']}\ndata: {json.dumps(ev['data'], ensure_ascii=False)}\n\n"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logging.basicConfig(level=logging.INFO)
        db.init_db(settings.sqlite_path)
        configure_tracing(settings)
        purge_expired(settings)
        app.state.embedder, app.state.index_error = None, None
        bundle = None
        try:
            app.state.embedder = build_embedder(settings)
            bundle = load_index(settings, app.state.embedder)
        except (IndexNotReady, RuntimeError) as exc:
            app.state.index_error = str(exc)
            log.warning("index not ready: %s", exc)
        llm = None
        try:
            llm = build_llm(settings)
        except Exception as exc:
            log.warning("LLM provider unavailable (%s); using extractive mode", exc)
        app.state.engine = ChatEngine(settings, bundle, llm)
        yield

    app = FastAPI(title="CarePal Assist API", version=VERSION, lifespan=lifespan,
                  description="Grounded, multilingual support assistant over TheCarePal's public information.")
    app.state.settings = settings
    app.state.sink = SqliteHandoffSink(settings)
    app.state.limiter = RateLimiter(settings.rate_limit_per_minute)
    app.state.ingest_lock = threading.Lock()
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["GET", "POST"],
                       allow_headers=["Authorization", "Content-Type"])

    @app.middleware("http")
    async def request_id_mw(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def err(request: Request, status: int, code: str, message: str) -> JSONResponse:
        return JSONResponse(status_code=status, content={"error": {
            "code": code, "message": message, "request_id": getattr(request.state, "request_id", None)}})

    @app.exception_handler(HTTPException)
    async def http_exc(request: Request, exc: HTTPException):
        return err(request, exc.status_code, "http_error", str(exc.detail))

    @app.exception_handler(EscalationError)
    async def esc_exc(request: Request, exc: EscalationError):
        return err(request, 422, "invalid_request", str(exc))

    @app.exception_handler(Exception)
    async def any_exc(request: Request, exc: Exception):
        log.exception("unhandled error")
        return err(request, 500, "internal_error", "Something went wrong. Please try again.")

    # ------------------------------------------------------------- dependencies
    def limited(request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        if not request.app.state.limiter.check(ip):
            raise HTTPException(429, "Too many requests; please slow down.")

    def admin(request: Request) -> None:
        key = settings.admin_api_key
        if key is None:
            raise HTTPException(503, "Admin access is not configured (ADMIN_API_KEY is unset).")
        auth = request.headers.get("authorization", "")
        supplied = auth[7:] if auth.lower().startswith("bearer ") else ""
        if not hmac.compare_digest(supplied.encode(), key.get_secret_value().encode()):
            raise HTTPException(401, "Invalid or missing admin credentials.")

    def engine_of(request: Request) -> ChatEngine:
        eng: ChatEngine = request.app.state.engine
        if not eng.ready:
            raise HTTPException(503, request.app.state.index_error or "Index not ready. Run ingestion first.")
        return eng

    # ------------------------------------------------------------------ public
    @app.get("/health")
    def health(request: Request) -> dict:
        eng: ChatEngine = request.app.state.engine
        b = eng.bundle
        return {
            "status": "ok" if eng.ready else "degraded", "version": VERSION, "index_ready": eng.ready,
            "index_error": request.app.state.index_error, "chunks": b.chunk_count if b else 0,
            "embedding_model": b.embedding_model if b else None,
            "embedding_semantic": b.embedder.semantic if b else None,
            "embedding_multilingual": b.embedder.multilingual if b else None,
            "generator": "llm" if eng.llm else "extractive", "retrieval_mode": settings.retrieval_mode,
            "rrf_k": settings.rrf_k, "tracing_enabled": tracing_enabled(),
        }

    @app.post("/chat", response_model=ChatResponse, dependencies=[Depends(limited)])
    def chat(body: ChatRequest, request: Request) -> ChatResponse:
        eng = engine_of(request)
        return collect(eng.run(body.message, body.session_id, debug=body.debug), body.debug)

    @app.post("/chat/stream", dependencies=[Depends(limited)])
    async def chat_stream(body: ChatRequest, request: Request) -> StreamingResponse:
        eng = engine_of(request)

        async def gen() -> AsyncIterator[str]:
            async for ev in aiter_events(eng.run(body.message, body.session_id, debug=body.debug)):
                yield sse(ev)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/feedback")
    def feedback(body: FeedbackRequest) -> dict:
        with db.session(settings.sqlite_path) as conn:
            if conn.execute("SELECT 1 FROM messages WHERE id=? AND role='assistant'", (body.message_id,)).fetchone() is None:
                raise HTTPException(404, "Unknown message_id.")
            conn.execute("INSERT INTO feedback VALUES (?,?,?,?,?)",
                         (uuid.uuid4().hex, body.message_id, body.value, redact_pii(body.comment or "") or None,
                          datetime.now(UTC).isoformat(timespec="seconds")))
        return {"status": "recorded"}

    @app.post("/support/escalate", response_model=EscalateResponse, dependencies=[Depends(limited)])
    def escalate(body: EscalateRequest, request: Request) -> EscalateResponse:
        sr = create_support_request(
            settings, request.app.state.sink, conversation_id=session_hash(body.session_id), name=body.name,
            phone=body.phone, consent=body.consent, reason=body.reason, question=body.question,
            language=body.language, honeypot=body.website)
        return EscalateResponse(
            request_id=sr.request_id, status=sr.status, delivery=sr.delivery, notified_team=sr.notified_team,
            duplicate=sr.duplicate, message=CONFIRMATION[body.language].format(rid=sr.request_id))

    # ------------------------------------------------------------------- admin
    @app.get("/admin/analytics", dependencies=[Depends(admin)])
    def admin_analytics() -> dict:
        return analytics.overview(settings)

    @app.get("/admin/unanswered", dependencies=[Depends(admin)])
    def admin_unanswered(status: str | None = None, limit: int = 50) -> dict:
        return {"clusters": analytics.unanswered_clusters(settings, status, min(max(limit, 1), 200))}

    @app.get("/admin/support-requests", dependencies=[Depends(admin)])
    def admin_support_requests(limit: int = 100) -> dict:
        return {"requests": analytics.support_requests(settings, limit=min(max(limit, 1), 500))}

    @app.post("/admin/ingest", dependencies=[Depends(admin)])
    def admin_ingest(body: IngestRequest, request: Request) -> dict:
        if not request.app.state.ingest_lock.acquire(blocking=False):
            raise HTTPException(409, "An ingestion run is already in progress.")
        try:
            embedder = request.app.state.embedder or build_embedder(settings)
            request.app.state.embedder = embedder
            try:
                report = run_ingest(settings, source=body.source, force=body.force, embedder=embedder)
            except CrawlBlocked as exc:
                raise HTTPException(409, f"Crawl not permitted: {exc}") from exc
            except IngestError as exc:
                raise HTTPException(422, str(exc)) from exc
            bundle = load_index(settings, embedder)
            request.app.state.engine.set_bundle(bundle)
            request.app.state.index_error = None
            return report.to_dict()
        finally:
            request.app.state.ingest_lock.release()

    @app.post("/evaluation/run", dependencies=[Depends(admin)])
    def evaluation_run(body: EvalRequest, request: Request) -> dict:
        from app.evaluation.runner import run_evaluation

        eng = engine_of(request)
        result = run_evaluation(settings, eng, split=body.split, modes=tuple(body.modes))
        if not body.include_details:
            result.pop("details", None)
        return result

    return app


def app_factory() -> FastAPI:  # for `uvicorn app.api.main:app_factory --factory`
    return create_app()
