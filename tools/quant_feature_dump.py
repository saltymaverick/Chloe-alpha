# tools/quant_feature_dump.py

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Dict, Any

import numpy as np
import pandas as pd

from engine_alpha.signals.quant_features import compute_quant_features, QuantFeatureConfig
from engine_alpha.core.regime import classify_regime
from engine_alpha.signals.signal_processor import get_signal_vector_live
from engine_alpha.core.confidence_engine import decide
from engine_alpha.data import live_prices


def _load_csv(path: Path) -> pd.DataFrame:
    """Load CSV and convert to DataFrame with proper timestamp index."""
    df = pd.read_csv(path)
    
    # Handle different timestamp column names
    ts_col = None
    for col in ['ts', 'timestamp', 'time']:
        if col in df.columns:
            ts_col = col
            break
    
    if ts_col:
        df[ts_col] = pd.to_datetime(df[ts_col])
        df = df.set_index(ts_col)
    else:
        # If no timestamp column, use row number as index
        df.index = pd.date_range(start='2020-01-01', periods=len(df), freq='1h')
    
    df = df.sort_index()
    
    # Ensure we have required columns (case-insensitive)
    required_cols = {'open', 'high', 'low', 'close'}
    df_cols_lower = {c.lower(): c for c in df.columns}
    
    for req_col in required_cols:
        if req_col not in df.columns and req_col not in df_cols_lower:
            raise ValueError(f"Missing required column: {req_col}")
    
    # Normalize column names to lowercase
    rename_map = {}
    for col in df.columns:
        if col.lower() in required_cols and col != col.lower():
            rename_map[col] = col.lower()
    if rename_map:
        df = df.rename(columns=rename_map)
    
    return df


def _df_to_rows(df: pd.DataFrame) -> list[dict]:
    """Convert DataFrame to list of dicts for classify_regime."""
    rows = []
    for idx, row in df.iterrows():
        ts_str = idx.isoformat() if hasattr(idx, 'isoformat') else str(idx)
        rows.append({
            'ts': ts_str,
            'open': float(row.get('open', 0.0)),
            'high': float(row.get('high', 0.0)),
            'low': float(row.get('low', 0.0)),
            'close': float(row.get('close', 0.0)),
            'volume': float(row.get('volume', 0.0)) if 'volume' in row else 0.0,
        })
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="Dump quant windows + Chloe decisions to JSONL")
    ap.add_argument("--symbol", default="ETHUSDT")
    ap.add_argument("--timeframe", default="1h")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--window", type=int, default=200)
    ap.add_argument("--horizon", type=int, default=1, help="Forward return horizon in bars")
    ap.add_argument("--output", default="reports/analysis/quant_windows.jsonl")
    args = ap.parse_args()

    csv_path = Path(args.csv)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not csv_path.exists():
        raise SystemExit(f"CSV file not found: {csv_path}")

    print(f"Loading CSV: {csv_path}")
    df = _load_csv(csv_path)
    print(f"Loaded {len(df)} rows")
    
    print("Computing quant features...")
    df_feat = compute_quant_features(df)
    print(f"Features computed, {len(df_feat)} rows")

    records = []
    total = len(df_feat) - args.window - args.horizon
    
    if total <= 0:
        raise SystemExit(f"Not enough data: need {args.window + args.horizon} rows, got {len(df_feat)}")

    print(f"Processing {total} windows...")
    
    # Store original get_live_ohlcv to restore later
    original_get_live_ohlcv = live_prices.get_live_ohlcv

    try:
        for i in range(args.window, len(df_feat) - args.horizon):
            window_df = df_feat.iloc[i - args.window : i].copy()
            current_row = df_feat.iloc[i]
            future_row = df_feat.iloc[i + args.horizon]

            ts = current_row.name.isoformat() if hasattr(current_row.name, 'isoformat') else str(current_row.name)

            # Convert window DataFrame to rows for classify_regime
            window_rows = _df_to_rows(window_df)
            
            # Regime from price-based classifier
            regime_result = classify_regime(window_rows)
            if isinstance(regime_result, dict):
                regime = regime_result.get("regime", "chop")
                regime_metrics = regime_result.get("metrics", {})
            else:
                # Fallback if classify_regime returns just a string
                regime = str(regime_result) if isinstance(regime_result, str) else "chop"
                regime_metrics = {}

            # Mock get_live_ohlcv to return our window data
            def mock_get_live_ohlcv(symbol: str, timeframe: str, limit: int = 200, no_cache: bool = True):
                return window_rows[-limit:] if len(window_rows) >= limit else window_rows
            
            live_prices.get_live_ohlcv = mock_get_live_ohlcv

            # Chloe's signal vector and confidence
            try:
                signal_result = get_signal_vector_live(
                    symbol=args.symbol,
                    timeframe=args.timeframe,
                    limit=args.window,
                )
                signal_vec = signal_result.get("signal_vector", [])
                raw_registry = signal_result.get("raw_registry", {})
                
                decision = decide(signal_vec, raw_registry, regime_override=regime)
                final = decision.get("final", {})
                
                final_dir = final.get("dir", 0)
                final_conf = float(final.get("conf", 0.0))
            except Exception as e:
                # If signal processing fails, use defaults
                print(f"Warning: signal processing failed at {ts}: {e}")
                final_dir = 0
                final_conf = 0.0

            # Forward return
            ret_fwd = float((future_row["close"] / current_row["close"]) - 1.0)

            feat_subset: Dict[str, Any] = {
                "ret_1h": float(current_row.get("ret_1h_clipped", np.nan)) if not pd.isna(current_row.get("ret_1h_clipped", np.nan)) else None,
                "ret_4h": float(current_row.get("ret_4h_clipped", np.nan)) if not pd.isna(current_row.get("ret_4h_clipped", np.nan)) else None,
                "ret_24h": float(current_row.get("ret_24h_clipped", np.nan)) if not pd.isna(current_row.get("ret_24h_clipped", np.nan)) else None,
                "vol_14": float(current_row.get("vol_14", np.nan)) if not pd.isna(current_row.get("vol_14", np.nan)) else None,
                "vol_50": float(current_row.get("vol_50", np.nan)) if not pd.isna(current_row.get("vol_50", np.nan)) else None,
                "atr_14": float(current_row.get("atr_14", np.nan)) if not pd.isna(current_row.get("atr_14", np.nan)) else None,
                "atr_50": float(current_row.get("atr_50", np.nan)) if not pd.isna(current_row.get("atr_50", np.nan)) else None,
                "ema_fast_slope": float(current_row.get("ema_fast_slope", np.nan)) if not pd.isna(current_row.get("ema_fast_slope", np.nan)) else None,
                "ema_slow_slope": float(current_row.get("ema_slow_slope", np.nan)) if not pd.isna(current_row.get("ema_slow_slope", np.nan)) else None,
                "rsi": float(current_row.get("rsi", np.nan)) if not pd.isna(current_row.get("rsi", np.nan)) else None,
                "bb_width": float(current_row.get("bb_width", np.nan)) if not pd.isna(current_row.get("bb_width", np.nan)) else None,
                "kc_width": float(current_row.get("kc_width", np.nan)) if not pd.isna(current_row.get("kc_width", np.nan)) else None,
                "squeeze_on": int(current_row.get("squeeze_on", 0)),
            }

            rec = {
                "ts": ts,
                "symbol": args.symbol,
                "timeframe": args.timeframe,
                "regime": regime,
                "final_dir": final_dir,
                "final_conf": round(final_conf, 2),
                "forward_ret": ret_fwd,
                "features": feat_subset,
                "regime_metrics": regime_metrics,
            }
            records.append(rec)

            if (i - args.window) % 2000 == 0 and (i - args.window) > 0:
                print(f"Progress: {i - args.window}/{total} ({100.0 * (i - args.window) / total:.1f}%)")

    finally:
        # Restore original get_live_ohlcv
        live_prices.get_live_ohlcv = original_get_live_ohlcv

    with out_path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    print(f"\n✅ Wrote {len(records)} records to {out_path}")


if __name__ == "__main__":
    main()


