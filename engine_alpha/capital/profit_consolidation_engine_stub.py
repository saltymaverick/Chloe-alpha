"""
Profit Consolidation Engine Stub - Advisory profit consolidation suggestions.

No real transfers or fund movement.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime, timezone, timedelta
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[2]
TRADES_PATH = ROOT / "reports" / "trades.jsonl"
CAPITAL_DIR = ROOT / "reports" / "capital"
CONFIG_DIR = ROOT / "config"


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Load JSONL file."""
    if not path.exists():
        return []
    records = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                continue
    return records


def compute_pnl_by_period(trades: List[Dict[str, Any]]) -> Dict[str, float]:
    """Compute PnL by period (daily, weekly, monthly)."""
    now = datetime.now(timezone.utc)
    daily_pnl = 0.0
    weekly_pnl = 0.0
    monthly_pnl = 0.0
    
    for ev in trades:
        if ev.get("logger_version") != "trades_v2":
            continue
        if ev.get("type") != "close":
            continue
        
        pct = ev.get("pct")
        if pct is None:
            continue
        
        try:
            pct = float(pct)
        except (TypeError, ValueError):
            continue
        
        ts_str = ev.get("time") or ev.get("ts")
        if not ts_str:
            continue
        
        # Parse timestamp
        try:
            if isinstance(ts_str, (int, float)):
                trade_time = datetime.fromtimestamp(ts_str, tz=timezone.utc)
            else:
                # Try ISO format
                trade_time = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except Exception:
            continue
        
        # Categorize by period
        age = now - trade_time
        
        if age <= timedelta(days=1):
            daily_pnl += pct
        if age <= timedelta(days=7):
            weekly_pnl += pct
        if age <= timedelta(days=30):
            monthly_pnl += pct
    
    return {
        "daily": daily_pnl,
        "weekly": weekly_pnl,
        "monthly": monthly_pnl,
    }


def generate_consolidation_advice() -> Dict[str, Any]:
    """Generate advisory profit consolidation suggestions."""
    trades = load_jsonl(TRADES_PATH)
    
    if not trades:
        return {
            "action": "none",
            "reason": "No trades found",
            "suggested_pct_of_profit": 0.0,
            "notes": ["No consolidation needed - no trade data"],
        }
    
    pnl_by_period = compute_pnl_by_period(trades)
    
    # Load thresholds (default if not in config)
    tuning_rules = {}
    try:
        import yaml
        rules_path = CONFIG_DIR / "tuning_rules.yaml"
        if rules_path.exists():
            tuning_rules = yaml.safe_load(rules_path.read_text()) or {}
    except Exception:
        pass
    
    # Default thresholds
    monthly_threshold = 0.08  # 8%
    consolidation_pct = 0.5  # 50% of profit
    
    # Check if monthly PnL exceeds threshold
    monthly_pnl = pnl_by_period["monthly"]
    
    if monthly_pnl >= monthly_threshold:
        return {
            "action": "consolidate",
            "reason": f"Monthly PnL ({monthly_pnl:.2%}) above threshold ({monthly_threshold:.2%})",
            "suggested_pct_of_profit": consolidation_pct,
            "to_subaccount": "VAULT",
            "pnl_by_period": pnl_by_period,
            "notes": [
                f"Move {consolidation_pct:.0%} of profit to VAULT subaccount.",
                "This is advisory only - no real transfer has been made.",
            ],
        }
    else:
        return {
            "action": "none",
            "reason": f"Monthly PnL ({monthly_pnl:.2%}) below threshold ({monthly_threshold:.2%})",
            "suggested_pct_of_profit": 0.0,
            "pnl_by_period": pnl_by_period,
            "notes": ["No consolidation needed at this time"],
        }


def main() -> None:
    """Generate consolidation advice."""
    advice = generate_consolidation_advice()
    advice["generated_at"] = datetime.now(timezone.utc).isoformat()
    
    # Write to reports
    CAPITAL_DIR.mkdir(parents=True, exist_ok=True)
    output_path = CAPITAL_DIR / "consolidation_advice.json"
    output_path.write_text(json.dumps(advice, indent=2, sort_keys=True))
    
    print(f"✅ Consolidation advice written to: {output_path}")
    print(f"   Action: {advice['action']}")
    print(f"   Reason: {advice['reason']}")


if __name__ == "__main__":
    main()


