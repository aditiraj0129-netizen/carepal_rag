"""Structure-aware chunking with stable IDs and source metadata.

* Splits on headings; a FAQ (a heading ending in '?') plus its answer is always one chunk.
* A paragraph and the list items that follow it stay together.
* Policy pages never use overlap and are only split on paragraph boundaries.
* chunk_id = sha1(url | section_path | normalised text)[:16]: unchanged text keeps its ID, which is
  what makes incremental indexing possible.
"""
from __future__ import annotations

import hashlib
import math
import re

from app.ingestion import scope
from app.ingestion.clean import normalize_text
from app.ingestion.models import Block, Chunk, Document

TARGET_WORDS = 170
MAX_WORDS = 300
OVERLAP_WORDS = 30

ADDRESS_RE = re.compile(r"lajpat nagar|hi-?tech city|oval building", re.I)
PHONE_RE = re.compile(r"(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}")


def approx_tokens(text: str) -> int:
    return math.ceil(len(text.split()) * 1.3)


def make_chunk_id(url: str, section_path: str, text: str) -> str:
    raw = f"{url}|{section_path}|{normalize_text(text).lower()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?।])\s+", text)
    return [p for p in parts if p.strip()]


def _units(blocks: list[Block]) -> list[str]:
    """Atomic units: a paragraph plus the list items that directly follow it."""
    units: list[str] = []
    cur: list[str] = []
    for b in blocks:
        if b.kind == "paragraph":
            if cur:
                units.append("\n".join(cur))
            cur = [b.text]
        else:  # list_item
            cur.append(f"- {b.text}")
    if cur:
        units.append("\n".join(cur))
    return units


def _split_long(unit: str, max_words: int) -> list[str]:
    if len(unit.split()) <= max_words:
        return [unit]
    out: list[str] = []
    cur: list[str] = []
    count = 0
    for s in _sentences(unit):
        w = len(s.split())
        if cur and count + w > max_words:
            out.append(" ".join(cur))
            cur, count = [], 0
        cur.append(s)
        count += w
    if cur:
        out.append(" ".join(cur))
    return out


def _pack(units: list[str], target: int, max_words: int, overlap: int) -> list[str]:
    pieces: list[str] = []
    for u in units:
        pieces.extend(_split_long(u, max_words))
    chunks: list[str] = []
    cur: list[str] = []
    count = 0
    for p in pieces:
        w = len(p.split())
        if cur and count + w > target:
            chunks.append("\n".join(cur))
            tail = " ".join(" ".join(cur).split()[-overlap:]) if overlap else ""
            cur, count = ([tail] if tail else []), len(tail.split())
        cur.append(p)
        count += w
    if cur:
        chunks.append("\n".join(cur))
    return chunks


def chunk_document(doc: Document) -> list[Chunk]:
    cls = scope.classify(doc.url)
    content_type, tier = cls if cls else ("other", "core")
    is_policy = content_type == "policy"
    base_flags = scope.page_flags(content_type)

    sections: list[tuple[str, bool, list[Block]]] = []  # (path, is_faq, blocks)
    stack: list[tuple[int, str]] = []
    cur_path, cur_faq, cur_blocks = "Introduction", False, []

    def close() -> None:
        if cur_blocks:
            sections.append((cur_path, cur_faq, list(cur_blocks)))

    for b in doc.blocks:
        if b.kind == "heading":
            close()
            cur_blocks = []
            if b.text.rstrip().endswith("?"):
                parent = " › ".join(t for _, t in stack if t != doc.title)
                cur_path = f"{parent} › {b.text}" if parent else b.text
                cur_faq = True
            else:
                while stack and stack[-1][0] >= b.level:
                    stack.pop()
                stack.append((b.level, b.text))
                cur_path = " › ".join(t for _, t in stack if t != doc.title) or doc.title
                cur_faq = False
        else:
            cur_blocks.append(b)
    close()

    chunks: list[Chunk] = []
    for path, is_faq, blocks in sections:
        if is_faq:
            q = path.split(" › ")[-1]
            ans = "\n".join(_units(blocks))
            texts = [f"Q: {q}\nA: {ans}"]
            ctype = "faq"
        else:
            texts = _pack(_units(blocks), TARGET_WORDS, MAX_WORDS, 0 if is_policy else OVERLAP_WORDS)
            ctype = content_type
        for t in texts:
            t = t.strip()
            if len(t.split()) < 3:
                continue
            header = f"{doc.title} › {path}"
            flags = list(base_flags)
            group = None
            if ADDRESS_RE.search(t):
                group = "address"
            elif PHONE_RE.search(t):
                group = "phone"
            chunks.append(Chunk(
                chunk_id=make_chunk_id(doc.url, path, t), url=doc.url, page_title=doc.title,
                section_path=path, content_type=ctype, tier=tier, flags=flags, text=t,
                embed_text=f"{header}\n{t}", bm25_text=f"{header}\n{t}", token_count=approx_tokens(t),
                provenance=doc.provenance, content_sha256=hashlib.sha256(t.encode()).hexdigest(),
                conflict_group=group,
            ))
    # drop exact-duplicate ids, then link neighbours
    seen: set[str] = set()
    unique = [c for c in chunks if not (c.chunk_id in seen or seen.add(c.chunk_id))]
    for i, c in enumerate(unique):
        c.prev_chunk_id = unique[i - 1].chunk_id if i > 0 else None
        c.next_chunk_id = unique[i + 1].chunk_id if i < len(unique) - 1 else None
    return unique
