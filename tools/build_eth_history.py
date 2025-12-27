#!/usr/bin/env python3
"""
Build full historical ETHUSDT 1h OHLCV CSV from Binance public data.

Steps:
1. Download monthly ZIPs (2019..current year, 01..12)
2. Unzip into CSVs
3. Merge into a single ETHUSDT_1h_merged.csv with header:
   timestamp,open,high,low,close,volume
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List

import zipfile
import urllib.request
import urllib.error


DATA_ROOT = Path(__file__).resolve().parents[1] / "data" / "ohlcv"
RAW_DIR = DATA_ROOT / "ETH_1h_raw"
MERGED_CSV = DATA_ROOT / "ETHUSDT_1h_merged.csv"


BASE_URL = "https://data.binance.vision/data/spot/monthly/klines/ETHUSDT/1h"


def download_file(url: str, dest: Path) -> bool:
    """
    Download a file from url to dest.
    Returns True on success, False on failure.
    """
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            print(f"  ↪ Already exists: {dest.name}")
            return True
        print(f"  ↓ Downloading {dest.name} ...")
        urllib.request.urlretrieve(url, dest)
        return True
    except urllib.error.HTTPError as e:
        print(f"  ✗ HTTPError for {dest.name}: {e.code}")
    except Exception as e:
        print(f"  ✗ Failed to download {dest.name}: {e}")
    return False


def download_monthly_zips(start_year: int = 2019, end_year: int | None = None) -> None:
    """
    Download ETHUSDT 1h monthly zip files from Binance Vision.
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    if end_year is None:
        end_year = datetime.utcnow().year

    print(f"=== Downloading ETHUSDT 1h zips {start_year}..{end_year} ===")
    for y in range(start_year, end_year + 1):
        for m in range(1, 13):
            ym = f"{y}-{m:02d}"
            fname = f"ETHUSDT-1h-{ym}.zip"
            url = f"{BASE_URL}/{fname}"
            dest = RAW_DIR / fname
            ok = download_file(url, dest)
            # If we hit current/future months, failures are expected
            time.sleep(0.1)


def unzip_all() -> List[Path]:
    """
    Unzip all .zip files in RAW_DIR into CSVs.
    Returns list of CSV paths.
    """
    csv_files: List[Path] = []
    print(f"=== Unzipping ZIP files in {RAW_DIR} ===")
    for zip_path in sorted(RAW_DIR.glob("ETHUSDT-1h-*.zip")):
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                for member in zf.namelist():
                    if member.endswith(".csv"):
                        out_path = RAW_DIR / member
                        print(f"  ↪ Extracting {zip_path.name} -> {out_path.name}")
                        zf.extract(member, RAW_DIR)
                        csv_files.append(out_path)
        except zipfile.BadZipFile:
            print(f"  ✗ Bad zip file: {zip_path}")
        except Exception as e:
            print(f"  ✗ Failed to unzip {zip_path}: {e}")
    return csv_files


def merge_csvs(csv_files: List[Path], merged_path: Path) -> None:
    """
    Merge all monthly CSVs into a single CSV with header:
    timestamp,open,high,low,close,volume
    Assumes Binance kline format: open_time,open,high,low,close,volume,...
    """
    print(f"=== Merging {len(csv_files)} CSV files into {merged_path.name} ===")

    merged_path.parent.mkdir(parents=True, exist_ok=True)
    with merged_path.open("w", newline="") as out_f:
        writer = csv.writer(out_f)
        writer.writerow(["ts", "open", "high", "low", "close", "volume"])

        for csv_path in sorted(csv_files):
            print(f"  ↪ Merging {csv_path.name}")
            with csv_path.open("r", newline="") as in_f:
                reader = csv.reader(in_f)
                header = next(reader, None)  # skip header

                for row in reader:
                    if not row:
                        continue
                    try:
                        # Binance kline CSV columns:
                        # 0: open time (ms)
                        # 1: open
                        # 2: high
                        # 3: low
                        # 4: close
                        # 5: volume
                        open_time_ms = int(row[0])
                        ts = datetime.utcfromtimestamp(open_time_ms / 1000.0).isoformat() + "Z"
                        o = row[1]
                        h = row[2]
                        l = row[3]
                        c = row[4]
                        v = row[5]
                        writer.writerow([ts, o, h, l, c, v])
                    except Exception:
                        continue


def sort_and_dedupe(merged_path: Path) -> None:
    """
    Sort merged CSV by timestamp and dedupe any duplicate rows.
    """
    print(f"=== Sorting and deduping {merged_path.name} ===")
    with merged_path.open("r", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)

        rows = [row for row in reader if row]

    # Sort by timestamp (column 0)
    rows.sort(key=lambda r: r[0])

    # Dedupe by timestamp
    deduped = []
    seen = set()
    for r in rows:
        ts = r[0]
        if ts in seen:
            continue
        seen.add(ts)
        deduped.append(r)

    tmp_path = merged_path.with_suffix(".tmp")
    with tmp_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(deduped)

    tmp_path.replace(merged_path)
    print(f"  ↪ Final rows: {len(deduped)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-year", type=int, default=2019)
    parser.add_argument("--end-year", type=int, default=None)
    args = parser.parse_args()

    print(f"DATA_ROOT: {DATA_ROOT}")
    print(f"RAW_DIR:   {RAW_DIR}")
    print(f"MERGED_CSV:{MERGED_CSV}")
    print()

    download_monthly_zips(start_year=args.start_year, end_year=args.end_year)
    csv_files = unzip_all()
    if not csv_files:
        print("✗ No CSV files found after unzipping.")
        sys.exit(1)

    merge_csvs(csv_files, MERGED_CSV)
    sort_and_dedupe(MERGED_CSV)

    print()
    print("=== Done! ===")
    print(f"Merged CSV is ready at: {MERGED_CSV}")
    print(f"Total candles: {len(csv_files)} monthly files merged")


if __name__ == "__main__":
    main()

