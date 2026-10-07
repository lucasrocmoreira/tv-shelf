"""TMDB (The Movie Database): show metadata, IMDb id, keywords and where it's streaming.

Free API. Accepts either the v4 "API Read Access Token" (starts with eyJ) or the v3 "API Key".
Streaming availability comes from TMDB's JustWatch data.
"""
import re

from .util import log, polite_get, similarity

API = "https://api.themoviedb.org/3"
IMG = "https://image.tmdb.org/t/p/"

STATUS = {
    "Returning Series": "Ongoing",
    "Ended": "Ended",
    "Canceled": "Canceled",
    "In Production": "Upcoming",
    "Planned": "Upcoming",
    "Pilot": "Upcoming",
}


class TMDBError(Exception):
    pass


class TMDB:
    def __init__(self, token: str, region: str = "US"):
        self.token = token.strip()
        self.region = region
        self.calls = 0

    def _get(self, path, **params):
        headers = {"Accept": "application/json"}
        if self.token.startswith("eyJ"):
            headers["Authorization"] = "Bearer " + self.token
        else:
            params["api_key"] = self.token
        self.calls += 1
        r = polite_get(API + path, host_delay=0.05, params=params, headers=headers)
        if r is None:
            raise TMDBError("no response")
        if r.status_code == 401:
            raise TMDBError("TMDB rejected the key (HTTP 401). Check the TMDB_TOKEN secret.")
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise TMDBError(f"HTTP {r.status_code}")
        return r.json()

    def search(self, title, year=None):
        params = {"query": title, "include_adult": "false", "language": "en-US"}
        if year:
            params["first_air_date_year"] = year
        res = self._get("/search/tv", **params) or {}
        return res.get("results") or []

    def best_match(self, title, year=None):
        """Strict title match, preferring the year when given and then popularity. None if unsure."""
        hits = self.search(title, year) or (self.search(title) if year else [])
        scored = []
        for h in hits[:10]:
            s = max(similarity(title, h.get("name", "")), similarity(title, h.get("original_name", "")))
            y = _year(h.get("first_air_date"))
            if year and y and abs(y - int(year)) > 1:
                s -= 0.3
            scored.append((s, h.get("popularity") or 0, h))
        scored.sort(key=lambda x: (round(x[0], 2), x[1]), reverse=True)
        if scored and scored[0][0] >= 0.9:
            return scored[0][2]["id"]
        return None

    def show(self, tv_id):
        d = self._get(f"/tv/{tv_id}", append_to_response="external_ids,keywords,watch/providers", language="en-US")
        return parse(d, self.region) if d else None


def _year(date):
    m = re.match(r"(\d{4})", date or "")
    return int(m.group(1)) if m else None


def _runtime(d):
    rts = [x for x in d.get("episode_run_time") or [] if isinstance(x, (int, float)) and x > 0]
    if rts:
        return round(sum(rts) / len(rts))
    for k in ("last_episode_to_air", "next_episode_to_air"):
        rt = (d.get(k) or {}).get("runtime")
        if isinstance(rt, (int, float)) and rt > 0:
            return int(rt)
    return None


def parse(d, region="US"):
    status = STATUS.get(d.get("status"), d.get("status") or None)
    start, end = _year(d.get("first_air_date")), _year(d.get("last_air_date"))
    episodes = d.get("number_of_episodes") or None
    runtime = _runtime(d)
    ext = d.get("external_ids") or {}
    kw = [k.get("name") for k in ((d.get("keywords") or {}).get("results") or []) if k.get("name")]
    prov = ((d.get("watch/providers") or {}).get("results") or {}).get(region) or {}
    streaming = [p["provider_name"] for p in sorted(prov.get("flatrate") or [], key=lambda p: p.get("display_priority", 99))]
    vote = d.get("vote_average") or 0
    votes = d.get("vote_count") or 0
    nxt = d.get("next_episode_to_air") or {}
    return {
        "tmdb": d["id"],
        "imdb_id": ext.get("imdb_id") or None,
        "wikidata_id": ext.get("wikidata_id") or None,
        "title": d.get("name") or d.get("original_name"),
        "original_title": d.get("original_name") if d.get("original_name") != d.get("name") else None,
        "year": start,
        "end_year": end if status in ("Ended", "Canceled") else None,
        "status": status,
        "type": d.get("type") or None,
        "seasons": d.get("number_of_seasons") or None,
        "episodes": episodes,
        "runtime": runtime,
        "hours": round(episodes * runtime / 60) if episodes and runtime else None,
        "networks": [n["name"] for n in d.get("networks") or [] if n.get("name")],
        "countries": d.get("origin_country") or [],
        "language": d.get("original_language") or None,
        "creators": [c["name"] for c in d.get("created_by") or [] if c.get("name")],
        "genres": [g["name"] for g in d.get("genres") or [] if g.get("name")],
        "keywords": kw[:15],
        "overview": d.get("overview") or None,
        "poster": IMG + "w342" + d["poster_path"] if d.get("poster_path") else None,
        "popularity": round(d.get("popularity") or 0, 1),
        "tmdb_score": round(vote * 10) if votes >= 20 else None,
        "tmdb_votes": votes,
        "streaming": streaming,
        "watch_link": prov.get("link"),
        "next_episode": nxt.get("air_date") if nxt else None,
    }


def check(token):
    """Fail fast with a clear message if the key doesn't work."""
    try:
        TMDB(token)._get("/configuration")
        return None
    except TMDBError as e:
        log(f"!! TMDB: {e}")
        return str(e)
