import requests
from requests_oauthlib import OAuth1

BASE_URL = "https://api.x.com/2"


def _make_auth(config: dict) -> OAuth1:
    return OAuth1(
        config["api_key"],
        config["api_secret"],
        config["access_token"],
        config["access_token_secret"],
    )


def verify_credentials(config: dict) -> str:
    """Verify credentials and return the username."""
    resp = requests.get(f"{BASE_URL}/users/me", auth=_make_auth(config), timeout=10)
    if resp.status_code == 401:
        raise PermissionError("Authentication failed. Check your API keys.")
    if resp.status_code == 403:
        raise PermissionError("Your app may lack the required permissions.")
    resp.raise_for_status()
    return resp.json()["data"]["username"]


def post_tweet(config: dict, text: str) -> dict:
    """Post a tweet and return the response data (id, text)."""
    resp = requests.post(
        f"{BASE_URL}/tweets",
        json={"text": text},
        auth=_make_auth(config),
        timeout=10,
    )
    if resp.status_code == 401:
        raise PermissionError("Authentication failed. Check your API keys.")
    if resp.status_code == 403:
        raise PermissionError("Your app may lack write permissions.")
    resp.raise_for_status()
    return resp.json()["data"]
