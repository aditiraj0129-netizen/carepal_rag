"""Types shared by the retrievers and the fusion step."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    rank: int  # 1-based
    score: float  # native score of the retriever that produced it
    retriever: str


@dataclass
class RankedList:
    """One retriever's own ranking. `name` identifies the list (e.g. dense_en, dense_orig, bm25)."""
    name: str
    hits: list[Hit] = field(default_factory=list)
    latency_ms: float = 0.0


@dataclass
class FusedHit:
    chunk_id: str
    rrf_score: float
    fused_rank: int
    contributions: dict[str, tuple[int, float]]  # list name -> (rank, native score)


@dataclass
class ChunkRecord:
    chunk_id: str
    url: str
    page_title: str
    section_path: str
    content_type: str
    tier: str
    flags: list[str]
    text: str
    conflict_group: str | None
    provenance: str
    prev_chunk_id: str | None = None
    next_chunk_id: str | None = None
