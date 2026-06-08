#!/usr/bin/env python3
"""Build a GitHub-Pages-friendly dataset from tracks_features_with_popularity_viz.csv.

Strategy:
- Keep ALL tracks in top 20% popularity per year (preserve hit structure)
- Randomly sample the rest per year up to a per-year cap
- Output a compact CSV for browser + GitHub push
"""

from __future__ import annotations

import argparse
import csv
import random
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set


FEATURE_FIELDS = ["danceability", "energy", "acousticness", "valence"]


def quantile(sorted_vals: List[int], q: float) -> float:
    if not sorted_vals:
        return 0.0
    pos = (len(sorted_vals) - 1) * q
    base = int(pos)
    rest = pos - base
    nxt = sorted_vals[base + 1] if base + 1 < len(sorted_vals) else sorted_vals[base]
    return sorted_vals[base] + rest * (nxt - sorted_vals[base])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="tracks_features_with_popularity_viz.csv")
    ap.add_argument("--feature-input", default="tracks_features.csv")
    ap.add_argument("--output", default="tracks_features_pages.csv")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--per-year-cap", type=int, default=7000)
    ap.add_argument("--core-hit-percent", type=int, default=20)
    args = ap.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)
    if not in_path.exists():
        raise SystemExit(f"Missing input: {in_path}")

    random.seed(args.seed)

    rows_by_year: Dict[int, List[dict]] = defaultdict(list)
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
            if d <= 0:
                continue
            row["year"] = str(y)
            row["spotify_popularity"] = str(p)
            row["duration_ms"] = str(d)
            track_id = (row.get("id") or "").strip()
            if track_id:
                feature_ids.add(track_id)
            rows_by_year[y].append(row)

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

    kept: List[dict] = []
    total_before = sum(len(v) for v in rows_by_year.values())

    for year in sorted(rows_by_year.keys()):
        rows = rows_by_year[year]
        pops = sorted(int(r["spotify_popularity"]) for r in rows)
        cutoff = quantile(pops, 1 - args.core_hit_percent / 100)

        core = [r for r in rows if int(r["spotify_popularity"]) >= cutoff]
        rest = [r for r in rows if int(r["spotify_popularity"]) < cutoff]

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
            features = feature_by_id.get((row.get("id") or "").strip(), {})
            for field in FEATURE_FIELDS:
                output_row[field] = row.get(field) or features.get(field, "")
            w.writerow(output_row)

    print(f"Input rows: {total_before:,}")
    print(f"Output rows: {len(kept):,}")
    print(f"Feature rows matched: {len(feature_by_id):,}")
    print(f"Wrote: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
