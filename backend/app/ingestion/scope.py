"""Which public pages are in scope, and how each is classified.

Derived from the approved research (docs/company-research.md section 7). Only pages on the
configured site host are ever eligible.
"""
from __future__ import annotations

from urllib.parse import urlparse

SERVICE_PATHS = {
    "/elderly", "/dementia", "/alzeihmer", "/alzheimer", "/livein-care", "/babycare",
    "/autism", "/emergency", "/doctor", "/therapy",
}
OVERVIEW_PATHS = {"/", "/services", "/consultation"}
POLICY_PATHS = {"/refund", "/privacy", "/terms"}
CONTACT_PATHS = {"/contact"}
PRODUCT_PATHS = {"/products", "/pharmaceutical", "/lisa"}
EXCLUDED_PATHS = {"/signup", "/careers", "/blogs", "/sitemap.xml", "/login"}


def normalize_path(url_or_path: str) -> str:
    path = urlparse(url_or_path).path if "://" in url_or_path else url_or_path
    path = path.rstrip("/") or "/"
    return path


def classify(url_or_path: str) -> tuple[str, str] | None:
    """Return (content_type, tier) or None when the page is out of scope."""
    path = normalize_path(url_or_path)
    if path in EXCLUDED_PATHS:
        return None
    if path in SERVICE_PATHS:
        return "service", "core"
    if path in OVERVIEW_PATHS:
        return "overview", "core"
    if path in POLICY_PATHS:
        return "policy", "core"
    if path in CONTACT_PATHS:
        return "contact", "core"
    if path in PRODUCT_PATHS:
        return "product", "products"
    if path.startswith("/docs/"):
        return "docs", "core"
    if path.startswith("/blog/"):
        return "blog", "educational"
    return None


def page_flags(content_type: str) -> list[str]:
    flags: list[str] = []
    if content_type in {"product", "blog"}:
        flags.append("no_medical_advice")
    if content_type == "blog":
        flags.append("general_information")
    return flags


def same_site(url: str, base_url: str) -> bool:
    """True only for the configured host (ignoring a leading www.)."""
    def host(u: str) -> str:
        h = (urlparse(u).hostname or "").lower()
        return h[4:] if h.startswith("www.") else h

    return urlparse(url).scheme in {"http", "https"} and host(url) == host(base_url)
