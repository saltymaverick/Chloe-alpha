#!/usr/bin/env python3
"""
Monitor Chloe status in a human-friendly way.

Prints:
- Timeframe
- Per-asset: trades, PF (from overseer / pf_local), trading enabled
- For ETH:
  - latest regime_state
  - latest drift_state (drift_score, pf_local)
  - latest confidence_state (confidence, components, penalties)
  - last 3 trades (direction, size, pnl if available)
"""

import json
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from engine_alpha.core.paths import REPORTS, CONFIG
from engine_alpha.loop.autonomous_trader import DEFAULT_TIMEFRAME


def load_json_safe(path: Path) -> Dict[str, Any]:
    """Load JSON file safely, return empty dict on error."""
    if not path.exists():
        return {}
    try:
        with path.open() as f:
            return json.load(f)
    except Exception:
        return {}


def get_timeframe() -> str:
    """Get timeframe from config."""
    try:
        config_path = CONFIG / "engine_config.json"
        if config_path.exists():
            cfg = load_json_safe(config_path)
            return cfg.get("timeframe", DEFAULT_TIMEFRAME)
    except Exception:
        pass
    return DEFAULT_TIMEFRAME


def get_mode() -> str:
    """Get current mode (PAPER/DRY_RUN)."""
    import os
    if os.getenv("MODE", "").upper() == "DRY_RUN" or os.getenv("CHLOE_DRY_RUN", "0") == "1":
        return "DRY_RUN"
    return "PAPER"


def get_overseer_report() -> Dict[str, Any]:
    """Load overseer report."""
    overseer_path = REPORTS / "research" / "overseer_report.json"
    return load_json_safe(overseer_path)


def get_pf_local() -> Dict[str, Any]:
    """Load PF local report."""
    return load_json_safe(REPORTS / "pf_local.json")


def get_recent_trades(symbol: str = "ETHUSDT", limit: int = 3) -> List[Dict[str, Any]]:
    """Get recent trades for a symbol."""
    trades_path = REPORTS / "trades.jsonl"
    if not trades_path.exists():
        return []
    
    trades = []
    try:
        with trades_path.open() as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    trade = json.loads(line)
                    trade_symbol = trade.get("symbol", "").upper()
                    if trade_symbol == symbol.upper():
                        trades.append(trade)
                except Exception:
                    continue
    except Exception:
        pass
    
    # Return most recent first
    return trades[-limit:][::-1]


def get_latest_dry_run_decision() -> Optional[Dict[str, Any]]:
    """Get latest decision from dry-run logs if available."""
    decision_path = REPORTS / "dry_run_decisions.jsonl"
    if not decision_path.exists():
        return None
    
    try:
        with decision_path.open() as f:
            lines = f.readlines()
            if lines:
                return json.loads(lines[-1])
    except Exception:
        pass
    return None


def format_pf(pf_val: Any) -> str:
    """Format PF value for display."""
    if isinstance(pf_val, (int, float)):
        return f"{pf_val:.2f}"
    return "—"


def format_confidence(conf: float) -> str:
    """Format confidence value."""
    return f"{conf:.2f}"


def main() -> None:
    """Print status report."""
    timeframe = get_timeframe()
    mode = get_mode()
    
    print("=" * 70)
    print(f"CHLOE STATUS ({mode}, {timeframe})")
    print("=" * 70)
    print()
    
    # Load overseer report
    overseer = get_overseer_report()
    phase = overseer.get("phase", "unknown")
    assets = overseer.get("assets", {})
    
    print(f"Timeframe: {timeframe}")
    print(f"Phase: {phase}")
    print()
    
    # ETHUSDT detailed view
    eth_info = assets.get("ETHUSDT", {})
    eth_trades = eth_info.get("total_trades", 0)
    eth_pf = format_pf(eth_info.get("pf"))
    eth_enabled = eth_info.get("trading_enabled", False)
    eth_comment = eth_info.get("overseer_comment", "N/A")
    
    print("ETHUSDT:")
    print(f"  Trades: {eth_trades}, PF: {eth_pf}")
    print(f"  Trading enabled: {eth_enabled}")
    print(f"  Status: {eth_comment}")
    
    # Try to get latest decision state from dry-run logs
    latest_decision = get_latest_dry_run_decision()
    if latest_decision:
        regime = latest_decision.get("regime", "unknown")
        drift = latest_decision.get("drift", {})
        drift_score = drift.get("drift_score", 0.0)
        pf_local = drift.get("pf_local", 0.0)
        confidence = latest_decision.get("confidence", {})
        conf_final = confidence.get("final", 0.0)
        components = confidence.get("components", {})
        penalties = confidence.get("penalties", {})
        
        print(f"  Regime (last decision): {regime}")
        print(f"  Drift: score={drift_score:.2f}, pf_local={pf_local:.3f}")
        print(f"  Confidence: {format_confidence(conf_final)}", end="")
        if components:
            flow = components.get("flow", 0.0)
            vol = components.get("volatility", 0.0)
            micro = components.get("microstructure", 0.0)
            cross = components.get("cross_asset", 0.0)
            print(f" (flow={flow:.1f}, vol={vol:.1f}, micro={micro:.1f}, cross={cross:.1f})")
        else:
            print()
        if penalties:
            regime_pen = penalties.get("regime", 1.0)
            drift_pen = penalties.get("drift", 1.0)
            print(f"    Penalties: regime={regime_pen:.2f}, drift={drift_pen:.2f}")
    
    # Recent trades
    recent_trades = get_recent_trades("ETHUSDT", limit=3)
    if recent_trades:
        print("  Last trades:")
        for i, trade in enumerate(recent_trades):
            ts = trade.get("ts", trade.get("timestamp", "N/A"))
            direction = trade.get("direction", trade.get("dir", "unknown"))
            size_mult = trade.get("size_multiplier", trade.get("size", "N/A"))
            pnl = trade.get("pct", trade.get("pnl", "N/A"))
            conf = trade.get("confidence", trade.get("conf", "N/A"))
            
            pnl_str = f"{pnl:+.4f}" if isinstance(pnl, (int, float)) else str(pnl)
            conf_str = f"{conf:.2f}" if isinstance(conf, (int, float)) else str(conf)
            size_str = f"{size_mult:.1f}x" if isinstance(size_mult, (int, float)) else str(size_mult)
            
            print(f"    - [t-{i+1}] {direction} size={size_str}, pnl={pnl_str}, conf={conf_str}")
    else:
        print("  Last trades: (none yet)")
    
    print()
    
    # Other assets summary
    print("Other assets:")
    for symbol, info in sorted(assets.items()):
        if symbol == "ETHUSDT":
            continue
        trades = info.get("total_trades", 0)
        pf = format_pf(info.get("pf"))
        enabled = info.get("trading_enabled", False)
        mode_str = "trading" if enabled else "research"
        print(f"  {symbol}: trades={trades}, PF={pf}, mode={mode_str}")
    
    print()
    print("=" * 70)
    print("For detailed overseer view: python -m tools.overseer_report")
    print("For recent trades: tail -5 reports/trades.jsonl | jq .")
    print("=" * 70)


if __name__ == "__main__":
    main()

