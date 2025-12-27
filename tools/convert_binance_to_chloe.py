#!/usr/bin/env python3
"""
Convert Binance historical CSV data to Chloe's Parquet format.

Handles common Binance CSV formats and converts to Chloe's expected structure:
- ts (ISO8601 with timezone)
- symbol, timeframe
- open, high, low, close, volume
- source tag

Usage:
    python3 -m tools.convert_binance_to_chloe --input binance_data/BTCUSDT_1h.csv --symbol BTCUSDT --timeframe 1h
    python3 -m tools.convert_binance_to_chloe --dir binance_data/ --timeframe 1h
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Dict, Any
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

DATA_DIR = ROOT_DIR / "data"
OHLVC_DIR = DATA_DIR / "ohlcv"


def detect_binance_format(df: pd.DataFrame) -> Dict[str, str]:
    """
    Detect Binance CSV column mapping.
    Returns dict mapping Chloe columns to Binance columns.
    """
    cols_lower = {c.lower(): c for c in df.columns}
    
    mapping = {}
    
    # Timestamp detection (common formats)
    if "timestamp" in cols_lower:
        mapping["ts"] = cols_lower["timestamp"]
    elif "open_time" in cols_lower:
        mapping["ts"] = cols_lower["open_time"]
    elif "time" in cols_lower:
        mapping["ts"] = cols_lower["time"]
    elif "date" in cols_lower:
        mapping["ts"] = cols_lower["date"]
    else:
        raise ValueError(f"Could not detect timestamp column. Available: {list(df.columns)}")
    
    # OHLCV detection
    for chloe_col in ["open", "high", "low", "close", "volume"]:
        if chloe_col in cols_lower:
            mapping[chloe_col] = cols_lower[chloe_col]
        elif f"{chloe_col}_price" in cols_lower:
            mapping[chloe_col] = cols_lower[f"{chloe_col}_price"]
        elif chloe_col == "volume" and "vol" in cols_lower:
            mapping[chloe_col] = cols_lower["vol"]
        else:
            raise ValueError(f"Could not detect {chloe_col} column. Available: {list(df.columns)}")
    
    return mapping


def parse_timestamp(ts_val: Any) -> pd.Timestamp:
    """Parse timestamp from various formats."""
    if pd.isna(ts_val):
        raise ValueError("Timestamp is NaN")
    
    # Try pandas parsing first
    try:
        ts = pd.to_datetime(ts_val, utc=True)
        return ts
    except Exception:
        pass
    
    # Try unix timestamp (seconds or milliseconds)
    try:
        ts_float = float(ts_val)
        if ts_float > 1e12:  # milliseconds
            ts = pd.to_datetime(ts_float, unit='ms', utc=True)
        else:  # seconds
            ts = pd.to_datetime(ts_float, unit='s', utc=True)
        return ts
    except Exception:
        pass
    
    raise ValueError(f"Could not parse timestamp: {ts_val}")


def convert_binance_csv(
    input_path: Path,
    symbol: str,
    timeframe: str,
    output_path: Optional[Path] = None,
) -> Path:
    """
    Convert a single Binance CSV to Chloe Parquet format.
    
    Returns:
        Path to output Parquet file
    """
    print(f"📥 Reading {input_path}...")
    
    # Read CSV (try common separators)
    try:
        df = pd.read_csv(input_path)
    except Exception as e:
        # Try with different separator
        try:
            df = pd.read_csv(input_path, sep=';')
        except Exception:
            raise ValueError(f"Failed to read CSV: {e}")
    
    if len(df) == 0:
        raise ValueError(f"CSV is empty: {input_path}")
    
    print(f"   Found {len(df)} rows, columns: {list(df.columns)}")
    
    # Detect column mapping
    mapping = detect_binance_format(df)
    print(f"   Detected mapping: {mapping}")
    
    # Build Chloe dataframe
    chloe_df = pd.DataFrame()
    
    # Parse timestamp
    ts_col = mapping["ts"]
    chloe_df["ts"] = df[ts_col].apply(parse_timestamp)
    
    # Add OHLCV
    for chloe_col in ["open", "high", "low", "close", "volume"]:
        binance_col = mapping[chloe_col]
        chloe_df[chloe_col] = pd.to_numeric(df[binance_col], errors='coerce')
    
    # Add metadata
    chloe_df["symbol"] = symbol.upper()
    chloe_df["timeframe"] = timeframe.lower()
    chloe_df["source"] = "binance_historical"
    chloe_df["source_tag"] = "static"
    
    # Sort by timestamp
    chloe_df = chloe_df.sort_values("ts").reset_index(drop=True)
    
    # Remove any rows with NaN timestamps or prices
    before = len(chloe_df)
    chloe_df = chloe_df.dropna(subset=["ts", "open", "high", "low", "close"])
    after = len(chloe_df)
    if before != after:
        print(f"   ⚠️  Removed {before - after} rows with NaN values")
    
    # Determine output path
    if output_path is None:
        # Use Chloe's standard path: data/ohlcv/{symbol}_{timeframe}_historical.parquet
        output_path = OHLVC_DIR / f"{symbol.lower()}_{timeframe.lower()}_historical.parquet"
    
    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Write Parquet
    chloe_df.to_parquet(output_path, index=False)
    print(f"✅ Wrote {len(chloe_df)} rows to {output_path}")
    print(f"   Date range: {chloe_df['ts'].min()} to {chloe_df['ts'].max()}")
    
    return output_path


def convert_directory(
    input_dir: Path,
    timeframe: str,
    pattern: str = "*_*.csv",
) -> list[Path]:
    """
    Convert all matching CSV files in a directory.
    
    Assumes filename format: {SYMBOL}_{TIMEFRAME}.csv or similar.
    """
    csv_files = list(input_dir.glob(pattern))
    
    if not csv_files:
        print(f"⚠️  No CSV files found matching {pattern} in {input_dir}")
        return []
    
    print(f"Found {len(csv_files)} CSV files to convert")
    
    converted = []
    for csv_file in csv_files:
        # Try to extract symbol from filename
        # Common patterns: BTCUSDT_1h.csv, BTC-USDT_1h.csv, BTCUSDT.csv
        stem = csv_file.stem
        parts = stem.split('_')
        
        if len(parts) >= 1:
            symbol = parts[0].upper().replace('-', '')
            # Ensure it ends with USDT
            if not symbol.endswith('USDT'):
                symbol = f"{symbol}USDT"
        else:
            print(f"⚠️  Could not extract symbol from {csv_file.name}, skipping")
            continue
        
        try:
            output_path = convert_binance_csv(
                csv_file,
                symbol=symbol,
                timeframe=timeframe,
            )
            converted.append(output_path)
        except Exception as e:
            print(f"❌ Failed to convert {csv_file.name}: {e}")
            import traceback
            traceback.print_exc()
    
    return converted


def main():
    parser = argparse.ArgumentParser(
        description="Convert Binance CSV to Chloe Parquet format",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Convert single file
  python3 -m tools.convert_binance_to_chloe --input binance_data/BTCUSDT_1h.csv --symbol BTCUSDT --timeframe 1h
  
  # Convert all CSVs in directory
  python3 -m tools.convert_binance_to_chloe --dir binance_data/ --timeframe 1h
  
  # Convert with custom output path
  python3 -m tools.convert_binance_to_chloe --input BTC.csv --symbol BTCUSDT --timeframe 1h --output data/ohlcv/btcusdt_1h_historical.parquet
        """
    )
    
    parser.add_argument("--input", type=str, help="Input CSV file path")
    parser.add_argument("--dir", type=str, help="Directory containing CSV files")
    parser.add_argument("--symbol", type=str, help="Symbol (e.g. BTCUSDT). Required if --input specified.")
    parser.add_argument("--timeframe", type=str, default="1h", help="Timeframe (default: 1h)")
    parser.add_argument("--output", type=str, help="Output Parquet path (optional, auto-generated if not specified)")
    parser.add_argument("--pattern", type=str, default="*_*.csv", help="Glob pattern for CSV files in directory (default: *_*.csv)")
    
    args = parser.parse_args()
    
    if not args.input and not args.dir:
        parser.error("Specify either --input FILE or --dir DIRECTORY")
    
    if args.input and not args.symbol:
        parser.error("--symbol is required when using --input")
    
    converted = []
    
    if args.input:
        # Single file conversion
        input_path = Path(args.input)
        if not input_path.exists():
            print(f"❌ Input file not found: {input_path}")
            sys.exit(1)
        
        output_path = Path(args.output) if args.output else None
        result = convert_binance_csv(
            input_path,
            symbol=args.symbol,
            timeframe=args.timeframe,
            output_path=output_path,
        )
        converted.append(result)
    
    elif args.dir:
        # Directory conversion
        input_dir = Path(args.dir)
        if not input_dir.exists():
            print(f"❌ Directory not found: {input_dir}")
            sys.exit(1)
        
        converted = convert_directory(
            input_dir,
            timeframe=args.timeframe,
            pattern=args.pattern,
        )
    
    print(f"\n✅ Conversion complete: {len(converted)} file(s) converted")
    print(f"\nNext steps:")
    print(f"1. Verify files: ls -lh {OHLVC_DIR}/*_historical.parquet")
    print(f"2. Run nightly research to merge historical data:")
    print(f"   python3 -m engine_alpha.reflect.nightly_research")


if __name__ == "__main__":
    main()


