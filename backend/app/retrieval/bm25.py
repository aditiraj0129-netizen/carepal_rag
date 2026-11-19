"""BM25 sparse retriever.

Deliberately independent of the vector store: it is built from chunk text in SQLite, has its own
persisted index file, and returns its own ranked list with native BM25 scores. It must never import
chromadb (enforced by tests/test_hybrid_integrity.py).
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from rank_bm25 import BM25Okapi

from app.retrieval.tokenization import tokenize
from app.retrieval.types import Hit, RankedList


class Bm25Index:
    def __init__(self, chunk_ids: list[str], corpus_tokens: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.chunk_ids = chunk_ids
        self.corpus_tokens = corpus_tokens
        self.k1, self.b = k1, b
        self._bm25 = BM25Okapi(corpus_tokens, k1=k1, b=b) if corpus_tokens else None
        self.df: Counter[str] = Counter()
        for toks in corpus_tokens:
            self.df.update(set(toks))

    @classmethod
    def build(cls, rows: Iterable[tuple[str, str]], k1: float = 1.5, b: float = 0.75) -> Bm25Index:
        ids, toks = [], []
        for cid, text in rows:
            ids.append(cid)
            toks.append(tokenize(text))
        return cls(ids, toks, k1, b)

    @property
    def size(self) -> int:
        return len(self.chunk_ids)

    @property
    def content_hash(self) -> str:
        h = hashlib.sha256()
        for cid, toks in zip(self.chunk_ids, self.corpus_tokens, strict=True):
            h.update(cid.encode())
            h.update(" ".join(toks).encode())
        return h.hexdigest()[:16]

    def idf(self, term: str) -> float:
        """Smoothed IDF; out-of-vocabulary terms get the highest weight (df = 0)."""
        return math.log((self.size + 1) / (self.df.get(term, 0) + 1)) + 1.0

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"k1": self.k1, "b": self.b, "chunk_ids": self.chunk_ids,
                                   "tokens": self.corpus_tokens}), encoding="utf-8")
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> Bm25Index:
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(data["chunk_ids"], data["tokens"], data["k1"], data["b"])


class Bm25Retriever:
    name = "bm25"

    def __init__(self, index: Bm25Index):
        self.index = index

    def search(self, query_terms: list[str], top_n: int) -> RankedList:
        t0 = time.perf_counter()
        hits: list[Hit] = []
        if self.index._bm25 is not None and query_terms:
            scores = self.index._bm25.get_scores(query_terms)
            order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))
            for i in order[:top_n]:
                if scores[i] <= 0:
                    break
                hits.append(Hit(self.index.chunk_ids[i], len(hits) + 1, float(scores[i]), self.name))
        return RankedList(self.name, hits, (time.perf_counter() - t0) * 1000)
