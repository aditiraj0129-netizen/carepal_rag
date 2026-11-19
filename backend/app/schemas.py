"""Pydantic request / response models for the public API."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

SessionId = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")


class ChatRequest(BaseModel):
    session_id: str = SessionId
    message: str = Field(min_length=1, max_length=1000)
    debug: bool = False


class CitationModel(BaseModel):
    alias: str
    chunk_id: str
    title: str
    url: str
    section: str
    snippet: str
    provenance: str = Field(description="scraped_html = text crawled from the site; research_summary = paraphrased snapshot")


class ChatResponse(BaseModel):
    message_id: str
    language: Literal["en", "hi", "hinglish"]
    route: str
    outcome: str
    answer: str
    citations: list[CitationModel] = []
    abstain_reason: str | None = None
    emergency_numbers: list[str] | None = None
    handoff_offer: dict[str, Any] | None = None
    related_pages: list[dict[str, Any]] = []
    generator: str
    timings_ms: dict[str, float] = {}
    degraded: list[str] = []
    retrieval_debug: dict[str, Any] | None = None


class FeedbackRequest(BaseModel):
    message_id: str = Field(min_length=8, max_length=64)
    value: Literal[1, -1]
    comment: str | None = Field(default=None, max_length=500)


class EscalateRequest(BaseModel):
    session_id: str = SessionId
    name: str = Field(min_length=2, max_length=80)
    phone: str = Field(min_length=10, max_length=20)
    consent: bool
    reason: Literal["unanswered", "low_confidence", "wants_human", "complaint", "emergency", "distress",
                    "privacy", "other"] = "other"
    question: str | None = Field(default=None, max_length=500)
    language: Literal["en", "hi", "hinglish"] = "en"
    website: str = Field(default="", max_length=200, description="Honeypot: must stay empty")


class EscalateResponse(BaseModel):
    request_id: str
    status: str
    delivery: str
    notified_team: bool
    duplicate: bool
    message: str


class IngestRequest(BaseModel):
    source: Literal["crawl", "snapshots"] = "crawl"
    force: bool = False


class EvalRequest(BaseModel):
    split: Literal["all", "dev", "test"] = "dev"
    modes: list[Literal["dense", "bm25", "hybrid"]] = ["dense", "bm25", "hybrid"]
    include_details: bool = False
