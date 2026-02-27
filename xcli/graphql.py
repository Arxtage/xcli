"""X browser-based client for free, cookie-authenticated read operations.

Uses GraphQL endpoints for tweets/users and v1.1 REST for DMs.
"""

import re
import uuid

import requests

from xcli.cookies import clear_cached_cookies, get_read_cookies
from xcli.query_ids import get_query_ids, invalidate_cache, scrape_query_ids

# Public bearer token used by X's web client (not tied to any user account)
BEARER_TOKEN = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs"
    "%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)

GRAPHQL_BASE = "https://x.com/i/api/graphql"

# Query IDs per operation — multiple fallbacks in case X rotates them
QUERY_IDS = {
    "SearchTimeline": ["M1jEez78PEfVfbQLvlWMvQ", "6AAys3t42mosm_yTI_QENg"],
    "HomeTimeline": ["edseUwk9sP5Phz__9TIRnA"],
    "HomeLatestTimeline": ["iOEZpOdfekFsxSlPQCQtPg"],
    "TweetDetail": ["97JF30KziU00483E_8elBA", "_NvJCnIjOW__EP5-RF197A"],
    "Bookmarks": ["RV1g3b8n_SGOHwkqKYSCFw", "tmd4ifV8RHltzn8ymGg1aw"],
    "Likes": ["JR2gceKucIKcVNB_9JkhsA", "ETJflBunfqNa1uE1mBPCaw"],
    "Following": ["BEkNpEt5pNETESoqMsTEGA"],
    "Followers": ["kuFUYP9eV1FPoEy4N-pi7w"],
    "UserByScreenName": ["xmU6X_CKHnXF_A26BfMEMQ", "qRednkZG-rn1P6b48NINmQ"],
    "UserTweets": ["H8OOoI-5ZE4NxgRr8lfyPg", "CdG2Vuc1v6F5JyEngGpxVw"],
}

# Minimal feature flags required by most endpoints
DEFAULT_FEATURES = {
    "rweb_tipjar_consumption_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "articles_preview_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "creator_subscriptions_quote_tweet_preview_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "rweb_video_timestamps_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
    "tweetypie_unmention_optimization_enabled": True,
    "vibe_api_enabled": True,
}

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _build_headers(cookies: dict) -> dict:
    """Build HTTP headers mimicking the X web client."""
    return {
        "Authorization": f"Bearer {BEARER_TOKEN}",
        "Cookie": f"auth_token={cookies['auth_token']}; ct0={cookies['ct0']}",
        "x-csrf-token": cookies["ct0"],
        "x-twitter-auth-type": "OAuth2Session",
        "x-twitter-active-user": "yes",
        "x-client-uuid": str(uuid.uuid4()),
        "User-Agent": USER_AGENT,
    }


def _try_query_ids(
    operation: str,
    query_ids: list[str],
    params: dict,
    cookies: dict,
    json_body: dict | None = None,
) -> dict | None:
    """Try each query ID for an operation. Returns response JSON or None if all 404.

    Tries GET first. If all IDs return 404 and *json_body* is provided,
    retries with POST (X has migrated some operations from GET to POST).
    """
    for method, attempts in [("GET", query_ids), ("POST", query_ids if json_body else [])]:
        all_404 = True

        for qid in attempts:
            url = f"{GRAPHQL_BASE}/{qid}/{operation}"
            headers = _build_headers(cookies)

            try:
                if method == "POST":
                    headers["Content-Type"] = "application/json"
                    resp = requests.post(url, json=json_body, headers=headers, timeout=15)
                else:
                    resp = requests.get(url, params=params, headers=headers, timeout=15)
            except requests.RequestException:
                all_404 = False
                continue

            if resp.status_code == 404:
                continue

            all_404 = False

            if resp.status_code == 401:
                clear_cached_cookies()
                fresh_cookies = get_read_cookies()
                headers = _build_headers(fresh_cookies)
                if method == "POST":
                    headers["Content-Type"] = "application/json"
                    resp = requests.post(url, json=json_body, headers=headers, timeout=15)
                else:
                    resp = requests.get(url, params=params, headers=headers, timeout=15)
                if resp.status_code == 401:
                    raise RuntimeError(
                        "X session expired. Log into x.com in your browser and try again."
                    )
                cookies.update(fresh_cookies)

            if resp.status_code == 429:
                raise RuntimeError("Rate limited by X. Wait a few minutes and try again.")

            if resp.status_code == 200:
                return resp.json()

            continue

        if not all_404:
            raise RuntimeError(
                f"All query IDs failed for {operation}. X may have changed their API."
            )

    # All IDs returned 404 for both GET and POST
    if query_ids:
        return None  # Signal to caller: stale IDs, try scraping

    raise RuntimeError(
        f"All query IDs failed for {operation}. X may have changed their API."
    )


def _graphql_request(
    operation: str, variables: dict, features: dict | None = None
) -> dict:
    """Make a request to X's GraphQL API (tries GET then POST).

    Two-pass approach:
    1. Try cached + hardcoded IDs (fast path)
    2. If all return 404 → scrape fresh IDs from X's JS bundles and retry
    """
    import json as json_mod

    if features is None:
        features = DEFAULT_FEATURES

    hardcoded = QUERY_IDS.get(operation, [])

    cookies = get_read_cookies()
    params = {
        "variables": json_mod.dumps(variables),
        "features": json_mod.dumps(features),
    }
    json_body = {"variables": variables, "features": features}

    # Pass 1: cached + hardcoded IDs
    ids = get_query_ids(operation, hardcoded)
    if ids:
        result = _try_query_ids(operation, ids, params, cookies, json_body)
        if result is not None:
            return result

    # Pass 2: all IDs returned 404 — scrape fresh ones
    invalidate_cache()
    fresh_ids = scrape_query_ids(operation, hardcoded)
    if fresh_ids:
        result = _try_query_ids(operation, fresh_ids, params, cookies, json_body)
        if result is not None:
            return result

    raise RuntimeError(
        f"All query IDs failed for {operation}. "
        "X may have rotated their API — try again later or update xcli."
    )


# ---------------------------------------------------------------------------
# Response parsing helpers
# ---------------------------------------------------------------------------


def _extract_user_info(user_result: dict) -> dict:
    """Extract screen_name and name from a user result node.

    X stores these in ``user_result.core`` (new) or ``user_result.legacy``
    (old).  We check both locations so the parser survives API changes.
    """
    user_core = user_result.get("core", {})
    user_legacy = user_result.get("legacy", {})
    return {
        "username": (
            user_core.get("screen_name")
            or user_legacy.get("screen_name", "")
        ),
        "name": (
            user_core.get("name")
            or user_legacy.get("name", "")
        ),
    }


def _parse_tweet(raw: dict) -> dict | None:
    """Extract a normalized tweet dict from X's nested GraphQL response."""
    # Handle tweet_results wrapper
    result = raw.get("tweet_results", raw).get("result", raw)

    # Handle __typename: TweetWithVisibilityResults
    if result.get("__typename") == "TweetWithVisibilityResults":
        result = result.get("tweet", result)

    legacy = result.get("legacy", {})
    core = result.get("core", {})
    user_result = core.get("user_results", {}).get("result", {})
    outer_user = _extract_user_info(user_result)

    retweeted_by = None

    # Detect retweets: the outer tweet's author retweeted the inner tweet
    rt_result = legacy.get("retweeted_status_result", {}).get("result", {})
    if rt_result:
        # Handle TweetWithVisibilityResults inside retweet
        if rt_result.get("__typename") == "TweetWithVisibilityResults":
            rt_result = rt_result.get("tweet", rt_result)

        retweeted_by = outer_user["username"]
        # Switch to the inner (original) tweet's data
        legacy = rt_result.get("legacy", {})
        core = rt_result.get("core", {})
        user_result = core.get("user_results", {}).get("result", {})
        outer_user = _extract_user_info(user_result)
        result = rt_result

    text = legacy.get("full_text", "")
    if not text:
        return None

    return {
        "id": legacy.get("id_str", result.get("rest_id", "")),
        "text": text,
        "author": outer_user,
        "retweetedBy": retweeted_by,
        "createdAt": legacy.get("created_at", ""),
        "replyCount": legacy.get("reply_count", 0),
        "likeCount": legacy.get("favorite_count", 0),
        "retweetCount": legacy.get("retweet_count", 0),
        "viewCount": int(
            result.get("views", {}).get("count", 0) or 0
        ),
    }


def _parse_user(raw: dict) -> dict:
    """Extract a normalized user dict from X's nested GraphQL response."""
    result = raw.get("user_results", raw).get("result", raw)
    info = _extract_user_info(result)
    legacy = result.get("legacy", {})
    return {
        "id": result.get("rest_id", ""),
        "username": info["username"],
        "name": info["name"],
        "bio": legacy.get("description", ""),
        "followers": legacy.get("followers_count", 0),
        "following": legacy.get("friends_count", 0),
    }


def _extract_timeline_tweets(data: dict, instruction_type: str = "TimelineAddEntries") -> list[dict]:
    """Navigate the instructions[].entries[] structure common to timeline endpoints."""
    tweets = []
    instructions = _find_instructions(data)

    for instruction in instructions:
        if instruction.get("type") != instruction_type:
            continue
        for entry in instruction.get("entries", []):
            content = entry.get("content", {})
            # Standard tweet entry
            item_content = content.get("itemContent", {})
            if item_content.get("itemType") == "TimelineTweet":
                tweet = _parse_tweet(item_content)
                if tweet:
                    tweets.append(tweet)
            # Module entries (conversations, etc.)
            for item in content.get("items", []):
                ic = item.get("item", {}).get("itemContent", {})
                if ic.get("itemType") == "TimelineTweet":
                    tweet = _parse_tweet(ic)
                    if tweet:
                        tweets.append(tweet)
    return tweets


def _extract_timeline_users(data: dict, instruction_type: str = "TimelineAddEntries") -> list[dict]:
    """Navigate the instructions[].entries[] structure for user-list endpoints."""
    users = []
    instructions = _find_instructions(data)

    for instruction in instructions:
        if instruction.get("type") != instruction_type:
            continue
        for entry in instruction.get("entries", []):
            content = entry.get("content", {})
            item_content = content.get("itemContent", {})
            if item_content.get("itemType") == "TimelineUser":
                user = _parse_user(item_content)
                if user.get("username"):
                    users.append(user)
    return users


def _find_instructions(data: dict) -> list:
    """Recursively find the 'instructions' list in the response."""
    if isinstance(data, dict):
        if "instructions" in data:
            return data["instructions"]
        for v in data.values():
            result = _find_instructions(v)
            if result:
                return result
    return []


# ---------------------------------------------------------------------------
# Public API functions
# ---------------------------------------------------------------------------


def _search_v1(query: str, count: int = 10) -> list[dict]:
    """Fallback: search tweets via the v1.1 REST API with cookie auth.

    Used when GraphQL SearchTimeline is broken (all query IDs return 404).
    Same auth pattern as whoami/dms.
    """
    cookies = get_read_cookies()
    headers = _build_headers(cookies)
    params = {
        "q": query,
        "count": count,
        "result_type": "recent",
        "tweet_mode": "extended",
    }
    resp = requests.get(
        "https://api.x.com/1.1/search/tweets.json",
        params=params,
        headers=headers,
        timeout=15,
    )
    if resp.status_code == 401:
        clear_cached_cookies()
        cookies = get_read_cookies()
        headers = _build_headers(cookies)
        resp = requests.get(
            "https://api.x.com/1.1/search/tweets.json",
            params=params,
            headers=headers,
            timeout=15,
        )
        if resp.status_code == 401:
            raise RuntimeError(
                "X session expired. Log into x.com in your browser and try again."
            )
    if resp.status_code == 429:
        raise RuntimeError("Rate limited by X. Wait a few minutes and try again.")
    if resp.status_code != 200:
        raise RuntimeError(f"v1.1 search failed with status {resp.status_code}")

    tweets = []
    for status in resp.json().get("statuses", []):
        user = status.get("user", {})
        tweets.append({
            "id": status.get("id_str", ""),
            "text": status.get("full_text", ""),
            "author": {
                "username": user.get("screen_name", ""),
                "name": user.get("name", ""),
            },
            "retweetedBy": None,
            "createdAt": status.get("created_at", ""),
            "replyCount": 0,  # v1.1 doesn't provide reply count
            "likeCount": status.get("favorite_count", 0),
            "retweetCount": status.get("retweet_count", 0),
            "viewCount": 0,  # v1.1 doesn't provide view count
        })
    return tweets[:count]


def search(query: str, count: int = 10) -> list[dict]:
    """Search tweets via GraphQL, falling back to v1.1 REST if GraphQL fails."""
    try:
        variables = {
            "rawQuery": query,
            "count": count,
            "querySource": "typed_query",
            "product": "Latest",
        }
        data = _graphql_request("SearchTimeline", variables)
        return _extract_timeline_tweets(data)[:count]
    except Exception:
        return _search_v1(query, count)


def get_home_timeline(count: int = 20) -> list[dict]:
    """Fetch the authenticated user's home timeline."""
    variables = {"count": count, "includePromotedContent": False}
    data = _graphql_request("HomeLatestTimeline", variables)
    return _extract_timeline_tweets(data)[:count]


def read_tweet(tweet_id: str) -> dict | None:
    """Fetch a single tweet by ID."""
    # Strip URL to just the ID
    match = re.search(r"/status/(\d+)", tweet_id)
    if match:
        tweet_id = match.group(1)

    variables = {
        "focalTweetId": tweet_id,
        "with_rux_injections": False,
        "includePromotedContent": False,
        "withCommunity": True,
        "withQuickPromoteEligibilityTweetFields": False,
        "withBirdwatchNotes": True,
        "withVoice": True,
        "withV2Timeline": True,
    }
    data = _graphql_request("TweetDetail", variables)
    tweets = _extract_timeline_tweets(data)
    # The focal tweet is the one matching tweet_id
    for t in tweets:
        if t["id"] == tweet_id:
            return t
    # Return first tweet if ID doesn't match exactly
    return tweets[0] if tweets else None


def get_bookmarks(count: int = 10) -> list[dict]:
    """Fetch the authenticated user's bookmarks."""
    variables = {"count": count, "includePromotedContent": False}
    data = _graphql_request("Bookmarks", variables)
    return _extract_timeline_tweets(data)[:count]


def get_likes(user_id: str, count: int = 10) -> list[dict]:
    """Fetch liked tweets for a user."""
    variables = {
        "userId": user_id,
        "count": count,
        "includePromotedContent": False,
    }
    data = _graphql_request("Likes", variables)
    return _extract_timeline_tweets(data)[:count]


def get_followers(user_id: str, count: int = 20) -> list[dict]:
    """Fetch followers for a user."""
    variables = {
        "userId": user_id,
        "count": count,
        "includePromotedContent": False,
    }
    data = _graphql_request("Followers", variables)
    return _extract_timeline_users(data)[:count]


def get_following(user_id: str, count: int = 20) -> list[dict]:
    """Fetch accounts a user is following."""
    variables = {
        "userId": user_id,
        "count": count,
        "includePromotedContent": False,
    }
    data = _graphql_request("Following", variables)
    return _extract_timeline_users(data)[:count]


def get_user_by_screen_name(screen_name: str) -> dict | None:
    """Resolve a @handle to user info (including rest_id)."""
    screen_name = screen_name.lstrip("@")
    variables = {
        "screen_name": screen_name,
        "withSafetyModeUserFields": True,
    }
    data = _graphql_request("UserByScreenName", variables)
    user_data = data.get("data", {}).get("user", {}).get("result", {})
    if not user_data:
        return None
    legacy = user_data.get("legacy", {})
    return {
        "id": user_data.get("rest_id", ""),
        "username": legacy.get("screen_name", ""),
        "name": legacy.get("name", ""),
        "bio": legacy.get("description", ""),
        "followers": legacy.get("followers_count", 0),
        "following": legacy.get("friends_count", 0),
    }


def get_user_tweets(handle: str, count: int = 10) -> list[dict]:
    """Fetch recent tweets for a user by @handle."""
    user = get_user_by_screen_name(handle)
    if not user or not user.get("id"):
        raise RuntimeError(f"User @{handle.lstrip('@')} not found.")
    variables = {
        "userId": user["id"],
        "count": count,
        "includePromotedContent": False,
        "withQuickPromoteEligibilityTweetFields": False,
        "withVoice": True,
        "withV2Timeline": True,
    }
    data = _graphql_request("UserTweets", variables)
    return _extract_timeline_tweets(data)[:count]


def get_mentions(username: str, count: int = 10) -> list[dict]:
    """Fetch recent mentions of @username via search."""
    return search(f"to:{username.lstrip('@')}", count=count)


def whoami() -> dict:
    """Verify cookie auth and return the authenticated user's info.

    Uses X's REST endpoint (not GraphQL) as a simple auth check.
    """
    cookies = get_read_cookies()
    headers = _build_headers(cookies)
    resp = requests.get(
        "https://api.x.com/1.1/account/verify_credentials.json",
        headers=headers,
        timeout=10,
    )
    if resp.status_code == 401:
        clear_cached_cookies()
        raise RuntimeError(
            "X session expired. Log into x.com in your browser and try again."
        )
    if resp.status_code != 200:
        raise RuntimeError(f"whoami failed with status {resp.status_code}")
    data = resp.json()
    return {
        "id": str(data.get("id", "")),
        "username": data.get("screen_name", ""),
        "name": data.get("name", ""),
        "bio": data.get("description", ""),
        "followers": data.get("followers_count", 0),
        "following": data.get("friends_count", 0),
    }


def _expand_dm_text(msg_data: dict) -> str:
    """Replace t.co links with expanded URLs in DM text."""
    text = msg_data.get("text", "")
    for url_entity in msg_data.get("entities", {}).get("urls", []):
        short = url_entity.get("url", "")
        expanded = url_entity.get("expanded_url", short)
        if short:
            text = text.replace(short, expanded)
    return text


def _parse_dm_inbox(data: dict) -> list[dict]:
    """Parse the v1.1 DM inbox response into per-conversation last messages.

    Returns one entry per conversation (the most recent message), sorted
    by timestamp descending.
    """
    inbox = data.get("inbox_initial_state", {})
    users = inbox.get("users", {})
    entries = inbox.get("entries", [])
    conversations = inbox.get("conversations", {})

    # Identify the authenticated user from conversations
    me_id = None
    for conv in conversations.values():
        participants = conv.get("participants", [])
        if len(participants) == 2:
            # We appear in every conversation — pick the common ID
            ids = {p.get("user_id") for p in participants}
            if me_id is None:
                me_id = ids
            else:
                me_id &= ids
    me_id = me_id.pop() if me_id and len(me_id) == 1 else None

    # Track the latest message per conversation
    latest: dict[str, dict] = {}
    for entry in entries:
        msg = entry.get("message", {})
        msg_data = msg.get("message_data", {})
        if not msg_data:
            continue
        conv_id = msg.get("conversation_id", "")
        ts = int(msg.get("time", "0") or "0")
        if conv_id in latest and latest[conv_id]["_ts"] >= ts:
            continue

        sender_id = msg_data.get("sender_id", "")
        recipient_id = msg_data.get("recipient_id", "")
        sender = users.get(sender_id, {})

        # The "other person" is whoever isn't me
        if me_id:
            other_id = recipient_id if sender_id == me_id else sender_id
        else:
            other_id = sender_id
        other = users.get(other_id, {})

        text = _expand_dm_text(msg_data)

        latest[conv_id] = {
            "other_username": other.get("screen_name", "unknown"),
            "other_name": other.get("name", ""),
            "sender_username": sender.get("screen_name", "unknown"),
            "text": text,
            "created_at": str(ts),
            "conversation_id": conv_id,
            "_ts": ts,
        }

    # Sort by timestamp descending (newest first)
    result = sorted(latest.values(), key=lambda m: m["_ts"], reverse=True)
    for m in result:
        del m["_ts"]
    return result


def get_dm_inbox(count: int = 10) -> list[dict]:
    """Fetch recent DMs via the v1.1 REST endpoint using browser cookies."""
    cookies = get_read_cookies()
    headers = _build_headers(cookies)
    resp = requests.get(
        "https://api.x.com/1.1/dm/inbox_initial_state.json",
        headers=headers,
        timeout=15,
    )
    if resp.status_code == 401:
        clear_cached_cookies()
        cookies = get_read_cookies()
        headers = _build_headers(cookies)
        resp = requests.get(
            "https://api.x.com/1.1/dm/inbox_initial_state.json",
            headers=headers,
            timeout=15,
        )
        if resp.status_code == 401:
            raise RuntimeError(
                "X session expired. Log into x.com in your browser and try again."
            )
    if resp.status_code == 429:
        raise RuntimeError("Rate limited by X. Wait a few minutes and try again.")
    if resp.status_code != 200:
        raise RuntimeError(f"DM inbox failed with status {resp.status_code}")
    return _parse_dm_inbox(resp.json())[:count]
