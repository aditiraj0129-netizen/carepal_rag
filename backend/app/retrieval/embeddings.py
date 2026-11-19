"""Embedders. The vector store never computes embeddings itself: we always pass vectors in.

* SentenceTransformerEmbedder: the real multilingual model (e.g. BAAI/bge-m3, multilingual-e5-*).
  Requires `pip install sentence-transformers` and network access to download weights once.
* HashingNgramEmbedder: an OFFLINE lexical fallback (hashed word + character n-grams). It is real
  dense vectors with real cosine search, but it is NOT semantic and NOT cross-lingual. It exists so the
  pipeline can run where model weights cannot be downloaded, and it reports itself as such.
"""
from __future__ import annotations

import hashlib
import re
from typing import Protocol

import numpy as np

from app.config import Settings
from app.retrieval.tokenization import normalize, tokenize


class Embedder(Protocol):
    model_id: str
    dim: int
    semantic: bool
    multilingual: bool

    def encode_passages(self, texts: list[str]) -> np.ndarray: ...
    def encode_queries(self, texts: list[str]) -> np.ndarray: ...


def _l2(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (m / norms).astype(np.float32)


class HashingNgramEmbedder:
    semantic = False
    multilingual = False

    def __init__(self, dim: int = 1024):
        self.dim = dim
        self.model_id = f"hashing-ngram-v1-{dim}"

    @staticmethod
    def _bucket(feature: str, dim: int) -> tuple[int, float]:
        h = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        n = int.from_bytes(h, "big")
        return n % dim, 1.0 if (n >> 63) & 1 else -1.0

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        counts: dict[str, float] = {}
        for tok in tokenize(text, stem=True, drop_stop=True):
            counts[f"w:{tok}"] = counts.get(f"w:{tok}", 0.0) + 1.0
            padded = f"<{tok}>"
            for n in (3, 4, 5):
                for i in range(len(padded) - n + 1):
                    key = f"c:{padded[i:i + n]}"
                    counts[key] = counts.get(key, 0.0) + 0.35
        for feat, c in counts.items():
            idx, sign = self._bucket(feat, self.dim)
            v[idx] += sign * (1.0 + np.log(c)) if c >= 1 else sign * c
        return v

    def encode_passages(self, texts: list[str]) -> np.ndarray:
        return _l2(np.vstack([self._vec(t) for t in texts])) if texts else np.zeros((0, self.dim), np.float32)

    def encode_queries(self, texts: list[str]) -> np.ndarray:
        return self.encode_passages(texts)


class SentenceTransformerEmbedder:
    semantic = True
    multilingual = True

    def __init__(self, model_name: str):
        try:
            from sentence_transformers import SentenceTransformer  # lazy: heavy dependency
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "sentence-transformers is not installed. Run: pip install -e '.[embeddings]' "
                "or set EMBED_BACKEND=hashing for the offline (non-semantic) fallback."
            ) from exc
        # CPU by default: the Apple-GPU (MPS) backend crashes in some torch builds, and CPU is
        # plenty fast for ~100 chunks. Override with EMBED_DEVICE=mps / cuda if you want.
        import os
        self._model = SentenceTransformer(model_name, device=os.environ.get("EMBED_DEVICE", "cpu"))
        self.model_id = model_name
        get_dim = getattr(self._model, "get_embedding_dimension", None) or self._model.get_sentence_embedding_dimension
        self.dim = int(get_dim())
        lower = model_name.lower()
        self._q_prefix = "query: " if "e5" in lower else ""
        self._p_prefix = "passage: " if "e5" in lower else ""

    def encode_passages(self, texts: list[str]) -> np.ndarray:  # pragma: no cover - needs model
        return _l2(np.asarray(self._model.encode([self._p_prefix + t for t in texts], batch_size=16,
                                                 show_progress_bar=False)))

    def encode_queries(self, texts: list[str]) -> np.ndarray:  # pragma: no cover - needs model
        return _l2(np.asarray(self._model.encode([self._q_prefix + t for t in texts],
                                                 show_progress_bar=False)))


def slug(model_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", model_id).strip("-").lower()[:40]


def build_embedder(settings: Settings) -> Embedder:
    if settings.embed_backend == "hashing":
        return HashingNgramEmbedder(settings.hashing_dim)
    return SentenceTransformerEmbedder(settings.embed_model)


__all__ = ["Embedder", "HashingNgramEmbedder", "SentenceTransformerEmbedder", "build_embedder", "slug",
           "normalize"]
