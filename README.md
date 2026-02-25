# xcli

A simple CLI tool to post to X from your terminal via the X API v2.

## Installation

```bash
pip install .
```

## Setup

You'll need X API credentials (API Key, API Secret, Access Token, Access Token Secret) from the [X Developer Portal](https://developer.x.com/).

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
