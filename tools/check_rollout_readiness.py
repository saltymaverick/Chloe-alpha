#!/usr/bin/env python3
"""
Check if Chloe is ready to proceed to the next rollout phase.

Usage:
    python3 -m tools.check_rollout_readiness
"""

import json
import sys
from pathlib import Path
from typing import Dict, Any

ROOT_DIR = Path(__file__).resolve().parents[1]
TRADING_ENABLEMENT_PATH = ROOT_DIR / "config" / "trading_enablement.json"
PF_LOCAL_PATH = ROOT_DIR / "reports" / "pf_local.json"
TRADES_PATH = ROOT_DIR / "reports" / "trades.jsonl"


def load_json(path: Path) -> Dict[str, Any]:
    """Load JSON file."""
    if not path.exists():
        return {}
    try:
        with path.open("r") as f:
            return json.load(f)
    except Exception:
        return {}


def count_trades() -> int:
    """Count total trades from trades.jsonl."""
    if not TRADES_PATH.exists():
        return 0
    
    count = 0
    try:
        with TRADES_PATH.open("r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    trade = json.loads(line)
                    if trade.get("type") == "close":
                        count += 1
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass
    
    return count


def check_phase_0_readiness() -> Dict[str, Any]:
    """Check if ready to move from Phase 0 to Phase 1."""
    pf_data = load_json(PF_LOCAL_PATH)
    pf_val = pf_data.get("pf", 0.0)
    trade_count = count_trades()
    
    ready = trade_count >= 10
    ideal = trade_count >= 15
    
    return {
        "phase": "phase_0",
        "ready": ready,
        "ideal": ideal,
        "trade_count": trade_count,
        "pf_val": pf_val,
        "criteria": {
            "min_trades": 10,
            "ideal_trades": 15,
            "min_pf": 1.0,
        },
        "recommendation": (
            "✅ Ready for Phase 1" if ready
            else f"⏳ Wait for {10 - trade_count} more trades"
        ),
    }


def check_phase_1_readiness() -> Dict[str, Any]:
    """Check if ready to move from Phase 1 to Phase 2."""
    # This would check ETHUSDT specifically
    # For now, simplified check
    pf_data = load_json(PF_LOCAL_PATH)
    pf_val = pf_data.get("pf", 0.0)
    trade_count = count_trades()
    
    ready = trade_count >= 15 and pf_val >= 1.0
    
    return {
        "phase": "phase_1",
        "ready": ready,
        "trade_count": trade_count,
        "pf_val": pf_val,
        "criteria": {
            "min_trades": 15,
            "min_pf": 1.0,
        },
        "recommendation": (
            "✅ Ready for Phase 2 (enable Tier 1)" if ready
            else f"⏳ Wait for more trades or better PF (current: {pf_val:.2f})"
        ),
    }


def main():
    cfg = load_json(TRADING_ENABLEMENT_PATH)
    current_phase = cfg.get("phase", "phase_0")
    
    print("=" * 80)
    print("🎯 CHLOE ROLLOUT READINESS CHECK")
    print("=" * 80)
    print()
    print(f"Current Phase: {current_phase}")
    print()
    
    if current_phase == "phase_0":
        result = check_phase_0_readiness()
        print("Phase 0 → Phase 1 Readiness:")
        print(f"  Trades: {result['trade_count']} (need {result['criteria']['min_trades']})")
        print(f"  PF: {result['pf_val']:.3f}")
        print(f"  Status: {result['recommendation']}")
        print()
        if result['ready']:
            print("Next step: Enable remaining Tier 1 assets one by one:")
            print("  1. BTCUSDT (already enabled)")
            print("  2. python3 -m tools.enable_trading AVAXUSDT")
            print("  3. python3 -m tools.enable_trading DOGEUSDT")
            print("  4. MATICUSDT (research-only until feed fixed)")
        else:
            print("Next step: Wait for more ETHUSDT and BTCUSDT trades")
    
    elif current_phase == "phase_1":
        result = check_phase_1_readiness()
        print("Phase 1 → Phase 2 Readiness:")
        print(f"  Trades: {result['trade_count']} (need {result['criteria']['min_trades']})")
        print(f"  PF: {result['pf_val']:.3f} (need {result['criteria']['min_pf']})")
        print(f"  Status: {result['recommendation']}")
        print()
        if result['ready']:
            print("Next step: Enable remaining Tier 1 assets one by one:")
            print("  1. BTCUSDT (already enabled)")
            print("  2. python3 -m tools.enable_trading AVAXUSDT")
            print("  3. python3 -m tools.enable_trading DOGEUSDT")
            print("  4. MATICUSDT (research-only until feed fixed)")
        else:
            print("Next step: Continue accumulating ETHUSDT and BTCUSDT trades")
    
    else:
        print(f"Phase {current_phase} - No specific readiness check defined yet.")
    
    print()
    print("=" * 80)


if __name__ == "__main__":
    main()


