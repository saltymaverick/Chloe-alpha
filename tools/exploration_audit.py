import json
from pathlib import Path
from collections import defaultdict
from typing import Dict, Any, List, Tuple


TRADES_PATH = Path("reports/trades.jsonl")
XRAY_PATH = Path("reports/xray/latest.jsonl")


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
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
                # Skip bad lines
                continue
    return records


def summarize_trades(trades: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Summarize trades per symbol, focusing on exploration trades.
    We only use v2 logs and type='close' events.
    """
    per_symbol: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "exploration_trades": 0,
        "exploration_wins": 0,
        "exploration_sum_pos": 0.0,
        "exploration_sum_neg": 0.0,
        "normal_trades": 0,
        "normal_wins": 0,
        "normal_sum_pos": 0.0,
        "normal_sum_neg": 0.0,
    })
    
    for ev in trades:
        if ev.get("logger_version") != "trades_v2":
            continue
        if ev.get("type") != "close":
            continue
        
        symbol = ev.get("symbol")
        if not symbol:
            continue
        
        pct = ev.get("pct")
        try:
            pct = float(pct)
        except (TypeError, ValueError):
            continue
        
        trade_kind = ev.get("trade_kind", "normal")
        bucket = per_symbol[symbol]
        
        if trade_kind == "exploration":
            bucket["exploration_trades"] += 1
            if pct > 0:
                bucket["exploration_wins"] += 1
                bucket["exploration_sum_pos"] += pct
            elif pct < 0:
                bucket["exploration_sum_neg"] += pct  # negative
        else:
            bucket["normal_trades"] += 1
            if pct > 0:
                bucket["normal_wins"] += 1
                bucket["normal_sum_pos"] += pct
            elif pct < 0:
                bucket["normal_sum_neg"] += pct  # negative
    
    # Compute PFs
    for symbol, bucket in per_symbol.items():
        # Exploration PF
        pos = bucket["exploration_sum_pos"]
        neg = bucket["exploration_sum_neg"]
        if neg < 0:
            bucket["exploration_pf"] = pos / abs(neg)
        elif bucket["exploration_trades"] > 0:
            # No losing trades yet
            bucket["exploration_pf"] = float("inf")
        else:
            bucket["exploration_pf"] = None
        
        # Normal PF
        pos = bucket["normal_sum_pos"]
        neg = bucket["normal_sum_neg"]
        if neg < 0:
            bucket["normal_pf"] = pos / abs(neg)
        elif bucket["normal_trades"] > 0:
            bucket["normal_pf"] = float("inf")
        else:
            bucket["normal_pf"] = None
    
    return per_symbol


def summarize_xray(events: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Summarize X-ray per symbol:
    - bars seen
    - bars with exploration_pass
    - bars with can_open
    """
    per_symbol: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "bars": 0,
        "exploration_bars": 0,
        "can_open_bars": 0,
    })
    
    for ev in events:
        if ev.get("logger_version") != "xray_v1":
            continue
        
        symbol = ev.get("symbol")
        if not symbol:
            continue
        
        gates = ev.get("gates") or {}
        per_symbol[symbol]["bars"] += 1
        
        if gates.get("exploration_pass"):
            per_symbol[symbol]["exploration_bars"] += 1
        
        if ev.get("can_open"):
            per_symbol[symbol]["can_open_bars"] += 1
    
    return per_symbol


def fmt_pf(pf: Any) -> str:
    if pf is None:
        return "—"
    if pf == float("inf"):
        return "∞"
    return f"{pf:0.2f}"


def print_summary(
    trade_summary: Dict[str, Dict[str, Any]],
    xray_summary: Dict[str, Dict[str, Any]],
) -> None:
    symbols = sorted(set(trade_summary.keys()) | set(xray_summary.keys()))
    
    print("")
    print("CHLOE EXPLORATION AUDIT")
    print("------------------------")
    print("")
    print(
        f"{'Symbol':8} "
        f"{'Bars':>6} "
        f"{'ExplBars':>9} "
        f"{'CanOpen':>8} "
        f"{'ExpTrades':>9} "
        f"{'ExpPF':>6} "
        f"{'NormTrades':>10} "
        f"{'NormPF':>7}"
    )
    print("-" * 80)
    
    for sym in symbols:
        ts = trade_summary.get(sym, {})
        xs = xray_summary.get(sym, {})
        
        bars = xs.get("bars", 0)
        exp_bars = xs.get("exploration_bars", 0)
        can_open_bars = xs.get("can_open_bars", 0)
        
        exp_trades = ts.get("exploration_trades", 0)
        norm_trades = ts.get("normal_trades", 0)
        
        exp_pf = fmt_pf(ts.get("exploration_pf"))
        norm_pf = fmt_pf(ts.get("normal_pf"))
        
        print(
            f"{sym:8} "
            f"{bars:6d} "
            f"{exp_bars:9d} "
            f"{can_open_bars:8d} "
            f"{exp_trades:9d} "
            f"{exp_pf:>6} "
            f"{norm_trades:10d} "
            f"{norm_pf:>7}"
        )
    
    print("")
    print("Legend:")
    print("  Bars       = total X-ray bars seen for symbol")
    print("  ExplBars   = bars where exploration_pass=True")
    print("  CanOpen    = bars where can_open=True")
    print("  ExpTrades  = closed exploration trades (from trades_v2)")
    print("  ExpPF      = PF for exploration trades (sum_pos / abs(sum_neg))")
    print("  NormTrades = closed non-exploration trades")
    print("  NormPF     = PF for normal trades")
    print("")


def main() -> None:
    trades = load_jsonl(TRADES_PATH)
    xray_events = load_jsonl(XRAY_PATH)
    
    trade_summary = summarize_trades(trades)
    xray_summary = summarize_xray(xray_events)
    
    if not trades and not xray_events:
        print("No trades or X-ray events found yet. Let Chloe run a bit longer.")
        return
    
    print_summary(trade_summary, xray_summary)


if __name__ == "__main__":
    main()

