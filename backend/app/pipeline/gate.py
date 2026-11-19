"""Unknown-answer detection. No single signal decides; thresholds are configurable and calibrated on the
dev split of the evaluation set (see app/evaluation).

Signals: (1) topic the site is known not to publish AND no retrieved chunk states it explicitly,
(2) retrieval strength (max dense cosine, IDF-weighted query-term coverage), (3) retriever agreement.
The generator's own INSUFFICIENT sentinel and the verifier are applied later in the engine.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.config import Settings
from app.pipeline.safety import topic_is_covered
from app.retrieval.bm25 import Bm25Index
from app.retrieval.hybrid import QueryPlan, RetrievalResult
from app.retrieval.tokenization import tokenize


@dataclass
class GateDecision:
    action: str  # answer | answer_low_confidence | abstain
    reason: str | None  # unpublished | no_content | None
    signals: dict[str, float | bool | None] = field(default_factory=dict)


def term_coverage(plan: QueryPlan, result: RetrievalResult, index: Bm25Index, top_chunks: int = 3) -> float:
    terms = list(dict.fromkeys(tokenize(plan.english_query)))
    if not terms:
        return 0.0
    present: set[str] = set()
    for _, rec in result.ordered()[:top_chunks]:
        present.update(tokenize(rec.text + " " + rec.page_title + " " + rec.section_path))
    total = sum(index.idf(t) for t in terms)
    found = sum(index.idf(t) for t in terms if t in present)
    return found / total if total else 0.0


def decide(plan: QueryPlan, result: RetrievalResult, index: Bm25Index, settings: Settings,
           topic: str | None) -> GateDecision:
    ordered = result.ordered()
    dense_lists = [lst for lst in result.lists if lst.name.startswith("dense")]
    max_dense = max((lst.hits[0].score for lst in dense_lists if lst.hits), default=None)
    coverage = term_coverage(plan, result, index) if ordered else 0.0
    bm25 = result.list_by_name("bm25")
    dense_top = dense_lists[0].hits[0].chunk_id if dense_lists and dense_lists[0].hits else None
    bm25_top = bm25.hits[0].chunk_id if bm25 and bm25.hits else None
    agreement = None
    if dense_top and bm25_top and bm25 and dense_lists:
        agreement = dense_top in {h.chunk_id for h in bm25.hits[:5]} or \
            bm25_top in {h.chunk_id for h in dense_lists[0].hits[:5]}
    signals = {"max_dense": max_dense, "term_coverage": coverage, "agreement": agreement,
               "n_candidates": float(len(ordered))}

    if not ordered:
        return GateDecision("abstain", "no_content", signals)
    if topic and not topic_is_covered(topic, [rec.text for _, rec in ordered[:settings.context_max_chunks]]):
        signals["topic"] = True
        return GateDecision("abstain", "unpublished", signals)
    dense_ok = max_dense is not None and max_dense >= settings.gate_tau_dense
    coverage_ok = coverage >= settings.gate_tau_coverage
    if not dense_ok and not coverage_ok:
        return GateDecision("abstain", "no_content", signals)
    weak = (not coverage_ok) or (max_dense is not None and not dense_ok) or agreement is False
    return GateDecision("answer_low_confidence" if weak else "answer", None, signals)
