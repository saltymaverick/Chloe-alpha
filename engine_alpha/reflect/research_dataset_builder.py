"""
Research Dataset Builder - Hybrid dataset with forward returns (Multi-Asset)

Builds per-symbol hybrid datasets mixing static historical data, live candles, and trade outcomes.
Enriches with forward return columns (ret_1h, ret_2h, ret_4h) for multi-horizon analysis.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Tuple

import json
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
OHLVC_DIR = DATA_DIR / "ohlcv"
REPORTS_DIR = ROOT_DIR / "reports"
RESEARCH_ROOT = REPORTS_DIR / "research"

# Legacy path for backward compatibility
RESEARCH_DIR = RESEARCH_ROOT
RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
HYBRID_DATASET_PATH = RESEARCH_DIR / "hybrid_research_dataset.parquet"


def _symbol_research_dir(symbol: str) -> Path:
    """Get per-symbol research directory."""
    d = RESEARCH_ROOT / symbol
    d.mkdir(parents=True, exist_ok=True)
    return d


def _hybrid_path(symbol: str) -> Path:
    """Get per-symbol hybrid dataset path."""
    return _symbol_research_dir(symbol) / "hybrid_research_dataset.parquet"


def _resolve_forward_horizons(timeframe: str) -> Dict[str, int]:
    """
    Return mapping of forward-return labels -> bars ahead for the given timeframe.
    """
    tf = timeframe.lower()
    if tf in {"15m", "15", "15min"}:
        return {"1h": 4, "2h": 8, "4h": 16}
    if tf in {"30m", "30", "30min"}:
        return {"1h": 2, "2h": 4, "4h": 8}
    # Default: assume 1 bar = 1h
    return {"1h": 1, "2h": 2, "4h": 4}


def load_static_dataset(path: Optional[Path]) -> pd.DataFrame:
    """Load static historical dataset (CSV or Parquet)."""
    if not path:
        return pd.DataFrame()
    if not path.exists():
        return pd.DataFrame()

    if path.suffix == ".parquet":
        df = pd.read_parquet(path)
    elif path.suffix == ".csv":
        df = pd.read_csv(path)
    else:
        raise ValueError(f"Unsupported static dataset format: {path}")

    if "ts" in df.columns:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    if "source_tag" not in df.columns:
        df["source_tag"] = "static"
    return df


def load_live_candles(symbol: str, timeframe: str) -> pd.DataFrame:
    """Load live candles from CSV file."""
    live_path = OHLVC_DIR / f"{symbol.lower()}_{timeframe.lower()}_live.csv"
    if not live_path.exists():
        return pd.DataFrame()

    df = pd.read_csv(live_path)
    if "ts" in df.columns:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df["symbol"] = symbol
    df["timeframe"] = timeframe
    df["source_tag"] = "live"
    df = df.sort_values("ts").reset_index(drop=True)
    return df


def load_trade_outcomes(symbol: str) -> pd.DataFrame:
    """
    Load per-symbol trade outcomes. Assumes a global trade_outcomes.jsonl
    with a 'symbol' field. Filters to the requested symbol.
    """
    path = RESEARCH_ROOT / "trade_outcomes.jsonl"
    if not path.exists():
        return pd.DataFrame()

    records = []
    with path.open("r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("symbol") == symbol:
                records.append(rec)

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    if "entry_ts" in df.columns:
        df["entry_ts"] = pd.to_datetime(df["entry_ts"], utc=True)
    if "exit_ts" in df.columns:
        df["exit_ts"] = pd.to_datetime(df["exit_ts"], utc=True)
    return df


def _add_forward_returns(
    df: pd.DataFrame,
    horizons_bars: Dict[str, int],
    close_col: str = "close",
    ts_col: str = "ts",
) -> pd.DataFrame:
    """
    Add forward returns (e.g. ret_1h, ret_2h, ret_4h) based on close, using
    a mapping of label -> bars ahead.
    """
    if close_col not in df.columns or ts_col not in df.columns:
        return df

    existing_ret_cols = {c for c in df.columns if c.startswith("ret_")}
    df = df.sort_values(ts_col).reset_index(drop=True)

    group_cols = []
    if "symbol" in df.columns:
        group_cols.append("symbol")
    if "timeframe" in df.columns:
        group_cols.append("timeframe")

    def _compute_group(g: pd.DataFrame) -> pd.DataFrame:
        g = g.sort_values(ts_col).reset_index(drop=True)
        close = g[close_col]

        for label, bars_ahead in horizons_bars.items():
            col_name = f"ret_{label}"
            if col_name in existing_ret_cols:
                continue
            fwd = close.shift(-bars_ahead)
            g[col_name] = (fwd - close) / close
        return g

    if group_cols:
        df = df.groupby(group_cols, group_keys=False).apply(_compute_group)
    else:
        df = _compute_group(df)

    return df


def build_hybrid_research_dataset(
    symbol: str = "ETHUSDT",
    timeframe: str = "15m",
    static_dataset_path: Optional[Path] = None,
    output_path: Optional[Path] = None,
) -> Tuple[Path, int]:
    """
    Build per-symbol hybrid dataset (live candles + trade outcomes).
    
    Only uses live data unless a static_dataset_path is provided.
    Writes to: reports/research/{symbol}/hybrid_research_dataset.parquet
    
    Returns (path, num_rows).
    """
    # Use per-symbol path by default
    if output_path is None:
        output_path = _hybrid_path(symbol)
    
    research_dir = output_path.parent
    research_dir.mkdir(parents=True, exist_ok=True)

    # For now, static dataset is optional (live only)
    static_df = pd.DataFrame()
    if static_dataset_path and static_dataset_path.exists():
        static_df = load_static_dataset(static_dataset_path)
        if not static_df.empty:
            static_df["symbol"] = symbol
            static_df["timeframe"] = timeframe

    live_df = load_live_candles(symbol, timeframe)
    trades_df = load_trade_outcomes(symbol)

    frames = []
    if not static_df.empty:
        frames.append(static_df)
    if not live_df.empty:
        frames.append(live_df)

    if not frames:
        # No data
        if output_path.exists():
            output_path.unlink()
        return output_path, 0

    hybrid = pd.concat(frames, ignore_index=True)

    # Optional: join trade info (if desired) near entry_ts
    # For now we keep trades separate; analyzer can use trade_outcomes directly if needed.

    # --- Merge Glassnode metrics (if available) ---
    try:
        from engine_alpha.data.glassnode_fetcher import load_cached_glassnode_metrics
        gn_df = load_cached_glassnode_metrics(symbol)
        if not gn_df.empty:
            hybrid = hybrid.merge(gn_df, on="ts", how="left")
            print(f"[HYBRID] Merged {len(gn_df.columns)-1} Glassnode metrics for {symbol}")
        else:
            # Optionally, you could call fetch_glassnode_metrics_for_symbol here
            pass
    except Exception as e:
        print(f"[HYBRID] Glassnode merge failed for {symbol}: {e}")
    # --- END Glassnode merge ---

    hybrid = hybrid.sort_values("ts").reset_index(drop=True)
    horizons = _resolve_forward_horizons(timeframe)
    hybrid = _add_forward_returns(hybrid, horizons_bars=horizons)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    hybrid.to_parquet(output_path)

    return output_path, len(hybrid)


def _iter_enabled_assets():
    try:
        from engine_alpha.config.assets import get_enabled_assets

        return get_enabled_assets()
    except Exception:
        return []


def build_all_hybrid_datasets(timeframe: Optional[str] = None) -> None:
    assets = _iter_enabled_assets()
    if not assets:
        print("⚠️  No enabled assets found; nothing to build.")
        return
    for asset in assets:
        tf = timeframe or getattr(asset, "base_timeframe", "15m")
        print(f"🧱 Building hybrid dataset for {asset.symbol} @ {tf} ...")
        build_hybrid_research_dataset(symbol=asset.symbol, timeframe=tf)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build hybrid research datasets.")
    parser.add_argument("--symbol", help="Symbol to build (default: ETHUSDT)")
    parser.add_argument("--timeframe", default="15m", help="Timeframe (default: 15m)")
    parser.add_argument("--static", help="Optional static dataset path")
    parser.add_argument("--all", action="store_true", help="Build for all enabled assets")
    args = parser.parse_args()

    static_path = Path(args.static).resolve() if args.static else None

    if args.all:
        build_all_hybrid_datasets(timeframe=args.timeframe)
    else:
        sym = args.symbol or "ETHUSDT"
        p, n = build_hybrid_research_dataset(symbol=sym.upper(), timeframe=args.timeframe, static_dataset_path=static_path)
        print(f"Hybrid research dataset for {sym.upper()} @ {args.timeframe} -> {p} ({n} rows)")
