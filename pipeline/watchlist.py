"""Your watchlist: config/watchlist.json.

The web app writes this file directly (once you connect it to GitHub in its Settings), the
"Add a show" issue form writes it too, and you can edit it by hand. Shape:

{"shows": {
   "tmdb:95396": {"tmdb": 95396, "title": "Severance", "year": 2022, "added": "2026-10-06",
                  "interest": 2, "watched": null},
   "q:the bear": {"title": "The Bear", "added": "2026-10-06"}   # added by title; matched on the next build
}}

Keys never change once written, so the app's edits (interest, watched) always find their show.
"""
import json

from .util import CONFIG_DIR, norm

PATH = CONFIG_DIR / "watchlist.json"


def load() -> dict:
    try:
        data = json.loads(PATH.read_text(encoding="utf-8")) or {}
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    shows = data.get("shows") if isinstance(data.get("shows"), dict) else {}
    return {"shows": {k: v for k, v in shows.items() if isinstance(v, dict)}}


def save(data: dict):
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def title_key(title: str) -> str:
    return "q:" + norm(title)
