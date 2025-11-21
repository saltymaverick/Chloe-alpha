"""
GPT Council Analyzer - Phase 44.3
Analyzes council performance logs and generates tuning suggestions via GPT (stub).
This is a utility module, NOT called from the trading loop.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any

from engine_alpha.core.paths import REPORTS

COUNCIL_LOG_PATH = REPORTS / "council_perf.jsonl"
TRADES_LOG_PATH = REPORTS / "trades.jsonl"
SUGGESTIONS_PATH = REPORTS / "gpt_suggestions.jsonl"


def load_recent_council_events(max_events: int = 200) -> List[Dict[str, Any]]:
    """
    Read the last max_events council_perf.jsonl events (if file exists).
    Returns a list of dicts (JSONL entries).
    """
    if not COUNCIL_LOG_PATH.exists():
        return []
    
    events = []
    try:
        with COUNCIL_LOG_PATH.open("r") as f:
            lines = f.readlines()
        # Read from the end (tail semantics) for efficiency
        for line in reversed(lines[-max_events:]):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                events.append(event)
            except json.JSONDecodeError:
                continue
        # Reverse to get chronological order
        events.reverse()
    except Exception:
        return []
    
    return events


def summarize_council_perf(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Given a list of council events (open/close), compute:
    - per-bucket stats: wins, losses, pf, avg_pct, trade_count
    - per-regime stats (e.g., chop, trend, high_vol)
    Return a nested dict summary safe for JSON dumping.
    """
    # Match opens and closes by sequence (assume opens come before closes)
    open_events = []
    close_events = []
    
    for event in events:
        event_type = event.get("event")
        if event_type == "open":
            open_events.append(event)
        elif event_type == "close":
            close_events.append(event)
    
    # Simple matching: pair closes with most recent open (by sequence)
    # In practice, you might want to match by timestamp or trade ID
    bucket_stats = defaultdict(lambda: {
        "wins": 0,
        "losses": 0,
        "win_pcts": [],
        "loss_pcts": [],
        "trade_count": 0,
        "total_pct": 0.0,
    })
    
    regime_stats = defaultdict(lambda: {
        "wins": 0,
        "losses": 0,
        "win_pcts": [],
        "loss_pcts": [],
        "trade_count": 0,
        "total_pct": 0.0,
    })
    
    # Match closes with opens (simple sequential matching)
    open_idx = 0
    for close_event in close_events:
        # Find the most recent open before this close
        matching_open = None
        for i in range(open_idx, len(open_events)):
            open_ts = open_events[i].get("ts", "")
            close_ts = close_event.get("ts", "")
            if open_ts <= close_ts:
                matching_open = open_events[i]
                open_idx = i + 1
            else:
                break
        
        if matching_open is None:
            continue
        
        pct = float(close_event.get("pct", 0.0))
        regime = matching_open.get("regime", "unknown")
        buckets = matching_open.get("buckets", [])
        
        # Aggregate by regime
        regime_stats[regime]["trade_count"] += 1
        regime_stats[regime]["total_pct"] += pct
        if pct > 0:
            regime_stats[regime]["wins"] += 1
            regime_stats[regime]["win_pcts"].append(pct)
        elif pct < 0:
            regime_stats[regime]["losses"] += 1
            regime_stats[regime]["loss_pcts"].append(abs(pct))
        
        # Aggregate by bucket
        for bucket in buckets:
            bucket_name = bucket.get("name", "unknown")
            bucket_stats[bucket_name]["trade_count"] += 1
            bucket_stats[bucket_name]["total_pct"] += pct
            if pct > 0:
                bucket_stats[bucket_name]["wins"] += 1
                bucket_stats[bucket_name]["win_pcts"].append(pct)
            elif pct < 0:
                bucket_stats[bucket_name]["losses"] += 1
                bucket_stats[bucket_name]["loss_pcts"].append(abs(pct))
    
    # Compute PF and averages
    def compute_pf(win_pcts: List[float], loss_pcts: List[float]) -> float:
        if not loss_pcts:
            return float("inf") if win_pcts else 0.0
        total_wins = sum(win_pcts)
        total_losses = sum(loss_pcts)
        if total_losses == 0:
            return float("inf") if total_wins > 0 else 0.0
        return total_wins / total_losses
    
    # Build summary
    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_events": len(events),
        "total_opens": len(open_events),
        "total_closes": len(close_events),
        "bucket_stats": {},
        "regime_stats": {},
    }
    
    for bucket_name, stats in bucket_stats.items():
        win_pcts = stats["win_pcts"]
        loss_pcts = stats["loss_pcts"]
        pf = compute_pf(win_pcts, loss_pcts)
        avg_pct = stats["total_pct"] / stats["trade_count"] if stats["trade_count"] > 0 else 0.0
        
        summary["bucket_stats"][bucket_name] = {
            "wins": stats["wins"],
            "losses": stats["losses"],
            "trade_count": stats["trade_count"],
            "pf": pf if pf != float("inf") else "inf",
            "avg_pct": avg_pct,
            "total_pct": stats["total_pct"],
        }
    
    for regime, stats in regime_stats.items():
        win_pcts = stats["win_pcts"]
        loss_pcts = stats["loss_pcts"]
        pf = compute_pf(win_pcts, loss_pcts)
        avg_pct = stats["total_pct"] / stats["trade_count"] if stats["trade_count"] > 0 else 0.0
        
        summary["regime_stats"][regime] = {
            "wins": stats["wins"],
            "losses": stats["losses"],
            "trade_count": stats["trade_count"],
            "pf": pf if pf != float("inf") else "inf",
            "avg_pct": avg_pct,
            "total_pct": stats["total_pct"],
        }
    
    return summary


def gpt_analyze_council(summary: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stub: would normally send 'summary' to GPT and get back suggestions.
    For now, returns a dummy suggestions dict that captures the summary and
    leaves a placeholder for GPT output.
    """
    return {
        "summary": summary,
        "suggestions": {
            "notes": "GPT analysis stub – no live changes applied.",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "potential_changes": {
                "council_weights": "Placeholder for suggested weight adjustments",
                "entry_thresholds": "Placeholder for suggested entry threshold changes",
                "exit_thresholds": "Placeholder for suggested exit threshold changes",
            },
        },
    }


def write_suggestions(suggestions: Dict[str, Any]) -> None:
    """
    Append a suggestions record to gpt_suggestions.jsonl.
    """
    try:
        SUGGESTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with SUGGESTIONS_PATH.open("a") as f:
            f.write(json.dumps(suggestions) + "\n")
    except Exception:
        # Logging must never break analysis
        pass


def run_gpt_council_analysis(max_events: int = 200) -> None:
    """
    Entrypoint: load recent council events, summarize them, pass through GPT stub,
    and write the suggestions to SUGGESTIONS_PATH.
    """
    events = load_recent_council_events(max_events=max_events)
    if not events:
        print("No council events found in council_perf.jsonl")
        return
    
    summary = summarize_council_perf(events)
    suggestions = gpt_analyze_council(summary)
    write_suggestions(suggestions)
    
    print(f"GPT council analysis complete:")
    print(f"  - Processed {len(events)} events")
    print(f"  - Summary written to suggestions")
    print(f"  - Suggestions saved to {SUGGESTIONS_PATH}")


if __name__ == "__main__":
    run_gpt_council_analysis()


















