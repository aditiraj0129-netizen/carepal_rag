"""Command line: ingest, ask, eval.

    python -m app.cli ingest --source crawl        # real crawl of the public site (robots.txt enforced)
    python -m app.cli ingest --source snapshots    # offline seed snapshots (clearly labelled provenance)
    python -m app.cli ask "Can I get a refund?"    # question -> retrieved chunk -> answer -> source URL
    python -m app.cli eval --split dev
"""
from __future__ import annotations

import argparse
import json
import sys

from app import db
from app.config import get_settings
from app.index import IndexNotReady, load_index
from app.ingestion.fetch import CrawlBlocked
from app.ingestion.pipeline import run_ingest
from app.pipeline.engine import ChatEngine
from app.llm.openai_compat import build_llm


def cmd_ingest(args: argparse.Namespace) -> int:
    s = get_settings()
    try:
        rep = run_ingest(s, source=args.source, force=args.force)
    except CrawlBlocked as exc:
        print(f"CRAWL NOT PERFORMED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(rep.to_dict(), indent=2, ensure_ascii=False))
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    s = get_settings()
    try:
        bundle = load_index(s)
    except IndexNotReady as exc:
        print(f"Index not ready: {exc}", file=sys.stderr)
        return 2
    engine = ChatEngine(s, bundle, build_llm(s))
    events = list(engine.run(args.question, "cli-session-000", debug=True, persist=not args.no_persist))
    dbg = next((e["data"] for e in events if e["event"] == "debug"), None)
    print(f"QUESTION: {args.question}")
    if dbg:
        print(f"QUERY PLAN: {dbg['query_plan']}")
        for name, hits in dbg["rankings"].items():
            print(f"  ranking[{name}]:", [(h["rank"], h["url"].rsplit('/', 1)[-1] or '/', h["score"]) for h in hits[:4]])
        top = dbg["fused"][0]
        print(f"  TOP FUSED CHUNK: {top['url']}  [{top['section']}]  rrf={top['rrf_score']}  per_list={top['per_list']}")
    answer = "".join(e["data"]["text"] for e in events if e["event"] == "token").strip()
    print(f"\nANSWER: {answer}")
    cites = next((e["data"]["citations"] for e in events if e["event"] == "citations"), [])
    for c in cites:
        print(f"\nSOURCE {c['alias']}: {c['url']}  (provenance: {c['provenance']})\n  section: {c['section']}\n  chunk:   {c['snippet']}")
    done = next(e["data"] for e in events if e["event"] == "done")
    print(f"\nOUTCOME: {done['outcome']}  route={done['route']}  language={done['language']}  generator={done['generator']}  "
          f"timings={done['timings_ms']}")
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    from app.evaluation.runner import run_evaluation

    s = get_settings()
    bundle = load_index(s)
    engine = ChatEngine(s, bundle, build_llm(s))
    res = run_evaluation(s, engine, split=args.split)
    res.pop("details", None)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="carepal")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ingest")
    a.add_argument("--source", choices=["crawl", "snapshots"], default="crawl")
    a.add_argument("--force", action="store_true")
    a.set_defaults(fn=cmd_ingest)
    b = sub.add_parser("ask")
    b.add_argument("question")
    b.add_argument("--no-persist", action="store_true")
    b.set_defaults(fn=cmd_ask)
    c = sub.add_parser("eval")
    c.add_argument("--split", choices=["all", "dev", "test"], default="dev")
    c.set_defaults(fn=cmd_eval)
    args = p.parse_args(argv)
    db.init_db(get_settings().sqlite_path)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
