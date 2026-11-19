"""Ingestion tests, including the real crawler running against a real local HTTP server."""
import pytest

from app import db
from app.ingestion import scope
from app.ingestion.chunk import chunk_document, make_chunk_id
from app.ingestion.clean import dedupe_documents, extract_document, parse_markdown_snapshot
from app.ingestion.fetch import CrawlBlocked, FetchError, HttpFetcher, RobotsPolicy
from app.ingestion.models import Block, Document
from app.ingestion.pipeline import run_ingest
from app.retrieval.embeddings import HashingNgramEmbedder
from tests.conftest import html_page, make_settings


# ------------------------------------------------------------------ cleaning
def test_html_extraction_drops_navigation_scripts_testimonials_and_ctas():
    html = html_page("Elderly Care", "<h1>Elderly Care</h1><p>Daily living support for seniors at home.</p>"
                                      "<h2>FAQ</h2><h3>Are caregivers vetted?</h3><p>Yes, caregivers are vetted before matching.</p>"
                                      "<ul><li>Meals</li><li>Bathing</li></ul><p>Book Elderly Care</p>")
    doc = extract_document(html, "https://x.test/elderly", "2026-01-01")
    texts = [b.text for b in doc.blocks]
    assert doc.title == "Elderly Care"
    assert "Daily living support for seniors at home." in texts and "Meals" in texts
    assert not any("Best service ever" in t or "Copyright" in t or "Home" == t for t in texts)
    assert "Book Elderly Care" not in texts  # CTA removed
    assert doc.provenance == "scraped_html"


def test_cross_page_boilerplate_and_within_page_duplicates_are_removed():
    def d(i, extra):
        return Document(f"https://x.test/p{i}", f"P{i}", [Block("heading", "T", 1), Block("paragraph", "Shared footer text everywhere"),
                                                           Block("paragraph", extra), Block("paragraph", extra)],
                        "scraped_html", "http", "")
    docs, stats = dedupe_documents([d(i, f"unique {i} content words") for i in range(5)], max_pages=3)
    assert stats["cross_page_boilerplate"] == 5 and stats["within_page_duplicates"] == 5
    assert all(len([b for b in x.blocks if b.kind == "paragraph"]) == 1 for x in docs)
    assert all(b.kind == "heading" or "unique" in b.text for x in docs for b in x.blocks)


def test_snapshot_parser_preserves_real_url_and_provenance():
    doc = parse_markdown_snapshot("---\nurl: https://www.thecarepal.com/refund\ntitle: Refund Policy\n"
                                  "provenance: research_summary\n---\n# Refund\n\nAll payments are non-refundable.\n")
    assert doc.url == "https://www.thecarepal.com/refund" and doc.provenance == "research_summary"
    assert [b.kind for b in doc.blocks] == ["heading", "paragraph"]


# ------------------------------------------------------------------ chunking
def doc_with_faq():
    return Document("https://www.thecarepal.com/dementia", "Dementia Care", [
        Block("heading", "Dementia Care", 1), Block("paragraph", "Dementia affects memory and daily functioning in older adults."),
        Block("heading", "Approach", 2), Block("paragraph", "Care plans are tailored to daily needs and habits at home."),
        Block("heading", "Is dementia care available part-time?", 3),
        Block("paragraph", "Plans range from part-time support to full-time live-in care."),
        Block("list_item", "Calming routines"), Block("list_item", "Safety supervision"),
    ], "scraped_html", "http", "")


def test_faq_question_and_answer_stay_in_one_chunk_with_metadata():
    chunks = chunk_document(doc_with_faq())
    faq = [c for c in chunks if c.content_type == "faq"]
    assert len(faq) == 1
    assert "Q: Is dementia care available part-time?" in faq[0].text and "part-time support" in faq[0].text
    assert "- Calming routines" in faq[0].text  # list stays with its answer
    assert faq[0].url.endswith("/dementia") and faq[0].section_path.endswith("Is dementia care available part-time?")
    assert faq[0].embed_text.startswith("Dementia Care")


def test_chunk_ids_are_stable_content_hashes_and_links_are_set():
    a, b = chunk_document(doc_with_faq()), chunk_document(doc_with_faq())
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b]
    assert a[0].next_chunk_id == a[1].chunk_id and a[1].prev_chunk_id == a[0].chunk_id and a[0].prev_chunk_id is None
    assert make_chunk_id("u", "s", "Text") != make_chunk_id("u", "s", "Other")


def test_policy_pages_never_use_overlap_and_flags_follow_scope():
    para = " ".join(f"word{i}" for i in range(200))
    doc = Document("https://www.thecarepal.com/refund", "Refund", [Block("heading", "Policy", 2)] +
                   [Block("paragraph", para + f" end{n}.") for n in range(3)], "scraped_html", "http", "")
    chunks = chunk_document(doc)
    assert len(chunks) >= 2
    first_words = {w for w in chunks[1].text.split()[:5]}
    assert not first_words & set(chunks[0].text.split()[-30:])  # no overlap carried into the next chunk
    prod = Document("https://www.thecarepal.com/products", "Products", [Block("paragraph", "Telmideed 40 is a blood pressure medicine.")],
                    "scraped_html", "http", "")
    assert "no_medical_advice" in chunk_document(prod)[0].flags


def test_scope_classification_and_site_guard():
    assert scope.classify("https://www.thecarepal.com/refund") == ("policy", "core")
    assert scope.classify("/blog/some-post") == ("blog", "educational")
    assert scope.classify("/careers") is None and scope.classify("/signup") is None
    assert scope.same_site("https://thecarepal.com/x", "https://www.thecarepal.com")
    assert not scope.same_site("https://evil.example/x", "https://www.thecarepal.com")


# ---------------------------------------------------- robots + real HTTP crawling
def fetcher_for(site, tmp_path, **kw):
    s = make_settings(tmp_path, site_base_url=site.base, **kw)
    return s, HttpFetcher(s)


def test_robots_disallow_is_enforced_and_nothing_disallowed_is_requested(site, tmp_path):
    site.routes["/robots.txt"] = (200, "text/plain", "User-agent: *\nDisallow: /privacy\n")
    site.page("/refund", html_page("Refund", "<h1>Refund</h1><p>All payments are non-refundable.</p>"))
    site.page("/privacy", html_page("Privacy", "<h1>Privacy</h1><p>Private text here for testing.</p>"))
    _, f = fetcher_for(site, tmp_path)
    f.prepare()
    assert f.fetch(f"{site.base}/refund").status == 200
    with pytest.raises(CrawlBlocked):
        f.fetch(f"{site.base}/privacy")
    assert "/privacy" not in site.hits  # the disallowed URL was never requested


@pytest.mark.parametrize("status,allowed", [(404, True), (403, False), (500, False)])
def test_robots_status_semantics(site, tmp_path, status, allowed):
    site.routes["/robots.txt"] = (status, "text/plain", "x")
    _, f = fetcher_for(site, tmp_path)
    if allowed:
        assert f.prepare().can_fetch(f"{site.base}/x")
    else:
        with pytest.raises(CrawlBlocked):
            f.prepare()


def test_robots_unreachable_means_no_crawl(tmp_path):
    s = make_settings(tmp_path, site_base_url="http://127.0.0.1:1")  # nothing listening
    with pytest.raises(CrawlBlocked):
        HttpFetcher(s).prepare()


def test_off_site_redirect_is_refused(site, tmp_path):
    site.routes["/robots.txt"] = (404, "text/plain", "")
    site.routes["/refund"] = (302, "text/plain", "https://evil.example/steal")
    _, f = fetcher_for(site, tmp_path)
    f.prepare()
    with pytest.raises(FetchError):
        f.fetch(f"{site.base}/refund")


def test_sitemap_discovery_filters_to_same_site(site, tmp_path):
    site.routes["/robots.txt"] = (404, "text/plain", "")
    site.routes["/sitemap.xml"] = (200, "application/xml",
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>{site.base}/refund</loc></url>'
        '<url><loc>https://evil.example/x</loc></url></urlset>')
    _, f = fetcher_for(site, tmp_path)
    f.prepare()
    assert f.discover_urls() == [f"{site.base}/refund"]


def build_site(site):
    site.routes["/robots.txt"] = (200, "text/plain", "User-agent: *\nDisallow: /careers\n")
    site.page("/refund", html_page("Refund Policy", "<h1>Refund Policy</h1><h2>Policy</h2><p>All payments made for our services are non-refundable.</p>"))
    site.page("/elderly", html_page("Elderly Care", "<h1>Elderly Care</h1><h2>What it includes</h2><p>Daily living support with meals and bathing at home.</p>"
                                                    "<h3>Are caregivers vetted?</h3><p>Caregivers are vetted before being matched with a family.</p>"))
    site.page("/careers", html_page("Careers", "<h1>Careers</h1><p>Join our team of caregivers today.</p>"))
    site.sitemap(["/refund", "/elderly", "/careers"])


def test_real_crawl_ingests_pages_and_is_incremental(site, tmp_path):
    build_site(site)
    s, f = fetcher_for(site, tmp_path)
    emb = HashingNgramEmbedder(128)

    r1 = run_ingest(s, source="crawl", embedder=emb, fetcher=f)
    assert r1.status == "ok" and "parsed" in r1.robots
    assert r1.pages_in_scope == 2 and "/careers" not in site.hits  # out-of-scope + robots-disallowed page never fetched
    assert r1.chunks_new == r1.chunks_total > 0 and r1.embeddings_computed == r1.chunks_new
    assert r1.provenance == {"scraped_html": 2}
    with db.session(s.sqlite_path) as conn:
        urls = {r["url"] for r in conn.execute("SELECT DISTINCT url FROM chunks")}
        assert urls == {f"{site.base}/refund", f"{site.base}/elderly"}
        assert conn.execute("SELECT COUNT(*) FROM chunks WHERE text LIKE '%Best service ever%'").fetchone()[0] == 0

    # nothing changed -> nothing new embedded, nothing removed
    r2 = run_ingest(s, source="crawl", embedder=emb, fetcher=HttpFetcher(s))
    assert r2.chunks_new == 0 and r2.embeddings_computed == 0 and r2.chunks_removed == 0
    assert r2.pages_unchanged == 2 and r2.chunks_unchanged == r1.chunks_total

    # change one page -> only its new chunk is embedded, the old chunk disappears
    site.page("/refund", html_page("Refund Policy", "<h1>Refund Policy</h1><h2>Policy</h2><p>Payments are refundable within a published window.</p>"))
    r3 = run_ingest(s, source="crawl", embedder=emb, fetcher=HttpFetcher(s))
    assert r3.pages_changed == [f"{site.base}/refund"]
    assert r3.chunks_new == 1 and r3.embeddings_computed == 1 and r3.chunks_removed == 1
    with db.session(s.sqlite_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM chunks WHERE text LIKE '%non-refundable%'").fetchone()[0] == 0

    # page leaves the sitemap -> its chunks are removed from SQLite, Chroma and BM25
    site.sitemap(["/elderly"])
    r4 = run_ingest(s, source="crawl", embedder=emb, fetcher=HttpFetcher(s))
    assert r4.pages_removed == [f"{site.base}/refund"] and r4.chunks_removed >= 1


def test_crawl_blocked_by_robots_records_a_blocked_run_and_fetches_nothing(site, tmp_path):
    site.routes["/robots.txt"] = (200, "text/plain", "User-agent: *\nDisallow: /\n")
    site.page("/refund", html_page("R", "<p>All payments made are non-refundable.</p>"))
    site.sitemap(["/refund"])
    s, f = fetcher_for(site, tmp_path)
    with pytest.raises(CrawlBlocked):
        run_ingest(s, source="crawl", embedder=HashingNgramEmbedder(64), fetcher=f)
    assert "/refund" not in site.hits and "/sitemap.xml" not in site.hits
    with db.session(s.sqlite_path) as conn:
        assert conn.execute("SELECT status FROM ingest_runs").fetchone()["status"] == "blocked"


def test_robots_policy_object_basics():
    import httpx
    transport = httpx.MockTransport(lambda req: httpx.Response(200, text="User-agent: *\nDisallow: /a\nCrawl-delay: 2\n"))
    with httpx.Client(transport=transport) as c:
        p = RobotsPolicy.load(c, "https://x.test", "CarePalAssistBot/0.1")
    assert not p.can_fetch("https://x.test/a/b") and p.can_fetch("https://x.test/b") and p.crawl_delay == 2.0
