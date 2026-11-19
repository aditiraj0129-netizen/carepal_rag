"""Hybrid orchestration: run the two independent retrievers in parallel, then fuse with our own RRF.

dense (Chroma)  --\
                   >-- fusion.rrf --> per-page cap --> chunk metadata from SQLite
bm25 (own index) -/
"""
from __future__ import annotations

import json
import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from app.config import Settings
from app.retrieval.bm25 import Bm25Retriever
from app.retrieval.dense import DenseRetriever
from app.retrieval.fusion import rrf
from app.retrieval.tokenization import tokenize
from app.retrieval.types import ChunkRecord, FusedHit, RankedList

log = logging.getLogger(__name__)


class RetrievalError(Exception):
    pass


@dataclass
class QueryPlan:
    original: str
    english_query: str
    language: str  # en | hi | hinglish
    source: str = "rules"  # rules | llm
    glossary_hits: list[str] = field(default_factory=list)


@dataclass
class RetrievalResult:
    mode: str
    lists: list[RankedList]
    fused: list[FusedHit]
    chunks: dict[str, ChunkRecord]
    timings_ms: dict[str, float]
    degraded: list[str] = field(default_factory=list)

    def ordered(self) -> list[tuple[FusedHit, ChunkRecord]]:
        return [(f, self.chunks[f.chunk_id]) for f in self.fused if f.chunk_id in self.chunks]

    def list_by_name(self, name: str) -> RankedList | None:
        return next((lst for lst in self.lists if lst.name == name), None)


def load_chunks(conn: sqlite3.Connection, ids: list[str]) -> dict[str, ChunkRecord]:
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = conn.execute(f"SELECT * FROM chunks WHERE chunk_id IN ({marks})", ids).fetchall()
    return {r["chunk_id"]: ChunkRecord(
        chunk_id=r["chunk_id"], url=r["url"], page_title=r["page_title"], section_path=r["section_path"],
        content_type=r["content_type"], tier=r["tier"], flags=json.loads(r["flags_json"] or "[]"),
        text=r["text"], conflict_group=r["conflict_group"], provenance=r["provenance"],
        prev_chunk_id=r["prev_chunk_id"], next_chunk_id=r["next_chunk_id"]) for r in rows}


class HybridRetriever:
    def __init__(self, dense: DenseRetriever, bm25: Bm25Retriever, settings: Settings):
        self.dense = dense
        self.bm25 = bm25
        self.settings = settings

    def bm25_terms(self, plan: QueryPlan) -> list[str]:
        """English rewrite terms, plus Roman-script original tokens already present in the corpus
        vocabulary (loan words such as 'dementia', 'nurse', 'refund' that Hinglish speakers keep)."""
        terms = tokenize(plan.english_query)
        for t in tokenize(plan.original):
            if t in self.bm25.index.df and t not in terms:
                terms.append(t)
        return terms

    def retrieve(self, plan: QueryPlan, conn: sqlite3.Connection, mode: str | None = None) -> RetrievalResult:
        mode = mode or self.settings.retrieval_mode
        s = self.settings
        jobs: dict[str, tuple] = {}
        if mode in ("dense", "hybrid"):
            jobs["dense_en"] = (self.dense.search, (plan.english_query, s.dense_top_n, "dense_en"))
            if plan.language != "en" and plan.original.strip() != plan.english_query.strip():
                jobs["dense_orig"] = (self.dense.search, (plan.original, s.dense_top_n, "dense_orig"))
        if mode in ("bm25", "hybrid"):
            jobs["bm25"] = (self.bm25.search, (self.bm25_terms(plan), s.bm25_top_n))

        lists: list[RankedList] = []
        degraded: list[str] = []
        with ThreadPoolExecutor(max_workers=max(1, len(jobs))) as pool:
            futures = {name: pool.submit(fn, *args) for name, (fn, args) in jobs.items()}
            for name, fut in futures.items():
                try:
                    lists.append(fut.result())
                except Exception as exc:  # isolate a failing retriever; use the others
                    log.exception("retriever %s failed", name)
                    degraded.append(f"{name}:{exc.__class__.__name__}")
        if not lists:
            raise RetrievalError(f"all retrievers failed: {degraded}")

        fused = rrf(lists, k=s.rrf_k, weights=s.rrf_weights)
        capped: list[FusedHit] = []
        per_page: dict[str, int] = {}
        records = load_chunks(conn, [f.chunk_id for f in fused])
        for f in fused:
            rec = records.get(f.chunk_id)
            if rec is None:  # index references a chunk that no longer exists in SQLite
                degraded.append(f"stale_chunk:{f.chunk_id}")
                continue
            if per_page.get(rec.url, 0) >= s.per_page_cap:
                continue
            per_page[rec.url] = per_page.get(rec.url, 0) + 1
            capped.append(FusedHit(f.chunk_id, f.rrf_score, len(capped) + 1, f.contributions))
            if len(capped) >= s.fused_limit:
                break
        timings = {lst.name: lst.latency_ms for lst in lists}
        timings["retrieval_wall"] = max(timings.values()) if timings else 0.0
        return RetrievalResult(mode, lists, capped, records, timings, degraded)
