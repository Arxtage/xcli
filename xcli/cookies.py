"""Extract auth_token and ct0 cookies from the user's browser for X GraphQL reads."""

import browser_cookie3

from xcli.config import CONFIG_FILE, save_config

BROWSERS = [
    ("Arc", browser_cookie3.arc),
    ("Chrome", browser_cookie3.chrome),
    ("Safari", browser_cookie3.safari),
    ("Firefox", browser_cookie3.firefox),
]

COOKIE_NAMES = {"auth_token", "ct0"}
DOMAINS = [".x.com", ".twitter.com"]


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


def _load_cached() -> dict | None:
    """Load cached cookies from config file."""
    if not CONFIG_FILE.exists():
        return None
    import json

    try:
        config = json.loads(CONFIG_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    token = config.get("read_auth_token")
    ct0 = config.get("read_ct0")
    if token and ct0:
        return {"auth_token": token, "ct0": ct0}
    return None


def _cache_cookies(cookies: dict) -> None:
    """Save cookies to the config file (merges with existing config)."""
    import json

    config = {}
    if CONFIG_FILE.exists():
        try:
            config = json.loads(CONFIG_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    config["read_auth_token"] = cookies["auth_token"]
    config["read_ct0"] = cookies["ct0"]
    save_config(config)


def get_read_cookies() -> dict:
    """Return {"auth_token": "...", "ct0": "..."} for X GraphQL reads.

    Tries cached cookies first, then extracts from browsers (Arc > Chrome > Safari > Firefox).
    Raises RuntimeError if no cookies found.
    """
    cached = _load_cached()
    if cached:
        return cached

    for name, browser_fn in BROWSERS:
        try:
            cookies = _extract_from_browser(browser_fn)
        except Exception:
            continue
        if cookies:
            _cache_cookies(cookies)
            return cookies

    raise RuntimeError(
        "Could not find X session cookies in any browser.\n"
        "Make sure you're logged into x.com in Arc, Chrome, Safari, or Firefox,\n"
        "then try again. You may need to close the browser first for cookie access."
    )


def clear_cached_cookies() -> None:
    """Remove cached cookies from config (forces re-extraction on next use)."""
    import json

    if not CONFIG_FILE.exists():
        return
    try:
        config = json.loads(CONFIG_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return
    config.pop("read_auth_token", None)
    config.pop("read_ct0", None)
    save_config(config)
