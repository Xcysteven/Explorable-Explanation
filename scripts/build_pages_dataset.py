#!/usr/bin/env python3
"""Build GitHub-Pages-friendly datasets from tracks_features_with_popularity_viz.csv.

Strategy:
- Build a compact song-level CSV for interaction and local search
- Build an aggregate JSON for the charts, distributions, counts, and feature trends
- Keep browser work small enough for GitHub Pages
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set


FEATURE_FIELDS = ["danceability", "energy", "acousticness", "valence", "tempo"]
AGG_FEATURE_FIELDS = ["duration", "explicit", *FEATURE_FIELDS]
HIST_BIN_SIZE = 0.25
HIST_MAX = 15.0


def quantile(sorted_vals: List[int], q: float) -> float:
    if not sorted_vals:
        return 0.0
    pos = (len(sorted_vals) - 1) * q
    base = int(pos)
    rest = pos - base
    nxt = sorted_vals[base + 1] if base + 1 < len(sorted_vals) else sorted_vals[base]
    return sorted_vals[base] + rest * (nxt - sorted_vals[base])


def mean(values: List[float]) -> Optional[float]:
    clean = [v for v in values if v is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)


def median(values: List[float]) -> Optional[float]:
    clean = sorted(v for v in values if v is not None)
    if not clean:
        return None
    mid = len(clean) // 2
    if len(clean) % 2:
        return clean[mid]
    return (clean[mid - 1] + clean[mid]) / 2


def safe_float(value: str) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed


def histogram(values: List[float]) -> List[int]:
    bin_count = int(HIST_MAX / HIST_BIN_SIZE)
    bins = [0] * bin_count
    for value in values:
        if value is None or value < 0 or value > HIST_MAX:
            continue
        index = min(bin_count - 1, int(value / HIST_BIN_SIZE))
        bins[index] += 1
    return bins


def summarize_rows(rows: List[dict]) -> dict:
    durations = [float(r["duration_min"]) for r in rows]
    explicit_values = [1.0 if r.get("explicit_bool") else 0.0 for r in rows]
    feature_values = {
        "duration": durations,
        "explicit": explicit_values,
        "danceability": [r.get("danceability_num") for r in rows],
        "energy": [r.get("energy_num") for r in rows],
        "acousticness": [r.get("acousticness_num") for r in rows],
        "valence": [r.get("valence_num") for r in rows],
        "tempo": [r.get("tempo_num") for r in rows],
    }
    return {
        "total": len(rows),
        "medianDuration": median(durations),
        "hist": histogram(durations),
        "features": {field: mean(feature_values[field]) for field in AGG_FEATURE_FIELDS},
    }


def summarize_hit_rows(rows: List[dict], cutoff: float) -> dict:
    hits = [r for r in rows if int(r["spotify_popularity"]) >= cutoff]
    summary = summarize_rows(hits)
    summary["hits"] = len(hits)
    summary["cutoff"] = cutoff
    summary["meanHitDuration"] = summary["features"]["duration"]
    summary["explicitShare"] = summary["features"]["explicit"]
    return summary


def build_aggregate(rows_by_year: Dict[int, List[dict]], thresholds: List[int]) -> dict:
    years = {}
    global_hits_by_threshold = {threshold: [] for threshold in thresholds}
    all_rows = []

    for year in sorted(rows_by_year.keys()):
        rows = rows_by_year[year]
        all_rows.extend(rows)
        pops = sorted(int(r["spotify_popularity"]) for r in rows)
        year_thresholds = {}
        for threshold in thresholds:
            cutoff = quantile(pops, 1 - threshold / 100)
            hit_summary = summarize_hit_rows(rows, cutoff)
            year_thresholds[str(threshold)] = hit_summary
            global_hits_by_threshold[threshold].extend(
                r for r in rows if int(r["spotify_popularity"]) >= cutoff
            )

        years[str(year)] = {
            "all": summarize_rows(rows),
            "thresholds": year_thresholds,
        }

    global_thresholds = {
        str(threshold): summarize_hit_rows(global_hits_by_threshold[threshold], -1)
        for threshold in thresholds
    }

    return {
        "schemaVersion": 1,
        "binSize": HIST_BIN_SIZE,
        "histMax": HIST_MAX,
        "thresholds": thresholds,
        "minYear": min(rows_by_year.keys()) if rows_by_year else None,
        "maxYear": max(rows_by_year.keys()) if rows_by_year else None,
        "global": {
            "all": summarize_rows(all_rows),
            "thresholds": global_thresholds,
        },
        "years": years,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="tracks_features_with_popularity_viz.csv")
    ap.add_argument("--feature-input", default="tracks_features.csv")
    ap.add_argument("--output", default="tracks_features_pages.csv")
    ap.add_argument("--aggregate-output", default="tracks_features_aggregates.json")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--per-year-cap", type=int, default=500)
    ap.add_argument("--core-hit-percent", type=int, default=3)
    ap.add_argument("--max-hit-percent", type=int, default=30)
    args = ap.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)
    if not in_path.exists():
        raise SystemExit(f"Missing input: {in_path}")

    random.seed(args.seed)

    raw_rows_by_year: Dict[int, List[dict]] = defaultdict(list)
    feature_ids: Set[str] = set()
    with in_path.open("r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            try:
                y = int(row["year"])
                p = int(float(row["spotify_popularity"]))
                d = int(float(row["duration_ms"]))
            except Exception:
                continue
            if y < 1980:
                continue
            if d <= 0 or d > HIST_MAX * 60000:
                continue
            row["year"] = str(y)
            row["spotify_popularity"] = str(p)
            row["duration_ms"] = str(d)
            row["duration_min"] = d / 60000
            row["explicit_bool"] = (row.get("explicit") or "").strip().lower() == "true"
            track_id = (row.get("id") or "").strip()
            if track_id:
                feature_ids.add(track_id)
            raw_rows_by_year[y].append(row)

    feature_by_id: Dict[str, Dict[str, str]] = {}
    feature_path = Path(args.feature_input)
    if feature_path.exists() and feature_ids:
        with feature_path.open("r", encoding="utf-8", newline="") as f:
            r = csv.DictReader(f)
            for row in r:
                track_id = (row.get("id") or "").strip()
                if track_id in feature_ids:
                    feature_by_id[track_id] = {
                        field: row.get(field, "")
                        for field in FEATURE_FIELDS
                    }
    elif feature_ids:
        print(f"Warning: feature input not found: {feature_path}")

    rows_by_year: Dict[int, List[dict]] = defaultdict(list)
    for year, rows in raw_rows_by_year.items():
        for row in rows:
            features = feature_by_id.get((row.get("id") or "").strip(), {})
            for field in FEATURE_FIELDS:
                row[field] = row.get(field) or features.get(field, "")
                row[f"{field}_num"] = safe_float(row.get(field, ""))
            rows_by_year[year].append(row)

    kept: List[dict] = []
    total_before = sum(len(v) for v in rows_by_year.values())
    thresholds = list(range(args.core_hit_percent, args.max_hit_percent + 1))
    aggregate = build_aggregate(rows_by_year, thresholds)
    aggregate_path = Path(args.aggregate_output)
    with aggregate_path.open("w", encoding="utf-8") as f:
        json.dump(aggregate, f, separators=(",", ":"))

    for year in sorted(rows_by_year.keys()):
        rows = rows_by_year[year]
        pops = sorted(int(r["spotify_popularity"]) for r in rows)
        cutoff = quantile(pops, 1 - args.core_hit_percent / 100)
        max_cutoff = quantile(pops, 1 - args.max_hit_percent / 100)

        core = [r for r in rows if int(r["spotify_popularity"]) >= cutoff]
        rest = [
            r for r in rows
            if max_cutoff <= int(r["spotify_popularity"]) < cutoff
        ]

        target = min(args.per_year_cap, len(rows))
        keep_rest_n = max(0, target - len(core))
        if keep_rest_n >= len(rest):
            sampled_rest = rest
        else:
            sampled_rest = random.sample(rest, keep_rest_n)

        kept.extend(core)
        kept.extend(sampled_rest)

    fieldnames = [
        "id",
        "name",
        "artists",
        "duration_ms",
        "year",
        "explicit",
        "spotify_popularity",
        "popularity_source",
        *FEATURE_FIELDS,
    ]
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        w.writeheader()
        for row in kept:
            output_row = {k: row.get(k, "") for k in fieldnames}
            w.writerow(output_row)

    print(f"Input rows: {total_before:,}")
    print(f"Output rows: {len(kept):,}")
    print(f"Feature rows matched: {len(feature_by_id):,}")
    print(f"Wrote: {out_path}")
    print(f"Wrote aggregates: {aggregate_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
