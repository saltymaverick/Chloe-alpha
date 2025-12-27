#!/usr/bin/env python3
"""
PF Attribution & Capital Mode Diagnosis (Phase 5e)
---------------------------------------------------

Read-only diagnostic tool that attributes PF to lanes and symbols,
explaining why capital_mode is set to its current value.

Outputs:
1. PF by lane (core, explore, exploit, shadow)
2. PF by symbol (sorted worst → best)
3. Loss contribution table
4. Capital mode explanation

This tool is READ-ONLY and does not modify any state or configs.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine_alpha.core.paths import REPORTS
from engine_alpha.research.pf_timeseries import _extract_return, _compute_pf_for_window
from engine_alpha.reflect.trade_sanity import filter_corrupted


def _load_json(path: Path) -> Dict[str, Any]:
    """Safely load JSON file."""
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Load JSONL file."""
    if not path.exists():
        return []
    trades = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    trades.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        pass
    return trades


def _parse_timestamp(ts: Any) -> Optional[datetime]:
    """Parse timestamp from various formats."""
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc)
        except Exception:
            return None
    if isinstance(ts, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                return datetime.strptime(ts, fmt).astimezone(timezone.utc)
            except Exception:
                continue
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            return None
    return None


def _classify_lane(trade: Dict[str, Any]) -> str:
    """Classify trade into lane (core, explore, exploit, shadow)."""
    # Check explicit lane field
    lane = trade.get("lane") or trade.get("lane_intent")
    if lane:
        lane_lower = str(lane).lower()
        if "exploit" in lane_lower:
            if "shadow" in lane_lower or trade.get("shadow_only"):
                return "shadow"
            return "exploit"
        if "explore" in lane_lower:
            return "explore"
        if "core" in lane_lower:
            return "core"
    
    # Check file source (fallback)
    # This is approximate - we'll use explicit lane when available
    return "core"  # Default to core


def _compute_pf_by_lane(
    trades: List[Dict[str, Any]],
    window_days: int,
    now: datetime,
) -> Tuple[Optional[float], int]:
    """Compute PF for a lane within a time window."""
    window_trades = []
    for trade in trades:
        ts = _parse_timestamp(trade.get("ts") or trade.get("timestamp"))
        if ts is None:
            continue
        delta = now - ts
        if delta.total_seconds() > window_days * 86400.0:
            continue
        
        # Only count closes for PF
        event_type = str(trade.get("type") or trade.get("event", "")).lower()
        if event_type not in ("close", "would_exit"):
            continue
        
        rets = _extract_return(trade)
        if rets is None:
            continue
        
        window_trades.append(rets)
    
    if not window_trades:
        return None, 0
    
    stats = _compute_pf_for_window(window_trades)
    return stats.pf, stats.trades


def _compute_pf_by_symbol(
    trades: List[Dict[str, Any]],
    window_days: int,
    now: datetime,
) -> Dict[str, Tuple[Optional[float], float, int]]:
    """Compute PF, PnL USD, and trade count per symbol."""
    by_symbol: Dict[str, List[Tuple[float, float]]] = defaultdict(list)
    
    for trade in trades:
        ts = _parse_timestamp(trade.get("ts") or trade.get("timestamp"))
        if ts is None:
            continue
        delta = now - ts
        if delta.total_seconds() > window_days * 86400.0:
            continue
        
        event_type = str(trade.get("type") or trade.get("event", "")).lower()
        if event_type not in ("close", "would_exit"):
            continue
        
        symbol = trade.get("symbol") or trade.get("pair")
        if not symbol or symbol == "UNKNOWN":
            # Skip trades without valid symbol
            continue
        rets = _extract_return(trade)
        if rets is None:
            continue
        
        r, w = rets
        pnl_usd = r * w  # Approximate PnL in USD
        by_symbol[symbol].append((r, w))
    
    results = {}
    for symbol, returns in by_symbol.items():
        stats = _compute_pf_for_window(returns)
        total_pnl = sum(r * w for r, w in returns)
        results[symbol] = (stats.pf, total_pnl, stats.trades)
    
    return results


def _get_capital_mode_explanation(
    capital_protection: Dict[str, Any],
    pf_by_symbol: Dict[str, Tuple[Optional[float], float, int]],
) -> Dict[str, Any]:
    """Generate capital mode explanation."""
    global_data = capital_protection.get("global", {}) or capital_protection
    mode = global_data.get("mode", "unknown")
    pf_7d = global_data.get("pf_7d")
    pf_30d = global_data.get("pf_30d")
    reasons = global_data.get("reasons", [])
    
    # Find top loss contributors
    symbol_losses = [
        (sym, pnl, pf, trades)
        for sym, (pf, pnl, trades) in pf_by_symbol.items()
        if pnl < 0
    ]
    symbol_losses.sort(key=lambda x: x[1])  # Sort by loss (most negative first)
    
    top_contributors = []
    total_loss = sum(pnl for _, pnl, _, _ in symbol_losses)
    for sym, pnl, pf, trades in symbol_losses[:5]:
        if total_loss != 0:
            pct_contrib = (pnl / total_loss) * 100
        else:
            pct_contrib = 0.0
        top_contributors.append({
            "symbol": sym,
            "pnl_usd": pnl,
            "pf": pf,
            "trades": trades,
            "pct_contribution": pct_contrib,
        })
    
    # Recommendation
    recommendation = "Unknown"
    if mode == "de_risk":
        if pf_7d is not None and pf_7d < 0.98:
            recommendation = "Wait for PF_7D recovery OR prune underperforming symbols"
    elif mode == "halt_new_entries":
        recommendation = "Immediate action required: halt all new entries until PF recovers"
    elif mode == "normal":
        recommendation = "System operating normally"
    
    return {
        "mode": mode,
        "pf_7d": pf_7d,
        "pf_30d": pf_30d,
        "trigger": reasons[0] if reasons else "unknown",
        "top_contributors": top_contributors,
        "recommendation": recommendation,
    }


def run_pf_attribution() -> Dict[str, Any]:
    """Run PF attribution analysis."""
    now = datetime.now(timezone.utc)
    
    # Load trade logs from all lanes
    core_trades_raw = _load_jsonl(REPORTS / "trades.jsonl")
    exploit_trades_raw = _load_jsonl(REPORTS / "loop" / "exploit_micro_log.jsonl")
    shadow_trades_raw = _load_jsonl(REPORTS / "reflect" / "shadow_exploit_log.jsonl")
    
    # Load exploration trades if present
    explore_trades_raw = []
    explore_dir = REPORTS / "exploration"
    if explore_dir.exists():
        for path in explore_dir.glob("*.jsonl"):
            explore_trades_raw.extend(_load_jsonl(path))
    
    # Filter corrupted events (analytics-only)
    core_trades = filter_corrupted(core_trades_raw)
    exploit_trades = filter_corrupted(exploit_trades_raw)
    shadow_trades = filter_corrupted(shadow_trades_raw)
    explore_trades = filter_corrupted(explore_trades_raw)
    
    # Classify trades by lane
    all_trades = []
    for trade in core_trades:
        trade["_lane"] = "core"
        all_trades.append(trade)
    
    for trade in exploit_trades:
        trade["_lane"] = "exploit"
        all_trades.append(trade)
    
    for trade in shadow_trades:
        trade["_lane"] = "shadow"
        all_trades.append(trade)
    
    for trade in explore_trades:
        trade["_lane"] = "explore"
        all_trades.append(trade)
    
    # Load capital protection
    capital_protection = _load_json(REPORTS / "risk" / "capital_protection.json")
    
    # Compute PF by lane (30D window)
    lane_pf = {}
    for lane in ["core", "explore", "exploit", "shadow"]:
        lane_trades = [t for t in all_trades if t.get("_lane") == lane]
        pf, trades = _compute_pf_by_lane(lane_trades, window_days=30, now=now)
        lane_pf[lane] = {"pf": pf, "trades": trades}
    
    # Compute PF by symbol (30D window)
    symbol_pf = _compute_pf_by_symbol(all_trades, window_days=30, now=now)
    
    # Sort symbols by PF (worst first)
    symbol_list = [
        (sym, pf, pnl, trades)
        for sym, (pf, pnl, trades) in symbol_pf.items()
    ]
    symbol_list.sort(key=lambda x: (x[1] if x[1] is not None else 0.0, x[2]))
    
    # Capital mode explanation
    mode_explanation = _get_capital_mode_explanation(capital_protection, symbol_pf)
    
    return {
        "lane_pf": lane_pf,
        "symbol_pf": symbol_list,
        "mode_explanation": mode_explanation,
        "generated_at": now.isoformat(),
    }


def main() -> int:
    """Main entry point."""
    result = run_pf_attribution()
    
    print("PF ATTRIBUTION & CAPITAL MODE DIAGNOSIS (Phase 5e)")
    print("=" * 70)
    print()
    
    # 1. PF by Lane
    print("PF BY LANE (30D)")
    print("-" * 70)
    lane_pf = result["lane_pf"]
    for lane in ["core", "explore", "exploit", "shadow"]:
        data = lane_pf.get(lane, {})
        pf = data.get("pf")
        trades = data.get("trades", 0)
        pf_str = f"{pf:.2f}" if pf is not None else "—"
        print(f"lane={lane:<10} PF={pf_str:<6} trades={trades}")
    print()
    
    # 2. PF by Symbol
    print("SYMBOL PF ATTRIBUTION (30D)")
    print("-" * 70)
    symbol_list = result["symbol_pf"]
    if symbol_list:
        for sym, pf, pnl, trades in symbol_list[:20]:  # Top 20
            pf_str = f"{pf:.2f}" if pf is not None else "—"
            pnl_str = f"{pnl:+.2f}" if pnl is not None else "0.00"
            print(f"{sym:<12} PF={pf_str:<6} pnl={pnl_str:<10} trades={trades}")
        if len(symbol_list) > 20:
            print(f"... and {len(symbol_list) - 20} more symbols")
    else:
        print("(no trades found)")
    print()
    
    # 3. Loss Contribution Table
    print("LOSS CONTRIBUTION TABLE (30D)")
    print("-" * 70)
    mode_explanation = result["mode_explanation"]
    top_contributors = mode_explanation.get("top_contributors", [])
    if top_contributors:
        for contrib in top_contributors:
            sym = contrib["symbol"]
            pnl = contrib["pnl_usd"]
            pf = contrib["pf"]
            pct = contrib["pct_contribution"]
            pf_str = f"{pf:.2f}" if pf is not None else "—"
            print(f"{sym:<12} PnL=${pnl:+.2f}  PF={pf_str:<6}  Contribution={pct:.1f}%")
    else:
        print("(no significant losses found)")
    print()
    
    # 4. Capital Mode Explanation
    print("CAPITAL MODE ATTRIBUTION")
    print("-" * 70)
    mode = mode_explanation.get("mode", "unknown")
    pf_7d = mode_explanation.get("pf_7d")
    pf_30d = mode_explanation.get("pf_30d")
    trigger = mode_explanation.get("trigger", "unknown")
    recommendation = mode_explanation.get("recommendation", "Unknown")
    
    print(f"capital_mode = {mode}")
    print(f"Triggered by: {trigger}")
    if pf_7d is not None:
        print(f"PF_7D = {pf_7d:.3f}")
    if pf_30d is not None:
        print(f"PF_30D = {pf_30d:.3f}")
    
    if top_contributors:
        print("Top contributors:")
        for contrib in top_contributors[:3]:
            sym = contrib["symbol"]
            pct = contrib["pct_contribution"]
            print(f"  - {sym} ({pct:.1f}%)")
    
    print(f"Recommendation: {recommendation}")
    print()
    print("=" * 70)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

