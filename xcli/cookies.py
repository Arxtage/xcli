"""Extract auth_token and ct0 cookies from the user's browser for X GraphQL reads."""

import browser_cookie3

BROWSERS = [
    ("Arc", browser_cookie3.arc),
    ("Chrome", browser_cookie3.chrome),
    ("Safari", browser_cookie3.safari),
    ("Firefox", browser_cookie3.firefox),
]

COOKIE_NAMES = {"auth_token", "ct0"}
DOMAINS = [".x.com", ".twitter.com"]

# In-memory cache — fresh cookies extracted once per CLI invocation
_memory_cache: dict | None = None


def _extract_from_browser(browser_fn) -> dict | None:
    """Try to extract auth_token and ct0 from a browser's cookie store."""
    found = {}
    for domain in DOMAINS:
        try:
            cj = browser_fn(domain_name=domain)
        except Exception:
            continue
        for cookie in cj:
            if cookie.name in COOKIE_NAMES and cookie.name not in found:
                found[cookie.name] = cookie.value
        if COOKIE_NAMES.issubset(found):
            return found
    if COOKIE_NAMES.issubset(found):
        return found
    return None


def get_read_cookies() -> dict:
    """Return {"auth_token": "...", "ct0": "..."} for X GraphQL reads.

    Extracts fresh cookies from the browser on first call, then caches
    in-memory for the rest of the process. The ct0 CSRF token rotates
    frequently, so we never persist cookies to disk.
    """
    global _memory_cache
    if _memory_cache:
        return _memory_cache

    for name, browser_fn in BROWSERS:
        try:
            cookies = _extract_from_browser(browser_fn)
        except Exception:
            continue
        if cookies:
            _memory_cache = cookies
            return cookies

    raise RuntimeError(
        "Could not find X session cookies in any browser.\n"
        "Make sure you're logged into x.com in Arc, Chrome, Safari, or Firefox,\n"
        "then try again. You may need to close the browser first for cookie access."
    )


def clear_cached_cookies() -> None:
    """Clear the in-memory cookie cache (forces re-extraction from browser)."""
    global _memory_cache
    _memory_cache = None
