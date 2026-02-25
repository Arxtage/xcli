import sys

import click

from xcli.api import post_tweet, verify_credentials
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
        username = verify_credentials(config)
    except PermissionError as e:
        raise click.ClickException(str(e))
    except Exception as e:
        raise click.ClickException(f"Verification failed: {e}")

    save_config(config)
    click.echo(f"Authenticated as @{username}. Credentials saved.")


@cli.command()
@click.argument("text")
def post(text: str):
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

    try:
        config = load_config()
    except (FileNotFoundError, ValueError) as e:
        raise click.ClickException(str(e))

    try:
        data = post_tweet(config, text)
    except PermissionError as e:
        raise click.ClickException(str(e))
    except Exception as e:
        raise click.ClickException(f"Failed to post: {e}")

    post_id = data["id"]
    click.echo(f"Posted! ID: {post_id}")
    click.echo(f"https://x.com/i/status/{post_id}")
