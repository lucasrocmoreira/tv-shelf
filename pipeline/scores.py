"""Rotten Tomatoes and Metacritic series scores, read from their public pages (neither has an API).

Best effort: every function returns None on failure instead of raising, so a layout change on one
site never breaks the daily run. Bump PARSER_VERSION after fixing a parser so every show is rechecked.
"""
import json
import re

from bs4 import BeautifulSoup

from .util import log, polite_get, similarity, slugify

PARSER_VERSION = 1


def _soup(html):
    return BeautifulSoup(html, "html.parser")


def _ld_json(soup):
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict):
                yield item


def _ld_rating(soup, best=100):
    for item in _ld_json(soup):
        agg = item.get("aggregateRating")
        if isinstance(agg, dict) and agg.get("ratingValue") not in (None, ""):
            try:
                v = float(agg["ratingValue"])
                b = float(agg.get("bestRating") or best)
            except (TypeError, ValueError):
                continue
            if b == best and 0 <= v <= best:
                return round(v)
    return None


def _page_title(soup):
    og = soup.find("meta", property="og:title")
    t = (og.get("content") if og else None) or (soup.title.string if soup.title else "") or ""
    return re.split(r"\s+[|\-–]\s+", t.strip())[0]


def _pct(v):
    try:
        v = float(str(v).strip().rstrip("%"))
    except (TypeError, ValueError):
        return None
    return round(v) if 0 <= v <= 100 else None


def _walk(obj, path=()):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield path + (k,), v
            yield from _walk(v, path + (k,))
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v, path)


_RT_CRITIC_KEYS = ("criticsScore", "tomatometerScore", "tomatometerAllCriticsScore")
_RT_AUDIENCE_KEYS = ("audienceScore", "audienceAllScore", "popcornmeterScore")


def _rt_from_json(blobs):
    critics = audience = None
    for blob in blobs:
        for path, v in _walk(blob):
            key = path[-1]
            if isinstance(v, dict) and (key in _RT_CRITIC_KEYS or key in _RT_AUDIENCE_KEYS):
                val = _pct(v.get("score") if v.get("score") not in (None, "") else v.get("value"))
                if val is None:
                    continue
                if key in _RT_CRITIC_KEYS and critics is None:
                    critics = val
                if key in _RT_AUDIENCE_KEYS and audience is None:
                    audience = val
    return critics, audience


_RT_RE = {
    "critics": [
        re.compile(r'"(?:criticsScore|tomatometerScore)"\s*:\s*\{[^{}]*?"(?:score|value)"\s*:\s*"?(\d{1,3})', re.S),
        re.compile(r'slot="criticsScore"[^>]*>\s*(\d{1,3})%', re.S),
        re.compile(r'tomatometerscore="(\d{1,3})"', re.I),
    ],
    "audience": [
        re.compile(r'"(?:audienceScore|popcornmeterScore)"\s*:\s*\{[^{}]*?"(?:score|value)"\s*:\s*"?(\d{1,3})', re.S),
        re.compile(r'slot="audienceScore"[^>]*>\s*(\d{1,3})%', re.S),
        re.compile(r'audiencescore="(\d{1,3})"', re.I),
    ],
}


def parse_rt(html):
    """(critics %, audience %) from a Rotten Tomatoes series page."""
    soup = _soup(html)
    blobs = []
    for tag in soup.find_all("script", type="application/json"):
        try:
            blobs.append(json.loads(tag.string or ""))
        except (json.JSONDecodeError, TypeError):
            pass
    critics, audience = _rt_from_json(blobs)
    if critics is None:
        for pat in _RT_RE["critics"]:
            m = pat.search(html)
            if m:
                critics = _pct(m.group(1))
                break
    if audience is None:
        for pat in _RT_RE["audience"]:
            m = pat.search(html)
            if m:
                audience = _pct(m.group(1))
                break
    if critics is None:
        critics = _ld_rating(soup)
    return critics, audience


_MC_RE = [
    re.compile(r"Metascore\s+(\d{1,3})\s+out of 100", re.I),
    re.compile(r'"metascore"\s*:\s*\{[^{}]*?"score"\s*:\s*(\d{1,3})', re.S),
]
_MC_USER_RE = re.compile(r"User score\s+(\d(?:\.\d)?)\s+out of 10", re.I)


def parse_mc(html):
    """(Metascore 0-100, user score 0-10) from a Metacritic series page."""
    soup = _soup(html)
    meta = None
    for pat in _MC_RE:
        m = pat.search(html)
        if m and 0 <= int(m.group(1)) <= 100:
            meta = int(m.group(1))
            break
    if meta is None:
        meta = _ld_rating(soup)
    m = _MC_USER_RE.search(html)
    user = float(m.group(1)) if m else None
    return meta, user


def _fetch(url, host_delay):
    r = polite_get(url, host_delay=host_delay)
    if r is None or r.status_code != 200:
        return None
    return r.text


def _plausible(html, title, year):
    """For guessed URLs only: the page must be about a show with this name from this year."""
    soup = _soup(html)
    if similarity(_page_title(soup), title) < 0.85:
        return False
    return not year or str(year) in html


def rotten_tomatoes(path=None, title=None, year=None):
    """{"rt_critics", "rt_audience", "rt_path", "rt_guessed"} or None.
    path is 'tv/slug' from Wikidata; without it the slug is guessed from the title and checked."""
    guessed = False
    if not path:
        if not title:
            return None
        path, guessed = "tv/" + slugify(title, "_"), True
    html = _fetch(f"https://www.rottentomatoes.com/{path}", 2.0)
    if not html:
        return None
    if guessed and not _plausible(html, title, year):
        log(f"    RT: guessed /{path} doesn't look like {title} ({year}); skipped")
        return None
    critics, audience = parse_rt(html)
    if critics is None and audience is None:
        if not getattr(rotten_tomatoes, "_warned", False):
            rotten_tomatoes._warned = True
            log(f"    RT: page loaded but no scores found on /{path} (layout may have changed)")
        return {"rt_critics": None, "rt_audience": None, "rt_path": path, "rt_guessed": guessed}
    return {"rt_critics": critics, "rt_audience": audience, "rt_path": path, "rt_guessed": guessed}


def metacritic(path=None, title=None, year=None):
    """{"metacritic", "metacritic_user", "mc_path", "mc_guessed"} or None."""
    guessed = False
    if not path:
        if not title:
            return None
        path, guessed = "tv/" + slugify(title, "-"), True
    html = _fetch(f"https://www.metacritic.com/{path}/", 2.0)
    if not html:
        return None
    if guessed and not _plausible(html, title, year):
        log(f"    Metacritic: guessed /{path}/ doesn't look like {title} ({year}); skipped")
        return None
    meta, user = parse_mc(html)
    return {"metacritic": meta, "metacritic_user": user, "mc_path": path, "mc_guessed": guessed}
