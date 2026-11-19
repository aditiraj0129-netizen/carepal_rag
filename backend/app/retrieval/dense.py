"""Dense retriever: embeds the query and asks ChromaDB for nearest vectors by cosine similarity.

Chroma is used ONLY as an ANN index here. No Chroma hybrid / sparse / where_document features are
used anywhere in retrieval (enforced by tests/test_hybrid_integrity.py). Must not import rank_bm25.
"""
from __future__ import annotations

import time
from pathlib import Path

import chromadb

from app.retrieval.embeddings import Embedder
from app.retrieval.types import Hit, RankedList


def open_collection(chroma_dir: Path, name: str, create: bool = True):
    chroma_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(chroma_dir))
    if create:
        return client.get_or_create_collection(
            name, embedding_function=None, configuration={"hnsw": {"space": "cosine"}})
    return client.get_collection(name, embedding_function=None)


class DenseRetriever:
    def __init__(self, embedder: Embedder, collection):
        self.embedder = embedder
        self.collection = collection

    def search(self, query: str, top_n: int, name: str = "dense") -> RankedList:
        t0 = time.perf_counter()
        count = self.collection.count()
        hits: list[Hit] = []
        if count and query.strip():
            vec = self.embedder.encode_queries([query])[0].tolist()
            res = self.collection.query(query_embeddings=[vec], n_results=min(top_n, count),
                                        include=["distances"])
            for rank, (cid, dist) in enumerate(zip(res["ids"][0], res["distances"][0], strict=True), 1):
                hits.append(Hit(cid, rank, 1.0 - float(dist), name))  # cosine similarity
        return RankedList(name, hits, (time.perf_counter() - t0) * 1000)
