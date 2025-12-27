#!/usr/bin/env python3
"""
Recovery Earn-Back Verification Tool

Shows all symbols currently in recovery and their earn-back status.
Displays demoted_at, recovery_stage, post-demotion sample count, and PF.
States "next unlock condition" in plain english.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

from engine_alpha.risk.recovery_earnback import (
    compute_earnback_state,
    get_default_recovery_config,
)

REPORTS = Path(__file__).resolve().parents[1] / "reports"


def load_symbol_states() -> Dict[str, Any]:
    """Load current symbol states."""
    state_path = REPORTS / "risk" / "symbol_states.json"
    if not state_path.exists():
        return {"symbols": {}}

    try:
        with open(state_path, "r") as f:
            data = json.load(f)
        return data.get("symbols", {})
    except Exception:
        return {"symbols": {}}


def load_capital_protection() -> Dict[str, Any]:
    """Load capital protection data."""
    cp_path = REPORTS / "risk" / "capital_protection.json"
    if not cp_path.exists():
        return {}

    try:
        with open(cp_path, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def get_next_unlock_condition(state: Dict[str, Any], symbol: str) -> str:
    """Get plain english description of next unlock condition."""
    recovery_stage = state.get("recovery_stage", "none")

    if recovery_stage == "none":
        return "Not in recovery"

    if recovery_stage == "sampling":
        config = get_default_recovery_config()
        min_trades = config["proving_min_trades"]
        current_trades = state.get("earnback_window", {}).get("n_closes", 0)
        remaining = min_trades - current_trades
        return f"Accumulate {remaining} more post-demotion trades to enter proving stage"

    if recovery_stage == "proving":
        config = get_default_recovery_config()
        pf_threshold = config["recovered_min_pf"]
        wr_threshold = config["recovered_min_winrate"]
        dd_threshold = config["recovered_max_drawdown"]

        return f"Maintain PF ≥ {pf_threshold}, Win Rate ≥ {wr_threshold:.0%}, Drawdown ≤ {dd_threshold:.0%} for {config['proving_min_trades']} trades"

    if recovery_stage == "recovered":
        return "Fully recovered - normal trading allowed"

    return "Unknown recovery stage"


def main():
    """Main verification function."""
    print("🔄 RECOVERY EARN-BACK VERIFICATION")
    print("=" * 50)

    symbol_states = load_symbol_states()
    capital_protection = load_capital_protection()

    if not symbol_states:
        print("❌ No symbol states found")
        return

    # Find symbols in recovery
    recovery_symbols = {}
    for symbol, state in symbol_states.items():
        recovery_stage = state.get("recovery_stage", "none")
        if recovery_stage != "none":
            recovery_symbols[symbol] = state

    if not recovery_symbols:
        print("✅ No symbols currently in recovery")
        print("All symbols have earned back or never demoted")
        return

    print(f"📊 {len(recovery_symbols)} symbols in recovery:")
    print()

    # Get capital protection data for demotion timestamps
    cp_symbols = (capital_protection.get("symbols") or {}) if isinstance(capital_protection, dict) else {}

    for symbol, state in recovery_symbols.items():
        print(f"🔄 {symbol}:")
        print(f"   Stage: {state.get('recovery_stage', 'unknown')}")

        # Get demotion info
        sym_cp = cp_symbols.get(symbol, {}) if isinstance(cp_symbols, dict) else {}
        demoted_at = sym_cp.get("demoted_at") or sym_cp.get("last_updated")
        if demoted_at:
            try:
                demote_dt = datetime.fromisoformat(demoted_at.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                days_since_demotion = (now - demote_dt).days
                print(f"   Demoted: {demote_dt.strftime('%Y-%m-%d %H:%M UTC')} ({days_since_demotion} days ago)")
            except:
                print(f"   Demoted: {demoted_at}")

        # Earn-back window stats
        earnback_window = state.get("earnback_window", {})
        n_closes = earnback_window.get("n_closes", 0)
        pf = earnback_window.get("pf")
        print(f"   Post-demotion trades: {n_closes}")
        if pf is not None:
            print(f"   Post-demotion PF: {pf:.3f}")

        # Current allowances
        allow_core = state.get("allow_core", False)
        allow_exploration = state.get("allow_exploration", False)
        allow_recovery = state.get("allow_recovery", False)
        print(f"   Allowances: Core={allow_core}, Exploration={allow_exploration}, Recovery={allow_recovery}")

        # Next unlock condition
        next_condition = get_next_unlock_condition(state, symbol)
        print(f"   Next unlock: {next_condition}")

        print()


if __name__ == "__main__":
    main()
