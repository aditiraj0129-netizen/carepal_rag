"""HTML / snapshot -> structured Document; normalisation and duplicate removal."""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

from bs4 import BeautifulSoup, Tag

from app.ingestion.models import Block, Document

DROP_TAGS = ["script", "style", "noscript", "svg", "nav", "footer", "header", "aside", "form", "iframe",
             "button", "template"]
BOILERPLATE_ATTR = re.compile(
    r"(^|[-_ ])(nav|navbar|menu|footer|cookie|banner|testimonial|review|social|share|breadcrumb|"
    r"sidebar|popup|modal|newsletter)([-_ ]|$)", re.I)
CTA = re.compile(
    r"^(book|get|talk to|sign ?up|log ?in|login as|submit your|schedule|download|read more|learn more|"
    r"contact us|send message|view all|get it on|chat on|call now)\b", re.I)
ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿"), None)


def normalize_text(s: str) -> str:
    s = unicodedata.normalize("NFC", s).translate(ZERO_WIDTH).replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def dedupe_key(s: str) -> str:
    return re.sub(r"[^\wऀ-ॿ]+", " ", normalize_text(s).lower()).strip()


def _is_cta(text: str) -> bool:
    return len(text.split()) <= 6 and bool(CTA.match(text))


def _is_boilerplate(el: Tag) -> bool:
    attrs = " ".join(el.get("class", []) + [el.get("id", "") or ""])
    return bool(attrs and BOILERPLATE_ATTR.search(attrs))


def extract_document(html: str, url: str, fetched_at: str, method: str = "http") -> Document:
    soup = BeautifulSoup(html, "lxml")
    title_el = soup.find("title")
    title = normalize_text(title_el.get_text()) if title_el else ""
    for tag in soup(DROP_TAGS):
        tag.decompose()
    for el in soup.find_all(True):
        if el.parent is not None and _is_boilerplate(el):
            el.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup
    blocks: list[Block] = []
    for el in root.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "summary", "dt", "dd"]):
        if el.name == "p" and el.find_parent("li") is not None:
            continue
        text = normalize_text(el.get_text(" ", strip=True))
        if len(text) < 2 or _is_cta(text):
            continue
        if el.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            blocks.append(Block("heading", text, int(el.name[1])))
        elif el.name == "summary":
            blocks.append(Block("heading", text, 3))
        elif el.name == "li":
            blocks.append(Block("list_item", text))
        else:
            blocks.append(Block("paragraph", text))
    if not title:
        h1 = next((b.text for b in blocks if b.kind == "heading" and b.level == 1), url)
        title = h1
    title = re.sub(r"\s*[|–—-]\s*(The ?CarePal|CarePal).*$", "", title, flags=re.I).strip() or title
    return Document(url=url, title=title, blocks=blocks, provenance="scraped_html", fetch_method=method,
                    fetched_at=fetched_at)


_FM = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.S)


def parse_markdown_snapshot(text: str) -> Document | None:
    """Parse seed/*.md (front matter + markdown) into a Document."""
    m = _FM.match(text)
    if not m:
        return None
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"')
    if "url" not in meta:
        return None
    blocks: list[Block] = []
    para: list[str] = []

    def flush() -> None:
        if para:
            blocks.append(Block("paragraph", normalize_text(" ".join(para))))
            para.clear()

    for raw in m.group(2).splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush()
            continue
        h = re.match(r"^(#{1,6})\s+(.*)$", line)
        if h:
            flush()
            blocks.append(Block("heading", normalize_text(h.group(2)), len(h.group(1))))
        elif re.match(r"^\s*[-*]\s+", line):
            flush()
            blocks.append(Block("list_item", normalize_text(re.sub(r"^\s*[-*]\s+", "", line))))
        else:
            para.append(line.strip())
    flush()
    return Document(
        url=meta["url"], title=meta.get("title", meta["url"]), blocks=blocks,
        provenance=meta.get("provenance", "research_summary"), fetch_method="snapshot",
        fetched_at=meta.get("fetched_at", ""),
    )


def dedupe_documents(docs: list[Document], max_pages: int = 3) -> tuple[list[Document], dict[str, int]]:
    """Drop within-page duplicates and non-heading blocks that recur on more than `max_pages` pages
    (shared navigation/CTA/footer text). Headings are never dropped by the cross-page rule."""
    page_counts: Counter[str] = Counter()
    for d in docs:
        page_counts.update({dedupe_key(b.text) for b in d.blocks if b.kind != "heading"})
    out: list[Document] = []
    stats = {"within_page_duplicates": 0, "cross_page_boilerplate": 0}
    for d in docs:
        seen: set[str] = set()
        kept: list[Block] = []
        for b in d.blocks:
            key = dedupe_key(b.text)
            if b.kind != "heading":
                if key in seen:
                    stats["within_page_duplicates"] += 1
                    continue
                if page_counts[key] > max_pages:
                    stats["cross_page_boilerplate"] += 1
                    continue
                seen.add(key)
            kept.append(b)
        out.append(Document(d.url, d.title, kept, d.provenance, d.fetch_method, d.fetched_at))
    return out, stats
