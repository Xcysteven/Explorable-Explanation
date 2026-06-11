#!/usr/bin/env python3
"""Build lazy-loaded song search shards from the full enriched dataset.

The main page should not download a full million-row CSV on load. This script
splits the feature-complete rows into shard files that are fetched only when a
user searches.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Set


FIELDNAMES = [
    "id",
    "name",
    "artists",
    "duration_ms",
    "year",
    "explicit",
    "spotify_popularity",
    "danceability",
    "energy",
    "acousticness",
    "valence",
    "tempo",
]

SIMPLIFIED_TO_TRADITIONAL = str.maketrans({
    "爱": "愛",
    "边": "邊",
    "变": "變",
    "长": "長",
    "车": "車",
    "尘": "塵",
    "从": "從",
    "灯": "燈",
    "点": "點",
    "东": "東",
    "对": "對",
    "发": "發",
    "风": "風",
    "广": "廣",
    "国": "國",
    "过": "過",
    "后": "後",
    "华": "華",
    "欢": "歡",
    "会": "會",
    "间": "間",
    "见": "見",
    "将": "將",
    "节": "節",
    "进": "進",
    "来": "來",
    "乐": "樂",
    "里": "裡",
    "恋": "戀",
    "梦": "夢",
    "们": "們",
    "难": "難",
    "气": "氣",
    "亲": "親",
    "让": "讓",
    "声": "聲",
    "时": "時",
    "说": "說",
    "台": "臺",
    "听": "聽",
    "万": "萬",
    "为": "為",
    "无": "無",
    "现": "現",
    "学": "學",
    "阳": "陽",
    "样": "樣",
    "叶": "葉",
    "义": "義",
    "阴": "陰",
    "拥": "擁",
    "与": "與",
    "云": "雲",
    "这": "這",
    "种": "種",
    "钟": "鐘",
    "转": "轉",
})


def normalize_text(value: str) -> str:
    value = (value or "").lower().translate(SIMPLIFIED_TO_TRADITIONAL)
    return re.sub(r"\s+", " ", value).strip()


def latin_tokens(value: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", normalize_text(value))


def has_cjk(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def shard_keys(row: dict, max_keys: int) -> Set[str]:
    name = normalize_text(row.get("name", ""))
    artists = normalize_text(row.get("artists", ""))
    text = f"{name} {artists}".strip()
    keys: Set[str] = set()

    # Artist tokens are prioritized so searches like "jay chou" still find
    # Chinese-titled rows where the Latin artist name appears after the title.
    ordered_tokens = [*latin_tokens(artists), *latin_tokens(name)]

    for token in ordered_tokens:
        if token:
            keys.add(token[0])
        if len(keys) >= max_keys:
            break

    if has_cjk(text):
        keys.add("cjk")

    if not keys:
        keys.add("other")

    return keys


def valid_row(row: dict, min_year: int, max_year: int) -> bool:
    try:
        year = int(float(row.get("year", "")))
        duration = int(float(row.get("duration_ms", "")))
    except ValueError:
        return False

    if year < min_year or year > max_year:
        return False
    if duration <= 0 or duration > 15 * 60000:
        return False
    if not (row.get("id") or "").strip():
        return False
    return True


def compact_row(row: dict) -> dict:
    return {field: row.get(field, "") for field in FIELDNAMES}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="tracks_features_with_popularity.csv")
    ap.add_argument("--output-dir", default="search-index")
    ap.add_argument("--min-year", type=int, default=1980)
    ap.add_argument("--max-year", type=int, default=2020)
    ap.add_argument("--max-keys-per-row", type=int, default=5)
    args = ap.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    if not input_path.exists():
        raise SystemExit(f"Missing input: {input_path}")

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    writers: Dict[str, csv.DictWriter] = {}
    files = {}
    counts = Counter()
    unique_tracks = 0

    def writer_for(key: str) -> csv.DictWriter:
        if key in writers:
            return writers[key]
        path = output_dir / f"{key}.csv"
        f = path.open("w", encoding="utf-8", newline="")
        files[key] = f
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, lineterminator="\n")
        writer.writeheader()
        writers[key] = writer
        return writer

    with input_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not valid_row(row, args.min_year, args.max_year):
                continue
            unique_tracks += 1
            output_row = compact_row(row)
            for key in shard_keys(row, args.max_keys_per_row):
                writer_for(key).writerow(output_row)
                counts[key] += 1

    for f in files.values():
        f.close()

    shards = []
    for key in sorted(counts):
        path = output_dir / f"{key}.csv"
        shards.append({
            "key": key,
            "file": f"{key}.csv",
            "rows": counts[key],
            "bytes": path.stat().st_size,
        })

    manifest = {
        "schemaVersion": 1,
        "minYear": args.min_year,
        "maxYear": args.max_year,
        "uniqueTracks": unique_tracks,
        "shards": shards,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )

    total_bytes = sum(item["bytes"] for item in shards)
    print(f"Unique tracks indexed: {unique_tracks:,}")
    print(f"Shard rows written: {sum(counts.values()):,}")
    print(f"Shards: {len(shards):,}")
    print(f"Total shard bytes: {total_bytes / 1024 / 1024:.1f} MB")
    print(f"Wrote: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
