"""Evidence tools restricted to the authoritative allowlist.

PubMed search is deliberately opinionated: field-tagged keywords, review-type
filter, relevance filtering and a relaxed fallback (see ``pubmed_query``).
E-utilities calls are throttled and retried so parallel agents stay polite
without needing an API key.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any

import httpx

from . import pubmed_query
from .config import settings
from .sources import GUIDE_SUMMARIES, is_allowed
from .tcm import search_tcm

USER_AGENT = "health-agent-platform/0.1 (research prototype; contact: demo)"
TIMEOUT = 20.0
PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# NCBI allows 3 requests/second without a key; keep a margin and serialize the
# throttle across threads so parallel retrieval cannot burst past the limit.
_THROTTLE_LOCK = threading.Lock()
_LAST_CALL = 0.0


def _min_interval() -> float:
    return 0.10 if settings.ncbi_api_key else 0.38


def _throttle() -> None:
    global _LAST_CALL
    with _THROTTLE_LOCK:
        wait = _min_interval() - (time.monotonic() - _LAST_CALL)
        if wait > 0:
            time.sleep(wait)
        _LAST_CALL = time.monotonic()



def _safe_call(fn, timeout: float):
    """Run fn in a daemon thread with a hard deadline.

    WSL's DNS proxy can occasionally hang inside getaddrinfo, which neither
    httpx timeouts nor socket timeouts bound.  The daemon thread is abandoned
    on timeout so the app keeps running.
    """
    box: dict[str, object] = {}

    def target() -> None:
        try:
            box["value"] = fn()
        except BaseException as error:  # noqa: BLE001 - re-raised in caller thread
            box["error"] = error

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise TimeoutError(f"network call exceeded {timeout:.0f}s")
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return box["value"]


def _get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    """GET JSON from E-utilities with throttling and 429/5xx backoff."""
    last_error: Exception | None = None
    for attempt in range(3):
        _throttle()
        try:
            with httpx.Client(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
                response = client.get(url, params=params)
            if response.status_code in (429, 500, 502, 503, 504):
                last_error = httpx.HTTPStatusError(
                    f"HTTP {response.status_code}", request=response.request, response=response,
                )
                time.sleep(1.5 * (attempt + 1))
                continue
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as error:
            last_error = error
            time.sleep(1.0 * (attempt + 1))
    raise last_error or RuntimeError("E-utilities request failed")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag in ("script", "style", "noscript"):
            self.skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript") and self.skip:
            self.skip -= 1

    def handle_data(self, data: str) -> None:
        if not self.skip and data.strip():
            self.parts.append(data.strip())


def _html_text(html: str, limit: int) -> str:
    """Prefer the page's main/article content; fall back to the whole document."""
    import re

    match = re.search(r"<(main|article)\b[^>]*>(.*?)</\1>", html, re.S | re.I)
    scope = match.group(2) if match else html
    parser = _TextExtractor()
    parser.feed(scope)
    return " ".join(" ".join(parser.parts).split())[:limit]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _eutils_common() -> dict[str, str]:
    params = {"tool": settings.ncbi_tool}
    if settings.ncbi_email:
        params["email"] = settings.ncbi_email
    if settings.ncbi_api_key:
        params["api_key"] = settings.ncbi_api_key
    return params


def _esearch(term: str, retmax: int, strict: bool) -> list[str]:
    params = {
        "db": "pubmed", "term": term, "retmode": "json",
        "retmax": max(1, min(retmax, 30)), "sort": "relevance",
        **_eutils_common(),
    }
    if strict:
        current_year = datetime.now(timezone.utc).year
        params.update({
            "datetype": "pdat",
            "mindate": str(current_year - 10),
            "maxdate": str(current_year),
        })
    payload = _get_json(f"{PUBMED_BASE}/esearch.fcgi", params)
    return (payload.get("esearchresult", {}) or {}).get("idlist", []) or []


def _esummary(ids: list[str]) -> list[dict[str, Any]]:
    params = {"db": "pubmed", "id": ",".join(ids), "retmode": "json", **_eutils_common()}
    result = _get_json(f"{PUBMED_BASE}/esummary.fcgi", params).get("result", {}) or {}
    return [result[uid] for uid in ids if uid in result]


def _pubmed_search_impl(term: str, retmax: int = 5) -> list[dict[str, Any]]:
    """Search PubMed with a guideline/review-first strategy.

    The strict query needs high-confidence publication types; when it yields
    too few results we relax to plain keyword matching.  In both cases the
    title-relevance filter and the guideline > review > other ranking apply.
    """
    words = pubmed_query.keywords(term)
    best: list[dict[str, Any]] = []
    for strict in (True, False):
        query = pubmed_query.build_query(term, strict=strict)
        try:
            ids = _esearch(query, retmax * 4, strict)
            summaries = _esummary(ids) if ids else []
        except httpx.HTTPError:
            summaries = []
        selected = pubmed_query.select(summaries, words, retmax) if summaries else []
        if len(selected) >= min(retmax, 3):
            best = selected
            break
        best = selected or best
    evidence = []
    for item in best:
        uid = str(item.get("uid") or "")
        title = (item.get("title") or "").strip().rstrip(".")
        if not uid or not title:
            continue
        journal = item.get("fulljournalname") or item.get("source") or ""
        year = (item.get("pubdate") or "").split(" ")[0]
        pubtypes = ", ".join(item.get("pubtype") or [])
        evidence.append({
            "source": "pubmed",
            "title": title,
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{uid}/",
            "snippet": f"{journal} {year}".strip() + (f" ({pubtypes})" if pubtypes else ""),
            "retrieved_at": _now(),
        })
    return evidence


def _openfda_label_search_impl(drug: str, limit: int = 3) -> list[dict[str, Any]]:
    """Search openFDA drug labels and return the official label sections."""
    query = f'openfda.generic_name:"{drug}" OR openfda.brand_name:"{drug}"'
    with httpx.Client(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
        response = client.get("https://api.fda.gov/drug/label.json", params={
            "search": query, "limit": max(1, min(limit, 5)),
        })
        if response.status_code == 404:
            return []
        response.raise_for_status()
        payload = response.json()
    evidence = []
    for item in payload.get("results", []) or []:
        openfda = item.get("openfda") or {}
        brand = " / ".join(openfda.get("brand_name") or []) or drug
        generic = " / ".join(openfda.get("generic_name") or []) or ""
        parts = []
        for key in ("indications_and_usage", "dosage_and_administration", "warnings", "contraindications"):
            value = item.get(key) or []
            if value:
                parts.append(f"{key}: {' '.join(value)[:600]}")
        snippet = " | ".join(parts)[: settings.max_snippet_chars]
        set_id = item.get("set_id") or ""
        evidence.append({
            "source": "openfda",
            "title": f"{brand} ({generic}) — FDA drug label",
            "url": f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={set_id}" if set_id else "https://api.fda.gov/drug/label.json",
            "snippet": snippet or "label has no usable sections",
            "retrieved_at": _now(),
        })
    return evidence


def _fetch_url_impl(url: str) -> list[dict[str, Any]]:
    """Fetch one allowlisted page and return it as evidence."""
    if not is_allowed(url):
        raise ValueError(f"URL is not on the source allowlist: {url}")
    with httpx.Client(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        if not is_allowed(str(response.url)):
            raise ValueError("redirect left the source allowlist")
    text = _html_text(response.text, 4000)
    return [{
        "source": url.split("/")[2],
        "title": url,
        "url": url,
        "snippet": text[: settings.max_snippet_chars],
        "summary_zh": GUIDE_SUMMARIES.get(url, ""),
        "retrieved_at": _now(),
    }]


def pubmed_search(term: str, retmax: int = 5, timeout: float | None = None):
    return _safe_call(lambda: _pubmed_search_impl(term, retmax), timeout or settings.tool_timeout_seconds)


def openfda_label_search(drug: str, limit: int = 3, timeout: float | None = None):
    return _safe_call(lambda: _openfda_label_search_impl(drug, limit), timeout or settings.tool_timeout_seconds)


def fetch_url(url: str, timeout: float | None = None):
    deadline = timeout or settings.tool_timeout_seconds

    def attempt() -> list:
        last: Exception | None = None
        for _ in range(2):
            try:
                return _fetch_url_impl(url)
            except Exception as error:  # noqa: BLE001 - one retry for flaky pages
                last = error
                time.sleep(1.0)
        raise last or RuntimeError("fetch failed")

    return _safe_call(attempt, deadline)


TOOLS = {
    "pubmed_search": {
        "fn": pubmed_search,
        "schema": {"term": "string (English keywords)", "retmax": "integer (optional)"},
        "description": "Search PubMed for guideline/review evidence about a symptom, condition or drug. Pass English keywords, not a Chinese phrase.",
    },
    "openfda_label_search": {
        "fn": openfda_label_search,
        "schema": {"drug": "string (English generic or brand name)", "limit": "integer (optional)"},
        "description": "Look up the official FDA drug label (indications, dosage, warnings, contraindications). Use an English generic or brand name.",
    },
    "tcm_search": {
        "fn": search_tcm,
        "schema": {"symptoms": "string (Chinese symptom text)", "limit": "integer (optional)"},
        "description": "Search the curated OTC Chinese patent medicine knowledge base: name, pattern, indications, dosage, contraindications, cautions, price range. Use Chinese symptom text.",
    },
    "fetch_url": {
        "fn": fetch_url,
        "schema": {"url": "string"},
        "description": "Fetch a page from the authoritative allowlist (NHS, WHO, CDC, DailyMed, PubMed).",
    },
}


# Argument aliases: models routinely rename "term" to query/keywords/q.
_ALIASES = {
    "pubmed_search": {"query": "term", "keywords": "term", "q": "term", "search": "term"},
    "openfda_label_search": {"query": "drug", "name": "drug", "drug_name": "drug"},
    "fetch_url": {"link": "url", "page": "url"},
    "tcm_search": {"query": "symptoms", "text": "symptoms", "term": "symptoms"},
}


def _normalize(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    spec = TOOLS.get(name) or {}
    allowed = set((spec.get("fn").__code__.co_varnames if spec.get("fn") else ())[:8])
    aliases = _ALIASES.get(name, {})
    normalized: dict[str, Any] = {}
    for key, value in (arguments or {}).items():
        target = aliases.get(key, key)
        if allowed and target not in allowed:
            continue
        normalized[target] = value
    return normalized


def run_tool(name: str, arguments: dict[str, Any]) -> str:
    spec = TOOLS.get(name)
    if spec is None:
        return json.dumps({"error": f"unknown tool: {name}"}, ensure_ascii=False)
    try:
        result = spec["fn"](**_normalize(name, arguments))
    except Exception as error:  # noqa: BLE001 - tool failures become observations
        return json.dumps({"error": f"{type(error).__name__}: {error}"}, ensure_ascii=False)
    return json.dumps(result, ensure_ascii=False)
