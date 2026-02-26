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

### Post

```bash
xcli post "Hello from the terminal!"
```

Pipe text from stdin:

```bash
echo "Hello from a pipe!" | xcli post -
```

### Media

Attach images (up to 4), or a single video/GIF:

```bash
xcli post "Check out this photo!" -m photo.jpg
xcli post "Multiple pics" -m a.jpg -m b.png -m c.jpg
xcli post "Watch this" -m video.mp4
```

Supported formats: `.jpg`, `.jpeg`, `.png`, `.webp`, `.gif`, `.mp4`, `.mov`

### Threads

Post a chain of replies using inline arguments:

```bash
xcli thread "First tweet" "Second tweet" "Third tweet"
```

Or from a file with optional media per tweet:

```bash
xcli thread --from thread.txt
cat thread.txt | xcli thread --from -
```

Thread file format — tweets separated by `---`, media attached with `@media:`:

```
First tweet with a photo
@media: photo.jpg
---
Second tweet, text only
---
Third tweet with a video
@media: clip.mp4
```

## License

MIT
