"""Optional LangSmith tracing and local error events.

* Tracing is OFF unless LANGSMITH_TRACING is true AND LANGSMITH_API_KEY is set.
* Every input/output is passed through sanitize_for_trace (PII redaction + truncation) first.
* A tracing failure can never break a request: all LangSmith calls are wrapped.
* Latency and failures are ALSO written to SQLite (messages / pipeline_events) so monitoring works
  without LangSmith.
"""
from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from app import db
from app.config import Settings
from app.observability.redaction import redact_pii, sanitize_for_trace

log = logging.getLogger(__name__)

_state: dict[str, Any] = {"enabled": False, "project": "carepal-assist"}


def configure_tracing(settings: Settings) -> bool:
    """Enable tracing only when explicitly configured. Returns whether it is on."""
    enabled = settings.tracing_enabled
    if enabled:
        # the langsmith SDK reads these from the environment
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key.get_secret_value()  # type: ignore[union-attr]
        os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
        try:
            import langsmith  # noqa: F401
        except ImportError:
            log.warning("LangSmith requested but not installed; tracing disabled")
            enabled = False
    _state.update(enabled=enabled, project=settings.langsmith_project)
    return enabled


def tracing_enabled() -> bool:
    return bool(_state["enabled"])


class Span:
    def __init__(self) -> None:
        self.outputs: dict[str, Any] = {}
        self.metadata: dict[str, Any] = {}
        self.run_id: str | None = None

    def set(self, **outputs: Any) -> None:
        self.outputs.update(outputs)


@contextmanager
def trace_span(name: str, run_type: str = "chain", inputs: dict[str, Any] | None = None,
               metadata: dict[str, Any] | None = None) -> Iterator[Span]:
    span = Span()
    cm = None
    run = None
    if _state["enabled"]:
        try:
            from langsmith import trace

            cm = trace(name=name, run_type=run_type, inputs=sanitize_for_trace(inputs or {}),
                       metadata=sanitize_for_trace(metadata or {}), project_name=_state["project"])
            run = cm.__enter__()
            span.run_id = str(getattr(run, "id", "")) or None
        except Exception:  # tracing must never break the request
            log.warning("LangSmith span start failed for %s; continuing untraced", name, exc_info=True)
            cm = run = None
    try:
        yield span
    except BaseException as exc:
        if cm is not None:
            try:
                cm.__exit__(type(exc), exc, exc.__traceback__)
            except Exception:
                log.debug("LangSmith span close failed", exc_info=True)
        raise
    else:
        if cm is not None:
            try:
                run.add_outputs(sanitize_for_trace(span.outputs))  # type: ignore[union-attr]
                cm.__exit__(None, None, None)
            except Exception:
                log.debug("LangSmith span close failed", exc_info=True)


def record_event(settings: Settings, *, level: str, stage: str, error_type: str, message: str,
                 message_id: str | None = None, degraded: bool = False) -> None:
    """Persist a pipeline error/degradation (redacted). Never raises."""
    try:
        with db.session(settings.sqlite_path) as conn:
            conn.execute(
                "INSERT INTO pipeline_events(id,message_id,level,stage,error_type,message_redacted,degraded,created_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (uuid.uuid4().hex, message_id, level, stage, error_type, redact_pii(message)[:500],
                 int(degraded), datetime.now(UTC).isoformat(timespec="seconds")))
    except Exception:
        log.exception("could not record pipeline event")
