"""
Chloe Tuning Dashboard - GPT-Aware Dashboard

Shows per-symbol tier, PF, tuning recommendations, and Dream reviews.
Read-only tool that displays current status based on roadmap and live data.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
GPT_REPORT_DIR = ROOT / "reports" / "gpt"
TRADES_PATH = ROOT / "reports" / "trades.jsonl"

REFL_IN = GPT_REPORT_DIR / "reflection_input.json"
REFL_OUT = GPT_REPORT_DIR / "reflection_output.json"
TUNE_OUT = GPT_REPORT_DIR / "tuning_preview.json"
DREAM_OUT = GPT_REPORT_DIR / "dream_output.json"


def load_json(path: Path) -> Dict[str, Any]:
    """Load JSON file, return empty dict if missing."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def safe_load(path: Path) -> Dict[str, Any]:
    """Safely load JSON file."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Load JSONL file, return empty list if missing."""
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


def compute_trade_stats() -> Dict[str, Dict[str, Any]]:
    """Compute per-symbol trade statistics from trades.jsonl."""
    trades = load_jsonl(TRADES_PATH)
    
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
                bucket["exploration_sum_neg"] += pct
        else:
            bucket["normal_trades"] += 1
            if pct > 0:
                bucket["normal_wins"] += 1
                bucket["normal_sum_pos"] += pct
            elif pct < 0:
                bucket["normal_sum_neg"] += pct
    
    # Compute PFs
    for symbol, bucket in per_symbol.items():
        # Exploration PF
        pos = bucket["exploration_sum_pos"]
        neg = bucket["exploration_sum_neg"]
        if neg < 0:
            bucket["exploration_pf"] = pos / abs(neg)
        elif bucket["exploration_trades"] > 0:
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
    
    return dict(per_symbol)


def format_pf(pf: Optional[float]) -> str:
    """Format PF value for display."""
    if pf is None:
        return "—"
    if pf == float("inf"):
        return "∞"
    return f"{pf:.2f}"


def get_status_summary(
    symbol: str,
    tier: str,
    exp_trades: int,
    exp_pf: Optional[float],
    norm_trades: int,
    norm_pf: Optional[float],
    conf_delta: float,
    cap_delta: int,
) -> str:
    """Generate status summary line based on tier and stats."""
    if tier == "tier1":
        if exp_trades >= 6 and norm_trades >= 2:
            return "STRONG. Ready for positive tuning when sample ≥ thresholds."
        else:
            return "Strong performer; await more sample before positive tuning."
    elif tier == "tier2":
        if exp_trades < 4:
            return "Under-sampled; gathering evidence."
        elif exp_pf is not None and 0.5 <= exp_pf < 1.5:
            return "Promising; more data needed before tuning."
        else:
            return "Neutral; continue observation."
    elif tier == "tier3":
        if exp_trades >= 7:
            return "Consistently weak; negative tuning recommended."
        else:
            return "Weak performer; gather more sample before negative tuning."
    else:
        return "Status unknown."


def main() -> None:
    """Display GPT-aware tuning dashboard."""
    print("\nCHLOE TUNING DASHBOARD (GPT-AWARE)")
    print("-" * 70)
    print()
    
    # Load data
    refl_in = safe_load(REFL_IN)
    refl_out = safe_load(REFL_OUT)
    tune_out = safe_load(TUNE_OUT)
    dream_out = safe_load(DREAM_OUT)
    
    # Get tiers and insights
    tiers = refl_out.get("tiers", {})
    insights = refl_out.get("symbol_insights", {})
    
    # Build Dream-label stats per symbol
    dream_stats: Dict[str, Dict[str, int]] = {}
    scenarios = dream_out.get("scenario_reviews", [])
    
    for sc in scenarios:
        sym = sc.get("symbol")
        if not sym:
            continue
        dream_stats.setdefault(sym, {"good": 0, "bad": 0, "improve": 0, "flat": 0})
        label = sc.get("label", "").lower()
        if label in ("good", "bad", "improve", "flat"):
            dream_stats[sym][label] += 1
    
    # Performance metrics from reflection_input
    perf: Dict[str, Dict[str, Any]] = {}
    symbols_data = refl_in.get("symbols", {})
    for sym, data in symbols_data.items():
        # Handle both nested structure and flat structure
        if isinstance(data, dict):
            perf[sym] = {
                "exp_pf": data.get("exploration_pf") or data.get("stats", {}).get("exploration_pf"),
                "exp_trades": data.get("exploration_trades", 0) or data.get("stats", {}).get("exploration_trades", 0),
                "norm_pf": data.get("normal_pf") or data.get("stats", {}).get("normal_pf"),
                "norm_trades": data.get("normal_trades", 0) or data.get("stats", {}).get("normal_trades", 0),
            }
        else:
            perf[sym] = {
                "exp_pf": None,
                "exp_trades": 0,
                "norm_pf": None,
                "norm_trades": 0,
            }
    
    # Fallback: compute from trades.jsonl if reflection_input doesn't have stats
    if not any(p.get("exp_trades", 0) > 0 for p in perf.values()):
        trade_stats = compute_trade_stats()
        for sym, stats in trade_stats.items():
            if sym not in perf:
                perf[sym] = {}
            perf[sym].update({
                "exp_pf": stats.get("exploration_pf"),
                "exp_trades": stats.get("exploration_trades", 0),
                "norm_pf": stats.get("normal_pf"),
                "norm_trades": stats.get("normal_trades", 0),
            })
    
    # Print grouped by tier
    for tier_name in ("tier1", "tier2", "tier3"):
        syms = tiers.get(tier_name, [])
        if not syms:
            continue
        
        print(f"\n{tier_name.upper()}:")
        print("-" * 70)
        
        for sym in syms:
            p = perf.get(sym, {})
            t = tune_out.get(sym, {})
            ds = dream_stats.get(sym, {})
            ins = insights.get(sym, {})
            
            print(f"\n{sym}:")
            print(f"  ExpTrades={p.get('exp_trades', 0):2d}  ExpPF={format_pf(p.get('exp_pf'))}")
            print(f"  NormTrades={p.get('norm_trades', 0):2d} NormPF={format_pf(p.get('norm_pf'))}")
            
            # Tuner proposals
            if t:
                conf_delta = t.get("conf_min_delta", 0.0)
                cap_delta = t.get("exploration_cap_delta", 0)
                if conf_delta != 0.0 or cap_delta != 0:
                    print(f"  Tuner proposal: conf_min_delta={conf_delta:+0.4f}, "
                          f"exploration_cap_delta={cap_delta:+d}")
                else:
                    print("  Tuner proposal: none")
            else:
                print("  Tuner proposal: none")
            
            # Dream stats
            if ds:
                print(f"  Dream: good={ds.get('good', 0)}, bad={ds.get('bad', 0)}, "
                      f"improve={ds.get('improve', 0)}, flat={ds.get('flat', 0)}")
            else:
                print("  Dream: no reviews yet")
            
            # Symbol insights (Reflection)
            if isinstance(ins, dict):
                comment = ins.get("comment", "")
                actions = ins.get("actions", [])
                if comment:
                    print(f"  Insights: {comment}")
                if actions:
                    print(f"  Actions: {', '.join(actions)}")
            elif isinstance(ins, list):
                if ins:
                    print("  Insights:")
                    for line in ins:
                        print(f"    - {line}")
    
    # Summary
    print("\n" + "-" * 70)
    print("SUMMARY:")
    total_syms = sum(len(tiers.get(t, [])) for t in ["tier1", "tier2", "tier3"])
    print(f"  Total symbols: {total_syms}")
    for tier in ["tier1", "tier2", "tier3"]:
        count = len(tiers.get(tier, []))
        if count > 0:
            print(f"  {tier.upper()}: {count}")
    
    # Check if GPT was used
    gpt_used = False
    if refl_out.get("notes"):
        notes = refl_out.get("notes", [])
        if any("stub" not in str(n).lower() for n in notes):
            gpt_used = True
    
    print()
    if gpt_used:
        print("🧠 GPT Reflection/Tuner/Dream: Active")
    else:
        print("ℹ️  Using stub reflection/tuner/dream (set USE_GPT_*=true to enable GPT)")
    print()
    print("💡 This dashboard is read-only and advisory.")
    print("   All tuning remains dry-run until explicitly enabled.")


if __name__ == "__main__":
    main()

