"""Evaluation runner: retrieval metrics per retriever mode (dense | bm25 | hybrid) and answer-level metrics.

Gold labels are anchored by page path + required words (not by chunk id), so re-chunking or swapping the
seed snapshots for a real crawl does not invalidate them. Answer correctness here is a LEXICAL PROXY
(required key-point words present in the answer); a human or LLM judge should still review failures.
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from app import db
from app.config import Settings
from app.evaluation import metrics as M
from app.ingestion.scope import normalize_path
from app.pipeline.engine import ChatEngine
from app.pipeline.language import detect_language
from app.pipeline.rewrite import build_plan
from app.retrieval.tokenization import tokenize

KS = (1, 3, 5)
ROUTE_TO_BEHAVIOUR = {
    "emergency": "escalate_emergency", "distress": "escalate_distress", "wants_human": "escalate_human",
    "complaint": "escalate_human", "medical_advice": "decline_medical", "account_request": "redirect_account",
    "injection": "decline_injection",
}


def load_questions(path: Path, split: str = "all") -> list[dict]:
    items = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    return items if split == "all" else [q for q in items if q.get("split") == split]


def relevant_grades(conn, gold: list[dict]) -> dict[str, int]:
    """grade 2 = right page and all required words present; grade 1 = right page only."""
    grades: dict[str, int] = {}
    for g in gold:
        path = normalize_path(g["url"])
        words = [w.lower() for w in g.get("must_contain", [])]
        for r in conn.execute("SELECT chunk_id, url, text, section_path FROM chunks"):
            if normalize_path(urlparse(r["url"]).path or "/") != path:
                continue
            hay = f'{r["section_path"]} {r["text"]}'.lower()
            grade = 2 if all(w in hay for w in words) else 1
            grades[r["chunk_id"]] = max(grades.get(r["chunk_id"], 0), grade)
    return grades


def run_retrieval_eval(settings: Settings, engine: ChatEngine, questions: list[dict],
                       modes: tuple[str, ...] = ("dense", "bm25", "hybrid")) -> dict:
    bundle = engine.bundle
    assert bundle is not None
    answerable = [q for q in questions if q["expected_behaviour"] == "answer" and q.get("gold")]
    out: dict = {"n_answerable": len(answerable), "modes": {}, "unmappable": []}
    per_mode: dict[str, list[dict]] = {m: [] for m in modes}
    with db.session(settings.sqlite_path) as conn:
        for q in answerable:
            grades = relevant_grades(conn, q["gold"])
            relevant = {cid for cid, g in grades.items() if g >= 2}
            if not relevant:
                out["unmappable"].append(q["id"])
                continue
            plan = build_plan(q["question"], q.get("language") or detect_language(q["question"]))
            for mode in modes:
                res = bundle.retriever.retrieve(plan, conn, mode)
                ranked = [f.chunk_id for f in res.fused]
                row = {"id": q["id"], "language": q.get("language", "en"), "mrr": M.reciprocal_rank(ranked, relevant),
                       "ndcg@5": M.ndcg_at_k(ranked, grades, 5), "ndcg@10": M.ndcg_at_k(ranked, grades, 10),
                       "top1_url": res.chunks[ranked[0]].url if ranked else None,
                       "retrieval_ms": res.timings_ms.get("retrieval_wall", 0.0)}
                for k in KS:
                    row[f"recall@{k}"] = M.recall_at_k(ranked, relevant, k)
                    row[f"precision@{k}"] = M.precision_at_k(ranked, relevant, k)
                per_mode[mode].append(row)
    keys = [f"recall@{k}" for k in KS] + [f"precision@{k}" for k in KS] + ["mrr", "ndcg@5", "ndcg@10"]

    def agg(rows: list[dict]) -> dict:
        return {"n": len(rows), **{k: round(M.mean([r[k] for r in rows]) or 0.0, 4) for k in keys}}

    for mode, rows in per_mode.items():
        langs = sorted({r["language"] for r in rows})
        out["modes"][mode] = {"overall": agg(rows),
                              "by_language": {lg: agg([r for r in rows if r["language"] == lg]) for lg in langs},
                              "rows": rows}
    return out


def observed_behaviour(route: str, outcome: str) -> str:
    if route in ROUTE_TO_BEHAVIOUR:
        return ROUTE_TO_BEHAVIOUR[route]
    return "answer" if outcome in ("answered", "answered_low_confidence") else "abstain"


def keypoints_covered(answer: str, key_points: list[str]) -> bool:
    ans = set(tokenize(answer, drop_stop=False))
    return all(set(tokenize(kp, drop_stop=False)) <= ans for kp in key_points)


def language_matches(expected: str, answer: str) -> bool:
    has_deva = any("ऀ" <= c <= "ॿ" for c in answer)
    return has_deva if expected == "hi" else (not has_deva)


def run_answer_eval(engine: ChatEngine, questions: list[dict]) -> dict:
    rows: list[dict] = []
    for q in questions:
        sid = f"eval-{uuid.uuid4().hex}"
        answer, citations, route, outcome, reason = "", [], "", "", None
        t0 = time.perf_counter()
        for ev in engine.run(q["question"], sid, persist=False):
            d = ev["data"]
            if ev["event"] == "meta":
                route = d["route"]
            elif ev["event"] == "token":
                answer += d["text"]
            elif ev["event"] == "replace":
                answer = d["text"]
            elif ev["event"] == "citations":
                citations = d["citations"]
            elif ev["event"] == "done":
                outcome, reason = d["outcome"], d.get("gap_reason")
        exp = q["expected_behaviour"]
        got = observed_behaviour(route, outcome)
        row = {"id": q["id"], "language": q.get("language", "en"), "category": q.get("category"), "expected": exp,
               "observed": got, "behaviour_ok": got == exp, "outcome": outcome, "gap_reason": reason,
               "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
        if exp == "answer":
            row["correct"] = got == "answer" and keypoints_covered(answer, q.get("key_points", []))
            gold_paths = {normalize_path(g["url"]) for g in q.get("gold", [])}
            cited_paths = {normalize_path(urlparse(c["url"]).path or "/") for c in citations}
            row["citation_ok"] = bool(citations) and cited_paths <= gold_paths and bool(cited_paths & gold_paths)
            row["gold_cited"] = bool(cited_paths & gold_paths)
        row["language_match"] = language_matches(q.get("language", "en"), answer) if q.get("language") in ("en", "hi") else True
        rows.append(row)

    def rate(sel: list[dict], key: str) -> float | None:
        vals = [r[key] for r in sel if key in r]
        return round(sum(vals) / len(vals), 4) if vals else None

    answerable = [r for r in rows if r["expected"] == "answer"]
    unans = [r for r in rows if r["expected"] == "abstain"]
    abst_pred = [r for r in rows if r["observed"] == "abstain"]
    tp = sum(1 for r in unans if r["observed"] == "abstain")
    summary = {
        "n_items": len(rows),
        "behaviour_accuracy": rate(rows, "behaviour_ok"),
        "answer_correctness_lexical_proxy": rate(answerable, "correct"),
        "answerable_answered_rate": round(sum(1 for r in answerable if r["observed"] == "answer") / len(answerable), 4) if answerable else None,
        "citation_correctness": rate(answerable, "citation_ok"),
        "gold_page_cited_rate": rate(answerable, "gold_cited"),
        "abstention": {
            "recall": round(tp / len(unans), 4) if unans else None,
            "precision": round(tp / len(abst_pred), 4) if abst_pred else None,
            "false_abstain_rate": round(sum(1 for r in answerable if r["observed"] == "abstain") / len(answerable), 4) if answerable else None,
        },
        "safety": {
            "emergency_recall": rate([r for r in rows if r["expected"] == "escalate_emergency"], "behaviour_ok"),
            "medical_decline_rate": rate([r for r in rows if r["expected"] == "decline_medical"], "behaviour_ok"),
        },
        "by_language": {lg: {"n": len([r for r in rows if r["language"] == lg]),
                             "behaviour_accuracy": rate([r for r in rows if r["language"] == lg], "behaviour_ok"),
                             "correctness": rate([r for r in answerable if r["language"] == lg], "correct")}
                        for lg in sorted({r["language"] for r in rows})},
        "language_match_rate": rate(rows, "language_match"),
        "latency_ms_mean": round(sum(r["latency_ms"] for r in rows) / len(rows), 1) if rows else None,
    }
    return {"summary": summary, "rows": rows}


def run_evaluation(settings: Settings, engine: ChatEngine, *, split: str = "all",
                   modes: tuple[str, ...] = ("dense", "bm25", "hybrid")) -> dict:
    if not engine.ready:
        raise RuntimeError("index not ready")
    questions = load_questions(settings.eval_questions_path, split)
    if not questions:
        raise RuntimeError(f"no evaluation questions for split={split!r} in {settings.eval_questions_path}")
    run_id = uuid.uuid4().hex[:12]
    retrieval = run_retrieval_eval(settings, engine, questions, modes)
    answers = run_answer_eval(engine, questions)
    result = {
        "run_id": run_id, "split": split, "n_questions": len(questions),
        "embedding_model": engine.bundle.embedding_model,  # type: ignore[union-attr]
        "embedding_semantic": engine.bundle.embedder.semantic,  # type: ignore[union-attr]
        "embedding_multilingual": engine.bundle.embedder.multilingual,  # type: ignore[union-attr]
        "generator": "llm" if engine.llm else "extractive",
        "retrieval": {"n_answerable": retrieval["n_answerable"], "unmappable": retrieval["unmappable"],
                      "modes": {m: {"overall": v["overall"], "by_language": v["by_language"]}
                                for m, v in retrieval["modes"].items()}},
        "answers": answers["summary"],
        "caveats": [
            "Answer correctness is a lexical key-point proxy, not a human or LLM judge.",
            "Gold labels were written against the seed snapshots (research summaries), not scraped page text.",
        ] + ([] if engine.bundle.embedder.multilingual else  # type: ignore[union-attr]
             ["Embedder is the offline hashing fallback: not semantic and not cross-lingual."]),
    }
    now = datetime.now(UTC).isoformat(timespec="seconds")
    with db.session(settings.sqlite_path) as conn:
        conn.execute("INSERT INTO eval_runs VALUES (?,?,?,?,?)",
                     (run_id, json.dumps({"modes": list(modes), "retrieval_mode": settings.retrieval_mode,
                                          "rrf_k": settings.rrf_k, "gate": [settings.gate_tau_dense, settings.gate_tau_coverage]}),
                      split, now, json.dumps(result)))
        for r in answers["rows"]:
            conn.execute("INSERT INTO eval_results VALUES (?,?,?,?,?)",
                         (run_id, r["id"], json.dumps(r), r["outcome"], r.get("gap_reason") or ""))
    result["details"] = {"answer_rows": answers["rows"],
                         "retrieval_rows": {m: v["rows"] for m, v in retrieval["modes"].items()}}
    return result
