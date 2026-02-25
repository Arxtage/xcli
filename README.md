# xcli

A simple CLI tool to post to X from your terminal via the X API v2.

## Installation

```bash
pip install .
```

## Setup

You'll need OAuth 1.0a credentials from the [X Developer Portal](https://developer.x.com/). Create an app in the portal and grab the following four tokens:

- **Consumer Key** / **Consumer Secret** — identify your app
- **Access Token** / **Access Token Secret** — grant access to a specific user account

Then run:

```bash
xcli setup
```

This prompts for your credentials, verifies them against the API, and saves them to `~/.xcli/config.json`.

## Usage

Post to X:

```bash
xcli post "Hello from the terminal!"
```

Pipe text from stdin:

```bash
echo "Hello from a pipe!" | xcli post -
```

## License

MIT
