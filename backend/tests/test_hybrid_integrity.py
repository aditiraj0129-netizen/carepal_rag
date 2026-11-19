"""Proves hybrid retrieval is two independent retrievers + our own RRF, not one vector-DB call."""
import ast
import re
from pathlib import Path

from app import db
from app.index import load_index
from app.retrieval.hybrid import QueryPlan

RET = Path(__file__).resolve().parents[1] / "app" / "retrieval"


def imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_bm25_module_does_not_touch_the_vector_store():
    assert "chromadb" not in imports(RET / "bm25.py")
    assert "app.retrieval.dense" not in {m for m in re.findall(r"from (app\.retrieval\.\w+)", (RET / "bm25.py").read_text())}


def test_dense_module_does_not_use_bm25():
    assert "rank_bm25" not in imports(RET / "dense.py")
    assert "app.retrieval.bm25" not in set(re.findall(r"from (app\.retrieval\.\w+)", (RET / "dense.py").read_text()))


def test_fusion_is_pure_and_database_free():
    assert not imports(RET / "fusion.py") & {"chromadb", "rank_bm25", "sqlite3"}


def test_no_native_chroma_hybrid_or_text_search_is_used_anywhere_in_retrieval():
    for f in RET.glob("*.py"):
        code = re.sub(r'""".*?"""', "", f.read_text(), flags=re.S)
        code = "\n".join(line.split("#")[0] for line in code.splitlines())
        for forbidden in ("where_document", "sparse_embedding", "SparseVector", "hybrid_search"):
            assert forbidden not in code, f"{f.name} uses {forbidden}"


def test_hybrid_result_has_both_independent_rankings_and_fuses_them(ingested):
    bundle = load_index(ingested)
    with db.session(ingested.sqlite_path) as conn:
        res = bundle.retriever.retrieve(QueryPlan("refund policy", "refund policy", "en"), conn, "hybrid")
    names = {lst.name for lst in res.lists}
    assert {"dense_en", "bm25"} <= names
    dense, bm25 = res.list_by_name("dense_en"), res.list_by_name("bm25")
    assert dense.hits and bm25.hits
    assert [h.score for h in bm25.hits] != [h.score for h in dense.hits]  # native, different scales
    top = res.fused[0]
    assert set(top.contributions) == {"dense_en", "bm25"}  # both retrievers contributed to the winner


def test_fusion_merges_chunks_found_by_only_one_retriever(ingested):
    """Across canned queries, fusion must surface chunks that only ONE retriever ranked (a union, not a copy)."""
    bundle = load_index(ingested)
    queries = ["Telmideed 40 blood pressure", "Razorpay payment", "Lajpat Nagar address", "wandering falls supervision",
               "how can I stop worrying about my father", "refund", "WhatsApp number"]
    only_one = 0
    with db.session(ingested.sqlite_path) as conn:
        for q in queries:
            res = bundle.retriever.retrieve(QueryPlan(q, q, "en"), conn, "hybrid")
            only_one += sum(1 for f in res.fused if len(f.contributions) == 1)
            d = [h.chunk_id for h in res.list_by_name("dense_en").hits]
            b = [h.chunk_id for h in res.list_by_name("bm25").hits]
            assert {f.chunk_id for f in res.fused} <= set(d) | set(b)
    assert only_one > 0


def test_hybrid_differs_from_either_single_retriever(ingested):
    bundle = load_index(ingested)
    diffs = 0
    with db.session(ingested.sqlite_path) as conn:
        for q in ["telmideed", "elderly caregivers vetted experienced", "free consultation baby", "privacy delete data"]:
            plan = QueryPlan(q, q, "en")
            order = {m: [f.chunk_id for f in bundle.retriever.retrieve(plan, conn, m).fused[:5]]
                     for m in ("dense", "bm25", "hybrid")}
            diffs += order["hybrid"] != order["dense"] or order["hybrid"] != order["bm25"]
    assert diffs > 0


def test_one_retriever_failing_degrades_instead_of_breaking(ingested):
    bundle = load_index(ingested)

    def boom(*a, **k):
        raise RuntimeError("vector store down")

    bundle.retriever.dense.search = boom
    with db.session(ingested.sqlite_path) as conn:
        res = bundle.retriever.retrieve(QueryPlan("refund", "refund", "en"), conn, "hybrid")
    assert res.degraded and res.list_by_name("bm25").hits
    assert all(set(f.contributions) == {"bm25"} for f in res.fused)
