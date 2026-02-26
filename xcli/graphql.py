"""X GraphQL client for free, cookie-authenticated read operations."""

import re
import uuid

import requests

from xcli.cookies import clear_cached_cookies, get_read_cookies

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


def _graphql_request(
    operation: str, variables: dict, features: dict | None = None
) -> dict:
    """Make a GET request to X's GraphQL API.

    Tries each query ID for the operation; retries with next ID on 404.
    On 401, clears cached cookies and retries once with fresh cookies.
    """
    import json as json_mod

    if features is None:
        features = DEFAULT_FEATURES

    query_ids = QUERY_IDS.get(operation)
    if not query_ids:
        raise ValueError(f"Unknown GraphQL operation: {operation}")

    cookies = get_read_cookies()

    params = {
        "variables": json_mod.dumps(variables),
        "features": json_mod.dumps(features),
    }

    last_error = None
    for qid in query_ids:
        url = f"{GRAPHQL_BASE}/{qid}/{operation}"
        headers = _build_headers(cookies)
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=15)
        except requests.RequestException as e:
            last_error = e
            continue

        if resp.status_code == 404:
            last_error = RuntimeError(f"Query ID {qid} returned 404")
            continue

        if resp.status_code == 401:
            # Cookies may have expired — clear cache and retry with fresh ones
            clear_cached_cookies()
            cookies = get_read_cookies()
            headers = _build_headers(cookies)
            resp = requests.get(url, params=params, headers=headers, timeout=15)
            if resp.status_code == 401:
                raise RuntimeError(
                    "X session expired. Log into x.com in your browser and try again."
                )

        if resp.status_code == 429:
            raise RuntimeError("Rate limited by X. Wait a few minutes and try again.")

        if resp.status_code != 200:
            last_error = RuntimeError(
                f"GraphQL {operation} returned {resp.status_code}: {resp.text[:200]}"
            )
            continue

        return resp.json()

    raise last_error or RuntimeError(f"All query IDs failed for {operation}")


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


def search(query: str, count: int = 10) -> list[dict]:
    """Search tweets via GraphQL."""
    variables = {
        "rawQuery": query,
        "count": count,
        "querySource": "typed_query",
        "product": "Latest",
    }
    data = _graphql_request("SearchTimeline", variables)
    return _extract_timeline_tweets(data)[:count]


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
