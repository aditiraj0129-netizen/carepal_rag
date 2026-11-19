"""End-to-end ingestion: fetch -> clean -> dedupe -> chunk -> embed (only new chunks) -> index.

Incremental indexing works at chunk level: a chunk's ID is a content hash, so unchanged text is
neither re-embedded nor re-written; chunks that disappeared are removed from SQLite, Chroma and the
embedding cache; the BM25 index (cheap) is rebuilt from SQLite every run.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Literal

import numpy as np

from app import db
from app.config import Settings
from app.ingestion import scope
from app.ingestion.chunk import chunk_document
from app.ingestion.clean import dedupe_documents, extract_document
from app.ingestion.fetch import (
    CrawlBlocked, FetchError, HttpFetcher, SnapshotSource, looks_js_rendered, render_with_playwright, utc_now,
)
from app.ingestion.models import Chunk, Document
from app.retrieval.bm25 import Bm25Index
from app.retrieval.dense import open_collection
from app.retrieval.embeddings import Embedder, build_embedder, slug

log = logging.getLogger(__name__)


class IngestError(Exception):
    pass


@dataclass
class IngestReport:
    source: str
    started_at: str
    finished_at: str = ""
    status: str = "running"
    robots: str = ""
    pages_in_scope: int = 0
    pages_fetched: int = 0
    pages_failed: list[str] = field(default_factory=list)
    pages_new: list[str] = field(default_factory=list)
    pages_changed: list[str] = field(default_factory=list)
    pages_unchanged: int = 0
    pages_removed: list[str] = field(default_factory=list)
    pages_without_chunks: list[str] = field(default_factory=list)
    chunks_total: int = 0
    chunks_new: int = 0
    chunks_unchanged: int = 0
    chunks_removed: int = 0
    embeddings_computed: int = 0
    dedupe: dict[str, int] = field(default_factory=dict)
    provenance: dict[str, int] = field(default_factory=dict)
    embedding_model: str = ""
    embedding_semantic: bool = False
    embedding_multilingual: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def page_sha(doc: Document) -> str:
    return hashlib.sha256(doc.text_for_hash.encode("utf-8")).hexdigest()


def collect_documents(settings: Settings, source: Literal["crawl", "snapshots"], only_urls: list[str] | None,
                      report: IngestReport, fetcher: HttpFetcher | None = None) -> list[Document]:
    if source == "snapshots":
        docs = [d for d in SnapshotSource(settings.seed_dir).documents() if scope.classify(d.url)]
        report.robots = "not applicable (local snapshots; no network access)"
        report.pages_in_scope = len(docs)
        report.pages_fetched = len(docs)
        return docs

    own = fetcher is None
    fetcher = fetcher or HttpFetcher(settings)
    try:
        robots = fetcher.prepare()  # raises CrawlBlocked when crawling is not allowed
        report.robots = robots.reason
        urls = only_urls or fetcher.discover_urls()
        urls = [u for u in urls if scope.classify(u)]
        report.pages_in_scope = len(urls)
        docs: list[Document] = []
        for url in urls:
            try:
                page = fetcher.fetch(url)
                doc = extract_document(page.html, url, page.fetched_at, "http")
                words = sum(len(b.text.split()) for b in doc.blocks)
                if settings.crawl_render_js and looks_js_rendered(page.html, words):
                    html = render_with_playwright(url, settings.crawl_user_agent)
                    doc = extract_document(html, url, utc_now(), "rendered")
                docs.append(doc)
                report.pages_fetched += 1
            except CrawlBlocked:
                raise
            except FetchError as exc:
                log.warning("fetch failed: %s", exc)
                report.pages_failed.append(str(exc))
        return docs
    finally:
        if own:
            fetcher.close()


def run_ingest(settings: Settings, *, source: Literal["crawl", "snapshots"] = "crawl", force: bool = False,
               embedder: Embedder | None = None, only_urls: list[str] | None = None,
               fetcher: HttpFetcher | None = None) -> IngestReport:
    report = IngestReport(source=source, started_at=utc_now())
    db.init_db(settings.sqlite_path)
    embedder = embedder or build_embedder(settings)
    report.embedding_model, report.embedding_semantic = embedder.model_id, embedder.semantic
    report.embedding_multilingual = embedder.multilingual
    try:
        docs = collect_documents(settings, source, only_urls, report, fetcher)
        if not docs:
            raise IngestError("no pages were collected; nothing to index")
        docs, report.dedupe = dedupe_documents(docs)
        report.provenance = {}
        for d in docs:
            report.provenance[d.provenance] = report.provenance.get(d.provenance, 0) + 1

        new_chunks: dict[str, Chunk] = {}
        per_url: dict[str, list[Chunk]] = {}
        for d in docs:
            cs = chunk_document(d)
            per_url[d.url] = cs
            if not cs:
                report.pages_without_chunks.append(d.url)
            for c in cs:
                new_chunks[c.chunk_id] = c
        report.chunks_total = len(new_chunks)

        collection_name = f"chunks-{slug(embedder.model_id)}-{embedder.dim}"
        collection = open_collection(settings.chroma_dir, collection_name)

        with db.session(settings.sqlite_path) as conn:
            existing_pages = {r["url"]: r["sha256"] for r in conn.execute("SELECT url, sha256 FROM pages")}
            scope_urls = {d.url for d in docs}
            full_run = only_urls is None
            old_rows = conn.execute("SELECT chunk_id, url FROM chunks").fetchall()
            old_ids = {r["chunk_id"] for r in old_rows if full_run or r["url"] in scope_urls}

            for d in docs:
                sha = page_sha(d)
                if d.url not in existing_pages:
                    report.pages_new.append(d.url)
                elif existing_pages[d.url] != sha or force:
                    report.pages_changed.append(d.url)
                else:
                    report.pages_unchanged += 1
                cls = scope.classify(d.url) or ("other", "core")
                conn.execute(
                    "INSERT OR REPLACE INTO pages(url,title,tier,content_type,sha256,fetched_at,status,provenance,"
                    "fetch_method,chunk_count) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (d.url, d.title, cls[1], cls[0], sha, d.fetched_at, "active", d.provenance, d.fetch_method,
                     len(per_url[d.url])))
            if full_run:
                for url in set(existing_pages) - scope_urls:
                    report.pages_removed.append(url)
                    conn.execute("DELETE FROM pages WHERE url=?", (url,))

            removed = old_ids - set(new_chunks)
            to_add = {cid: c for cid, c in new_chunks.items() if cid not in old_ids or force}
            report.chunks_removed = len(removed)
            report.chunks_new = len(to_add)
            report.chunks_unchanged = len(new_chunks) - len(to_add)

            if removed:
                rm = list(removed)
                for i in range(0, len(rm), 500):
                    batch = rm[i:i + 500]
                    marks = ",".join("?" * len(batch))
                    conn.execute(f"DELETE FROM chunks WHERE chunk_id IN ({marks})", batch)
                    conn.execute(f"DELETE FROM embedding_cache WHERE chunk_id IN ({marks})", batch)
                    collection.delete(ids=batch)

            # embeddings: reuse cache, compute only what is missing
            ids = list(to_add)
            vectors: dict[str, np.ndarray] = {}
            if ids:
                marks = ",".join("?" * len(ids))
                for r in conn.execute(
                        f"SELECT chunk_id, vector FROM embedding_cache WHERE model_id=? AND chunk_id IN ({marks})",
                        [embedder.model_id, *ids]):
                    vectors[r["chunk_id"]] = np.frombuffer(r["vector"], dtype=np.float32)
                missing = [cid for cid in ids if cid not in vectors]
                if missing:
                    mat = embedder.encode_passages([to_add[cid].embed_text for cid in missing])
                    report.embeddings_computed = len(missing)
                    for cid, vec in zip(missing, mat, strict=True):
                        vectors[cid] = vec.astype(np.float32)
                        conn.execute("INSERT OR REPLACE INTO embedding_cache(chunk_id,model_id,dim,vector) "
                                     "VALUES (?,?,?,?)", (cid, embedder.model_id, embedder.dim, vec.tobytes()))
                now = utc_now()
                for cid in ids:
                    c = to_add[cid]
                    conn.execute(
                        "INSERT OR REPLACE INTO chunks(chunk_id,url,page_title,section_path,content_type,tier,"
                        "flags_json,text,embed_text,bm25_text,token_count,prev_chunk_id,next_chunk_id,"
                        "conflict_group,provenance,content_sha256,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (c.chunk_id, c.url, c.page_title, c.section_path, c.content_type, c.tier,
                         json.dumps(c.flags), c.text, c.embed_text, c.bm25_text, c.token_count, c.prev_chunk_id,
                         c.next_chunk_id, c.conflict_group, c.provenance, c.content_sha256, now))
                for i in range(0, len(ids), 200):
                    batch = ids[i:i + 200]
                    meta = []
                    for cid in batch:
                        c = to_add[cid]
                        m = {"url": c.url, "page_title": c.page_title, "section_path": c.section_path,
                             "content_type": c.content_type, "tier": c.tier, "provenance": c.provenance}
                        if c.conflict_group:
                            m["conflict_group"] = c.conflict_group
                        meta.append(m)
                    collection.upsert(ids=batch, embeddings=[vectors[c].tolist() for c in batch], metadatas=meta)

            # neighbour links may change even when text did not
            for cs in per_url.values():
                for c in cs:
                    conn.execute("UPDATE chunks SET prev_chunk_id=?, next_chunk_id=? WHERE chunk_id=?",
                                 (c.prev_chunk_id, c.next_chunk_id, c.chunk_id))
                    conn.execute("UPDATE chunks SET page_title=?, provenance=? WHERE chunk_id=?",
                                 (c.page_title, c.provenance, c.chunk_id))

            # BM25: rebuilt from SQLite (single source of truth) after all writes
            rows = conn.execute("SELECT chunk_id, bm25_text FROM chunks ORDER BY chunk_id").fetchall()
            bm25 = Bm25Index.build((r["chunk_id"], r["bm25_text"]) for r in rows)
            bm25.save(settings.bm25_path)

            # sanity checks before declaring the index usable
            sql_count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            if collection.count() != sql_count or bm25.size != sql_count:
                raise IngestError(
                    f"index inconsistency: sqlite={sql_count} chroma={collection.count()} bm25={bm25.size}")
            conn.execute(
                "INSERT OR REPLACE INTO index_state(id,embedding_model,embedding_dim,chroma_collection,bm25_file,"
                "chunk_count,bm25_hash,updated_at) VALUES (1,?,?,?,?,?,?,?)",
                (embedder.model_id, embedder.dim, collection_name, str(settings.bm25_path), sql_count,
                 bm25.content_hash, utc_now()))
            report.status = "ok"
            report.finished_at = utc_now()
            conn.execute("INSERT INTO ingest_runs(started_at,finished_at,source,status,report_json) VALUES (?,?,?,?,?)",
                         (report.started_at, report.finished_at, source, "ok", json.dumps(report.to_dict())))
        return report
    except CrawlBlocked as exc:
        report.status, report.finished_at = "blocked", utc_now()
        _log_failed_run(settings, report, str(exc))
        raise
    except Exception as exc:
        report.status, report.finished_at = "failed", utc_now()
        _log_failed_run(settings, report, str(exc))
        raise


def _log_failed_run(settings: Settings, report: IngestReport, error: str) -> None:
    try:
        with db.session(settings.sqlite_path) as conn:
            d = report.to_dict()
            d["error"] = error
            conn.execute("INSERT INTO ingest_runs(started_at,finished_at,source,status,report_json) VALUES (?,?,?,?,?)",
                         (report.started_at, report.finished_at, report.source, report.status, json.dumps(d)))
    except Exception:  # never mask the original error
        log.exception("could not record failed ingest run")
