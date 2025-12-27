"""
Weighted Multi-Horizon Analyzer - Hybrid Self-Learning Mode

Analyzes hybrid dataset with weighted statistics to overweight recent live data.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

try:
    import pandas as pd
except ImportError:
    pd = None

ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT_DIR / "config"
REPORTS_DIR = ROOT_DIR / "reports"
RESEARCH_DIR = REPORTS_DIR / "research"
RESEARCH_ROOT = RESEARCH_DIR

WEIGHTS_CFG_PATH = CONFIG_DIR / "research_weights.json"
ANALYZER_OUT_PATH = RESEARCH_DIR / "multi_horizon_stats.json"


def _symbol_research_dir(symbol: str) -> Path:
    """Get per-symbol research directory."""
    d = RESEARCH_ROOT / symbol
    d.mkdir(parents=True, exist_ok=True)
    return d


def _analyzer_output_path(symbol: str) -> Path:
    """Get per-symbol analyzer output path."""
    return _symbol_research_dir(symbol) / "multi_horizon_stats.json"


@dataclass
class WeightsConfig:
    source_weights: Dict[str, float]
    recency_half_life_days: float
    min_trades_per_regime: int
    min_weighted_trades_per_regime: float
    max_threshold_step_per_night: float
    min_expectancy_edge: float


def load_weights_config(path: Path = WEIGHTS_CFG_PATH) -> WeightsConfig:
    """Load research weights configuration."""
    if not path.exists():
        # Return defaults
        return WeightsConfig(
            source_weights={"static": 1.0, "live": 3.0},
            recency_half_life_days=14.0,
            min_trades_per_regime=40,
            min_weighted_trades_per_regime=30.0,
            max_threshold_step_per_night=0.05,
            min_expectancy_edge=0.0005,
        )
    
    with path.open("r") as f:
        cfg = json.load(f)
    
    return WeightsConfig(
        source_weights=cfg.get("source_weights", {"static": 1.0, "live": 3.0}),
        recency_half_life_days=float(cfg.get("recency_half_life_days", 14)),
        min_trades_per_regime=int(cfg.get("min_trades_per_regime", 40)),
        min_weighted_trades_per_regime=float(cfg.get("min_weighted_trades_per_regime", 30.0)),
        max_threshold_step_per_night=float(cfg.get("max_threshold_step_per_night", 0.05)),
        min_expectancy_edge=float(cfg.get("min_expectancy_edge", 0.0005)),
    )


def _compute_recency_weight(ts_series: pd.Series, half_life_days: float) -> pd.Series:
    """Compute exponential decay weights based on recency."""
    if ts_series.empty:
        return ts_series
    
    max_ts = ts_series.max()
    if hasattr(max_ts, 'tz'):
        max_ts = pd.Timestamp(max_ts).tz_convert("UTC") if ts_series.dt.tz else pd.Timestamp(max_ts)
    else:
        max_ts = pd.Timestamp(max_ts)
    
    age_days = (max_ts - ts_series).dt.total_seconds() / 86400.0
    # Exponential decay: w = 0.5 ** (age_days / half_life_days)
    return (0.5 ** (age_days / half_life_days)).astype("float32")


def _prepare_weighted_df(dataset_path: Path, weights_cfg: WeightsConfig) -> pd.DataFrame:
    """Load dataset and compute weights."""
    if pd is None:
        raise ImportError("pandas is required for weighted analyzer")
    
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset_path}")

    if dataset_path.suffix == ".parquet":
        df = pd.read_parquet(dataset_path)
    elif dataset_path.suffix == ".csv":
        df = pd.read_csv(dataset_path)
    else:
        raise ValueError(f"Unsupported dataset format: {dataset_path.suffix}")

    if "ts" not in df.columns:
        raise ValueError("Dataset must have 'ts' column with timestamps")

    df["ts"] = pd.to_datetime(df["ts"], utc=True)

    # Base source weights
    if "source_tag" not in df.columns:
        df["source_tag"] = "static"
    base_weight = df["source_tag"].map(weights_cfg.source_weights).fillna(1.0)

    # Recency weights
    recency_w = _compute_recency_weight(df["ts"], weights_cfg.recency_half_life_days)

    df["weight"] = (base_weight * recency_w).astype("float32")

    return df


def _weighted_stats(group: pd.DataFrame, ret_col: str) -> Dict:
    """Compute weighted statistics for a group."""
    w = group["weight"].values
    r = group[ret_col].values

    if len(r) == 0 or w.sum() <= 0:
        return {
            "count": 0,
            "weighted_count": 0.0,
            "mean": 0.0,
            "std": 0.0,
            "hit_rate": 0.0,
        }

    w_sum = w.sum()
    mean = (w * r).sum() / w_sum

    # Weighted variance
    diff = r - mean
    var = (w * diff * diff).sum() / w_sum
    std = math.sqrt(max(var, 0.0))

    hit_rate = float((w[r > 0].sum() / w_sum)) if w_sum > 0 else 0.0

    return {
        "count": int(len(r)),
        "weighted_count": float(w_sum),
        "mean": float(mean),
        "std": float(std),
        "hit_rate": float(hit_rate),
    }


def _compute_regime_confidence(
    df: "pd.DataFrame",
    symbol: str = "ETHUSDT",
    timeframe: str = "1h",
    window: int = 200,
) -> "pd.DataFrame":
    """
    Compute regime and confidence for each row using Chloe's signal pipeline.
    
    This runs the same logic as signal_return_analyzer to compute regime
    and confidence on-the-fly from OHLCV data.
    """
    import sys
    import os
    sys.path.insert(0, str(ROOT_DIR))
    
    from engine_alpha.core.regime import classify_regime
    from engine_alpha.signals import signal_processor
    from engine_alpha.data import live_prices
    from engine_alpha.core.confidence_engine import decide, REGIME_BUCKET_WEIGHTS, BUCKET_ORDER
    from engine_alpha.loop.autonomous_trader import NEUTRAL_THRESHOLD
    
    # Add regime and confidence columns
    df["regime"] = "chop"
    df["confidence"] = 0.0
    
    # Set MODE to PAPER for consistency
    os.environ.setdefault("MODE", "PAPER")
    
    # Store original functions for restoration
    original_get_live_ohlcv = live_prices.get_live_ohlcv
    original_signal_get_live_ohlcv = getattr(signal_processor, 'get_live_ohlcv', None)
    
    # Process in windows (sliding window approach)
    total = len(df) - window
    progress_interval = max(1, total // 20) if total > 0 else 1
    
    try:
        for i in range(window, len(df)):
            if (i - window) % progress_interval == 0:
                pct = ((i - window) / total) * 100 if total > 0 else 0
                print(f"   Computing regime/confidence: {pct:.1f}% ({i - window}/{total})")
            
            # Build window ending at current bar
            window_start = i - window + 1
            window_candles = df.iloc[window_start:i + 1].copy()
            
            # Convert DataFrame to list of dicts (format expected by signal processor)
            window_rows = []
            for _, row in window_candles.iterrows():
                window_rows.append({
                    "ts": row["ts"].isoformat() if hasattr(row["ts"], "isoformat") else str(row["ts"]),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("volume", 0.0)),
                })
            
            # Mock get_live_ohlcv to return window (same as signal_return_analyzer)
            def mock_get_live_ohlcv(symbol: str, timeframe: str, limit: int = 200, no_cache: bool = True):
                return window_rows[-limit:] if len(window_rows) >= limit else window_rows
            
            live_prices.get_live_ohlcv = mock_get_live_ohlcv
            if original_signal_get_live_ohlcv is not None:
                signal_processor.get_live_ohlcv = mock_get_live_ohlcv
            
            try:
                # Get regime from price-based classifier (last 20 bars)
                regime_window = window_rows[-20:] if len(window_rows) >= 20 else window_rows
                regime_info = classify_regime(regime_window)
                regime = regime_info.get("regime", "chop")
                
                # Get signal vector (same as signal_return_analyzer)
                from engine_alpha.signals.signal_processor import get_signal_vector_live
                out = get_signal_vector_live(symbol=symbol, timeframe=timeframe, limit=window)
                
                # Get decision with regime override
                decision = decide(
                    out["signal_vector"],
                    out["raw_registry"],
                    regime_override=regime
                )
                
                # Apply Phase 54 adjustments (matching signal_return_analyzer)
                buckets = decision.get("buckets", {})
                bucket_dirs = {name: buckets.get(name, {}).get("dir", 0) 
                              for name in ["momentum", "meanrev", "flow", "positioning", "timing", "sentiment", "onchain_flow"]}
                bucket_confs = {name: buckets.get(name, {}).get("conf", 0.0) 
                               for name in ["momentum", "meanrev", "flow", "positioning", "timing", "sentiment", "onchain_flow"]}
                
                # Phase 54 adjustments
                bucket_weight_adj = {name: 1.0 for name in bucket_dirs.keys()}
                if os.getenv("MODE", "PAPER").upper() == "PAPER":
                    if regime in ("trend_down", "trend_up"):
                        bucket_weight_adj["momentum"] = 1.10
                        bucket_weight_adj["flow"] = 1.05
                        bucket_weight_adj["positioning"] = 1.05
                    elif regime == "chop":
                        bucket_weight_adj["meanrev"] = 1.10
                        bucket_weight_adj["flow"] = 0.90
                
                # Recompute with Phase 54 adjustments
                regime_weights = REGIME_BUCKET_WEIGHTS.get(regime, REGIME_BUCKET_WEIGHTS.get("chop", {}))
                
                weighted_score = 0.0
                weight_sum = 0.0
                
                for bucket_name in BUCKET_ORDER:
                    dir_val = bucket_dirs.get(bucket_name, 0)
                    conf_val = bucket_confs.get(bucket_name, 0.0)
                    base_weight = float(regime_weights.get(bucket_name, 0.0))
                    adjusted_weight = base_weight * bucket_weight_adj.get(bucket_name, 1.0)
                    
                    if dir_val == 0 or adjusted_weight <= 0.0 or conf_val <= 0.0:
                        continue
                    
                    score = dir_val * conf_val
                    weighted_score += adjusted_weight * score
                    weight_sum += adjusted_weight
                
                if weight_sum <= 0.0:
                    final_score = 0.0
                else:
                    final_score = weighted_score / weight_sum
                
                # Apply neutral zone logic
                score_abs = abs(final_score)
                if score_abs < NEUTRAL_THRESHOLD:
                    effective_final_conf = 0.0
                else:
                    effective_final_conf = min(score_abs, 1.0)
                
                # Round confidence
                effective_final_conf = round(effective_final_conf, 2)
                
                df.at[df.index[i], "regime"] = regime
                df.at[df.index[i], "confidence"] = effective_final_conf
                
            except Exception as e:
                # Skip rows that fail (defensive)
                if os.getenv("DEBUG_SIGNALS") == "1":
                    print(f"⚠️  Error computing regime/confidence for row {i}: {e}")
                continue
    
    finally:
        # Restore original functions
        live_prices.get_live_ohlcv = original_get_live_ohlcv
        if original_signal_get_live_ohlcv is not None:
            signal_processor.get_live_ohlcv = original_signal_get_live_ohlcv
    
    return df


def run_analyzer_for_symbol(
    symbol: str,
    hybrid_path: Path,
    timeframe: str = "15m",
    window: int = 200,
    compute_regime_conf: bool = True,
) -> Path:
    """
    Run weighted multi-horizon analyzer for a given symbol.
    Writes: reports/research/{symbol}/multi_horizon_stats.json
    """
    output_path = _analyzer_output_path(symbol)
    return run_analyzer(
        dataset_path=hybrid_path,
        output_path=output_path,
        symbol=symbol,
        timeframe=timeframe,
        window=window,
        compute_regime_conf=compute_regime_conf,
    )


def run_analyzer(
    dataset_path: Path,
    output_path: Path = ANALYZER_OUT_PATH,
    regime_col: str = "regime",
    conf_col: str = "confidence",
    symbol: str = "ETHUSDT",
    timeframe: str = "15m",
    window: int = 200,
    compute_regime_conf: bool = True,
) -> Path:
    """
    Run weighted multi-horizon analyzer on hybrid dataset.
    
    If regime/confidence columns are missing, computes them on-the-fly
    using Chloe's signal pipeline (same as signal_return_analyzer).
    """
    if pd is None:
        raise ImportError("pandas is required for weighted analyzer")
    
    weights_cfg = load_weights_config()
    df = _prepare_weighted_df(dataset_path, weights_cfg)

    # Find forward return columns (ret_1h, ret_2h, ret_4h, etc.)
    ret_cols = [c for c in df.columns if c.startswith("ret_")]
    
    if not ret_cols:
        raise ValueError("Dataset must have forward return columns (ret_1h, ret_2h, etc.)")

    # Compute regime/confidence if missing
    if compute_regime_conf and (regime_col not in df.columns or conf_col not in df.columns):
        print("📊 Computing regime and confidence on-the-fly...")
        df = _compute_regime_confidence(df, symbol=symbol, timeframe=timeframe, window=window)
        print(f"   ✅ Computed regime/confidence for {len(df)} rows")

    # Bucket confidence into deciles (0.0–1.0)
    if conf_col not in df.columns:
        raise ValueError(f"Dataset must have '{conf_col}' column (or set compute_regime_conf=True)")
    
    df["conf_bucket"] = (df[conf_col].clip(0.0, 0.999) * 10).astype("int32")

    results = {}

    for horizon_col in ret_cols:
        horizon_key = horizon_col  # e.g. "ret_1h"
        horizon_stats = {}

        grouped = df.groupby([regime_col, "conf_bucket"], dropna=False)

        for (regime, conf_bucket), g in grouped:
            stats = _weighted_stats(g, horizon_col)

            key = f"{regime}|{conf_bucket}"
            horizon_stats[key] = stats

        results[horizon_key] = {
            "weights_config": {
                "source_weights": weights_cfg.source_weights,
                "recency_half_life_days": weights_cfg.recency_half_life_days,
            },
            "stats": horizon_stats,
        }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as f:
        json.dump(results, f, indent=2)

    return output_path


if __name__ == "__main__":
    ds = RESEARCH_DIR / "hybrid_research_dataset.parquet"
    if not ds.exists():
        print(f"❌ Dataset not found: {ds}")
        print("   Run research_dataset_builder first")
    else:
        out = run_analyzer(dataset_path=ds)
        print(f"✅ Wrote weighted analyzer stats to {out}")

