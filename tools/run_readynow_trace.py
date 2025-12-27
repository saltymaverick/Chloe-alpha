#!/usr/bin/env python3
"""
ReadyNow Trace Diagnostic (Phase 5e)
------------------------------------

Read-only diagnostic tool that traces why symbols are ReadyNow=YES or NO.

For each symbol, shows:
- execution_quality status
- drift status
- policy level
- sample_window sufficiency
- persistence (bars above threshold)

This tool is READ-ONLY and does not modify any state or configs.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine_alpha.core.paths import REPORTS


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
    entries = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        pass
    return entries


def _get(obj: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Safely descend nested dicts."""
    current = obj
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current


def _get_execution_quality(
    execql: Dict[str, Any],
    symbol: str,
) -> Tuple[str, str]:
    """Get execution quality label and status."""
    label = _get(execql, "data", symbol, "summary", "overall_label") or \
            _get(execql, "symbols", symbol, "overall_label") or \
            _get(execql, "symbols", symbol, "label") or "unknown"
    
    if label == "hostile":
        return label, "fail"
    elif label == "degraded":
        return label, "warn"
    else:
        return label, "ok"


def _get_drift_status(
    drift: Dict[str, Any],
    symbol: str,
) -> Tuple[str, str]:
    """Get drift status."""
    status = _get(drift, "symbols", symbol, "status") or "unknown"
    
    if status == "degrading":
        return status, "fail"
    elif status == "improving":
        return status, "ok"
    else:
        return status, "ok"  # neutral is ok


def _get_policy_level(
    policy: Dict[str, Any],
    symbol: str,
) -> Tuple[str, str]:
    """Get policy level (Phase 5f: policy-aware, not policy-punitive)."""
    level = _get(policy, "symbols", symbol, "level") or "unknown"
    
    if level == "blocked":
        return level, "fail"  # Hard blocker
    elif level == "reduced":
        return level, "ok"  # Phase 5f: reduced is allowed (penalty applied, not blocker)
    else:
        return level, "ok"  # full is ok


def _check_sample_window(
    pf_ts: Dict[str, Any],
    symbol: str,
) -> Tuple[bool, str]:
    """Check if sample window is sufficient."""
    symbols = pf_ts.get("symbols", {})
    symbol_data = symbols.get(symbol, {})
    
    # Check 7D and 30D windows
    win7d = symbol_data.get("7d", {})
    win30d = symbol_data.get("30d", {})
    
    trades_7d = win7d.get("trades", 0)
    trades_30d = win30d.get("trades", 0)
    
    # Minimum thresholds (from live_candidate_scanner logic)
    if trades_7d < 10 or trades_30d < 20:
        return False, f"insufficient (7d={trades_7d}, 30d={trades_30d})"
    
    return True, "sufficient"


def _check_persistence(
    history: List[Dict[str, Any]],
    symbol: str,
    cutoff: datetime,
) -> Tuple[str, str]:
    """Check persistence (bars above threshold)."""
    symbol_history = [
        e for e in history
        if e.get("symbol") == symbol
    ]
    
    # Filter by cutoff
    recent_history = []
    for entry in symbol_history:
        ts_str = entry.get("ts")
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).astimezone(timezone.utc)
            if ts >= cutoff:
                recent_history.append(entry)
        except Exception:
            continue
    
    if not recent_history:
        return "0/0", "fail"
    
    # Count entries with score >= 0.75 and hard_pass
    above_threshold = sum(
        1 for e in recent_history
        if (e.get("score") or 0.0) >= 0.75 and e.get("hard_pass")
    )
    total = len(recent_history)
    
    # Need at least 12 readings and 80% above threshold
    if total < 12:
        return f"{above_threshold}/{total}", "fail"
    
    ratio = above_threshold / total if total > 0 else 0.0
    if ratio < 0.8:
        return f"{above_threshold}/{total}", "fail"
    
    return f"{above_threshold}/{total}", "ok"


def _trace_symbol_readynow(
    symbol: str,
    live_candidates: Dict[str, Any],
    execql: Dict[str, Any],
    drift: Dict[str, Any],
    policy: Dict[str, Any],
    pf_ts: Dict[str, Any],
    history: List[Dict[str, Any]],
    cutoff: datetime,
) -> Dict[str, Any]:
    """Trace ReadyNow status for a single symbol."""
    symbols_data = live_candidates.get("symbols", {})
    symbol_data = symbols_data.get(symbol, {})
    
    ready_now = symbol_data.get("ready_now", False)
    if isinstance(ready_now, str):
        ready_now = ready_now.upper() in ("Y", "YES", "TRUE")
    
    # Check each component
    exec_label, exec_status = _get_execution_quality(execql, symbol)
    drift_status, drift_ok = _get_drift_status(drift, symbol)
    policy_level, policy_ok = _get_policy_level(policy, symbol)
    sample_ok, sample_msg = _check_sample_window(pf_ts, symbol)
    persistence_str, persistence_ok = _check_persistence(history, symbol, cutoff)
    
    # Collect reasons (Phase 5f: policy=reduced is not a blocker)
    reasons = []
    if exec_status == "fail":
        reasons.append(f"execution_quality={exec_label}")
    if drift_ok == "fail":
        reasons.append(f"drift={drift_status}")
    if policy_ok == "fail":
        reasons.append(f"policy={policy_level}")  # Only blocked fails
    if not sample_ok:
        reasons.append(f"sample_window={sample_msg}")
    if persistence_ok == "fail":
        reasons.append(f"persistence={persistence_str}")
    
    # Phase 5f: Add annotation for policy=reduced
    if policy_level == "reduced" and policy_ok == "ok":
        # Note: policy=reduced applies penalty but doesn't block
        pass  # Will be shown in components
    
    return {
        "symbol": symbol,
        "ready_now": ready_now,
        "reasons": reasons,
        "components": {
            "execution_quality": {"value": exec_label, "status": exec_status},
            "drift": {"value": drift_status, "status": drift_ok},
            "policy": {"value": policy_level, "status": policy_ok},
            "sample_window": {"value": sample_msg, "status": "ok" if sample_ok else "fail"},
            "persistence": {"value": persistence_str, "status": persistence_ok},
        },
    }


def run_readynow_trace() -> Dict[str, Any]:
    """Run ReadyNow trace analysis."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    
    # Load all required inputs
    live_candidates = _load_json(REPORTS / "risk" / "live_candidates.json")
    execql = _load_json(REPORTS / "research" / "execution_quality.json")
    drift = _load_json(REPORTS / "research" / "drift_report.json")
    policy = _load_json(REPORTS / "research" / "exploration_policy_v3.json")
    pf_ts = _load_json(REPORTS / "pf" / "pf_timeseries.json")
    history = _load_jsonl(REPORTS / "risk" / "live_candidates_history.jsonl")
    
    # Get all symbols from capital plan
    capital_plan = _load_json(REPORTS / "risk" / "capital_plan.json")
    symbols = set()
    
    symbols_data = capital_plan.get("symbols", {}) or capital_plan.get("by_symbol", {})
    for sym in symbols_data.keys():
        if isinstance(sym, str) and sym.endswith("USDT"):
            symbols.add(sym)
    
    # Also get symbols from live_candidates
    live_symbols = live_candidates.get("symbols", {})
    for sym in live_symbols.keys():
        if isinstance(sym, str) and sym.endswith("USDT"):
            symbols.add(sym)
    
    # Trace each symbol
    traces = []
    blockers = []
    
    for symbol in sorted(symbols):
        trace = _trace_symbol_readynow(
            symbol=symbol,
            live_candidates=live_candidates,
            execql=execql,
            drift=drift,
            policy=policy,
            pf_ts=pf_ts,
            history=history,
            cutoff=cutoff,
        )
        traces.append(trace)
        
        if not trace["ready_now"] and trace["reasons"]:
            # Get primary blocker
            primary = trace["reasons"][0] if trace["reasons"] else "unknown"
            blockers.append((symbol, primary))
    
    return {
        "traces": traces,
        "blockers": blockers,
        "generated_at": now.isoformat(),
    }


def main() -> int:
    """Main entry point."""
    result = run_readynow_trace()
    
    print("READYNOW TRACE (Why Exploits Are Blocked) (Phase 5e)")
    print("=" * 70)
    print()
    
    traces = result["traces"]
    blockers = result["blockers"]
    
    # Show traces for exploit-intent symbols first
    capital_plan = _load_json(REPORTS / "risk" / "capital_plan.json")
    symbols_data = capital_plan.get("symbols", {}) or capital_plan.get("by_symbol", {})
    
    exploit_symbols = [
        sym for sym, data in symbols_data.items()
        if data.get("lane_intent") == "exploit"
    ]
    
    # Show traces
    for trace in traces:
        symbol = trace["symbol"]
        ready_now = trace["ready_now"]
        reasons = trace["reasons"]
        components = trace["components"]
        
        # Prioritize exploit symbols
        is_exploit = symbol in exploit_symbols
        if not is_exploit and len(traces) > 10:
            continue  # Skip non-exploit symbols if too many
        
        print(f"READYNOW TRACE — {symbol}")
        print("-" * 70)
        print(f"ready_now: {'YES' if ready_now else 'NO'}")
        
        if not ready_now:
            print("Reasons:")
            for reason in reasons:
                print(f"  - {reason}")
        else:
            print("Reasons: (all checks passed)")
        
        print("Components:")
        for comp_name, comp_data in components.items():
            value = comp_data["value"]
            status = comp_data["status"]
            status_str = "✓" if status == "ok" else "✗"
            print(f"  - {comp_name} = {value} ({status_str})")
        print()
    
    # Summary table
    if blockers:
        print("READYNOW BLOCK SUMMARY")
        print("-" * 70)
        for symbol, reason in blockers[:20]:
            print(f"{symbol:<12} → {reason}")
        if len(blockers) > 20:
            print(f"... and {len(blockers) - 20} more blocked symbols")
    else:
        print("READYNOW BLOCK SUMMARY")
        print("-" * 70)
        print("(no blockers found)")
    
    print()
    print("=" * 70)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

