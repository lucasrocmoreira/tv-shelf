"""Apply an "Add a show" issue form to config/watchlist.json (run by .github/workflows/watchlist-edit.yml)."""
import os
import re

from . import watchlist
from .util import now_iso


def field(body, label):
    m = re.search(r"###\s*" + re.escape(label) + r"\s*\n+(.*?)(?=\n###|\Z)", body or "", re.S)
    v = (m.group(1).strip() if m else "")
    return "" if v in ("_No response_", "None") else v


def main():
    body = os.environ.get("ISSUE_BODY", "")
    title = field(body, "Show title")
    year = field(body, "First year (optional)")
    action = field(body, "What to do") or "Add to watchlist"
    wl = watchlist.load()
    if not title:
        result = "Nothing to do: no title given"
    else:
        key = watchlist.title_key(title)
        existing = [k for k, v in wl["shows"].items() if watchlist.title_key(v.get("title", "")) == key]
        if action.startswith("Remove"):
            for k in existing:
                del wl["shows"][k]
            result = f"Removed {title}" if existing else f"{title} wasn't on the list"
        elif action.startswith("Mark"):
            for k in existing:
                wl["shows"][k]["watched"] = now_iso()[:10]
            result = f"Marked {title} as watched" if existing else f"{title} wasn't on the list"
        elif existing:
            result = f"{title} is already on the list"
        else:
            entry = {"title": title, "added": now_iso()[:10], "interest": 0, "watched": None}
            if year.isdigit():
                entry["year"] = int(year)
            wl["shows"][key] = entry
            result = f"Added {title}"
    watchlist.save(wl)
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as f:
        f.write(f"result={result}\n")
    print(result)


if __name__ == "__main__":
    main()
