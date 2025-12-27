#!/usr/bin/env python3
"""
Chloe Real-Time HUD - Terminal status display updating every second.

Shows:
- Current phase and enabled trading symbols
- ETHUSDT and MATICUSDT status (trades, PF)
- Recent ETH trades (closes)
- Recent MATIC decisions
- Global PF summary

Run with: python3 -m tools.hud
Exit with: Ctrl+C
"""

import json
import time
import os
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

CONFIG_DIR = ROOT_DIR / "config"
REPORTS_DIR = ROOT_DIR / "reports"
SCORECARDS_DIR = REPORTS_DIR / "scorecards"
LOGS_DIR = ROOT_DIR / "logs"

TRADING_ENABLEMENT_PATH = CONFIG_DIR / "trading_enablement.json"
SCORECARDS_PATH = SCORECARDS_DIR / "asset_scorecards.json"
PF_LOCAL_PATH = REPORTS_DIR / "pf_local.json"
TRADES_PATH = REPORTS_DIR / "trades.jsonl"
MATIC_LOG_PATH = LOGS_DIR / "matic_decisions.log"


def clear_screen():
    """Clear the terminal screen."""
    os.system("clear" if os.name != "nt" else "cls")


def load_json_safe(path: Path, default: Any = None) -> Any:
    """Load JSON file safely, returning default if file doesn't exist or is invalid."""
    if default is None:
        default = {}
    
    if not path.exists():
        return default
    
    try:
        with path.open("r", encoding="utf-8") as f:
            data = f.read().strip()
            if not data:
                return default
            return json.loads(data)
    except (json.JSONDecodeError, IOError, OSError):
        return default


def read_last_lines(path: Path, n: int = 5) -> List[str]:
    """Read last N lines from a text file."""
    if not path.exists():
        return []
    
    try:
        with path.open("r", encoding="utf-8") as f:
            lines = f.readlines()
        return [line.strip() for line in lines[-n:] if line.strip()]
    except (IOError, OSError):
        return []


def get_asset_card(scorecards: Dict[str, Any], symbol: str) -> Dict[str, Any]:
    """Extract asset scorecard for a given symbol."""
    assets = scorecards.get("assets", [])
    
    if isinstance(assets, dict):
        return assets.get(symbol, {})
    
    if isinstance(assets, list):
        for row in assets:
            if row.get("symbol") == symbol:
                return row
    
    return {}


def count_trades_from_jsonl(symbol: str, trades_path: Path) -> int:
    """Count close trades for a symbol from trades.jsonl."""
    if not trades_path.exists():
        return 0
    
    count = 0
    try:
        with trades_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if obj.get("type") == "close" and obj.get("symbol", "ETHUSDT").upper() == symbol.upper():
                        # Filter out ghost closes
                        entry_px = obj.get("entry_px")
                        exit_px = obj.get("exit_px")
                        regime = obj.get("regime", "")
                        if not ((entry_px is None and exit_px is None) or regime == "unknown"):
                            count += 1
                except (json.JSONDecodeError, KeyError):
                    continue
    except (IOError, OSError):
        pass
    
    return count


def get_recent_trades(trades_path: Path, symbol: str, limit: int = 3) -> List[Dict[str, Any]]:
    """Get recent close trades for a symbol."""
    if not trades_path.exists():
        return []
    
    trades = []
    try:
        with trades_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if obj.get("type") == "close" and obj.get("symbol", "ETHUSDT").upper() == symbol.upper():
                        # Filter out ghost closes
                        entry_px = obj.get("entry_px")
                        exit_px = obj.get("exit_px")
                        regime = obj.get("regime", "")
                        if not ((entry_px is None and exit_px is None) or regime == "unknown"):
                            trades.append(obj)
                except (json.JSONDecodeError, KeyError):
                    continue
    except (IOError, OSError):
        pass
    
    return trades[-limit:]


def format_timestamp(ts_str: str) -> str:
    """Format ISO timestamp to shorter display format."""
    try:
        # Handle various timestamp formats
        if "T" in ts_str:
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        return ts_str
    except (ValueError, AttributeError):
        return ts_str[:19] if len(ts_str) >= 19 else ts_str


def main():
    """Main HUD loop."""
    print("Starting Chloe Real-Time HUD...")
    print("Press Ctrl+C to exit.")
    time.sleep(1)
    
    try:
        while True:
            clear_screen()
            
            # Current time
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            
            # Load data files
            trading_cfg = load_json_safe(TRADING_ENABLEMENT_PATH, {})
            scorecards = load_json_safe(SCORECARDS_PATH, {})
            pf_obj = load_json_safe(PF_LOCAL_PATH, {})
            
            # Extract phase and enabled symbols
            phase = trading_cfg.get("phase", "unknown")
            enabled = trading_cfg.get("enabled_for_trading", [])
            
            # Get asset scorecards
            eth_card = get_asset_card(scorecards, "ETHUSDT")
            matic_card = get_asset_card(scorecards, "MATICUSDT")
            
            # Extract metrics
            eth_pf = eth_card.get("pf")
            eth_trades_scorecard = eth_card.get("total_trades", 0)
            # Also count from trades.jsonl for accuracy
            eth_trades_count = count_trades_from_jsonl("ETHUSDT", TRADES_PATH)
            
            matic_pf = matic_card.get("pf")
            matic_trades_scorecard = matic_card.get("total_trades", 0)
            matic_trades_count = count_trades_from_jsonl("MATICUSDT", TRADES_PATH)
            
            # Get recent ETH trades
            eth_trades_recent = get_recent_trades(TRADES_PATH, "ETHUSDT", limit=3)
            
            # Get recent MATIC decisions
            matic_decisions = read_last_lines(MATIC_LOG_PATH, n=5)
            
            # Print HUD
            print("=" * 60)
            print("CHLOE REAL-TIME HUD")
            print("=" * 60)
            print(f"Time:  {now}")
            print(f"Phase: {phase}")
            print()
            
            print(f"Trading enabled (paper): {', '.join(enabled) if enabled else 'None'}")
            print()
            
            print("ASSET STATUS")
            print("-" * 60)
            eth_pf_str = f"{eth_pf:.3f}" if eth_pf is not None else "—"
            print(f"ETHUSDT:   trades={eth_trades_count} (scorecard: {eth_trades_scorecard}), PF={eth_pf_str}")
            matic_pf_str = f"{matic_pf:.3f}" if matic_pf is not None else "—"
            print(f"MATICUSDT: trades={matic_trades_count} (scorecard: {matic_trades_scorecard}), PF={matic_pf_str}")
            print()
            
            print("RECENT ETH TRADES (closes)")
            print("-" * 60)
            if not eth_trades_recent:
                print("  (no ETH closes yet)")
            else:
                for t in eth_trades_recent:
                    ts = format_timestamp(t.get("ts", "?"))
                    pct = t.get("pct", 0.0)
                    regime = t.get("regime", "?")
                    reason = t.get("exit_reason", t.get("exit_label", "?"))
                    direction = "LONG" if t.get("dir", 0) == 1 else "SHORT" if t.get("dir", 0) == -1 else "FLAT"
                    print(f"  {ts} | {direction:5s} | pct={pct:+.4f} | regime={regime:12s} | exit={reason}")
            print()
            
            print("RECENT MATIC DECISIONS")
            print("-" * 60)
            if not matic_decisions:
                print("  (no MATIC decisions logged yet)")
            else:
                for line in matic_decisions:
                    # Extract key info from log line
                    if " | " in line:
                        _, msg = line.split(" | ", 1)
                        # Try to extract decision and reason
                        decision = "?"
                        reason = "?"
                        if "decision=" in msg:
                            try:
                                decision_part = [p for p in msg.split() if "decision=" in p][0]
                                decision = decision_part.split("=")[1]
                            except (IndexError, ValueError):
                                pass
                        if "reason=" in msg:
                            try:
                                reason_part = [p for p in msg.split() if "reason=" in p][0]
                                reason = reason_part.split("=")[1]
                            except (IndexError, ValueError):
                                pass
                        # Extract regime, dir, conf if available
                        regime = "?"
                        dir_str = "?"
                        conf = "?"
                        if "regime=" in msg:
                            try:
                                regime_part = [p for p in msg.split() if "regime=" in p][0]
                                regime = regime_part.split("=")[1]
                            except (IndexError, ValueError):
                                pass
                        if "dir=" in msg:
                            try:
                                dir_part = [p for p in msg.split() if "dir=" in p][0]
                                dir_val = dir_part.split("=")[1]
                                dir_str = "LONG" if dir_val == "1" else "SHORT" if dir_val == "-1" else "FLAT"
                            except (IndexError, ValueError):
                                pass
                        if "conf=" in msg:
                            try:
                                conf_part = [p for p in msg.split() if "conf=" in p][0]
                                conf = conf_part.split("=")[1]
                            except (IndexError, ValueError):
                                pass
                        print(f"  {decision:7s} | {regime:12s} | {dir_str:5s} | conf={conf:5s} | {reason}")
                    else:
                        print(f"  {line}")
            print()
            
            print("PF (global)")
            print("-" * 60)
            if pf_obj:
                pf_val = pf_obj.get("pf", 0.0)
                count = pf_obj.get("count", 0)
                window = pf_obj.get("window", 150)
                print(f"  PF={pf_val:.3f}  count={count}  window={window}")
            else:
                print("  No PF data yet.")
            print()
            
            print("Press Ctrl+C to exit.")
            
            time.sleep(1.0)
    
    except KeyboardInterrupt:
        print("\n\nExiting HUD...")
        sys.exit(0)
    except Exception as e:
        print(f"\n\nError in HUD: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

