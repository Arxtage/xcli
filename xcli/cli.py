import os
import sys

import click

from xcli.api import (
    ALLOWED_EXTENSIONS,
    GIF_EXTENSIONS,
    IMAGE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    post_tweet,
    upload_media,
    verify_credentials,
)
from xcli.config import load_config, save_config
from xcli import graphql


@click.group()
def cli():
    """A CLI tool to post and read on X from your terminal."""


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def _display_tweet_list(tweets: list[dict]) -> None:
    """Format and display a list of tweets."""
    if not tweets:
        click.echo("  No tweets found.")
        return
    for i, t in enumerate(tweets, 1):
        author = t.get("author", {})
        handle = f"@{author['username']}" if author.get("username") else ""

        if t.get("retweetedBy"):
            click.echo(f"  {i}. RT by @{t['retweetedBy']}")
            click.echo(f"     {handle}: {t['text']}")
        else:
            click.echo(f"  {i}. {handle}")
            click.echo(f"     {t['text']}")

        link = f"x.com/i/status/{t['id']}" if t.get("id") else ""
        click.echo(
            f"     {t.get('replyCount', 0)} replies  "
            f"{t.get('likeCount', 0)} likes  "
            f"{t.get('retweetCount', 0)} reposts"
            + (f" — {link}" if link else "")
        )
        click.echo()


def _display_single_tweet(tweet: dict) -> None:
    """Format and display a single tweet in detail."""
    author = tweet.get("author", {})
    handle = f"@{author['username']}" if author.get("username") else ""
    name = author.get("name", "")

    if tweet.get("retweetedBy"):
        click.echo(f"RT by @{tweet['retweetedBy']}")
    click.echo(f"{name} ({handle})")
    click.echo(f"\n  {tweet['text']}\n")
    click.echo(
        f"  {tweet.get('replyCount', 0)} replies  "
        f"{tweet.get('likeCount', 0)} likes  "
        f"{tweet.get('retweetCount', 0)} reposts  "
        f"{tweet.get('viewCount', 0)} views"
    )
    if tweet.get("createdAt"):
        click.echo(f"  Posted: {tweet['createdAt']}")
    if tweet.get("id"):
        click.echo(f"  https://x.com/i/status/{tweet['id']}")


def _display_user_list(users: list[dict]) -> None:
    """Format and display a list of users."""
    if not users:
        click.echo("  No users found.")
        return
    for u in users:
        click.echo(f"  @{u.get('username', '')} — {u.get('name', '')}")
        if u.get("bio"):
            click.echo(f"    {u['bio'][:120]}")
        click.echo(
            f"    Followers: {u.get('followers', 0)}  "
            f"Following: {u.get('following', 0)}"
        )


# ---------------------------------------------------------------------------
# Setup (unchanged)
# ---------------------------------------------------------------------------


@cli.command()
def setup():
    """Configure your X API credentials (for posting)."""
    click.echo("Enter your X API credentials.\n")
    consumer_key = click.prompt("Consumer Key", hide_input=True)
    consumer_secret = click.prompt("Consumer Secret", hide_input=True)
    access_token = click.prompt("Access Token", hide_input=True)
    access_token_secret = click.prompt("Access Token Secret", hide_input=True)

    config = {
        "consumer_key": consumer_key,
        "consumer_secret": consumer_secret,
        "access_token": access_token,
        "access_token_secret": access_token_secret,
    }

    click.echo("\nVerifying credentials...")
    try:
        user_info = verify_credentials(config)
    except PermissionError as e:
        raise click.ClickException(str(e))
    except Exception as e:
        raise click.ClickException(f"Verification failed: {e}")

    config["user_id"] = user_info["id"]
    config["username"] = user_info["username"]
    save_config(config)
    click.echo(f"Authenticated as @{user_info['username']}. Credentials saved.")


# ---------------------------------------------------------------------------
# Post + Thread (unchanged)
# ---------------------------------------------------------------------------


def _validate_media_files(media: tuple[str, ...]) -> None:
    """Validate media file paths, extensions, and combination rules."""
    for path in media:
        if not os.path.isfile(path):
            raise click.ClickException(f"File not found: {path}")
        ext = os.path.splitext(path)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise click.ClickException(
                f"Unsupported file type '{ext}'. "
                f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            )

    video_or_gif = [
        p for p in media
        if os.path.splitext(p)[1].lower() in VIDEO_EXTENSIONS | GIF_EXTENSIONS
    ]
    images = [
        p for p in media
        if os.path.splitext(p)[1].lower() in IMAGE_EXTENSIONS
    ]

    if video_or_gif and len(media) > 1:
        raise click.ClickException("Only 1 video or GIF allowed per post (no other media).")
    if images and len(images) > 4:
        raise click.ClickException("Maximum 4 images per post.")


def _upload_media_files(config: dict, media: tuple[str, ...] | list[str]) -> list[str]:
    """Upload media files and return list of media_ids."""
    media_ids = []
    for path in media:
        click.echo(f"Uploading {os.path.basename(path)}...")
        media_id = upload_media(config, path)
        media_ids.append(media_id)
        click.echo(f"  Uploaded (ID: {media_id})")
    return media_ids


@cli.command()
@click.argument("text")
@click.option(
    "-m", "--media",
    multiple=True,
    type=click.Path(),
    help="Attach media file (image/video/GIF). Repeatable, up to 4 images or 1 video/GIF.",
)
@click.option(
    "-q", "--quote",
    default=None,
    help="Quote tweet by URL or ID.",
)
def post(text: str, media: tuple[str, ...], quote: str | None):
    """Post to X. Use '-' to read from stdin."""
    if text == "-":
        text = sys.stdin.read().strip()

    if not text:
        raise click.ClickException("Post text cannot be empty.")

    length = len(text)
    if length > 280:
        raise click.ClickException(
            f"Post is {length} characters. Maximum is 280."
        )

    if media:
        _validate_media_files(media)

    try:
        config = load_config()
    except (FileNotFoundError, ValueError) as e:
        raise click.ClickException(str(e))

    quote_id = None
    if quote:
        import re
        match = re.search(r"/status/(\d+)", quote)
        quote_id = match.group(1) if match else quote

    try:
        media_ids = _upload_media_files(config, media) if media else None
        data = post_tweet(config, text, media_ids=media_ids, quote_tweet_id=quote_id)
    except PermissionError as e:
        raise click.ClickException(str(e))
    except Exception as e:
        raise click.ClickException(f"Failed to post: {e}")

    post_id = data["id"]
    click.echo(f"Posted! ID: {post_id}")
    click.echo(f"https://x.com/i/status/{post_id}")


def _parse_thread_file(content: str) -> list[dict]:
    """Parse thread file format into list of {text, media} dicts.

    Tweets are separated by '---' on its own line.
    Media is attached via '@media: path' lines.
    """
    tweets = []
    blocks = content.split("\n---\n")
    for i, block in enumerate(blocks, 1):
        text_lines = []
        media_files = []
        for line in block.strip().splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("@media:"):
                media_path = stripped[len("@media:"):].strip()
                media_files.append(media_path)
            else:
                text_lines.append(line)
        text = "\n".join(text_lines).strip()
        if not text:
            raise click.ClickException(f"Tweet #{i} in thread file has no text.")
        tweets.append({"text": text, "media": media_files})
    return tweets


@cli.command()
@click.argument("tweets", nargs=-1)
@click.option(
    "--from", "from_file",
    type=click.Path(),
    help="Read thread from file (use '-' for stdin). Supports @media: directives.",
)
def thread(tweets: tuple[str, ...], from_file: str | None):
    """Post a thread (chain of replies).

    Inline mode:  xcli thread "First" "Second" "Third"

    File mode:    xcli thread --from thread.txt
    """
    if from_file and tweets:
        raise click.ClickException("Use either inline text arguments or --from, not both.")

    if from_file:
        if from_file == "-":
            content = sys.stdin.read()
        else:
            if not os.path.isfile(from_file):
                raise click.ClickException(f"File not found: {from_file}")
            with open(from_file) as f:
                content = f.read()
        tweet_entries = _parse_thread_file(content)
    elif tweets:
        tweet_entries = [{"text": t, "media": []} for t in tweets]
    else:
        raise click.ClickException("Provide tweet texts as arguments or use --from.")

    if len(tweet_entries) < 2:
        raise click.ClickException("A thread must have at least 2 tweets.")

    # Validate all tweets before posting any
    for i, entry in enumerate(tweet_entries, 1):
        length = len(entry["text"])
        if length > 280:
            raise click.ClickException(
                f"Tweet #{i} is {length} characters. Maximum is 280."
            )
        if entry["media"]:
            _validate_media_files(tuple(entry["media"]))

    try:
        config = load_config()
    except (FileNotFoundError, ValueError) as e:
        raise click.ClickException(str(e))

    prev_id = None
    for i, entry in enumerate(tweet_entries, 1):
        try:
            media_ids = None
            if entry["media"]:
                click.echo(f"[{i}/{len(tweet_entries)}] Uploading media...")
                media_ids = _upload_media_files(config, entry["media"])

            data = post_tweet(
                config,
                entry["text"],
                media_ids=media_ids,
                reply_to_id=prev_id,
            )
            prev_id = data["id"]
            click.echo(f"[{i}/{len(tweet_entries)}] https://x.com/i/status/{prev_id}")
        except PermissionError as e:
            raise click.ClickException(str(e))
        except click.ClickException:
            raise
        except Exception as e:
            raise click.ClickException(
                f"Failed to post tweet #{i}: {e}"
            )

    click.echo(f"Thread posted! ({len(tweet_entries)} tweets)")


# ---------------------------------------------------------------------------
# Check (all reading via browser cookies — GraphQL + v1.1 REST)
# ---------------------------------------------------------------------------


def _get_username() -> str:
    """Get username from config or GraphQL whoami."""
    try:
        config = load_config()
        if config.get("username"):
            return config["username"]
    except (FileNotFoundError, ValueError):
        pass
    # Fall back to GraphQL whoami
    user = graphql.whoami()
    return user["username"]


def _display_replies_graphql(username: str) -> None:
    """Display recent posts and mentions via GraphQL."""
    click.echo("--- Recent Posts ---")
    try:
        tweets = graphql.get_user_tweets(username, count=5)
        if not tweets:
            click.echo("  No recent posts found.\n")
        else:
            for t in tweets:
                click.echo(f"  {t['text']}")
                click.echo(
                    f"    Replies: {t.get('replyCount', 0)}  "
                    f"Likes: {t.get('likeCount', 0)}  "
                    f"Reposts: {t.get('retweetCount', 0)}"
                )
            click.echo()
    except Exception as e:
        click.echo(f"  (GraphQL failed: {e})\n")

    click.echo("--- Recent Mentions ---")
    try:
        mentions = graphql.get_mentions(username, count=10)
        if not mentions:
            click.echo("  No recent mentions found.\n")
        else:
            for t in mentions:
                author = t.get("author", {})
                handle = f"@{author['username']}" if author.get("username") else ""
                click.echo(f"  {handle}: {t['text']}")
            click.echo()
    except Exception as e:
        click.echo(f"  (GraphQL failed: {e})\n")


def _display_dms() -> None:
    """Display recent DM messages via browser cookies."""
    click.echo("--- Recent DMs ---")
    try:
        messages = graphql.get_dm_inbox(count=10)
    except Exception as e:
        click.echo(f"  (Failed to fetch DMs: {e})\n")
        return
    if not messages:
        click.echo("  No recent DMs found.\n")
    else:
        from datetime import datetime, timezone

        for msg in messages:
            raw_ts = msg.get("created_at", "")
            try:
                ts = datetime.fromtimestamp(
                    int(raw_ts) / 1000, tz=timezone.utc
                ).strftime("%Y-%m-%d")
            except (ValueError, OSError):
                ts = raw_ts[:10]
            other = msg.get("other_username", "unknown")
            sender = msg.get("sender_username", "")
            prefix = "you" if sender != other else f"@{sender}"
            click.echo(f"  @{other} ({ts}) {prefix}: {msg['text']}")
        click.echo()


@cli.command()
def mentions():
    """Show your recent posts and mentions."""
    try:
        username = _get_username()
    except Exception as e:
        raise click.ClickException(f"Failed to get user info: {e}")
    _display_replies_graphql(username)


@cli.command()
def dms():
    """Show your recent DMs."""
    _display_dms()


# ---------------------------------------------------------------------------
# New read commands (all use GraphQL + browser cookies)
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("username")
@click.option("-n", "--count", default=10, help="Number of tweets.")
def user(username: str, count: int):
    """Fetch tweets from a specific user by @handle."""
    try:
        tweets = graphql.get_user_tweets(username, count=count)
    except Exception as e:
        raise click.ClickException(str(e))
    _display_tweet_list(tweets)


@cli.command()
@click.argument("query")
@click.option("-n", "--count", default=10, help="Number of results.")
def search(query: str, count: int):
    """Search tweets on X."""
    try:
        tweets = graphql.search(query, count=count)
    except Exception as e:
        raise click.ClickException(str(e))
    _display_tweet_list(tweets)


@cli.command()
@click.option("-n", "--count", default=20, help="Number of tweets.")
def feed(count: int):
    """Show your home feed."""
    try:
        tweets = graphql.get_home_timeline(count=count)
    except Exception as e:
        raise click.ClickException(str(e))
    _display_tweet_list(tweets)


@cli.command()
@click.argument("tweet")
def read(tweet: str):
    """Read a single tweet by URL or ID."""
    try:
        result = graphql.read_tweet(tweet)
    except Exception as e:
        raise click.ClickException(str(e))
    if not result:
        raise click.ClickException("Tweet not found.")
    _display_single_tweet(result)


@cli.command()
@click.option("-n", "--count", default=10, help="Number of bookmarks.")
def bookmarks(count: int):
    """Show your bookmarked tweets."""
    try:
        tweets = graphql.get_bookmarks(count=count)
    except Exception as e:
        raise click.ClickException(str(e))
    _display_tweet_list(tweets)


@cli.command()
@click.option("-n", "--count", default=10, help="Number of liked tweets.")
def likes(count: int):
    """Show your liked tweets."""
    try:
        user = graphql.whoami()
    except Exception as e:
        raise click.ClickException(str(e))
    try:
        tweets = graphql.get_likes(user["id"], count=count)
    except Exception as e:
        raise click.ClickException(str(e))
    _display_tweet_list(tweets)


@cli.command()
@click.option("-n", "--count", default=20, help="Number of followers.")
def followers(count: int):
    """Show your followers."""
    try:
        user = graphql.whoami()
    except Exception as e:
        raise click.ClickException(str(e))
    try:
        users = graphql.get_followers(user["id"], count=count)
    except Exception as e:
        raise click.ClickException(str(e))
    _display_user_list(users)


@cli.command()
@click.option("-n", "--count", default=20, help="Number of accounts.")
def following(count: int):
    """Show accounts you follow."""
    try:
        user = graphql.whoami()
    except Exception as e:
        raise click.ClickException(str(e))
    try:
        users = graphql.get_following(user["id"], count=count)
    except Exception as e:
        raise click.ClickException(str(e))
    _display_user_list(users)


@cli.command()
def whoami():
    """Verify browser cookie auth and show your X profile."""
    try:
        user = graphql.whoami()
    except Exception as e:
        raise click.ClickException(str(e))
    click.echo(f"@{user['username']} — {user['name']}")
    if user.get("bio"):
        click.echo(f"  {user['bio']}")
    click.echo(
        f"  Followers: {user.get('followers', 0)}  "
        f"Following: {user.get('following', 0)}"
    )
