# The Streamlined Era: Hit Duration Trends

An interactive explorable explanation about how popular music has changed across the streaming era. The project uses Spotify-style track data to examine whether hit songs have become shorter, more explicit, and different in their audio features over time.

The site is built as a scroll-driven story rather than a static dashboard. It moves from listening examples, to a 1980s-versus-modern comparison, to interactive charts where users can test the pattern themselves.

## Project Goals

- Show how hit song duration changes from 1980 onward.
- Compare hit songs against the broader catalog for each year.
- Let users adjust what counts as a "hit" using a popularity percentile slider.
- Highlight 2015 as a narrative checkpoint for Spotify personalization, while avoiding a direct causation claim.
- Let users search for a song and see where it sits relative to the larger trend.

## Main Interactions

- Scroll-based presentation slides for different music eras.
- Spotify listening embeds for key comparison songs.
- Average hit duration line chart by release year.
- Song length distribution chart that updates when a year is selected.
- Explicit-content trend chart using the same hit threshold.
- Feature explorer for energy, danceability, valence, acousticness, and tempo.
- Song search section with song-level stats, a radar chart, and mini trend charts.

## Tech Stack

- HTML, CSS, and vanilla JavaScript
- D3.js for custom chart rendering and scroll-driven visual behavior
- Plotly for selected charting support
- Python for data preparation
- Spotify Web API for popularity enrichment

The frontend is static and can be served by GitHub Pages.

## Repository Structure

```text
.
├── index.html
├── tracks_features_aggregates.json
├── tracks_features_pages.csv
├── spotify_data clean.csv
├── assets/
│   ├── era-classic.mp4
│   └── era-modern.mp4
├── scripts/
│   ├── enrich_tracks_popularity.py
│   └── build_pages_dataset.py
├── chorus.ipynb
├── main.ipynb
├── LICENSE
└── README.md
```

## Data Files

The deployed site uses two browser-facing data files:

```text
tracks_features_aggregates.json
tracks_features_pages.csv
```

`tracks_features_aggregates.json` contains precomputed full-catalog statistics for charts, distributions, counts, and feature trends. This keeps the charts statistically grounded without forcing the browser to parse hundreds of thousands of raw rows.

`tracks_features_pages.csv` is a smaller song-level interaction sample used for random tracks and local search.

If the aggregate JSON is missing, the site falls back to row-based calculation from CSV files in this order:

1. `tracks_features_pages.csv`
2. `tracks_features_with_popularity_viz.csv`
3. `tracks_features_with_popularity.csv`

For GitHub Pages, the intended committed dataset is:

```text
tracks_features_aggregates.json
tracks_features_pages.csv
```

Large local data files are intentionally ignored by Git:

```text
tracks_features.csv
tracks_features_with_popularity.csv
tracks_features_with_popularity_viz.csv
spotify_popularity_cache.csv
.env
```

This keeps the repository deployable and avoids committing raw data, generated large files, cached API results, or secrets.

## Required CSV Columns

The visualization expects these columns:

```text
id
name
artists
duration_ms
year
explicit
spotify_popularity
```

These columns are optional but used by the feature explorer and song search when available:

```text
danceability
energy
acousticness
valence
tempo
```

## How "Hit" Is Defined

A hit is defined operationally as the top X percent of tracks by `spotify_popularity` within each release year.

The default threshold is top 10 percent. The deployed slider is constrained to top 3 percent through top 30 percent so the page can use compact precomputed aggregates instead of a large raw CSV.

## Run Locally

Serve the project with a local web server:

```bash
python3 -m http.server 8000
```

Then open:

```text
http://localhost:8000/index.html
```

Do not open `index.html` directly with `file://`. The browser needs a local server so JavaScript can load the CSV with `fetch()`.

## Rebuild the Data

If you have the full raw dataset, place it in the repo root as:

```text
tracks_features.csv
```

Install the Python dependency if needed:

```bash
pip3 install requests
```

Create a local `.env` file for Spotify credentials:

```bash
export SPOTIFY_CLIENT_ID="your_client_id"
export SPOTIFY_CLIENT_SECRET="your_client_secret"
```

Load the credentials into your shell:

```bash
source .env
```

Enrich the raw data with Spotify popularity:

```bash
python3 scripts/enrich_tracks_popularity.py \
  --input tracks_features.csv \
  --output-full tracks_features_with_popularity.csv \
  --output-viz tracks_features_with_popularity_viz.csv \
  --cache spotify_popularity_cache.csv
```

Build the smaller GitHub Pages dataset:

```bash
python3 scripts/build_pages_dataset.py \
  --input tracks_features_with_popularity_viz.csv \
  --feature-input tracks_features.csv \
  --output tracks_features_pages.csv \
  --aggregate-output tracks_features_aggregates.json
```

Serve locally again and confirm the page loads:

```bash
python3 -m http.server 8000
```

## Spotify Credentials

Do not commit real Spotify API credentials.

The enrichment script reads credentials from command-line arguments or environment variables. The client-side constants in `index.html` are placeholders and should stay placeholders unless the project is reworked to use a safer backend or proxy.

For a public GitHub Pages deployment, treat browser-visible credentials as public. If live Spotify lookup is required, move that request behind a server-side endpoint.

## Deploy to GitHub Pages

Commit the static site files:

```text
index.html
tracks_features_aggregates.json
tracks_features_pages.csv
assets/
scripts/
README.md
LICENSE
```

Do not commit:

```text
.env
tracks_features.csv
tracks_features_with_popularity.csv
tracks_features_with_popularity_viz.csv
spotify_popularity_cache.csv
```

Then enable GitHub Pages in the repository settings and point it at the branch and folder that contain `index.html`.

## Notes and Limitations

- The charts show patterns in the dataset, not proof that Spotify caused the changes.
- Spotify popularity is not the same thing as historical chart position.
- Dataset coverage can vary by year, especially near the most recent years.
- Spotify embeds may not play in every browser, account state, or region.
- Browser autoplay restrictions mean audio usually needs a user gesture.
- The 2015 marker is used as narrative context for personalization, not as a causal boundary.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
