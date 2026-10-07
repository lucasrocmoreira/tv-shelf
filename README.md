# TV Shelf

Your TV watchlist, ranked by IMDb, Metacritic, Rotten Tomatoes (critics and audience) and TMDB scores,
with filters by streaming service, genre, theme, network, status and how long a show takes to finish.
Add shows from the app, mark them watched when you're done. A GitHub Actions job refreshes scores
every day and publishes the site to GitHub Pages.

Series only: TMDB's TV search never returns films, so single movies can't end up on the list.

## How it works

| Piece | Source | Notes |
|---|---|---|
| Your list | `config/watchlist.json` in this repo | The app writes it with your GitHub token |
| Show details, IMDb id, genres, themes, seasons, runtime, poster | TMDB API (free key) | Refreshed every run |
| Where it's streaming | TMDB's JustWatch data, US by default | Change `WATCH_REGION` in the workflow |
| IMDb rating and votes | IMDb's official daily dataset (`title.ratings.tsv.gz`) | No key; personal, non-commercial use |
| Rotten Tomatoes critics + audience | Public series page | No API; best effort |
| Metacritic | Public series page | No API; best effort |
| Exact RT and Metacritic pages | Wikidata, by IMDb id | Falls back to a title guess, which is checked against title and year and flagged in the app |
| TMDB user score | TMDB API | Shown once a show has 20+ votes |

Scores of ongoing shows are re-checked weekly, finished shows monthly. New shows are scored a few minutes after you add them.

The **Average score** is the mean of the scores a show has, each on a 0 to 100 scale (IMDb 8.7 counts as 87).
Pick which sources count under "Scores in the average".

## Setup (about 10 minutes, once)

### 1. Repository and Pages
1. Use this repository as is (public, so GitHub Pages is free).
2. **Settings > Pages**: set **Source** to **GitHub Actions**.

### 2. TMDB key
1. Create a free account at https://www.themoviedb.org/signup.
2. Go to **Settings > API** (https://www.themoviedb.org/settings/api), request a **Developer** key, and describe it as a personal watchlist.
3. Copy the **API Read Access Token** (the long one starting with `eyJ`).
4. In this repo: **Settings > Secrets and variables > Actions > New repository secret**, name `TMDB_TOKEN`, paste it.

That's the only key the build needs.

### 3. Run it
1. **Actions** tab: enable workflows if GitHub asks.
2. **Update TV shelf > Run workflow**.
3. When it finishes, the site is at `https://<your-username>.github.io/tv-shelf/`.

### 4. Connect the app (once per device)
Open **Settings** in the app:
- **GitHub token**: a fine-grained token with **Contents: Read and write** on this repository only
  (https://github.com/settings/personal-access-tokens/new). Lets the app save your list.
- **TMDB token** (optional but recommended): the same `eyJ…` token. Lets "Add a show" search as you type so you pick the exact series.
  Without it you add by title and the build matches it.

Both tokens stay in that browser's storage only, never in the repository.

## Day to day
- **Add a show**: search, tap Add. Details and scores appear in about 5 minutes (it shows as "Updating" until then).
- **Rank**: change "Rank by", tap streaming services, or open the filters. Tap a theme or genre tag inside a show to filter by it.
- **Interest stars** (1 to 3): your own priority; "Rank by my interest" sorts by it, breaking ties by average score.
- **Pick for me**: picks at random from the top 5 of the current view.
- **Finished a show**: open it and tap **✓ Watched**. It moves to the Watched tab (undo is in the toast). **Remove** deletes it entirely.
- **Without the app**: Issues > New issue > **Add or remove a show**.

These are instant and don't rebuild: watched, interest, remove. Adding a show triggers a rebuild.

## Limits worth knowing
- The site and `config/watchlist.json` are public. Anyone with the link can see your list (never your tokens).
- Rotten Tomatoes and Metacritic have no API. If either changes its page layout, those scores stop updating
  (the rest keeps working and the app shows a warning) until the parser in `pipeline/scores.py` is adjusted.
  Bump `PARSER_VERSION` there after a fix so every show is rechecked.
- Rotten Tomatoes series scores are averages across seasons; Metacritic often scores seasons separately and its
  series page shows the series-level Metascore when it has one. Expect gaps for older or non-US shows.
- IMDb ratings with fewer than 50 votes are left out of the average.

## Run locally
```bash
pip install -r requirements.txt
export TMDB_TOKEN=eyJ...
python -m pipeline.build
python -m http.server -d site 8000   # then open http://localhost:8000
```
