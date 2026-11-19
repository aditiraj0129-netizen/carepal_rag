"""Polite, robots-respecting fetching of public pages, plus snapshot loading.

Rules enforced here (not just documented):
* robots.txt is fetched first and every URL is checked against it (RFC 9309 semantics:
  2xx parse, 404/other 4xx => allowed, 401/403 => treated as disallow-all, 5xx/network error => disallow-all).
* Only the configured site host is ever requested, including across redirects.
* A fixed delay between requests, an identifying User-Agent, a response size cap, HTML only.
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import httpx
from defusedxml import ElementTree as SafeET

from app.config import Settings
from app.ingestion import scope
from app.ingestion.clean import parse_markdown_snapshot
from app.ingestion.models import Document, FetchedPage

log = logging.getLogger(__name__)


class CrawlBlocked(Exception):
    """robots.txt (or its unavailability) forbids crawling; nothing was fetched."""


class FetchError(Exception):
    pass


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class RobotsPolicy:
    def __init__(self, parser: robotparser.RobotFileParser | None, deny_all: bool, reason: str,
                 user_agent: str):
        self._parser = parser
        self.deny_all = deny_all
        self.reason = reason
        self.user_agent = user_agent

    @property
    def crawl_delay(self) -> float | None:
        if self._parser is None:
            return None
        delay = self._parser.crawl_delay(self.user_agent)
        return float(delay) if delay is not None else None

    def can_fetch(self, url: str) -> bool:
        if self.deny_all:
            return False
        if self._parser is None:  # robots.txt absent => allowed
            return True
        return self._parser.can_fetch(self.user_agent, url)

    @classmethod
    def load(cls, client: httpx.Client, base_url: str, user_agent: str) -> RobotsPolicy:
        url = urljoin(base_url, "/robots.txt")
        try:
            resp = client.get(url)
        except httpx.HTTPError as exc:
            return cls(None, True, f"robots.txt unreachable ({exc.__class__.__name__}); refusing to crawl",
                       user_agent)
        if resp.status_code == 200:
            parser = robotparser.RobotFileParser()
            parser.parse(resp.text.splitlines())
            return cls(parser, False, "robots.txt parsed", user_agent)
        if resp.status_code in (401, 403):
            return cls(None, True, f"robots.txt returned {resp.status_code}; treating as disallow-all",
                       user_agent)
        if 400 <= resp.status_code < 500:
            return cls(None, False, f"robots.txt returned {resp.status_code}; no restrictions published",
                       user_agent)
        return cls(None, True, f"robots.txt returned {resp.status_code}; refusing to crawl", user_agent)


class HttpFetcher:
    method = "http"

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.settings = settings
        self.base_url = settings.site_base_url
        self._client = client or httpx.Client(
            headers={"User-Agent": settings.crawl_user_agent, "Accept": "text/html,application/xml"},
            timeout=settings.crawl_timeout_seconds,
            follow_redirects=False,
        )
        self.robots: RobotsPolicy | None = None
        self._last_request = 0.0

    def close(self) -> None:
        self._client.close()

    def prepare(self) -> RobotsPolicy:
        """Fetch robots.txt; raise CrawlBlocked if crawling is not permitted."""
        self.robots = RobotsPolicy.load(self._client, self.base_url, self.settings.crawl_user_agent)
        log.info("robots: %s", self.robots.reason)
        if self.robots.deny_all:
            raise CrawlBlocked(self.robots.reason)
        return self.robots

    def _wait(self) -> None:
        delay = max(self.settings.crawl_delay_seconds, (self.robots.crawl_delay or 0) if self.robots else 0)
        elapsed = time.monotonic() - self._last_request
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self._last_request = time.monotonic()

    def _get(self, url: str, max_redirects: int = 3) -> httpx.Response:
        if self.robots is None:
            raise CrawlBlocked("prepare() must be called before fetching")
        current = url
        for _ in range(max_redirects + 1):
            if not scope.same_site(current, self.base_url):
                raise FetchError(f"refusing off-site URL: {current}")
            if not self.robots.can_fetch(current):
                raise CrawlBlocked(f"robots.txt disallows {current}")
            self._wait()
            try:
                resp = self._client.get(current)
            except httpx.HTTPError as exc:
                raise FetchError(f"{current}: {exc.__class__.__name__}: {exc}") from exc
            if resp.status_code in (301, 302, 303, 307, 308) and "location" in resp.headers:
                current = urljoin(current, resp.headers["location"])
                continue
            return resp
        raise FetchError(f"too many redirects for {url}")

    def fetch(self, url: str) -> FetchedPage:
        resp = self._get(url)
        if resp.status_code != 200:
            raise FetchError(f"{url}: HTTP {resp.status_code}")
        ctype = resp.headers.get("content-type", "")
        if "html" not in ctype.lower():
            raise FetchError(f"{url}: unexpected content-type {ctype!r}")
        if len(resp.content) > self.settings.crawl_max_bytes:
            raise FetchError(f"{url}: response larger than {self.settings.crawl_max_bytes} bytes")
        return FetchedPage(url=url, status=200, html=resp.text, fetched_at=utc_now(), method="http")

    def discover_urls(self) -> list[str]:
        """Read /sitemap.xml (and one level of nested sitemaps); return same-site URLs."""
        sitemap_url = urljoin(self.base_url, "/sitemap.xml")
        urls: list[str] = []
        seen: set[str] = set()

        def parse(url: str, depth: int) -> None:
            if url in seen or depth > 1:
                return
            seen.add(url)
            resp = self._get(url)
            if resp.status_code != 200:
                raise FetchError(f"{url}: HTTP {resp.status_code}")
            root = SafeET.fromstring(resp.content)
            for el in root.iter():
                if not el.tag.endswith("loc") or not el.text:
                    continue
                loc = el.text.strip()
                if root.tag.endswith("sitemapindex"):
                    parse(loc, depth + 1)
                elif scope.same_site(loc, self.base_url):
                    urls.append(loc)

        parse(sitemap_url, 0)
        return sorted(set(urls))


def looks_js_rendered(html: str, extracted_word_count: int) -> bool:
    markers = ('id="root"', "id='root'", 'id="__next"', "<noscript")
    return extracted_word_count < 40 and any(m in html for m in markers)


def render_with_playwright(url: str, user_agent: str, timeout_ms: int = 20000) -> str:
    """Optional JS rendering. Requires `pip install playwright` + `playwright install chromium`."""
    from playwright.sync_api import sync_playwright  # lazy import

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_context(user_agent=user_agent).new_page()
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            return page.content()
        finally:
            browser.close()


class SnapshotSource:
    """Loads pre-saved page text from seed/*.md (used when the live site cannot be crawled).

    Each file's front matter carries the real source URL and a `provenance` label, which is
    preserved all the way to the API response so snapshots are never mistaken for scraped text.
    """

    method = "snapshot"

    def __init__(self, seed_dir: Path):
        self.seed_dir = Path(seed_dir)

    def documents(self) -> list[Document]:
        docs: list[Document] = []
        for path in sorted(self.seed_dir.glob("*.md")):
            doc = parse_markdown_snapshot(path.read_text(encoding="utf-8"))
            if doc is not None:
                docs.append(doc)
        return docs


def path_of(url: str) -> str:
    return urlparse(url).path or "/"
