"""Print the evidence-gate signals for every evaluation question (used to calibrate thresholds).
Usage: python scripts/gate_signals.py > gate_signals.jsonl"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import get_settings  # noqa: E402
from app.index import load_index  # noqa: E402
from app.pipeline.engine import ChatEngine  # noqa: E402
from app.retrieval.embeddings import build_embedder  # noqa: E402

s = get_settings()
engine = ChatEngine(s, load_index(s, build_embedder(s)), None)
for line in open(s.eval_questions_path, encoding="utf-8"):
    q = json.loads(line)
    ev = list(engine.run(q["question"], "gate-signals-01", persist=False, debug=True))
    dbg = next((e["data"] for e in ev if e["event"] == "debug"), None)
    done = next(e["data"] for e in ev if e["event"] == "done")
    gate = (dbg or {}).get("gate") or {}
    print(json.dumps({"id": q["id"], "expect": q["expected_behaviour"], "lang": q.get("language"),
                      "outcome": done.get("outcome"), "gate": gate.get("action"), "reason": gate.get("reason"),
                      "signals": gate.get("signals"), "english_query": (dbg or {}).get("plan", {}).get("english_query")},
                     ensure_ascii=False))
