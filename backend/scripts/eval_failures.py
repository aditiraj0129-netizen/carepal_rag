"""Print every evaluation question where the first retrieved page was wrong, or behaviour was wrong,
using the real index. Usage: python scripts/eval_failures.py > eval_failures.txt"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import db  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.index import load_index  # noqa: E402
from app.pipeline.engine import ChatEngine  # noqa: E402
from app.retrieval.embeddings import build_embedder  # noqa: E402

s = get_settings()
engine = ChatEngine(s, load_index(s, build_embedder(s)), None)
for line in open(s.eval_questions_path, encoding="utf-8"):
    q = json.loads(line)
    ev = list(engine.run(q["question"], "eval-failures-01", persist=False, debug=True))
    done = next(e for e in ev if e["event"] == "done")["data"]
    cits = next((e for e in ev if e["event"] == "citations"), {"data": {}})["data"].get("citations", [])
    urls = [c["url"].split(".com")[1] or "/" for c in cits]
    gold = [g["url"].split(".com")[1] for g in q.get("gold", [])]
    print(json.dumps({"id": q["id"], "q": q["question"], "expect": q["expected_behaviour"], "gold": gold,
                      "outcome": done.get("outcome"), "cited": urls}, ensure_ascii=False))
