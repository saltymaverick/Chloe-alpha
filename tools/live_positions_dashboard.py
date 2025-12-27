# tools/live_positions_dashboard.py

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from engine_alpha.loop import position_manager as pm


def load_positions_from_disk() -> Dict[str, Any]:
    """
    Load raw position state from the persistent JSON file.
    Falls back to empty if missing or invalid.
    """
    path: Path = pm.POSITION_STATE_PATH
    if not path.exists():
        return {"positions": {}}
    
    try:
        data = json.loads(path.read_text())
        if isinstance(data, dict) and "positions" in data and isinstance(data["positions"], dict):
            return data
        # Backward-compatible: if file is just a dict of positions
        if isinstance(data, dict):
            return {"positions": data}
    except Exception:
        pass
    
    return {"positions": {}}


def summarize_positions(positions_dict: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Build summary stats:
      - total open positions
      - total exploration vs normal
      - per-symbol counts
    """
    summary: Dict[str, Any] = {
        "total_open": 0,
        "exploration_open": 0,
        "normal_open": 0,
        "per_symbol": {},
    }
    
    for key_str, pos in positions_dict.items():
        if not isinstance(pos, dict):
            continue
        
        dir_val = pos.get("dir", 0)
        if dir_val == 0:
            # Closed / flat
            continue
        
        symbol = str(pos.get("symbol", "UNKNOWN")).upper()
        timeframe = str(pos.get("timeframe", "15m")).lower()
        trade_kind = str(pos.get("trade_kind", "normal"))
        summary["total_open"] += 1
        
        if trade_kind == "exploration":
            summary["exploration_open"] += 1
        else:
            summary["normal_open"] += 1
        
        sym_entry = summary["per_symbol"].setdefault(symbol, {
            "timeframes": {},
            "exploration_open": 0,
            "normal_open": 0,
        })
        
        tf_entry = sym_entry["timeframes"].setdefault(timeframe, {
            "positions": [],
        })
        
        if trade_kind == "exploration":
            sym_entry["exploration_open"] += 1
        else:
            sym_entry["normal_open"] += 1
        
        tf_entry["positions"].append(pos)
    
    return summary


def fmt_dir(d: Any) -> str:
    try:
        d = int(d)
    except Exception:
        return "?"
    if d > 0:
        return "LONG"
    if d < 0:
        return "SHORT"
    return "FLAT"


def print_dashboard(summary: Dict[str, Any]) -> None:
    print("")
    print("CHLOE LIVE POSITIONS DASHBOARD")
    print("------------------------------")
    print("")
    print(f"Total open positions    : {summary['total_open']}")
    print(f"  Exploration positions : {summary['exploration_open']}")
    print(f"  Normal positions      : {summary['normal_open']}")
    print("")
    
    if summary["total_open"] == 0:
        print("No open positions found (all symbols flat).")
        print("")
        return
    
    print(f"{'Symbol':8} {'TF':6} {'Kind':12} {'Dir':7} {'EntryPx':>10} {'RiskBand':>9} {'Regime':>12}")
    print("-" * 70)
    
    per_symbol = summary["per_symbol"]
    for symbol in sorted(per_symbol.keys()):
        sym_entry = per_symbol[symbol]
        for timeframe, tf_entry in sym_entry["timeframes"].items():
            for pos in tf_entry["positions"]:
                trade_kind = pos.get("trade_kind", "normal")
                dir_str = fmt_dir(pos.get("dir", 0))
                entry_px = pos.get("entry_px", pos.get("entry_price", ""))
                risk_band = pos.get("risk_band", "")
                regime = pos.get("regime", "")
                
                print(
                    f"{symbol:8} {timeframe:6} {trade_kind:12} {dir_str:7} "
                    f"{str(entry_px):>10} {str(risk_band):>9} {str(regime):>12}"
                )
    
    print("")
    print("Notes:")
    print("  - Kind = 'exploration' trades are from the new exploration lane.")
    print("  - Dir  = LONG/SHORT based on dir field.")
    print("  - EntryPx = price at entry (approximate).")
    print("  - This dashboard reads from position_state.json (shared state).")
    print("")


def main() -> None:
    state = load_positions_from_disk()
    positions_dict = state.get("positions", {})
    if not isinstance(positions_dict, dict):
        positions_dict = {}
    
    summary = summarize_positions(positions_dict)
    print_dashboard(summary)


if __name__ == "__main__":
    main()

