#!/usr/bin/env python3
"""Enrich tracks_features.csv with Spotify popularity.

Usage examples:
  SPOTIFY_CLIENT_ID=... SPOTIFY_CLIENT_SECRET=... \
    python3 scripts/enrich_tracks_popularity.py

  python3 scripts/enrich_tracks_popularity.py \
    --client-id ... --client-secret ... --max-ids 5000
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import requests

TOKEN_URL = "https://accounts.spotify.com/api/token"
TRACKS_URL = "https://api.spotify.com/v1/tracks"


def chunked(items: List[str], size: int) -> Iterable[List[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def get_token(client_id: str, client_secret: str, timeout: float = 20.0) -> str:
    if client_id in {"YOUR_ID", "YOUR_CLIENT_ID"} or client_secret in {"YOUR_SECRET", "YOUR_CLIENT_SECRET"}:
        raise RuntimeError(
            "Spotify credentials are placeholders. Replace YOUR_ID/YOUR_SECRET with real values."
        )
    resp = requests.post(
        TOKEN_URL,
        data={"grant_type": "client_credentials"},
        auth=(client_id, client_secret),
        timeout=timeout,
    )
    if resp.status_code >= 400:
        detail = ""
        try:
            payload = resp.json()
            detail = payload.get("error_description") or payload.get("error") or ""
        except Exception:
            detail = resp.text[:300]
        raise RuntimeError(
            f"Failed to get Spotify token (HTTP {resp.status_code}). {detail}".strip()
        )
    payload = resp.json()
    token = payload.get("access_token")
    if not token:
        raise RuntimeError("Spotify token response missing access_token")
    return token


def load_cache(cache_path: Path) -> Dict[str, Optional[int]]:
    cache: Dict[str, Optional[int]] = {}
    if not cache_path.exists():
        return cache
    with cache_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            track_id = (row.get("id") or "").strip()
            if not track_id:
                continue
            raw = (row.get("spotify_popularity") or "").strip()
            cache[track_id] = int(raw) if raw.isdigit() else None
    return cache


def append_cache_rows(cache_path: Path, rows: List[Tuple[str, Optional[int]]]) -> None:
    exists = cache_path.exists()
    with cache_path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if not exists:
            writer.writerow(["id", "spotify_popularity"])
        for track_id, pop in rows:
            writer.writerow([track_id, "" if pop is None else pop])


def collect_unique_ids(input_csv: Path, id_col: str, max_ids: Optional[int]) -> List[str]:
    seen = set()
    ids: List[str] = []
    with input_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            track_id = (row.get(id_col) or "").strip()
            if len(track_id) != 22 or track_id in seen:
                continue
            seen.add(track_id)
            ids.append(track_id)
            if max_ids and len(ids) >= max_ids:
                break
    return ids


def fetch_batch(
    ids: List[str],
    token: str,
    market: Optional[str],
    timeout: float,
) -> Dict[str, Optional[int]]:
    params = {"ids": ",".join(ids)}
    if market:
        params["market"] = market
    headers = {"Authorization": f"Bearer {token}"}

    while True:
        resp = requests.get(TRACKS_URL, params=params, headers=headers, timeout=timeout)

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "3"))
            time.sleep(retry_after + 1)
            continue

        if resp.status_code == 401:
            raise PermissionError("401 Unauthorized from Spotify API. Check credentials.")

        if resp.status_code == 403:
            raise PermissionError(
                "403 Forbidden from Spotify API. Your app/account may not have access to track popularity fields."
            )

        resp.raise_for_status()
        payload = resp.json()
        tracks = payload.get("tracks", [])
        out: Dict[str, Optional[int]] = {}
        for tid, track in zip(ids, tracks):
            if not track:
                out[tid] = None
            else:
                pop = track.get("popularity")
                out[tid] = int(pop) if isinstance(pop, int) else None
        return out


def enrich_cache(
    unique_ids: List[str],
    cache: Dict[str, Optional[int]],
    cache_path: Path,
    client_id: str,
    client_secret: str,
    market: Optional[str],
    batch_size: int,
    sleep_secs: float,
    timeout: float,
) -> Dict[str, Optional[int]]:
    missing = [tid for tid in unique_ids if tid not in cache]
    if not missing:
        print("All IDs already cached.")
        return cache

    print(f"Need to fetch popularity for {len(missing):,} track IDs")
    token = get_token(client_id, client_secret, timeout=timeout)

    fetched = 0
    started = time.time()
    for i, batch in enumerate(chunked(missing, batch_size), start=1):
        try:
            result = fetch_batch(batch, token, market=market, timeout=timeout)
        except PermissionError as exc:
            print(f"\nERROR: {exc}")
            print("Stopping early. Existing cache remains saved.")
            break
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            if status == 401:
                token = get_token(client_id, client_secret, timeout=timeout)
                result = fetch_batch(batch, token, market=market, timeout=timeout)
            else:
                raise

        new_rows: List[Tuple[str, Optional[int]]] = []
        for tid in batch:
            pop = result.get(tid)
            cache[tid] = pop
            new_rows.append((tid, pop))

        append_cache_rows(cache_path, new_rows)
        fetched += len(batch)

        if i % 20 == 0 or fetched == len(missing):
            elapsed = time.time() - started
            rate = fetched / elapsed if elapsed else 0.0
            print(f"Fetched {fetched:,}/{len(missing):,} ({rate:.1f} IDs/sec)")

        if sleep_secs > 0:
            time.sleep(sleep_secs)

    return cache


def write_enriched_outputs(
    input_csv: Path,
    output_full_csv: Path,
    output_viz_csv: Path,
    cache: Dict[str, Optional[int]],
    min_year: int,
    max_year: int,
    allow_proxy_if_missing: bool,
) -> None:
    def float_or_none(v: str) -> Optional[float]:
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def clamp01(v: float) -> float:
        return max(0.0, min(1.0, v))

    def popularity_proxy(row: Dict[str, str]) -> Optional[int]:
        dance = float_or_none(row.get("danceability", ""))
        energy = float_or_none(row.get("energy", ""))
        valence = float_or_none(row.get("valence", ""))
        acoustic = float_or_none(row.get("acousticness", ""))
        instrumental = float_or_none(row.get("instrumentalness", ""))
        tempo = float_or_none(row.get("tempo", ""))
        if None in (dance, energy, valence, acoustic, instrumental, tempo):
            return None
        tempo_norm = clamp01((tempo - 60.0) / 140.0)
        score01 = (
            0.30 * clamp01(energy)
            + 0.25 * clamp01(dance)
            + 0.15 * clamp01(valence)
            + 0.10 * (1.0 - clamp01(acoustic))
            + 0.10 * (1.0 - clamp01(instrumental))
            + 0.10 * tempo_norm
        )
        return int(round(100.0 * clamp01(score01)))

    with input_csv.open("r", encoding="utf-8", newline="") as fin, \
        output_full_csv.open("w", encoding="utf-8", newline="") as fout_full, \
        output_viz_csv.open("w", encoding="utf-8", newline="") as fout_viz:

        reader = csv.DictReader(fin)
        if reader.fieldnames is None:
            raise RuntimeError("Input CSV is missing a header")

        full_fields = reader.fieldnames + ["spotify_popularity"]
        full_writer = csv.DictWriter(fout_full, fieldnames=full_fields)
        full_writer.writeheader()

        viz_fields = ["id", "name", "artists", "duration_ms", "year", "spotify_popularity", "popularity_source"]
        viz_writer = csv.DictWriter(fout_viz, fieldnames=viz_fields)
        viz_writer.writeheader()

        total = 0
        viz_rows = 0
        for row in reader:
            total += 1
            track_id = (row.get("id") or "").strip()
            pop = cache.get(track_id)
            row["spotify_popularity"] = "" if pop is None else str(pop)
            full_writer.writerow(row)

            try:
                year = int((row.get("year") or "").strip())
                duration_ms = int((row.get("duration_ms") or "").strip())
            except ValueError:
                continue

            if year < min_year or year > max_year:
                continue
            if duration_ms <= 0:
                continue
            source = "api"
            final_pop = pop
            if final_pop is None and allow_proxy_if_missing:
                final_pop = popularity_proxy(row)
                source = "proxy"
            if final_pop is None:
                continue

            viz_writer.writerow(
                {
                    "id": track_id,
                    "name": (row.get("name") or "").strip(),
                    "artists": (row.get("artists") or "").strip(),
                    "duration_ms": str(duration_ms),
                    "year": str(year),
                    "spotify_popularity": str(final_pop),
                    "popularity_source": source,
                }
            )
            viz_rows += 1

            if total % 200_000 == 0:
                print(f"Wrote {total:,} rows (viz rows: {viz_rows:,})")

    print(f"Wrote enriched full CSV: {output_full_csv}")
    print(f"Wrote viz CSV: {output_viz_csv} ({viz_rows:,} rows)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Add Spotify popularity to tracks_features.csv")
    parser.add_argument("--input", default="tracks_features.csv", help="Input CSV path")
    parser.add_argument("--output-full", default="tracks_features_with_popularity.csv", help="Full enriched CSV path")
    parser.add_argument(
        "--output-viz",
        default="tracks_features_with_popularity_viz.csv",
        help="Slim enriched CSV used by visualization",
    )
    parser.add_argument("--cache", default="spotify_popularity_cache.csv", help="Cache CSV path")
    parser.add_argument(
        "--client-id",
        default=os.getenv("SPOTIFY_CLIENT_ID"),
        help="Spotify client id",
    )
    parser.add_argument(
        "--client-secret",
        default=os.getenv("SPOTIFY_CLIENT_SECRET"),
        help="Spotify client secret",
    )
    parser.add_argument("--market", default="US", help="Optional market code (default: US)")
    parser.add_argument("--batch-size", type=int, default=50, help="Spotify IDs per request (max 50)")
    parser.add_argument("--sleep", type=float, default=0.1, help="Sleep between API calls")
    parser.add_argument("--timeout", type=float, default=25.0, help="HTTP timeout seconds")
    parser.add_argument("--max-ids", type=int, default=None, help="Only fetch first N unique IDs (debug)")
    parser.add_argument("--min-year", type=int, default=1980, help="Min year for viz output")
    parser.add_argument("--max-year", type=int, default=2100, help="Max year for viz output")
    parser.add_argument("--skip-fetch", action="store_true", help="Skip API and only build outputs from cache")
    parser.add_argument(
        "--allow-proxy-if-missing",
        action="store_true",
        help="When API popularity is missing, compute a proxy popularity score from audio features for viz output.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.batch_size < 1 or args.batch_size > 50:
        raise SystemExit("--batch-size must be between 1 and 50")

    input_csv = Path(args.input)
    output_full_csv = Path(args.output_full)
    output_viz_csv = Path(args.output_viz)
    cache_path = Path(args.cache)

    if not input_csv.exists():
        raise SystemExit(f"Input CSV not found: {input_csv}")

    cache = load_cache(cache_path)
    print(f"Loaded cache entries: {len(cache):,}")

    unique_ids = collect_unique_ids(input_csv, id_col="id", max_ids=args.max_ids)
    print(f"Unique valid track IDs discovered: {len(unique_ids):,}")

    if not args.skip_fetch:
        if not args.client_id or not args.client_secret:
            raise SystemExit(
                "Missing Spotify credentials. Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET, "
                "or pass --client-id and --client-secret."
            )

        cache = enrich_cache(
            unique_ids=unique_ids,
            cache=cache,
            cache_path=cache_path,
            client_id=args.client_id,
            client_secret=args.client_secret,
            market=args.market,
            batch_size=args.batch_size,
            sleep_secs=args.sleep,
            timeout=args.timeout,
        )

    write_enriched_outputs(
        input_csv=input_csv,
        output_full_csv=output_full_csv,
        output_viz_csv=output_viz_csv,
        cache=cache,
        min_year=args.min_year,
        max_year=args.max_year,
        allow_proxy_if_missing=args.allow_proxy_if_missing,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
