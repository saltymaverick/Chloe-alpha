#!/usr/bin/env python3
"""
Liquidity Sweeps Scan CLI Tool - Runs liquidity sweep detection for all symbols.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine_alpha.research.advanced_structure.liquidity_sweeps import compute_liquidity_sweeps
from engine_alpha.core.paths import REPORTS
from pathlib import Path
import json
from datetime import datetime, timezone


def main() -> int:
    """Main entry point."""
    try:
        RESEARCH_DIR = REPORTS / "research"
        RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH = RESEARCH_DIR / "liquidity_sweeps.json"
        
        # Get enabled symbols
        try:
            from tools.intel_dashboard import load_symbol_registry
            symbols = load_symbol_registry()
        except Exception:
            symbols = [
                "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "AVAXUSDT",
                "LINKUSDT", "DOTUSDT", "ADAUSDT", "ATOMUSDT", "XRPUSDT", "DOGEUSDT"
            ]
        
        if not symbols:
            symbols = [
                "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "AVAXUSDT",
                "LINKUSDT", "DOTUSDT", "ADAUSDT", "ATOMUSDT", "XRPUSDT", "DOGEUSDT"
            ]
        
        # Load volume imbalance for cross-reference (optional)
        volume_imbalance_data = {}
        try:
            vi_path = RESEARCH_DIR / "volume_imbalance.json"
            if vi_path.exists():
                vi_data = json.loads(vi_path.read_text())
                volume_imbalance_data = vi_data.get("symbols", {})
        except Exception:
            pass
        
        # Compute for each symbol
        all_results = {}
        
        for symbol in symbols:
            try:
                symbol_result = compute_liquidity_sweeps(symbol, volume_imbalance_data)
                all_results.update(symbol_result)
            except Exception as e:
                print(f"Warning: Failed to process {symbol}: {e}", file=sys.stderr)
                all_results[symbol] = {
                    "session": "Unknown",
                    "htf_pool": "none",
                    "equal_highs_1h": False,
                    "equal_lows_1h": False,
                    "sell_sweep_5m": False,
                    "buy_sweep_5m": False,
                    "sell_sweep_15m": False,
                    "buy_sweep_15m": False,
                    "breaker": "none",
                    "strength": 0.0,
                    "notes": [f"Error: {str(e)}"],
                }
        
        # Compute health
        health_status = "ok"
        health_reasons = []
        
        unknown_sessions = sum(1 for r in all_results.values() if r.get("session") == "Unknown" or r.get("session") == "unknown")
        if unknown_sessions == len(all_results) and len(all_results) > 0:
            health_status = "degraded"
            health_reasons.append("unknown_session_for_all")
        
        # Write output
        output_data = {
            "version": "v2.1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "health": {
                "status": health_status,
                "reasons": health_reasons,
            },
            "symbols": all_results,
        }
        
        OUTPUT_PATH.write_text(json.dumps(output_data, indent=2))
        
        # Print summary
        print("LIQUIDITY SWEEPS SCAN")
        print("=" * 70)
        print(f"{'Symbol':<10} {'Session':<8} {'Pool':<6} {'Sweep5m':<8} {'Sweep15m':<9} {'Breaker':<8} {'Strength':<8}")
        print("-" * 70)
        
        for sym in sorted(all_results.keys()):
            info = all_results[sym]
            session = info.get("session", "Unknown")
            pool = info.get("htf_pool", "none")
            sweep_5m = "Y" if (info.get("sell_sweep_5m") or info.get("buy_sweep_5m")) else "N"
            sweep_15m = "Y" if (info.get("sell_sweep_15m") or info.get("buy_sweep_15m")) else "N"
            breaker = info.get("breaker", "none")
            strength = info.get("strength", 0.0)
            
            print(f"{sym:<10} {session:<8} {pool:<6} {sweep_5m:<8} {sweep_15m:<9} {breaker:<8} {strength:<8.2f}")
        
        print()
        return 0
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

