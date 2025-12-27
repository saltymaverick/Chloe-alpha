#!/usr/bin/env python3
"""
Download and convert CryptoDataDownload Binance OHLCV data for all 12 coins.

Downloads CSVs from CryptoDataDownload and converts them to Chloe Parquet format.
Outputs to data/research_backtest/ for use in nightly research.

Usage:
    python3 -m tools.download_cryptodatadownload
"""

from __future__ import annotations

import sys
from pathlib import Path
from io import StringIO
import pandas as pd
import requests

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

BASE_URL = "https://www.cryptodatadownload.com/cdd"

# Where to store original CSVs and processed Parquets
RAW_DIR = ROOT_DIR / "data" / "raw_cryptodatadownload"
OUT_DIR = ROOT_DIR / "data" / "research_backtest"

RAW_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR.mkdir(parents=True, exist_ok=True)

SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "MATICUSDT",
    "ATOMUSDT",
    "BNBUSDT",
    "DOTUSDT",
    "ADAUSDT",
    "XRPUSDT",
    "DOGEUSDT",
]


def download_csv(sym: str) -> Path | None:
    """Download CSV from CryptoDataDownload."""
    filename = f"Binance_{sym}_1h.csv"
    url = f"{BASE_URL}/{filename}"
    out_path = RAW_DIR / filename
    
    if out_path.exists():
        print(f"[SKIP] Already have {out_path}")
        return out_path
    
    print(f"[DL] {sym} from {url}")
    try:
        resp = requests.get(url, timeout=30)
        if resp.status_code != 200:
            print(f"[WARN] Failed to download {url}: HTTP {resp.status_code}")
            return None
        
        out_path.write_bytes(resp.content)
        print(f"[OK] Saved {out_path} ({len(resp.content)} bytes)")
        return out_path
    except Exception as e:
        print(f"[ERROR] Failed to download {sym}: {e}")
        return None


def convert_to_parquet(sym: str, csv_path: Path) -> Path:
    """Convert CryptoDataDownload CSV to Chloe Parquet format."""
    print(f"[CONVERT] {csv_path.name} -> Parquet for {sym}")
    
    # CryptoDataDownload format:
    # Line 1: URL comment (https://www.CryptoDataDownload.com)
    # Line 2: Header row: Unix,Date,Symbol,Open,High,Low,Close,Volume BTC,Volume USDT,tradecount
    # Line 3+: Data rows
    
    # Read file and skip first line (URL comment)
    try:
        with csv_path.open('r') as f:
            lines = f.readlines()
            # Skip first line if it's a URL
            if lines and 'cryptodatadownload' in lines[0].lower():
                lines = lines[1:]
            # Write to temporary string buffer
            content = ''.join(lines)
            df = pd.read_csv(StringIO(content))
    except Exception as e:
        raise ValueError(f"Failed to read CSV {csv_path}: {e}")
    
    if len(df) == 0:
        raise ValueError(f"CSV is empty: {csv_path}")
    
    # CryptoDataDownload columns: Unix,Date,Symbol,Open,High,Low,Close,Volume BTC,Volume USDT,tradecount
    # We want: ts, open, high, low, close, volume
    
    # Check for Date column (capital D in CryptoDataDownload)
    date_col = None
    for candidate in ["Date", "date", "timestamp", "Timestamp"]:
        if candidate in df.columns:
            date_col = candidate
            break
    
    if date_col is None:
        raise ValueError(f"{csv_path} missing date column. Available: {list(df.columns)}")
    
    # Check OHLC columns (case-insensitive)
    ohlc_cols = {}
    for chloe_col in ["open", "high", "low", "close"]:
        found = False
        for candidate in [chloe_col.capitalize(), chloe_col.upper(), chloe_col.lower(), chloe_col]:
            if candidate in df.columns:
                ohlc_cols[chloe_col] = candidate
                found = True
                break
        if not found:
            raise ValueError(f"{csv_path} missing '{chloe_col}' column. Available: {list(df.columns)}")
    
    # Volume column: prefer Volume USDT, fallback to Volume BTC
    volume_col = None
    for candidate in ["Volume USDT", "Volume_(USDT)", "Volume USD", "Volume_(USD)", "Volume USDT", "Volume_(BTC)", "Volume BTC", "Volume_(Volume)"]:
        if candidate in df.columns:
            volume_col = candidate
            break
    
    if volume_col is None:
        # Fallback: if there's literally a 'volume' column (case-insensitive)
        for candidate in df.columns:
            if 'volume' in candidate.lower():
                volume_col = candidate
                break
        if volume_col is None:
            raise ValueError(f"{csv_path} missing a recognizable volume column. Available: {list(df.columns)}")
    
    # Build Chloe dataframe
    chloe_df = pd.DataFrame()
    # Handle date parsing - CryptoDataDownload may have milliseconds (.000)
    try:
        chloe_df["ts"] = pd.to_datetime(df[date_col], utc=True, format='mixed')
    except Exception:
        # Fallback: try without format specification
        chloe_df["ts"] = pd.to_datetime(df[date_col], utc=True, errors='coerce')
    chloe_df["open"] = pd.to_numeric(df[ohlc_cols["open"]], errors='coerce')
    chloe_df["high"] = pd.to_numeric(df[ohlc_cols["high"]], errors='coerce')
    chloe_df["low"] = pd.to_numeric(df[ohlc_cols["low"]], errors='coerce')
    chloe_df["close"] = pd.to_numeric(df[ohlc_cols["close"]], errors='coerce')
    chloe_df["volume"] = pd.to_numeric(df[volume_col], errors='coerce')
    
    # Add metadata
    chloe_df["symbol"] = sym
    chloe_df["timeframe"] = "1h"
    chloe_df["source"] = "cryptodatadownload"
    chloe_df["source_tag"] = "static"
    
    # CDD is usually newest-first, so sort ascending
    chloe_df = chloe_df.sort_values("ts").reset_index(drop=True)
    
    # Remove any rows with NaN timestamps or prices
    before = len(chloe_df)
    chloe_df = chloe_df.dropna(subset=["ts", "open", "high", "low", "close"])
    after = len(chloe_df)
    if before != after:
        print(f"   ⚠️  Removed {before - after} rows with NaN values")
    
    out_parquet = OUT_DIR / f"{sym}_1h.parquet"
    chloe_df.to_parquet(out_parquet, index=False)
    print(f"[OK] Wrote {out_parquet} with {len(chloe_df)} rows")
    print(f"     Date range: {chloe_df['ts'].min()} to {chloe_df['ts'].max()}")
    
    return out_parquet


def main():
    """Download and convert all symbols."""
    print("=" * 80)
    print("CryptoDataDownload Downloader + Converter")
    print("=" * 80)
    print(f"Raw CSVs: {RAW_DIR}")
    print(f"Output Parquets: {OUT_DIR}")
    print()
    
    downloaded = 0
    converted = 0
    errors = []
    
    for sym in SYMBOLS:
        print(f"\n{'='*80}")
        print(f"Processing {sym}")
        print(f"{'='*80}")
        
        # Download
        csv_path = download_csv(sym)
        if csv_path is None:
            errors.append(f"{sym}: Download failed")
            continue
        downloaded += 1
        
        # Convert
        try:
            convert_to_parquet(sym, csv_path)
            converted += 1
        except Exception as e:
            error_msg = f"{sym}: Conversion failed: {e}"
            print(f"[ERROR] {error_msg}")
            errors.append(error_msg)
            import traceback
            traceback.print_exc()
    
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    print(f"Downloaded: {downloaded}/{len(SYMBOLS)}")
    print(f"Converted: {converted}/{len(SYMBOLS)}")
    
    if errors:
        print(f"\nErrors ({len(errors)}):")
        for err in errors:
            print(f"  - {err}")
    
    if converted > 0:
        print(f"\n✅ Successfully converted {converted} symbols")
        print(f"\nNext steps:")
        print(f"1. Verify files: ls -lh {OUT_DIR}/*.parquet")
        print(f"2. Run nightly research:")
        print(f"   python3 -m engine_alpha.reflect.nightly_research")
        print(f"3. Check hybrid datasets:")
        print(f"   python3 -c \"import pandas as pd; df = pd.read_parquet('reports/research/BTCUSDT/hybrid_research_dataset.parquet'); print(f'BTCUSDT: {{len(df)}} rows, {{df[\\\"ts\\\"].min()}} to {{df[\\\"ts\\\"].max()}}')\"")
    else:
        print("\n⚠️  No files converted. Check errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()

