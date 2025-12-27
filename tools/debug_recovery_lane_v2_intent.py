#!/usr/bin/env python3
"""
Debug Recovery Lane V2 Intent (Phase 5H.2.1)
---------------------------------------------

Shows recovery intent (direction, confidence) for each allowed symbol
from recovery_ramp_v2.json. Helps diagnose why recovery lane v2 sees
no valid signals.
"""

from __future__ import annotations

import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine_alpha.loop.recovery_intent import compute_recovery_intent
from engine_alpha.core.paths import REPORTS
from engine_alpha.loop.recovery_lane_v2 import (
    ENTRY_CONF_MIN,
    ENTRY_CONF_MIN_CHOP,
)


def _load_json(path: Path) -> dict:
    """Load JSON file."""
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def main() -> int:
    """Main entry point."""
    print("RECOVERY LANE V2 INTENT DEBUG (Phase 5H.2.1)")
    print("=" * 80)
    print()
    
    # Load recovery ramp v2 state
    ramp_v2_path = REPORTS / "risk" / "recovery_ramp_v2.json"
    ramp_v2 = _load_json(ramp_v2_path)
    
    if not ramp_v2:
        print("recovery_ramp_v2.json not found. Run recovery_ramp_v2 first.")
        return 1
    
    decision = ramp_v2.get("decision", {})
    allowed_symbols = decision.get("allowed_symbols", [])
    
    if not allowed_symbols:
        print("No allowed symbols in recovery_ramp_v2.json.")
        print(f"Reason: {decision.get('reason', 'unknown')}")
        return 1
    
    print(f"Found {len(allowed_symbols)} allowed symbol(s)")
    print()
    print(f"{'Symbol':<12} {'Dir':<6} {'Conf':<6} {'Entry':<6} {'Exit':<6} {'Regime':<12} {'Reason'}")
    print("-" * 80)
    
    for symbol in allowed_symbols:
        try:
            intent = compute_recovery_intent(symbol=symbol, timeframe="15m")
            
            direction = intent.get("direction", 0)
            confidence = intent.get("confidence", 0.0)
            entry_ok = intent.get("entry_ok", False)
            exit_ok = intent.get("exit_ok", False)
            regime = intent.get("regime", "unknown")
            reason = intent.get("reason", "")
            
            dir_str = "LONG" if direction == 1 else "SHORT" if direction == -1 else "FLAT"
            conf_str = f"{confidence:.3f}" if confidence > 0 else "0.000"
            entry_str = "Y" if entry_ok else "N"
            exit_str = "Y" if exit_ok else "N"
            
            print(f"{symbol:<12} {dir_str:<6} {conf_str:<6} {entry_str:<6} {exit_str:<6} {regime:<12} {reason}")
        except Exception as e:
            print(f"{symbol:<12} ERROR: {str(e)}")
    
    print()
    print("=" * 80)
    print()
    print("Interpretation:")
    print("  • Dir: LONG/SHORT/FLAT")
    print("  • Conf: Confidence score [0.0, 1.0]")
    print("  • Entry: Y if direction != 0 AND confidence >= 0.50")
    print("  • Exit: Y if confidence < 0.42")
    print(f"  • Recovery Lane V2 requires: Entry=Y AND confidence >= {ENTRY_CONF_MIN:.2f} (normal) or >= {ENTRY_CONF_MIN_CHOP:.2f} (chop)")
    print("  • Cooldowns: TP cooldown = 15 min, Close cooldown = 10 min, No-signal cooldown = 5 min")
    print()
    
    # Phase 5H.2 Conservative Tightening: Show pass/fail for each symbol
    print("Entry Threshold Check:")
    print("-" * 80)
    for symbol in allowed_symbols:
        try:
            intent = compute_recovery_intent(symbol=symbol, timeframe="15m")
            confidence = intent.get("confidence", 0.0)
            entry_ok = intent.get("entry_ok", False)
            regime = intent.get("regime", "unknown")
            is_chop = regime.lower() == "chop"
            required_conf = ENTRY_CONF_MIN_CHOP if is_chop else ENTRY_CONF_MIN
            conf_pass = confidence >= required_conf
            overall_pass = entry_ok and conf_pass
            
            status = "✅ PASS" if overall_pass else "❌ FAIL"
            print(f"  {symbol:<12} Regime={regime:<12} Conf={confidence:.3f} ReqConf={required_conf:.2f} {status}")
        except Exception:
            print(f"  {symbol:<12} ERROR")
    print()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

