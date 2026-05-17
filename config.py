import json
import os
from pathlib import Path

SETTINGS_DIR = Path.home() / ".obs-pygui"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"

DEFAULT_SETTINGS = {
    "display_scenes": True,
    "display_sources": True,
    "display_audio": True,
    "display_stats": True,
    "display_media": True,
    "scan_timeout_ms": 200,
    "connect_timeout_ms": 5000,
    "auto_reconnect": True,
}


def _ensure_dir():
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)


def load() -> dict:
    _ensure_dir()
    if not SETTINGS_FILE.exists():
        return dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged = dict(DEFAULT_SETTINGS)
        merged.update(data)
        return merged
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_SETTINGS)


def save(settings: dict) -> None:
    _ensure_dir()
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except OSError:
        pass
