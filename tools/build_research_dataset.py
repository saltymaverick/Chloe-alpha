#!/usr/bin/env python3
"""
Build unified research dataset by merging base CSV + live candles.

Merges:
1. Base historical CSV: data/ohlcv/ETHUSDT_1h_merged.csv
2. Live candles: data/live/ETHUSDT_1h.jsonl

into:
- data/research/ETHUSDT_1h_research.csv
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime


def load_base_csv(csv_path: Path) -> List[Dict[str, Any]]:
    """Load base historical CSV."""
    if not csv_path.exists():
        return []
    
    rows = []
    with csv_path.open("r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Normalize column names
            normalized = {
                "ts": row.get("ts") or row.get("timestamp") or row.get("time"),
                "open": float(row.get("open", 0.0)),
                "high": float(row.get("high", 0.0)),
                "low": float(row.get("low", 0.0)),
                "close": float(row.get("close", 0.0)),
                "volume": float(row.get("volume", 0.0)),
            }
            if normalized["ts"]:
                rows.append(normalized)
    
    return rows


def load_live_jsonl(jsonl_path: Path) -> List[Dict[str, Any]]:
    """Load live candles from JSONL."""
    if not jsonl_path.exists():
        return []
    
    rows = []
    seen_ts = set()
    
    with jsonl_path.open("r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                ts = record.get("ts")
                if ts and ts not in seen_ts:
                    seen_ts.add(ts)
                    rows.append({
                        "ts": ts,
                        "open": float(record.get("open", 0.0)),
                        "high": float(record.get("high", 0.0)),
                        "low": float(record.get("low", 0.0)),
                        "close": float(record.get("close", 0.0)),
                        "volume": float(record.get("volume", 0.0)),
                    })
            except (json.JSONDecodeError, ValueError, TypeError):
                continue
    
    return rows


def merge_datasets(base_rows: List[Dict[str, Any]], live_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Merge base CSV + live candles.
    
    Rules:
    - Use ts as primary key
    - Start with all rows from base CSV
    - Append any live candles whose ts > last base CSV ts
    - If live ts overlaps, let base CSV win (dedupe)
    """
    if not base_rows:
        return sorted(live_rows, key=lambda x: x["ts"])
    
    if not live_rows:
        return base_rows
    
    # Build timestamp set from base CSV
    base_ts_set = {row["ts"] for row in base_rows}
    
    # Find last base timestamp
    last_base_ts = max(base_rows, key=lambda x: x["ts"])["ts"]
    
    # Parse timestamps for comparison
    try:
        last_base_dt = datetime.fromisoformat(last_base_ts.replace("Z", "+00:00"))
    except ValueError:
        # If parsing fails, just dedupe
        last_base_dt = None
    
    # Start with base rows
    merged = list(base_rows)
    
    # Add live rows that are new
    for live_row in live_rows:
        live_ts = live_row["ts"]
        
        # Skip if already in base
        if live_ts in base_ts_set:
            continue
        
        # If we can parse timestamps, only add if after last base
        if last_base_dt:
            try:
                live_dt = datetime.fromisoformat(live_ts.replace("Z", "+00:00"))
                if live_dt <= last_base_dt:
                    continue
            except ValueError:
                pass
        
        merged.append(live_row)
    
    # Sort by timestamp
    merged.sort(key=lambda x: x["ts"])
    
    return merged


def write_csv(rows: List[Dict[str, Any]], output_path: Path) -> None:
    """Write merged dataset to CSV."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with output_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["ts", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build unified research dataset from base CSV + live candles"
    )
    parser.add_argument(
        "--base",
        type=Path,
        default=Path("data/ohlcv/ETHUSDT_1h_merged.csv"),
        help="Base historical CSV file",
    )
    parser.add_argument(
        "--live",
        type=Path,
        default=Path("data/live/ETHUSDT_1h.jsonl"),
        help="Live candles JSONL file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/research/ETHUSDT_1h_research.csv"),
        help="Output merged CSV file",
    )
    args = parser.parse_args()
    
    print("=" * 80)
    print("BUILDING RESEARCH DATASET")
    print("=" * 80)
    print(f"Base CSV: {args.base}")
    print(f"Live JSONL: {args.live}")
    print(f"Output: {args.output}")
    print("=" * 80)
    
    # Load base CSV
    print(f"\n📖 Loading base CSV...")
    base_rows = load_base_csv(args.base)
    print(f"   Loaded {len(base_rows)} rows from base CSV")
    
    # Load live candles
    print(f"\n📖 Loading live candles...")
    live_rows = load_live_jsonl(args.live)
    print(f"   Loaded {len(live_rows)} rows from live JSONL")
    
    # Merge datasets
    print(f"\n🔨 Merging datasets...")
    merged = merge_datasets(base_rows, live_rows)
    print(f"   Merged dataset: {len(merged)} total rows")
    
    if len(merged) > len(base_rows):
        new_rows = len(merged) - len(base_rows)
        print(f"   ✨ Added {new_rows} new live candles")
    
    # Write output
    print(f"\n💾 Writing merged CSV...")
    write_csv(merged, args.output)
    print(f"✅ Wrote merged dataset to: {args.output}")
    
    if merged:
        first_ts = merged[0]["ts"]
        last_ts = merged[-1]["ts"]
        print(f"\n📊 Dataset range: {first_ts} → {last_ts}")


if __name__ == "__main__":
    main()


