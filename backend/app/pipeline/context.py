"""Context construction: pick the smallest sufficient evidence and give each source a short alias.

The model only ever sees aliases (S1..Sn); the server maps them back to chunk IDs / URLs, so the model
cannot invent a source. Retrieved text is wrapped as untrusted data.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.config import Settings
from app.retrieval.hybrid import RetrievalResult, load_chunks
from app.retrieval.types import ChunkRecord


@dataclass
class SourceRef:
    alias: str
    chunk: ChunkRecord
    fused_rank: int


@dataclass
class Context:
    sources: list[SourceRef]

    def by_alias(self) -> dict[str, SourceRef]:
        return {s.alias: s for s in self.sources}

    def prompt_block(self) -> str:
        parts = ["<context>"]
        for s in self.sources:
            c = s.chunk
            flags = ",".join(c.flags)
            parts.append(f'<source id="{s.alias}" title="{c.page_title}" section="{c.section_path}" '
                         f'type="{c.content_type}" flags="{flags}">\n{c.text}\n</source>')
        parts.append("</context>")
        return "\n".join(parts)


def build_context(result: RetrievalResult, conn: sqlite3.Connection, settings: Settings,
                  max_words: int = 900) -> Context:
    chosen: list[tuple[int, ChunkRecord]] = []
    words = 0
    for fused, rec in result.ordered():
        if len(chosen) >= settings.context_max_chunks:
            break
        w = len(rec.text.split())
        if chosen and words + w > max_words:
            continue
        chosen.append((fused.fused_rank, rec))
        words += w
    # always include members of a conflict group (e.g. the two published addresses / phone numbers)
    groups = {rec.conflict_group for _, rec in chosen if rec.conflict_group}
    have = {rec.chunk_id for _, rec in chosen}
    for g in groups:
        rows = conn.execute("SELECT chunk_id FROM chunks WHERE conflict_group=? LIMIT 6", (g,)).fetchall()
        missing = [r["chunk_id"] for r in rows if r["chunk_id"] not in have]
        for cid, rec in load_chunks(conn, missing).items():
            chosen.append((len(chosen) + 1, rec))
            have.add(cid)
    return Context([SourceRef(f"S{i}", rec, rank) for i, (rank, rec) in enumerate(chosen, 1)])
