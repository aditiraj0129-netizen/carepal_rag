import math

import pytest

from app.evaluation import metrics as M
from app.retrieval.fusion import rrf
from app.retrieval.types import Hit, RankedList


def rl(name, ids, scores=None):
    scores = scores or [1.0] * len(ids)
    return RankedList(name, [Hit(c, i + 1, s, name) for i, (c, s) in enumerate(zip(ids, scores))])


def test_rrf_matches_hand_computed_scores():
    dense, bm25 = rl("dense", ["a", "b", "c"]), rl("bm25", ["b", "a", "d"])
    fused = {f.chunk_id: f for f in rrf([dense, bm25], k=60)}
    assert fused["a"].rrf_score == pytest.approx(1 / 61 + 1 / 62)
    assert fused["b"].rrf_score == pytest.approx(1 / 62 + 1 / 61)
    assert fused["c"].rrf_score == pytest.approx(1 / 63)
    assert fused["d"].rrf_score == pytest.approx(1 / 63)


def test_rrf_dedupes_by_chunk_id_and_keeps_per_list_provenance():
    fused = rrf([rl("dense", ["a", "b"], [0.9, 0.5]), rl("bm25", ["a", "c"], [7.0, 3.0])])
    assert [f.chunk_id for f in fused].count("a") == 1
    top = fused[0]
    assert top.chunk_id == "a" and top.fused_rank == 1
    assert top.contributions == {"dense": (1, 0.9), "bm25": (1, 7.0)}


def test_rrf_k_is_configurable_and_changes_scores():
    a = rrf([rl("x", ["a"])], k=10)[0].rrf_score
    b = rrf([rl("x", ["a"])], k=100)[0].rrf_score
    assert a == pytest.approx(1 / 11) and b == pytest.approx(1 / 101)


def test_rrf_weights_can_flip_the_order():
    lists = [rl("dense", ["a", "b"]), rl("bm25", ["b", "a"])]
    assert rrf(lists, weights={"dense": 3.0})[0].chunk_id == "a"
    assert rrf(lists, weights={"bm25": 3.0})[0].chunk_id == "b"


def test_rrf_counts_a_chunk_once_per_list_and_is_deterministic():
    dup = RankedList("dense", [Hit("a", 1, 1, "dense"), Hit("a", 2, 1, "dense"), Hit("b", 3, 1, "dense")])
    assert rrf([dup])[0].rrf_score == pytest.approx(1 / 61)
    tie = [f.chunk_id for f in rrf([rl("x", ["z"]), rl("y", ["m"])])]
    assert tie == sorted(tie)  # equal score + equal best rank -> chunk_id order


def test_rrf_rejects_bad_k_and_handles_empty():
    with pytest.raises(ValueError):
        rrf([], k=0)
    assert rrf([]) == []


def test_recall_precision_mrr_hand_computed():
    ranked, rel = ["x", "a", "y", "b"], {"a", "b"}
    assert M.recall_at_k(ranked, rel, 1) == 0.0
    assert M.recall_at_k(ranked, rel, 3) == 0.5
    assert M.recall_at_k(ranked, rel, 5) == 1.0
    assert M.precision_at_k(ranked, rel, 3) == pytest.approx(1 / 3)
    assert M.reciprocal_rank(ranked, rel) == 0.5
    assert M.reciprocal_rank(["q"], rel) == 0.0


def test_ndcg_graded_hand_computed():
    grades = {"a": 2, "b": 1}
    got = M.ndcg_at_k(["b", "a"], grades, 2)
    dcg = (2 ** 1 - 1) / math.log2(2) + (2 ** 2 - 1) / math.log2(3)
    idcg = (2 ** 2 - 1) / math.log2(2) + (2 ** 1 - 1) / math.log2(3)
    assert got == pytest.approx(dcg / idcg)
    assert M.ndcg_at_k(["a", "b"], grades, 2) == pytest.approx(1.0)
    assert M.ndcg_at_k(["z"], grades, 3) == 0.0


def test_metric_edge_cases():
    with pytest.raises(ValueError):
        M.recall_at_k(["a"], set(), 1)
    with pytest.raises(ValueError):
        M.precision_at_k(["a"], {"a"}, 0)
