import os
import sys

import click

from xcli.api import (
    ALLOWED_EXTENSIONS,
    GIF_EXTENSIONS,
    IMAGE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    get_dm_events,
    get_mentions,
    get_recent_tweets,
    post_tweet,
    upload_media,
    verify_credentials,
)
from xcli.config import load_config, save_config


@click.group()
def cli():
    """A simple CLI tool to post to X from your terminal."""


@cli.command()
def setup():
    """Configure your X API credentials."""
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
def post(text: str, media: tuple[str, ...]):
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

    try:
        media_ids = _upload_media_files(config, media) if media else None
        data = post_tweet(config, text, media_ids=media_ids)
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


def _ensure_user_id(config: dict) -> str:
    """Return cached user_id from config, or fetch and cache it."""
    if config.get("user_id"):
        return config["user_id"]
    try:
        user_info = verify_credentials(config)
    except PermissionError as e:
        raise click.ClickException(str(e))
    except Exception as e:
        raise click.ClickException(f"Failed to fetch user info: {e}")
    config["user_id"] = user_info["id"]
    config["username"] = user_info["username"]
    save_config(config)
    return user_info["id"]


def _display_replies(config: dict, user_id: str) -> None:
    """Display recent posts with metrics and recent mentions."""
    skip_msg = "(Skipped: your API tier may not support this endpoint)"

    tweets = get_recent_tweets(config, user_id)
    if tweets is None:
        click.echo(f"--- Recent Posts ---\n  {skip_msg}\n")
    else:
        click.echo("--- Recent Posts ---")
        if not tweets:
            click.echo("  No recent posts found.\n")
        else:
            for t in tweets:
                click.echo(f"  {t['text']}")
                m = t.get("public_metrics", {})
                click.echo(
                    f"    Replies: {m.get('reply_count', 0)}  "
                    f"Likes: {m.get('like_count', 0)}  "
                    f"Reposts: {m.get('retweet_count', 0)}"
                )
            click.echo()

    mentions = get_mentions(config, user_id)
    if mentions is None:
        click.echo(f"--- Recent Mentions ---\n  {skip_msg}\n")
    else:
        click.echo("--- Recent Mentions ---")
        if not mentions["tweets"]:
            click.echo("  No recent mentions found.\n")
        else:
            for t in mentions["tweets"]:
                username = mentions["users"].get(t.get("author_id"), "unknown")
                date = t.get("created_at", "")[:10]
                click.echo(f"  @{username} ({date}): {t['text']}")
            click.echo()


def _display_dms(config: dict) -> None:
    """Display recent DM messages."""
    skip_msg = "(Skipped: your API tier may not support this endpoint)"

    result = get_dm_events(config)
    if result is None:
        click.echo(f"--- Recent DMs ---\n  {skip_msg}\n")
    else:
        click.echo("--- Recent DMs ---")
        if not result["events"]:
            click.echo("  No recent DMs found.\n")
        else:
            for ev in result["events"]:
                username = result["users"].get(ev.get("sender_id"), "unknown")
                date = ev.get("created_at", "")[:10]
                text = ev.get("text", "")
                click.echo(f"  @{username} ({date}): {text}")
            click.echo()


@cli.command()
@click.option("--replies", is_flag=True, help="Show only replies and mentions.")
@click.option("--dms", is_flag=True, help="Show only DMs.")
def check(replies: bool, dms: bool):
    """Check recent replies, mentions, and DMs."""
    try:
        config = load_config()
    except (FileNotFoundError, ValueError) as e:
        raise click.ClickException(str(e))

    try:
        user_id = _ensure_user_id(config)
    except click.ClickException:
        raise
    except Exception as e:
        raise click.ClickException(f"Failed to get user info: {e}")

    show_all = not replies and not dms

    if show_all or replies:
        _display_replies(config, user_id)
    if show_all or dms:
        _display_dms(config)
