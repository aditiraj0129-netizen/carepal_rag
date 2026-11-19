"""Loads the built index (Chroma collection + BM25 + embedder) and guards against mismatches."""
from __future__ import annotations

from dataclasses import dataclass

from app import db
from app.config import Settings
from app.retrieval.bm25 import Bm25Index, Bm25Retriever
from app.retrieval.dense import DenseRetriever, open_collection
from app.retrieval.embeddings import Embedder, build_embedder
from app.retrieval.hybrid import HybridRetriever


class IndexNotReady(Exception):
    """The index is missing or was built with a different embedding model."""


@dataclass
class IndexBundle:
    embedder: Embedder
    retriever: HybridRetriever
    bm25_index: Bm25Index
    collection_name: str
    chunk_count: int
    embedding_model: str


def load_index(settings: Settings, embedder: Embedder | None = None) -> IndexBundle:
    db.init_db(settings.sqlite_path)
    with db.session(settings.sqlite_path) as conn:
        row = conn.execute("SELECT * FROM index_state WHERE id=1").fetchone()
    if row is None or not settings.bm25_path.exists():
        raise IndexNotReady("No index found. Run ingestion first: python -m app.cli ingest --source crawl "
                            "(or --source snapshots).")
    embedder = embedder or build_embedder(settings)
    if row["embedding_model"] != embedder.model_id:
        raise IndexNotReady(
            f"Index was built with '{row['embedding_model']}' but the configured embedder is "
            f"'{embedder.model_id}'. Re-run ingestion (querying with a different model silently breaks retrieval).")
    collection = open_collection(settings.chroma_dir, row["chroma_collection"], create=False)
    bm25 = Bm25Index.load(settings.bm25_path)
    if collection.count() != row["chunk_count"] or bm25.size != row["chunk_count"]:
        raise IndexNotReady("Index stores disagree on chunk count; re-run ingestion with --force.")
    retriever = HybridRetriever(DenseRetriever(embedder, collection), Bm25Retriever(bm25), settings)
    return IndexBundle(embedder, retriever, bm25, row["chroma_collection"], row["chunk_count"], row["embedding_model"])
