#!/usr/bin/env python3
"""
Diagnostic tool to trace why no trades are opening in backtests.
Traces the full execution pipeline: OHLCV → Regime → Signals → Confidence → Entry Decision
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Dict, Any, List

from engine_alpha.data.historical_prices import load_ohlcv_csv
from engine_alpha.data import live_prices
from engine_alpha.signals import signal_processor
from engine_alpha.core.regime import classify_regime
from engine_alpha.core.confidence_engine import decide
from engine_alpha.loop.autonomous_trader import (
    compute_entry_min_conf,
    regime_allows_entry,
    _load_entry_thresholds,
    ENTRY_THRESHOLDS_DEFAULT,
)
from engine_alpha.core.risk_adapter import evaluate as risk_eval


def analyze_bar(
    symbol: str,
    timeframe: str,
    timestamp: str,
    csv_path: str,
    window: int = 200,
) -> Dict[str, Any]:
    """Analyze a single bar to understand why trades don't open."""
    
    # Load candles
    all_candles = load_ohlcv_csv(symbol, timeframe, csv_path=csv_path)
    
    # Find target candle
    target_idx = None
    for i, c in enumerate(all_candles):
        if c.get("ts") == timestamp:
            target_idx = i
            break
    
    if target_idx is None:
        return {"error": f"Timestamp {timestamp} not found in CSV"}
    
    # Get window ending at target
    start_idx = max(0, target_idx - window + 1)
    window_candles = all_candles[start_idx:target_idx + 1]
    current_bar = window_candles[-1]
    
    # Mock get_live_ohlcv
    def mock_get_live_ohlcv(sym: str, tf: str, limit: int = 200, no_cache: bool = True):
        return window_candles[-limit:] if len(window_candles) >= limit else window_candles
    
    # Patch
    original_live = live_prices.get_live_ohlcv
    original_signal = signal_processor.get_live_ohlcv
    live_prices.get_live_ohlcv = mock_get_live_ohlcv
    signal_processor.get_live_ohlcv = mock_get_live_ohlcv
    
    try:
        # 1. Regime classification
        regime_window = window_candles[-20:] if len(window_candles) >= 20 else window_candles
        regime_info = classify_regime(regime_window)
        price_based_regime = regime_info.get("regime", "chop")
        regime_metrics = regime_info.get("metrics", {})
        
        # 2. Signal processing
        signal_out = signal_processor.get_signal_vector_live(
            symbol=symbol,
            timeframe=timeframe,
            limit=window
        )
        signal_vector = signal_out["signal_vector"]
        raw_registry = signal_out["raw_registry"]
        
        # 3. Confidence aggregation
        decision = decide(
            signal_vector,
            raw_registry,
            regime_override=price_based_regime
        )
        final = decision.get("final", {})
        buckets = decision.get("buckets", {})
        
        base_final_dir = final.get("dir", 0)
        base_final_conf = final.get("conf", 0.0)
        final_score = final.get("score", 0.0)
        
        # 4. Neutral zone check
        NEUTRAL_THRESHOLD = 0.30  # From autonomous_trader.py
        score_abs = abs(final_score)
        if score_abs < NEUTRAL_THRESHOLD:
            effective_final_dir = 0
            effective_final_conf = score_abs
        else:
            effective_final_dir = 1 if final_score > 0 else -1
            effective_final_conf = min(score_abs, 1.0)
        
        effective_final_conf = round(effective_final_conf, 2)
        
        # 5. Risk adapter
        risk_result = risk_eval() or {}
        adapter_band = risk_result.get("band") or "A"
        
        # 6. Entry threshold
        entry_min_conf = compute_entry_min_conf(price_based_regime, adapter_band)
        
        # 7. Regime gate
        regime_allowed = regime_allows_entry(price_based_regime)
        
        # 8. Entry decision
        can_open = (
            regime_allowed
            and effective_final_dir != 0
            and effective_final_conf >= entry_min_conf
        )
        
        # Build diagnostic report
        report = {
            "timestamp": timestamp,
            "current_bar": {
                "ts": current_bar.get("ts"),
                "close": current_bar.get("close"),
            },
            "regime": {
                "price_based_regime": price_based_regime,
                "metrics": regime_metrics,
                "allows_entry": regime_allowed,
            },
            "signals": {
                "vector_length": len(signal_vector),
                "vector_sample": signal_vector[:5] if len(signal_vector) >= 5 else signal_vector,
                "raw_registry_keys": list(raw_registry.keys())[:5],
            },
            "confidence": {
                "final_score": final_score,
                "base_final_dir": base_final_dir,
                "base_final_conf": base_final_conf,
                "effective_final_dir": effective_final_dir,
                "effective_final_conf": effective_final_conf,
                "neutral_threshold": NEUTRAL_THRESHOLD,
                "neutralized": score_abs < NEUTRAL_THRESHOLD,
            },
            "buckets": {
                name: {
                    "dir": buckets.get(name, {}).get("dir", 0),
                    "conf": buckets.get(name, {}).get("conf", 0.0),
                    "score": buckets.get(name, {}).get("score", 0.0),
                }
                for name in ["momentum", "meanrev", "flow", "positioning", "timing"]
            },
            "entry": {
                "risk_band": adapter_band,
                "entry_min_conf": entry_min_conf,
                "can_open": can_open,
                "blockers": [],
            },
        }
        
        # Identify blockers
        blockers = []
        if not regime_allowed:
            blockers.append(f"REGIME_GATE: {price_based_regime} not allowed (only trend_down/high_vol)")
        if effective_final_dir == 0:
            blockers.append(f"NEUTRAL_ZONE: final_score={final_score:.4f} < {NEUTRAL_THRESHOLD}")
        if effective_final_conf < entry_min_conf:
            blockers.append(
                f"THRESHOLD: conf={effective_final_conf:.2f} < entry_min={entry_min_conf:.2f}"
            )
        
        report["entry"]["blockers"] = blockers
        
        return report
        
    finally:
        # Restore
        live_prices.get_live_ohlcv = original_live
        signal_processor.get_live_ohlcv = original_signal


def main():
    parser = argparse.ArgumentParser(description="Diagnose why no trades open")
    parser.add_argument("--symbol", default="ETHUSDT", help="Symbol")
    parser.add_argument("--timeframe", default="1h", help="Timeframe")
    parser.add_argument("--timestamp", required=True, help="ISO timestamp")
    parser.add_argument("--csv", required=True, help="CSV path")
    parser.add_argument("--window", type=int, default=200, help="Window size")
    parser.add_argument("--sample", type=int, default=10, help="Sample N bars")
    
    args = parser.parse_args()
    
    # Set MODE to PAPER for consistency
    os.environ.setdefault("MODE", "PAPER")
    
    print("=" * 80)
    print("ZERO TRADES DIAGNOSTIC")
    print("=" * 80)
    
    # Load candles
    all_candles = load_ohlcv_csv(args.symbol, args.timeframe, csv_path=args.csv)
    
    # Find target
    target_idx = None
    for i, c in enumerate(all_candles):
        if c.get("ts") == args.timestamp:
            target_idx = i
            break
    
    if target_idx is None:
        print(f"❌ Timestamp {args.timestamp} not found")
        return 1
    
    # Analyze target bar
    print(f"\n📊 Analyzing bar: {args.timestamp}")
    report = analyze_bar(
        args.symbol,
        args.timeframe,
        args.timestamp,
        args.csv,
        args.window,
    )
    
    if "error" in report:
        print(f"❌ Error: {report['error']}")
        return 1
    
    # Print summary
    print(f"\n🔍 REGIME: {report['regime']['price_based_regime']}")
    print(f"   Allows entry: {report['regime']['allows_entry']}")
    
    print(f"\n📈 CONFIDENCE:")
    print(f"   Final score: {report['confidence']['final_score']:.4f}")
    print(f"   Effective dir: {report['confidence']['effective_final_dir']}")
    print(f"   Effective conf: {report['confidence']['effective_final_conf']:.2f}")
    print(f"   Neutralized: {report['confidence']['neutralized']}")
    
    print(f"\n🎯 ENTRY:")
    print(f"   Risk band: {report['entry']['risk_band']}")
    print(f"   Entry min conf: {report['entry']['entry_min_conf']:.2f}")
    print(f"   Can open: {report['entry']['can_open']}")
    
    if report['entry']['blockers']:
        print(f"\n🚫 BLOCKERS:")
        for blocker in report['entry']['blockers']:
            print(f"   - {blocker}")
    
    print(f"\n📦 BUCKETS:")
    for name, data in report['buckets'].items():
        print(f"   {name:12s}: dir={data['dir']:2d}, conf={data['conf']:.2f}, score={data['score']:.4f}")
    
    # Sample more bars
    print(f"\n📊 Sampling {args.sample} bars around target...")
    sample_start = max(0, target_idx - args.sample // 2)
    sample_end = min(len(all_candles), target_idx + args.sample // 2 + 1)
    
    regime_counts = {}
    conf_distribution = []
    neutralized_count = 0
    
    for i in range(sample_start, sample_end):
        bar = all_candles[i]
        bar_report = analyze_bar(
            args.symbol,
            args.timeframe,
            bar.get("ts"),
            args.csv,
            args.window,
        )
        
        if "error" not in bar_report:
            regime = bar_report["regime"]["price_based_regime"]
            regime_counts[regime] = regime_counts.get(regime, 0) + 1
            
            conf = bar_report["confidence"]["effective_final_conf"]
            conf_distribution.append(conf)
            
            if bar_report["confidence"]["neutralized"]:
                neutralized_count += 1
    
    print(f"\n📊 SAMPLE STATISTICS ({len(conf_distribution)} bars):")
    print(f"   Regime distribution: {regime_counts}")
    if conf_distribution:
        avg_conf = sum(conf_distribution) / len(conf_distribution)
        max_conf = max(conf_distribution)
        min_conf = min(conf_distribution)
        print(f"   Confidence: avg={avg_conf:.2f}, min={min_conf:.2f}, max={max_conf:.2f}")
        print(f"   Neutralized: {neutralized_count}/{len(conf_distribution)} ({100*neutralized_count/len(conf_distribution):.1f}%)")
    
    # Save full report
    report_path = Path("reports") / "diagnostics" / f"zero_trades_{args.timestamp.replace(':', '-')}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2))
    print(f"\n💾 Full report saved to: {report_path}")
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

