"""Retrieval metrics. `ranked` is a list of chunk ids (best first); `relevant` is the set of ids that count as
relevant; nDCG additionally takes graded relevance (id -> grade, 0 = irrelevant)."""
from __future__ import annotations

import math
from collections.abc import Iterable, Sequence


def recall_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    if not relevant:
        raise ValueError("recall is undefined without relevant items")
    return len(set(ranked[:k]) & relevant) / len(relevant)


def precision_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    if k <= 0:
        raise ValueError("k must be positive")
    return len(set(ranked[:k]) & relevant) / k


def reciprocal_rank(ranked: Sequence[str], relevant: set[str]) -> float:
    for i, cid in enumerate(ranked, 1):
        if cid in relevant:
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked: Sequence[str], grades: dict[str, int], k: int) -> float:
    def dcg(gs: Iterable[int]) -> float:
        return sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(gs))

    actual = dcg(grades.get(cid, 0) for cid in ranked[:k])
    ideal = dcg(sorted((g for g in grades.values() if g > 0), reverse=True)[:k])
    return actual / ideal if ideal > 0 else 0.0


def mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None
