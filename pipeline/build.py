"""Build: read your watchlist, fetch show details and scores, write site/data.json.

Run locally:  TMDB_TOKEN=... python -m pipeline.build
Environment:  TMDB_TOKEN (required), WATCH_REGION (default US), MAX_SCORE_LOOKUPS (default 150).
"""
import os
import sys
import traceback

from . import imdb, scores, wikidata, watchlist
from .tmdb import TMDB, TMDBError, check
from .util import CACHE_DIR, SITE_DIR, days_since, load_json, log, now_iso, save_json

MAX_SCORE_LOOKUPS = int(os.environ.get("MAX_SCORE_LOOKUPS", "150"))
UNMATCHED_RETRY_DAYS = 3


def env(name):
    v = os.environ.get(name, "").strip()
    return v or None


def refresh_days(show):
    """Ongoing shows' scores move as seasons land; finished ones barely change."""
    return 7 if show.get("status") in ("Ongoing", "Upcoming", None) else 30


def resolve_ids(wl, api, matches, status):
    """tmdb id for every watchlist entry. Title-only entries ("q:...") are matched by search."""
    ids = {}
    for key, e in wl["shows"].items():
        if isinstance(e.get("tmdb"), int):
            ids[key] = e["tmdb"]
            continue
        m = matches.get(key) or {}
        if m.get("tmdb"):
            ids[key] = m["tmdb"]
            continue
        if not api or days_since(m.get("checked")) < UNMATCHED_RETRY_DAYS:
            continue
        try:
            tid = api.best_match(e.get("title", ""), e.get("year"))
        except TMDBError as err:
            log(f"  search failed for {e.get('title')}: {err}")
            continue
        matches[key] = {"tmdb": tid, "title": e.get("title"), "checked": now_iso()}
        log(f"  matched '{e.get('title')}' -> {tid or 'no confident match'}")
        if tid:
            ids[key] = tid
    return ids


def fetch_details(ids, api, cache, status):
    if not api:
        return
    ok = fail = 0
    for tid in sorted(set(ids.values())):
        try:
            rec = api.show(tid)
        except TMDBError as e:
            fail += 1
            log(f"  TMDB {tid}: {e}")
            if "401" in str(e):
                break
            continue
        if rec:
            cache[str(tid)] = {**rec, "fetched": now_iso()}
            ok += 1
    status["tmdb"] = "ok" if not fail else f"{fail} shows failed to refresh; showing saved details"
    log(f"TMDB: refreshed {ok} shows ({api.calls} calls)")


def score_key(rec):
    return rec.get("imdb_id") or f"tmdb:{rec['tmdb']}"


def refresh_scores(recs, wd, cache, status):
    todo = []
    for rec in recs:
        c = cache.get(score_key(rec)) or {}
        if c.get("v") != scores.PARSER_VERSION or days_since(c.get("checked")) >= refresh_days(rec):
            todo.append((days_since(c.get("checked")), rec))
    todo.sort(key=lambda x: -x[0])  # never-scored and stalest first
    todo = [r for _, r in todo[:MAX_SCORE_LOOKUPS]]
    if not todo:
        return
    log(f"Scores: checking Rotten Tomatoes and Metacritic for {len(todo)} shows")
    rt_hits = mc_hits = 0
    for rec in todo:
        links = wd.get(rec.get("imdb_id") or "") or {}
        title, year = rec["title"], rec.get("year")
        entry = {"checked": now_iso(), "v": scores.PARSER_VERSION}
        try:
            rt = scores.rotten_tomatoes(links.get("rt"), title, year)
            mc = scores.metacritic(links.get("mc"), title, year)
        except Exception as e:  # a parser bug must not sink the run
            log(f"  {title}: {type(e).__name__}: {e}")
            continue
        entry.update(rt or {})
        entry.update(mc or {})
        rt_hits += bool(rt and (rt.get("rt_critics") is not None or rt.get("rt_audience") is not None))
        mc_hits += bool(mc and mc.get("metacritic") is not None)
        cache[score_key(rec)] = entry
        log(f"  {title}: RT {entry.get('rt_critics')}/{entry.get('rt_audience')}, Metacritic {entry.get('metacritic')}")
    status["rotten_tomatoes"] = "ok" if rt_hits or len(todo) < 3 else "no scores found this run (site layout may have changed)"
    status["metacritic"] = "ok" if mc_hits or len(todo) < 3 else "no scores found this run (site layout may have changed)"


def assemble(wl, ids, details, ratings, sc):
    out = []
    for key, e in wl["shows"].items():
        base = {
            "key": key,
            "added": e.get("added"),
            "interest": e.get("interest") or 0,
            "watched": e.get("watched") or None,
        }
        rec = details.get(str(ids.get(key))) if key in ids else None
        if not rec:
            out.append({**base, "title": e.get("title") or key, "year": e.get("year"), "poster": e.get("poster"),
                        "matched": False, "scores": {}, "links": {}})
            continue
        r = ratings.get(rec.get("imdb_id") or "")
        c = sc.get(score_key(rec)) or {}
        show = {k: v for k, v in rec.items() if k not in ("fetched", "wikidata_id")}
        show.update(base)
        show["matched"] = True
        show["imdb_rating"] = r[0] if r else None
        show["imdb_votes"] = r[1] if r else None
        show["metacritic_user"] = c.get("metacritic_user")
        show["rt_guessed"] = bool(c.get("rt_guessed"))
        show["mc_guessed"] = bool(c.get("mc_guessed"))
        show["scores"] = {
            "imdb": round(r[0] * 10) if r and r[1] >= 50 else None,
            "metacritic": c.get("metacritic"),
            "rt_critics": c.get("rt_critics"),
            "rt_audience": c.get("rt_audience"),
            "tmdb": rec.get("tmdb_score"),
        }
        links = {"tmdb": f"https://www.themoviedb.org/tv/{rec['tmdb']}"}
        if rec.get("imdb_id"):
            links["imdb"] = f"https://www.imdb.com/title/{rec['imdb_id']}/"
        if c.get("rt_path"):
            links["rt"] = f"https://www.rottentomatoes.com/{c['rt_path']}"
        if c.get("mc_path"):
            links["metacritic"] = f"https://www.metacritic.com/{c['mc_path']}/"
        if rec.get("watch_link"):
            links["watch"] = rec["watch_link"]
        show["links"] = links
        show.pop("watch_link", None)
        out.append(show)
    return out


def main():
    status = {}
    token = env("TMDB_TOKEN")
    api = None
    if not token:
        status["tmdb"] = "not configured: add the TMDB_TOKEN secret"
    else:
        err = check(token)
        if err:
            status["tmdb"] = err
        else:
            api = TMDB(token, env("WATCH_REGION") or "US")

    wl = watchlist.load()
    log(f"Watchlist: {len(wl['shows'])} shows")
    matches = load_json(CACHE_DIR / "matches.json", {})
    details = load_json(CACHE_DIR / "tmdb.json", {})
    sc = load_json(CACHE_DIR / "scores.json", {})
    wd = load_json(CACHE_DIR / "wikidata.json", {})

    ids = resolve_ids(wl, api, matches, status)
    fetch_details(ids, api, details, status)
    recs = [details[str(t)] for t in set(ids.values()) if str(t) in details]

    try:
        ratings = imdb.ratings([r.get("imdb_id") for r in recs])
        status["imdb"] = "ok"
    except Exception as e:
        ratings = {}
        status["imdb"] = f"dataset download failed ({type(e).__name__}); IMDb scores missing this run"

    wd = wikidata.lookup([r.get("imdb_id") for r in recs], wd)
    refresh_scores(recs, wd, sc, status)

    shows = assemble(wl, ids, details, ratings, sc)
    # Keep caches to shows still on the list, so removed shows don't linger forever.
    live = {str(t) for t in ids.values()}
    details = {k: v for k, v in details.items() if k in live}
    matches = {k: v for k, v in matches.items() if k in wl["shows"]}

    save_json(CACHE_DIR / "matches.json", matches)
    save_json(CACHE_DIR / "tmdb.json", details)
    save_json(CACHE_DIR / "scores.json", sc)
    save_json(CACHE_DIR / "wikidata.json", wd)
    save_json(SITE_DIR / "data.json", {"generated": now_iso(), "status": status, "shows": shows}, pretty=False)
    log(f"Wrote {len(shows)} shows. Status: {status}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
