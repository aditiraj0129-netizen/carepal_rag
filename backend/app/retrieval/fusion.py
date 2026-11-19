"""Reciprocal Rank Fusion, implemented independently of any retriever or database.

    RRF(d) = sum over lists l containing d of  w_l / (k + rank_l(d))     (rank is 1-based)

It consumes only ranked lists (chunk ids + ranks), so it is rank-based and needs no score
normalisation. Chunk ids are the stable de-duplication key; per-list rank and native score are kept
as provenance for debugging and analytics.
"""
from __future__ import annotations

import logging

from app.retrieval.types import FusedHit, RankedList

log = logging.getLogger(__name__)


def rrf(lists: list[RankedList], k: int = 60, weights: dict[str, float] | None = None) -> list[FusedHit]:
    if k <= 0:
        raise ValueError("RRF k must be positive")
    weights = weights or {}
    scores: dict[str, float] = {}
    contrib: dict[str, dict[str, tuple[int, float]]] = {}
    for lst in lists:
        w = float(weights.get(lst.name, 1.0))
        seen: set[str] = set()
        for hit in lst.hits:
            if hit.chunk_id in seen:  # a chunk counts once per list (its best rank)
                continue
            seen.add(hit.chunk_id)
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + w / (k + hit.rank)
            contrib.setdefault(hit.chunk_id, {})[lst.name] = (hit.rank, hit.score)

    def best_rank(cid: str) -> int:
        return min(r for r, _ in contrib[cid].values())

    ordered = sorted(scores, key=lambda cid: (-scores[cid], best_rank(cid), cid))  # deterministic ties
    fused = [FusedHit(cid, scores[cid], i, contrib[cid]) for i, cid in enumerate(ordered, 1)]
    for lst in lists:
        log.debug("ranking %s: %s", lst.name, [(h.chunk_id, h.rank, round(h.score, 4)) for h in lst.hits[:10]])
    log.debug("fused: %s", [(f.chunk_id, round(f.rrf_score, 5)) for f in fused[:10]])
    return fused
