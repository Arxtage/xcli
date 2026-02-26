# xcli

A CLI tool to post and read on X from your terminal.

- **Posting** uses the official X API v2 (OAuth 1.0a) — requires API keys
- **Reading** uses your browser's login session (cookies) — free, no API key needed

## Installation

```bash
pip install .
```

## Setup

### Reading (browser cookies — automatic)

Just log into [x.com](https://x.com) in Arc, Chrome, Safari, or Firefox. xcli automatically extracts your session cookies for read operations. No configuration needed.

Verify it works:

```bash
xcli whoami
```

### Posting (API credentials — required for `post` and `thread`)

You'll need OAuth 1.0a credentials from the [X Developer Portal](https://developer.x.com/). Create an app and grab:

- **Consumer Key** / **Consumer Secret** — identify your app
- **Access Token** / **Access Token Secret** — grant access to a specific user account

Then run:

```bash
xcli setup
```

This prompts for your credentials, verifies them, and saves them to `~/.xcli/config.json`.

## Usage

### Read Commands

All read commands use browser cookies — no API setup required.

#### Home Timeline

```bash
xcli home
xcli home -n 10
```

Example output:

```
  1. @paulg
     For the foreseeable future, everything about starting a startup...
     3 replies  631 likes  39 reposts — x.com/i/status/123

  2. RT by @armantsaturian
     @svlevine: At Physical Intelligence, we teamed up with...
     0 replies  428 likes  43 reposts — x.com/i/status/456

  3. @vaborsh
     Nano Banana 2 is our new faster and better SOTA image...
     64 replies  1114 likes  71 reposts — x.com/i/status/789
```

Retweets are shown with `RT by @handle` followed by the original author and content.

#### Search

```bash
xcli search "python"
xcli search "from:elonmusk" -n 5
```

#### Read a Tweet

```bash
xcli read https://x.com/user/status/1234567890
xcli read 1234567890
```

#### Bookmarks

```bash
xcli bookmarks
xcli bookmarks -n 20
```

#### Likes

```bash
xcli likes
xcli likes -n 20
```

#### Followers / Following

```bash
xcli followers
xcli followers -n 50
xcli following
xcli following -n 50
```

#### Who Am I

```bash
xcli whoami
```

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

### Quote Tweet

```bash
xcli post "My take on this" -q https://x.com/user/status/1234567890
xcli post "Interesting" -q 1234567890
```

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

### Check

See recent activity — posts, mentions, and DMs. All use browser cookies (free, no API keys needed).

```bash
xcli check
```

Show only replies and mentions:

```bash
xcli check --replies
```

Show only DMs:

```bash
xcli check --dms
```

Example output:

```
--- Recent Posts ---
  1. @you
     Hello from the terminal!
     2 replies  5 likes  1 reposts — x.com/i/status/123

--- Recent Mentions ---
  @alice: @you love this tool!

--- Recent DMs ---
  @charlie (2026-02-26): Hey, wanted to ask about your project
```

## License

MIT
