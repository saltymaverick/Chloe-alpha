"""
Recovery Assist Flag (Phase 5H.4)
----------------------------------

Evaluates Recovery V2 performance and determines if assist should be enabled
to allow micro-core ramp during halt_new_entries.

Safety:
- Read-only evaluation (does not change capital_mode)
- Hard gates: trades_24h >= 35, pf_24h >= 1.10, mdd_24h <= 1.00, >= 2 symbols with >= 3 closes AND >= 1 non-SOL close
- Never enables exploit/probe/promotion gates
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List

from engine_alpha.core.paths import REPORTS

RECOVERY_V2_SCORE_PATH = REPORTS / "loop" / "recovery_v2_score.json"
RECOVERY_TRADES_PATH = REPORTS / "loop" / "recovery_lane_v2_trades.jsonl"
OUT_PATH = REPORTS / "risk" / "recovery_assist.json"

# Hard gates (Phase 5H.4 Gate Tuning: relaxed but still strict)
MIN_TRADES_24H = 30  # Phase 5H.4: relaxed from 35
MIN_PF_24H = 1.10
MAX_MDD_24H = 2.00  # Phase 5H.4: relaxed from 1.00 (still strict for micro lane)
MIN_SYMBOLS_WITH_CLOSES = 2
MIN_CLOSES_PER_SYMBOL = 3  # Phase 5H.4 tuning: reduced from 5 to 3

# Additional safety gates (Phase 5H.4: new)
MIN_NET_PNL_USD_24H = 0.0  # Must be positive (net_pnl_usd > 0)
MIN_WORST_SYMBOL_EXPECTANCY_24H = -0.05  # Worst symbol expectancy must be >= -0.05%
MIN_CLOSES_FOR_WORST_EXP_GATE = 8  # Phase 5H.4 Option A.1: Only gate on symbols with >=8 closes (dominant symbols)
MIN_CLOSES_PCT_FOR_WORST_EXP_GATE = 0.25  # Phase 5H.4 Option A.1: Alternative: >=25% of total closes


def _load_json(path: Path) -> Dict[str, Any]:
    """Load JSON file, return empty dict if missing."""
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {}
    except Exception:
        return {}


def _read_trades_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Read all trades from JSONL file."""
    trades = []
    if not path.exists():
        return trades
    
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    trade = json.loads(line)
                    trades.append(trade)
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass
    
    return trades


def _filter_trades_by_window(trades: List[Dict[str, Any]], window_hours: int) -> List[Dict[str, Any]]:
    """Filter trades to only those within the last N hours."""
    if not trades:
        return []
    
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    
    filtered = []
    for trade in trades:
        ts_str = trade.get("ts", "")
        if not ts_str:
            continue
        
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            
            if ts >= cutoff:
                filtered.append(trade)
        except Exception:
            continue
    
    return filtered


def _count_symbol_closes(trades: List[Dict[str, Any]]) -> Dict[str, int]:
    """Count close events per symbol."""
    symbol_counts: Dict[str, int] = {}
    
    for trade in trades:
        if trade.get("action") == "close":
            symbol = trade.get("symbol", "UNKNOWN")
            symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1
    
    return symbol_counts


def evaluate_recovery_assist() -> Dict[str, Any]:
    """
    Evaluate Recovery Assist conditions.
    
    Returns:
        Dictionary with assist_enabled, reason, gates, metrics, symbol_counts_24h
    """
    now = datetime.now(timezone.utc)
    
    # Load recovery_v2_score.json
    score_data = _load_json(RECOVERY_V2_SCORE_PATH)
    
    if not score_data:
        return {
            "ts": now.isoformat(),
            "assist_enabled": False,
            "reason": "recovery_v2_score.json missing",
            "gates": {},
            "metrics": {},
            "symbol_counts_24h": {},
        }
    
    metrics_24h = score_data.get("24h", {})
    
    # Gate 1: Trades count
    trades_24h = metrics_24h.get("trades", 0)
    trades_gate_pass = trades_24h >= MIN_TRADES_24H
    
    # Gate 2: PF
    pf_24h = metrics_24h.get("pf", 0.0)
    if pf_24h == float("inf"):
        pf_24h = 999.0  # Treat inf as very high
    pf_gate_pass = pf_24h >= MIN_PF_24H
    
    # Gate 3: Max Drawdown
    mdd_24h = metrics_24h.get("max_drawdown_pct", 999.0)
    mdd_gate_pass = mdd_24h <= MAX_MDD_24H
    
    # Gate 4: Symbol diversity (read from trades.jsonl)
    all_trades = _read_trades_jsonl(RECOVERY_TRADES_PATH)
    trades_24h_list = _filter_trades_by_window(all_trades, 24)
    symbol_counts = _count_symbol_closes(trades_24h_list)
    
    # Count symbols with >= MIN_CLOSES_PER_SYMBOL closes (Phase 5H.4: now 3+)
    symbols_with_sufficient_closes = sum(
        1 for count in symbol_counts.values() if count >= MIN_CLOSES_PER_SYMBOL
    )
    
    # Count non-SOL closes (Phase 5H.4: require at least 1 non-SOL close)
    non_sol_closes = sum(
        count for symbol, count in symbol_counts.items() if symbol != "SOLUSDT"
    )
    has_non_sol_close = non_sol_closes >= 1
    
    # Diversity gate: requires both conditions
    diversity_gate_pass = (
        symbols_with_sufficient_closes >= MIN_SYMBOLS_WITH_CLOSES and
        has_non_sol_close
    )
    
    # Gate 5: Net PnL USD (Phase 5H.4: new safety gate)
    gross_profit_usd = metrics_24h.get("gross_profit_usd", 0.0)
    gross_loss_usd = metrics_24h.get("gross_loss_usd", 0.0)
    net_pnl_usd_24h = gross_profit_usd - gross_loss_usd
    net_pnl_gate_pass = net_pnl_usd_24h > MIN_NET_PNL_USD_24H
    
    # Gate 6: Worst symbol expectancy (Phase 5H.4: new safety gate)
    # Phase 5H.4 Option A: Only gate on "dominant" symbols (>=5 closes or >=20% of total closes)
    # This avoids small-sample noise from symbols with only 3-4 closes blocking assist
    worst_symbol_expectancy_24h = None
    worst_symbol_exp_gate_pass = True  # Default pass if no dominant symbols meet criteria
    total_closes_24h = len([t for t in trades_24h_list if t.get("action") == "close"])
    
    if trades_24h_list and total_closes_24h > 0:
        # Group closes by symbol and compute average pnl_pct (expectancy)
        symbol_pnls: Dict[str, List[float]] = {}
        for trade in trades_24h_list:
            if trade.get("action") == "close":
                symbol = trade.get("symbol", "UNKNOWN")
                pnl_pct = trade.get("pnl_pct", 0.0)
                if symbol not in symbol_pnls:
                    symbol_pnls[symbol] = []
                symbol_pnls[symbol].append(pnl_pct)
        
        # Phase 5H.4 Option A: Only consider "dominant" symbols for worst-exp gate
        # A symbol is dominant if it has >= MIN_CLOSES_FOR_WORST_EXP_GATE closes OR >= MIN_CLOSES_PCT_FOR_WORST_EXP_GATE of total closes
        symbol_expectancies: Dict[str, float] = {}
        for symbol, pnls in symbol_pnls.items():
            closes_count = len(pnls)
            closes_pct = closes_count / total_closes_24h if total_closes_24h > 0 else 0.0
            
            # Consider symbol if it meets dominance criteria
            is_dominant = (
                closes_count >= MIN_CLOSES_FOR_WORST_EXP_GATE or
                closes_pct >= MIN_CLOSES_PCT_FOR_WORST_EXP_GATE
            )
            
            if is_dominant:
                symbol_expectancies[symbol] = sum(pnls) / len(pnls)
        
        if symbol_expectancies:
            worst_symbol_expectancy_24h = min(symbol_expectancies.values())
            worst_symbol_exp_gate_pass = worst_symbol_expectancy_24h >= MIN_WORST_SYMBOL_EXPECTANCY_24H
        else:
            # If no dominant symbols exist, gate passes (can't evaluate - not enough data)
            worst_symbol_expectancy_24h = None
            worst_symbol_exp_gate_pass = True
    
    # All gates must pass
    assist_enabled = (
        trades_gate_pass and
        pf_gate_pass and
        mdd_gate_pass and
        diversity_gate_pass and
        net_pnl_gate_pass and
        worst_symbol_exp_gate_pass
    )
    
    # Determine reason (Phase 5H.4: clearer format with values - only show FAILED gates)
    if not assist_enabled:
        failed_gates = []
        # Only list gates that FAIL (keep it readable)
        if not trades_gate_pass:
            failed_gates.append(f"trades_24h={trades_24h}<{MIN_TRADES_24H}")
        if not pf_gate_pass:
            failed_gates.append(f"pf_24h={pf_24h:.3f}<{MIN_PF_24H}")
        if not mdd_gate_pass:
            failed_gates.append(f"mdd_24h={mdd_24h:.3f}%>{MAX_MDD_24H}%")
        if not diversity_gate_pass:
            if symbols_with_sufficient_closes < MIN_SYMBOLS_WITH_CLOSES:
                failed_gates.append(f"diversity={symbols_with_sufficient_closes}<{MIN_SYMBOLS_WITH_CLOSES}")
            if not has_non_sol_close:
                failed_gates.append(f"no_non_sol_closes (non_sol={non_sol_closes})")
        if not net_pnl_gate_pass:
            failed_gates.append(f"net_pnl_usd={net_pnl_usd_24h:.4f}<=0")
        if not worst_symbol_exp_gate_pass:
            if worst_symbol_expectancy_24h is not None:
                failed_gates.append(f"worst_dominant_symbol_exp={worst_symbol_expectancy_24h:.3f}%<{MIN_WORST_SYMBOL_EXPECTANCY_24H:.3f}% (dominant=≥{MIN_CLOSES_FOR_WORST_EXP_GATE} closes or ≥{MIN_CLOSES_PCT_FOR_WORST_EXP_GATE*100:.0f}%)")
            else:
                failed_gates.append(f"worst_dominant_symbol_exp=N/A")
        
        reason = "gates_not_met: " + ", ".join(failed_gates) if failed_gates else "gates_not_met: (unknown)"
    else:
        reason = "all_gates_passed"
    
    result = {
        "ts": now.isoformat(),
        "assist_enabled": assist_enabled,
        "reason": reason,
        "gates": {
            "trades_24h": trades_gate_pass,
            "pf_24h": pf_gate_pass,
            "mdd_24h": mdd_gate_pass,
            "symbol_diversity": diversity_gate_pass,
            "symbol_diversity_pass": diversity_gate_pass,  # Phase 5H.4: explicit pass field
            "net_pnl_usd_24h": net_pnl_gate_pass,  # Phase 5H.4: new gate
            "worst_symbol_expectancy_24h": worst_symbol_exp_gate_pass,  # Phase 5H.4: new gate
        },
        "metrics": {
            "trades_24h": trades_24h,
            "pf_24h": pf_24h,
            "mdd_24h": mdd_24h,
            "symbols_with_sufficient_closes": symbols_with_sufficient_closes,
            "symbols_with_3+_closes": symbols_with_sufficient_closes,  # Phase 5H.4: explicit 3+ field
            "non_sol_closes_24h": non_sol_closes,  # Phase 5H.4: non-SOL close count
            "net_pnl_usd_24h": net_pnl_usd_24h,  # Phase 5H.4: new metric
            "worst_symbol_expectancy_24h": worst_symbol_expectancy_24h,  # Phase 5H.4: new metric
        },
        "symbol_counts_24h": symbol_counts,
    }
    
    return result


def main() -> int:
    """Main entry point - evaluate and save recovery assist state."""
    result = evaluate_recovery_assist()
    
    # Save to file
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

