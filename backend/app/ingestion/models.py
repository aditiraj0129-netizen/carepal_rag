"""Plain data types shared across ingestion."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Block:
    kind: str  # heading | paragraph | list_item
    text: str
    level: int = 0


@dataclass
class Document:
    url: str
    title: str
    blocks: list[Block]
    provenance: str  # "scraped_html" | "research_summary"
    fetch_method: str  # "http" | "rendered" | "snapshot"
    fetched_at: str

    @property
    def text_for_hash(self) -> str:
        return "\n".join(f"{b.kind}:{b.text}" for b in self.blocks)


@dataclass
class Chunk:
    chunk_id: str
    url: str
    page_title: str
    section_path: str
    content_type: str
    tier: str
    flags: list[str]
    text: str
    embed_text: str
    bm25_text: str
    token_count: int
    provenance: str
    content_sha256: str
    conflict_group: str | None = None
    prev_chunk_id: str | None = None
    next_chunk_id: str | None = None


@dataclass
class FetchedPage:
    url: str
    status: int
    html: str
    fetched_at: str
    method: str = "http"
    final_url: str | None = None
    extra: dict[str, str] = field(default_factory=dict)
