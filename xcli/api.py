import mimetypes
import os
import time

import requests
from requests_oauthlib import OAuth1

BASE_URL = "https://api.x.com/2"
UPLOAD_URL = "https://upload.twitter.com/1.1/media/upload.json"

SIMPLE_UPLOAD_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB chunks

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov"}
GIF_EXTENSIONS = {".gif"}
ALLOWED_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS | GIF_EXTENSIONS


def _make_auth(config: dict) -> OAuth1:
    return OAuth1(
        config["consumer_key"],
        config["consumer_secret"],
        config["access_token"],
        config["access_token_secret"],
    )


def verify_credentials(config: dict) -> dict:
    """Verify credentials and return {"id": ..., "username": ...}."""
    resp = requests.get(
        f"{BASE_URL}/users/me",
        params={"user.fields": "id,username"},
        auth=_make_auth(config),
        timeout=10,
    )
    if resp.status_code == 401:
        raise PermissionError("Authentication failed. Check your API keys.")
    if resp.status_code == 403:
        raise PermissionError("Your app may lack the required permissions.")
    resp.raise_for_status()
    data = resp.json()["data"]
    return {"id": data["id"], "username": data["username"]}


def post_tweet(
    config: dict,
    text: str,
    media_ids: list[str] | None = None,
    reply_to_id: str | None = None,
    quote_tweet_id: str | None = None,
) -> dict:
    """Post a tweet and return the response data (id, text)."""
    payload: dict = {"text": text}
    if media_ids:
        payload["media"] = {"media_ids": media_ids}
    if reply_to_id:
        payload["reply"] = {"in_reply_to_tweet_id": reply_to_id}
    if quote_tweet_id:
        payload["quote_tweet_id"] = quote_tweet_id

    resp = requests.post(
        f"{BASE_URL}/tweets",
        json=payload,
        auth=_make_auth(config),
        timeout=10,
    )
    if resp.status_code == 401:
        raise PermissionError("Authentication failed. Check your API keys.")
    if resp.status_code == 403:
        raise PermissionError("Your app may lack write permissions.")
    resp.raise_for_status()
    return resp.json()["data"]


def upload_media(config: dict, file_path: str) -> str:
    """Upload a media file and return the media_id string."""
    file_path = os.path.abspath(file_path)
    file_size = os.path.getsize(file_path)
    ext = os.path.splitext(file_path)[1].lower()
    media_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"

    if ext in VIDEO_EXTENSIONS:
        media_category = "tweet_video"
    elif ext in GIF_EXTENSIONS:
        media_category = "tweet_gif"
    else:
        media_category = "tweet_image"

    if media_category == "tweet_image" and file_size <= SIMPLE_UPLOAD_MAX_BYTES:
        return _simple_upload(config, file_path, media_type, media_category)
    return _chunked_upload(config, file_path, file_size, media_type, media_category)


def _simple_upload(
    config: dict, file_path: str, media_type: str, media_category: str
) -> str:
    """Simple single-request upload for small images."""
    auth = _make_auth(config)
    with open(file_path, "rb") as f:
        resp = requests.post(
            UPLOAD_URL,
            files={"media": (os.path.basename(file_path), f, media_type)},
            data={"media_category": media_category},
            auth=auth,
            timeout=60,
        )
    resp.raise_for_status()
    return resp.json()["media_id_string"]


def _chunked_upload(
    config: dict,
    file_path: str,
    file_size: int,
    media_type: str,
    media_category: str,
) -> str:
    """Chunked upload (INIT → APPEND → FINALIZE → poll STATUS) for videos and large files."""
    auth = _make_auth(config)

    # INIT
    resp = requests.post(
        f"{UPLOAD_URL}/initialize",
        json={
            "total_bytes": file_size,
            "media_type": media_type,
            "media_category": media_category,
        },
        auth=auth,
        timeout=30,
    )
    resp.raise_for_status()
    media_id = resp.json()["id"]

    # APPEND
    with open(file_path, "rb") as f:
        segment_index = 0
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            resp = requests.post(
                f"{UPLOAD_URL}/{media_id}/append",
                files={"file": (os.path.basename(file_path), chunk, media_type)},
                data={"segment_index": segment_index},
                auth=auth,
                timeout=120,
            )
            resp.raise_for_status()
            segment_index += 1

    # FINALIZE
    resp = requests.post(
        f"{UPLOAD_URL}/{media_id}/finalize",
        auth=auth,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    # Poll STATUS if processing
    processing_info = data.get("processing_info")
    while processing_info and processing_info.get("state") != "succeeded":
        if processing_info.get("state") == "failed":
            error = processing_info.get("error", {}).get("message", "Unknown error")
            raise RuntimeError(f"Media processing failed: {error}")
        wait_secs = processing_info.get("check_after_secs", 5)
        time.sleep(wait_secs)
        resp = requests.get(
            UPLOAD_URL,
            params={"media_id": media_id},
            auth=auth,
            timeout=30,
        )
        resp.raise_for_status()
        processing_info = resp.json().get("processing_info")

    return media_id


def get_dm_events(config: dict, max_results: int = 20) -> list[dict]:
    """Fetch recent DM events via the v2 API (requires DM permissions).

    Returns a list of dicts with keys:
        other_username, other_name, sender_username, text, created_at, conversation_id
    """
    auth = _make_auth(config)

    resp = requests.get(
        f"{BASE_URL}/dm_events",
        params={
            "dm_event.fields": "id,text,created_at,sender_id,dm_conversation_id,event_type",
            "max_results": min(max_results, 100),
            "expansions": "sender_id,participant_ids",
            "user.fields": "username,name",
            "event_types": "MessageCreate",
        },
        auth=auth,
        timeout=15,
    )
    if resp.status_code == 403:
        raise PermissionError(
            "Your app lacks DM permissions. In the X Developer Portal, set "
            "app permissions to 'Read and write and Direct message', regenerate "
            "your access tokens, then run 'xcli setup' again."
        )
    if resp.status_code == 401:
        raise PermissionError("Authentication failed. Check your API keys.")
    resp.raise_for_status()
    data = resp.json()

    # Build user lookup from includes
    users_by_id: dict[str, dict] = {}
    for u in data.get("includes", {}).get("users", []):
        users_by_id[u["id"]] = {"username": u.get("username", ""), "name": u.get("name", "")}

    # Get authenticated user's ID
    my_id = config.get("user_id", "")

    # Group events by conversation, keep only the latest per conversation
    latest: dict[str, dict] = {}
    for event in data.get("data", []):
        conv_id = event.get("dm_conversation_id", "")
        if conv_id in latest:
            continue  # events come newest-first, so first seen = latest

        sender_id = event.get("sender_id", "")
        sender = users_by_id.get(sender_id, {"username": "unknown", "name": ""})

        # Determine the "other" person in the conversation
        # Convention: conversation IDs for 1:1 are "{lower_id}-{higher_id}"
        parts = conv_id.split("-")
        other_id = next((p for p in parts if p != my_id), sender_id)
        other = users_by_id.get(other_id, {"username": other_id, "name": ""})

        latest[conv_id] = {
            "other_username": other["username"],
            "other_name": other["name"],
            "sender_username": sender["username"],
            "text": event.get("text", ""),
            "created_at": event.get("created_at", ""),
            "conversation_id": conv_id,
        }

    return list(latest.values())
