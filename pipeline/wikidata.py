"""Wikidata links each show's IMDb id to its exact Rotten Tomatoes and Metacritic pages,
so a show isn't scored from a different show (or film) that happens to share its name."""
import time

from .util import days_since, log, now_iso, session

ENDPOINT = "https://query.wikidata.org/sparql"
RECHECK_DAYS = 45


def _run(ids):
    values = " ".join('"' + i.replace('"', "") + '"' for i in ids)
    query = f"""SELECT ?imdb ?rt ?mc WHERE {{
      VALUES ?imdb {{ {values} }}
      ?item wdt:P345 ?imdb .
      OPTIONAL {{ ?item wdt:P1258 ?rt . }}
      OPTIONAL {{ ?item wdt:P1712 ?mc . }}
    }}"""
    r = session.get(
        ENDPOINT,
        params={"query": query, "format": "json"},
        headers={"Accept": "application/sparql-results+json", "User-Agent": "tv-shelf/1.0 (personal watchlist site)"},
        timeout=90,
    )
    r.raise_for_status()
    return r.json()["results"]["bindings"]


def _tv_path(value):
    """Keep only series pages: 'tv/severance' (not 'm/...' films or 'tv/x/s01' seasons)."""
    v = (value or "").strip().strip("/")
    for prefix in ("https://www.rottentomatoes.com/", "https://www.metacritic.com/"):
        if v.startswith(prefix):
            v = v[len(prefix):]
    parts = v.split("/")
    if len(parts) == 2 and parts[0] == "tv" and parts[1]:
        return v
    return None


def lookup(imdb_ids, cache: dict) -> dict:
    """Fill cache[imdb_id] = {"rt": "tv/slug"|None, "mc": "tv/slug"|None, "checked"} where needed."""
    todo = [i for i in imdb_ids if i and days_since((cache.get(i) or {}).get("checked")) >= RECHECK_DAYS]
    if not todo:
        return cache
    log(f"Wikidata: looking up {len(todo)} shows")
    for n in range(0, len(todo), 100):
        batch = todo[n : n + 100]
        try:
            rows = _run(batch)
        except Exception as e:
            log(f"  Wikidata lookup failed ({type(e).__name__}: {str(e)[:120]}); will retry next run")
            return cache
        found = {}
        for row in rows:
            entry = found.setdefault(row["imdb"]["value"], {})
            if "rt" in row and not entry.get("rt"):
                entry["rt"] = _tv_path(row["rt"]["value"])
            if "mc" in row and not entry.get("mc"):
                entry["mc"] = _tv_path(row["mc"]["value"])
        for i in batch:
            cache[i] = {"rt": None, "mc": None, **found.get(i, {}), "checked": now_iso()}
        time.sleep(1)
    return cache
