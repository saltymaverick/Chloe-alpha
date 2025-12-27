"""
Run Microstructure Scan - Compute bar-level microstructure features.

This tool computes microstructure features for all enabled symbols and
writes a snapshot to reports/research/microstructure_snapshot_15m.json.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine_alpha.research.microstructure_engine import (
    compute_microstructure_snapshot,
    save_microstructure_snapshot,
)


def main() -> int:
    """Main entry point."""
    print("MICROSTRUCTURE SCAN (15m)")
    print("=" * 70)
    print()
    
    try:
        # Compute snapshot
        snapshot = compute_microstructure_snapshot(timeframe="15m")
        symbols_data = snapshot.get("symbols", {})
        
        if not symbols_data:
            print("⚠️  No microstructure data computed.")
            print("   Ensure OHLCV data is available for enabled symbols.")
            return 0
        
        # Save snapshot
        output_path = save_microstructure_snapshot(snapshot, timeframe="15m")
        print(f"✅ Microstructure snapshot written to: {output_path}")
        print()
        
        # Print summary
        print("MICROSTRUCTURE SUMMARY")
        print("-" * 70)
        print(f"Symbols analyzed: {len(symbols_data)}")
        print()
        
        # Display summary stats per symbol (new format: symbol -> {micro_regime, metrics})
        for symbol in sorted(symbols_data.keys()):
            symbol_data = symbols_data[symbol]
            
            # Handle both old format (timestamp -> features) and new format (summary)
            if isinstance(symbol_data, dict) and "micro_regime" in symbol_data:
                # New summary format
                micro_regime = symbol_data.get("micro_regime", "unknown")
                metrics = symbol_data.get("metrics", {})
                
                body_ratio = metrics.get("body_ratio")
                volatility = metrics.get("volatility")
                spread = metrics.get("spread")
                wick_ratio = metrics.get("wick_ratio")
                
                print(f"{symbol}:")
                print(f"  - Micro regime: {micro_regime}")
                if body_ratio is not None:
                    print(f"  - Body ratio: {body_ratio:.4f}")
                if wick_ratio is not None and wick_ratio < 1000:  # Filter out extreme values
                    print(f"  - Wick ratio: {wick_ratio:.2f}")
                if volatility is not None:
                    print(f"  - Volatility: {volatility:.6f}")
                if spread is not None:
                    print(f"  - Spread: {spread:.6f}")
                # v2 metrics
                noise_score = metrics.get("noise_score")
                compression_score = metrics.get("compression_score")
                expansion_score = metrics.get("expansion_score")
                if noise_score is not None:
                    print(f"  - Noise: {noise_score:.2f}")
                if compression_score is not None:
                    print(f"  - Compression: {compression_score:.2f}")
                if expansion_score is not None:
                    print(f"  - Expansion: {expansion_score:.2f}")
                print()
            elif isinstance(symbol_data, dict):
                # Old format: timestamp -> features (for backward compatibility)
                timestamps = sorted(symbol_data.keys())
                recent_bars = timestamps[-100:] if len(timestamps) > 100 else timestamps
                
                if not recent_bars:
                    continue
                
                # Extract features for recent bars
                body_ratios = []
                volatilities = []
                regimes = []
                
                for ts in recent_bars:
                    features = symbol_data[ts]
                    if not isinstance(features, dict):
                        continue
                    
                    body_ratio = features.get("body_ratio")
                    volatility = features.get("volatility")
                    regime = features.get("micro_regime")
                    
                    if body_ratio is not None:
                        body_ratios.append(body_ratio)
                    if volatility is not None:
                        volatilities.append(volatility)
                    if regime:
                        regimes.append(regime)
                
                # Compute averages
                avg_body_ratio = sum(body_ratios) / len(body_ratios) if body_ratios else 0.0
                avg_volatility = sum(volatilities) / len(volatilities) if volatilities else None
                
                # Count regimes
                regime_counts = {}
                for r in regimes:
                    regime_counts[r] = regime_counts.get(r, 0) + 1
                
                last_regime = regimes[-1] if regimes else "unknown"
                noisy_count = regime_counts.get("noisy", 0)
                
                print(f"{symbol}:")
                print(f"  - Last bar regime: {last_regime}")
                print(f"  - Avg body_ratio ({len(recent_bars)} bars): {avg_body_ratio:.2f}")
                if avg_volatility is not None:
                    print(f"  - Avg volatility: {avg_volatility:.4f}")
                print(f"  - Noisy bars (last {len(recent_bars)}): {noisy_count}")
                print()
            else:
                # Unknown format, skip
                continue
        
        # Overall summary
        print("OVERALL SUMMARY")
        print("-" * 70)
        
        # Find cleanest and noisiest symbols
        symbol_noisy_counts = {}
        symbol_clean_counts = {}
        
        for symbol, symbol_data in symbols_data.items():
            if not symbol_data:
                continue
            
            # Handle new summary format
            if isinstance(symbol_data, dict) and "micro_regime" in symbol_data:
                regime = symbol_data.get("micro_regime", "unknown")
                if regime == "noisy":
                    symbol_noisy_counts[symbol] = 1
                elif regime == "clean_trend":
                    symbol_clean_counts[symbol] = 1
            elif isinstance(symbol_data, dict):
                # Old format: timestamp -> features
                timestamps = sorted(symbol_data.keys())
                recent_bars = timestamps[-100:]
                
                noisy_count = 0
                clean_count = 0
                
                for ts in recent_bars:
                    features = symbol_data[ts]
                    if not isinstance(features, dict):
                        continue
                    regime = features.get("micro_regime")
                    if regime == "noisy":
                        noisy_count += 1
                    elif regime == "clean_trend":
                        clean_count += 1
                
                symbol_noisy_counts[symbol] = noisy_count
                symbol_clean_counts[symbol] = clean_count
        
        if symbol_clean_counts:
            cleanest = sorted(symbol_clean_counts.items(), key=lambda x: x[1], reverse=True)[:3]
            print("  - Cleanest trend symbols:")
            for sym, count in cleanest:
                print(f"    {sym}: {count} clean_trend bars")
        
        if symbol_noisy_counts:
            noisiest = sorted(symbol_noisy_counts.items(), key=lambda x: x[1], reverse=True)[:3]
            print("  - Noisiest symbols:")
            for sym, count in noisiest:
                print(f"    {sym}: {count} noisy bars")
        
        print()
        print("=" * 70)
        print("Note: All microstructure analysis is advisory-only.")
        print("=" * 70)
        
        return 0
    
    except Exception as e:
        print(f"❌ Microstructure scan failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

