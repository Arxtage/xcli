"""Auto-discover GraphQL query IDs from X's JavaScript bundles.

When hardcoded query IDs go stale (404), this module scrapes fresh ones
from X's JS bundles served via abs.twimg.com, caches them locally, and
provides them to graphql.py for retry.
"""

import json
import os
import re
import time

import requests

# Same User-Agent used by graphql.py
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_CACHE_DIR = os.path.expanduser("~/.xcli")
_CACHE_FILE = os.path.join(_CACHE_DIR, "query_ids.json")
_CACHE_TTL = 86400  # 24 hours

# Operations we care about (matches keys in graphql.QUERY_IDS)
_KNOWN_OPS = {
    "SearchTimeline",
    "HomeTimeline",
    "HomeLatestTimeline",
    "TweetDetail",
    "Bookmarks",
    "Likes",
    "Following",
    "Followers",
    "UserByScreenName",
    "UserTweets",
}

# Regex patterns to extract queryId/operationName pairs from minified JS.
# X's build output varies, so we try multiple patterns for robustness.
_QUERY_ID_PATTERNS = [
    # {queryId:"abc123",operationName:"UserByScreenName",...}
    re.compile(
        r'\{queryId:"([a-zA-Z0-9_-]{15,30})",operationName:"([A-Za-z]+)"'
    ),
    # {queryId: "abc123", operationName: "UserByScreenName", ...}
    re.compile(
        r'\{queryId:\s*"([a-zA-Z0-9_-]{15,30})",\s*operationName:\s*"([A-Za-z]+)"'
    ),
    # operationName:"X",queryId:"Y" (reversed order)
    re.compile(
        r'operationName:"([A-Za-z]+)"[^}]*queryId:"([a-zA-Z0-9_-]{15,30})"'
    ),
]

# Patterns to find JS bundle URLs in X's HTML
_BUNDLE_URL_PATTERNS = [
    re.compile(r'src="(https://abs\.twimg\.com/responsive-web/client-web[^"]+\.js)"'),
    re.compile(r'href="(https://abs\.twimg\.com/responsive-web/client-web[^"]+\.js)"'),
    re.compile(r'src="(https://abs\.twimg\.com/responsive-web/client-web-legacy[^"]+\.js)"'),
    re.compile(r'"(https://abs\.twimg\.com/responsive-web/client-web/[^"]+\.js)"'),
]


# ---------------------------------------------------------------------------
# Cache layer
# ---------------------------------------------------------------------------


def _load_cache() -> dict | None:
    """Load cached query IDs if they exist and aren't expired."""
    try:
        with open(_CACHE_FILE) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None

    scraped_at = data.get("_scraped_at", 0)
    if time.time() - scraped_at > _CACHE_TTL:
        return None

    return data


def _save_cache(ids: dict) -> None:
    """Save query IDs to the cache file."""
    os.makedirs(_CACHE_DIR, exist_ok=True)
    data = {"_scraped_at": time.time(), **ids}
    try:
        with open(_CACHE_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass  # Non-fatal — we can always re-scrape


def invalidate_cache() -> None:
    """Delete the cached query IDs, forcing a re-scrape on next use."""
    try:
        os.remove(_CACHE_FILE)
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------


def _scrape_fresh_ids() -> dict[str, str]:
    """Scrape query IDs from X's JavaScript bundles.

    Returns a dict mapping operation name to query ID, e.g.:
    {"UserByScreenName": "xmU6X_CKHnXF_A26BfMEMQ", ...}
    """
    found: dict[str, str] = {}

    # Fetch X's homepage to find JS bundle URLs
    try:
        resp = requests.get(
            "https://x.com",
            headers={"User-Agent": _USER_AGENT},
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException:
        return found

    html = resp.text

    # Collect unique bundle URLs
    bundle_urls: list[str] = []
    seen = set()
    for pattern in _BUNDLE_URL_PATTERNS:
        for url in pattern.findall(html):
            if url not in seen:
                seen.add(url)
                bundle_urls.append(url)

    # Download each bundle and extract query IDs
    for url in bundle_urls:
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": _USER_AGENT},
                timeout=10,
            )
            resp.raise_for_status()
        except requests.RequestException:
            continue

        js = resp.text
        for pat in _QUERY_ID_PATTERNS:
            for match in pat.finditer(js):
                groups = match.groups()
                # Handle both orderings (queryId first vs operationName first)
                if groups[0].isalpha() and not groups[1].isalpha():
                    # operationName first, queryId second (reversed pattern)
                    op_name, query_id = groups[0], groups[1]
                elif len(groups[0]) > len(groups[1]) or not groups[0][0].isupper():
                    # queryId first (standard pattern)
                    query_id, op_name = groups[0], groups[1]
                else:
                    query_id, op_name = groups[0], groups[1]

                if op_name in _KNOWN_OPS and op_name not in found:
                    found[op_name] = query_id

        # Stop early if we found all operations
        if len(found) >= len(_KNOWN_OPS):
            break

    return found


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_query_ids(operation: str, hardcoded: list[str] | None = None) -> list[str]:
    """Return query IDs to try for an operation: cached first, then hardcoded.

    This is the fast path — no network requests unless the cache is populated.
    """
    ids: list[str] = []
    seen = set()

    # Cached IDs first (most likely to be fresh)
    cache = _load_cache()
    if cache:
        cached_id = cache.get(operation)
        if cached_id and cached_id not in seen:
            ids.append(cached_id)
            seen.add(cached_id)

    # Then hardcoded fallbacks
    for qid in hardcoded or []:
        if qid not in seen:
            ids.append(qid)
            seen.add(qid)

    return ids


def scrape_query_ids(operation: str, hardcoded: list[str] | None = None) -> list[str]:
    """Force-scrape fresh query IDs, cache them, and return IDs to try.

    This is the slow path (~2-5s) — only called when all cached/hardcoded IDs 404.
    """
    fresh = _scrape_fresh_ids()
    if fresh:
        _save_cache(fresh)

    ids: list[str] = []
    seen = set()

    # Freshly scraped ID first
    scraped_id = fresh.get(operation)
    if scraped_id and scraped_id not in seen:
        ids.append(scraped_id)
        seen.add(scraped_id)

    # Hardcoded as last resort
    for qid in hardcoded or []:
        if qid not in seen:
            ids.append(qid)
            seen.add(qid)

    return ids
