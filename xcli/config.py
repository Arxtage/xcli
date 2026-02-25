import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".xcli"
CONFIG_FILE = CONFIG_DIR / "config.json"

REQUIRED_KEYS = ["consumer_key", "consumer_secret", "access_token", "access_token_secret"]


def save_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2))
    CONFIG_FILE.chmod(0o600)


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        raise FileNotFoundError("Run 'xcli setup' first.")
    config = json.loads(CONFIG_FILE.read_text())
    missing = [k for k in REQUIRED_KEYS if not config.get(k)]
    if missing:
        raise ValueError(
            f"Config is missing: {', '.join(missing)}. Run 'xcli setup' again."
        )
    return config
