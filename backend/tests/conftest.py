from __future__ import annotations

import http.server
import threading
from pathlib import Path

import pytest

from app.config import Settings
from app.index import load_index
from app.ingestion.pipeline import run_ingest
from app.pipeline.engine import ChatEngine
from app.retrieval.embeddings import HashingNgramEmbedder

ROOT = Path(__file__).resolve().parents[1]


def make_settings(tmp: Path, **kw) -> Settings:
    base = dict(_env_file=None, data_dir=tmp, seed_dir=ROOT / "seed",
                eval_questions_path=ROOT / "eval" / "questions.jsonl", embed_backend="hashing",
                admin_api_key="test-admin-key", crawl_delay_seconds=0.0, rate_limit_per_minute=1000)
    base.update(kw)
    return Settings(**base)


@pytest.fixture(scope="session")
def ingested(tmp_path_factory):
    """A real index built from the seed snapshots (SQLite + Chroma + BM25 on disk)."""
    s = make_settings(tmp_path_factory.mktemp("index"))
    report = run_ingest(s, source="snapshots")
    assert report.status == "ok"
    return s


@pytest.fixture(scope="session")
def engine(ingested):
    return ChatEngine(ingested, load_index(ingested), None)


@pytest.fixture(scope="session")
def embedder():
    return HashingNgramEmbedder(256)


class LocalSite:
    """A real HTTP server (separate thread) standing in for a website, used to test the real crawler."""

    def __init__(self):
        self.routes: dict[str, tuple[int, str, str]] = {}
        self.hits: list[str] = []
        site = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                site.hits.append(self.path)
                status, ctype, body = site.routes.get(self.path.split("?")[0], (404, "text/plain", "nope"))
                if status in (301, 302):
                    self.send_response(status)
                    self.send_header("Location", body)
                    self.end_headers()
                    return
                data = body.encode()
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def page(self, path: str, html: str) -> None:
        self.routes[path] = (200, "text/html; charset=utf-8", html)

    def sitemap(self, paths: list[str]) -> None:
        locs = "".join(f"<url><loc>{self.base}{p}</loc></url>" for p in paths)
        self.routes["/sitemap.xml"] = (200, "application/xml",
                                       f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{locs}</urlset>')

    def close(self) -> None:
        self.server.shutdown()


@pytest.fixture
def site():
    s = LocalSite()
    yield s
    s.close()


def html_page(title: str, body: str) -> str:
    return f"""<html><head><title>{title} | TheCarePal</title><script>var x=1;</script></head><body>
<nav><a href="/">Home</a><a href="/services">Services</a></nav>
<main>{body}</main>
<div class="testimonial"><p>Best service ever, my mother loved it!</p></div>
<footer><p>Copyright Carepalz</p></footer></body></html>"""
