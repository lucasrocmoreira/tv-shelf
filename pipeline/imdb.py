"""IMDb ratings from IMDb's official daily dataset (title.ratings.tsv.gz).

IMDb has no free API but publishes this file every day for personal, non-commercial use:
https://developer.imdb.com/non-commercial-datasets/  No key needed.
"""
import gzip
import io

from .util import log, session

URL = "https://datasets.imdbws.com/title.ratings.tsv.gz"


def ratings(ids):
    """{tconst: (rating 0-10, votes)} for the ids asked for. Empty dict if the download fails."""
    want = {i for i in ids if i}
    if not want:
        return {}
    try:
        r = session.get(URL, timeout=120)
        r.raise_for_status()
    except Exception as e:
        log(f"!! IMDb dataset download failed: {e}")
        raise
    out = {}
    with gzip.open(io.BytesIO(r.content), "rt", encoding="utf-8") as f:
        next(f, None)  # header: tconst averageRating numVotes
        for line in f:
            tconst, _, rest = line.partition("\t")
            if tconst in want:
                avg, _, votes = rest.rstrip("\n").partition("\t")
                try:
                    out[tconst] = (float(avg), int(votes))
                except ValueError:
                    pass
    log(f"IMDb: ratings for {len(out)} of {len(want)} shows")
    return out
