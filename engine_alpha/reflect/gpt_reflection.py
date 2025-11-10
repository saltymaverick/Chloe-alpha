"""
GPT Reflection - Phase 4
Reflection and confidence calibration.
"""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from engine_alpha.core.paths import REPORTS
from engine_alpha.core.gpt_client import load_prompt, query_gpt


def _read_trades(trades_path: Path, n: int = 20) -> List[Dict[str, Any]]:
    """
    Read last N trades from trades.jsonl.
    
    Args:
        trades_path: Path to trades.jsonl
        n: Number of trades to read (default: 20)
    
    Returns:
        List of trade dictionaries
    """
    trades = []
    if not trades_path.exists():
        return trades
    
    # Read all lines
    with open(trades_path, "r") as f:
        lines = f.readlines()
    
    # Get last N lines
    for line in lines[-n:]:
        line = line.strip()
        if line:
            try:
                trades.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    
    return trades


def _read_last_reflection(reflections_path: Path) -> Optional[Dict[str, Any]]:
    """
    Read last reflection from reflections file.
    
    Args:
        reflections_path: Path to gpt_reflection.jsonl
    
    Returns:
        Last reflection dictionary or None
    """
    if not reflections_path.exists():
        return None
    
    # Read last line
    with open(reflections_path, "r") as f:
        lines = f.readlines()
    
    if not lines:
        return None
    
    # Get last non-empty line
    for line in reversed(lines):
        line = line.strip()
        if line:
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    
    return None


def _calculate_pf_from_trades(trades: List[Dict[str, Any]]) -> float:
    """
    Calculate profit factor from trades.
    
    Args:
        trades: List of trade dictionaries
    
    Returns:
        Profit factor
    """
    if not trades:
        return 1.0
    
    # Filter CLOSE events (these have P&L)
    close_trades = [t for t in trades if t.get("event") == "CLOSE"]
    
    positive_sum = 0.0
    negative_sum = 0.0
    
    for trade in close_trades:
        pnl_pct = trade.get("pnl_pct", 0.0)
        if pnl_pct > 0:
            positive_sum += pnl_pct
        elif pnl_pct < 0:
            negative_sum += abs(pnl_pct)
    
    if negative_sum == 0:
        return 999.0 if positive_sum > 0 else 1.0
    
    return positive_sum / negative_sum


def reflect_on_batch(trades_path: Optional[Path] = None, reflections_path: Optional[Path] = None,
                     n: int = 20) -> Dict[str, Any]:
    """
    Reflect on batch of trades.
    
    Args:
        trades_path: Path to trades.jsonl (default: REPORTS/trades.jsonl)
        reflections_path: Path to gpt_reflection.jsonl (default: REPORTS/gpt_reflection.jsonl)
        n: Number of trades to analyze (default: 20)
    
    Returns:
        Reflection dictionary
    """
    if trades_path is None:
        trades_path = REPORTS / "trades.jsonl"
    if reflections_path is None:
        reflections_path = REPORTS / "gpt_reflection.jsonl"
    
    # Read last N trades
    trades = _read_trades(trades_path, n)
    
    # Calculate current PF
    current_pf = _calculate_pf_from_trades(trades)
    
    # Read previous reflection
    last_reflection = _read_last_reflection(reflections_path)
    previous_pf = last_reflection.get("pf", 1.0) if last_reflection else 1.0
    
    # Calculate PF delta
    pf_delta = current_pf - previous_pf
    
    # Compose reflection (placeholder GPT insight for Phase 4)
    insight = f"PF changed by {pf_delta:.4f}. Trading performance {'improved' if pf_delta > 0 else 'declined'}."
    if not trades:
        insight = "No trades to analyze."
    
    # Confidence adjustment (placeholder)
    confidence_adjust = {
        "mean": 0.0,
        "sd": 0.0
    }
    
    reflection = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "pf": current_pf,
        "pf_delta": pf_delta,
        "n_trades": len(trades),
        "insight": insight,
        "confidence_adjust": confidence_adjust,
    }
    
    # Append to reflections file
    reflections_path.parent.mkdir(parents=True, exist_ok=True)
    with open(reflections_path, "a") as f:
        f.write(json.dumps(reflection) + "\n")
    
    return reflection


def calibrate_confidence(current_conf: float, reason_score: float) -> float:
    """
    Calibrate confidence using weighted adjustment.
    
    Args:
        current_conf: Current confidence value
        reason_score: Reason score for adjustment
    
    Returns:
        Adjusted confidence
    """
    # Simple weighted adjustment: new = current_conf + 0.2*(reason_score - current_conf)
    new_conf = current_conf + 0.2 * (reason_score - current_conf)
    
    # Clamp to [0, 1]
    return max(0.0, min(1.0, new_conf))


def _summarize_trades(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    closes = [t for t in trades if t.get("event") == "CLOSE"]
    wins = [t for t in closes if t.get("pnl_pct", 0.0) > 0]
    losses = [t for t in closes if t.get("pnl_pct", 0.0) < 0]
    total_close = len(closes)
    win_rate = len(wins) / total_close if total_close else 0.0
    avg_win = sum(t.get("pnl_pct", 0.0) for t in wins) / len(wins) if wins else 0.0
    avg_loss = sum(t.get("pnl_pct", 0.0) for t in losses) / len(losses) if losses else 0.0
    recent = closes[-5:]
    return {
        "total_trades": len(trades),
        "closed_trades": total_close,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "recent_closes": recent,
    }


def _mean(values: List[float]) -> Optional[float]:
    filtered = [float(v) for v in values if isinstance(v, (int, float))]
    if not filtered:
        return None
    return sum(filtered) / len(filtered)


def _parse_ts(ts: Any) -> Optional[datetime]:
    if not isinstance(ts, str) or not ts:
        return None
    candidate = ts.strip()
    try:
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        return datetime.fromisoformat(candidate)
    except Exception:
        return None


def _summarize_open_positions(trades_path: Path, lookback: int = 100) -> Dict[str, Any]:
    events = _read_trades(trades_path, lookback)
    if not events:
        return {"open_count": 0}
    # Process in chronological order
    try:
        events = sorted(events, key=lambda t: t.get("ts", ""))
    except Exception:
        pass
    active: List[Dict[str, Any]] = []
    for event in events:
        event_type = str(event.get("type") or event.get("event") or "").lower()
        if event_type == "open":
            active.append(event)
        elif event_type == "close":
            if active:
                active.pop()
    now = datetime.now(timezone.utc)
    long_count = 0
    short_count = 0
    conf_values: List[float] = []
    risk_mult_values: List[float] = []
    bar_estimates: List[float] = []
    last_open_ts: Optional[str] = None
    for position in active:
        direction = position.get("dir")
        if isinstance(direction, (int, float)):
            if float(direction) > 0:
                long_count += 1
            elif float(direction) < 0:
                short_count += 1
        conf = position.get("conf") or position.get("confidence")
        if isinstance(conf, (int, float)):
            conf_values.append(float(conf))
        risk_mult = position.get("risk_mult")
        if isinstance(risk_mult, (int, float)):
            risk_mult_values.append(float(risk_mult))
        ts = position.get("ts")
        if isinstance(ts, str):
            last_open_ts = ts if (last_open_ts is None or ts > last_open_ts) else last_open_ts
            dt = _parse_ts(ts)
            if dt:
                hours_open = (now - dt).total_seconds() / 3600.0
                if hours_open >= 0:
                    bar_estimates.append(hours_open)
    summary: Dict[str, Any] = {
        "open_count": len(active),
        "by_dir": {"long": long_count, "short": short_count},
    }
    avg_conf = _mean(conf_values)
    if avg_conf is not None:
        summary["avg_conf"] = avg_conf
    avg_risk_mult = _mean(risk_mult_values)
    if avg_risk_mult is not None:
        summary["avg_risk_mult"] = avg_risk_mult
    avg_bars_open = _mean(bar_estimates)
    if avg_bars_open is not None:
        summary["avg_bars_open"] = avg_bars_open
    if last_open_ts:
        summary["last_open_ts"] = last_open_ts
    return summary


def _load_policy_context() -> Dict[str, Any]:
    snapshot_path = REPORTS / "orchestrator_snapshot.json"
    risk_path = REPORTS / "risk_adapter.json"
    context: Dict[str, Any] = {}
    try:
        snapshot = json.loads(snapshot_path.read_text()) if snapshot_path.exists() else {}
    except Exception:
        snapshot = {}
    try:
        risk = json.loads(risk_path.read_text()) if risk_path.exists() else {}
    except Exception:
        risk = {}

    if snapshot:
        inputs = snapshot.get("inputs", {}) if isinstance(snapshot, dict) else {}
        policy = snapshot.get("policy", {}) if isinstance(snapshot, dict) else {}
        context.update(
            {
                "rec": inputs.get("rec"),
                "allow_opens": policy.get("allow_opens"),
                "allow_pa": policy.get("allow_pa"),
            }
        )
    if risk:
        context.update(
            {
                "band": risk.get("band"),
                "mult": risk.get("mult"),
            }
        )
    return context


def run_gpt_reflection(n: int = 20) -> Dict[str, Any]:
    """
    Generate GPT-based reflection summary for recent trades.
    """
    trades_path = REPORTS / "trades.jsonl"
    trades = _read_trades(trades_path, n=n)
    summary = _summarize_trades(trades)
    prompt_template = load_prompt("reflection")
    if not prompt_template:
        prompt_template = "Provide a concise reflection on the provided trades."

    context = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "trade_summary": summary,
    }
    open_summary: Optional[Dict[str, Any]] = None
    policy_context: Optional[Dict[str, Any]] = None
    if summary.get("closed_trades", 0) == 0:
        open_summary = _summarize_open_positions(trades_path)
        policy_context = _load_policy_context()
        if open_summary:
            context["open_positions"] = open_summary
        if policy_context:
            context["policy"] = policy_context
        prompt = (
            f"{prompt_template}\n\nNO CLOSED TRADES — SUMMARIZE OPEN POSITIONS\n"
            f"{json.dumps(open_summary or {}, indent=2)}\nPolicy:\n{json.dumps(policy_context or {}, indent=2)}"
        )
    else:
        prompt = f"{prompt_template}\n\nContext:\n{json.dumps(context, indent=2)}"
    result = query_gpt(prompt, "reflection")
    ts = datetime.now(timezone.utc).isoformat()

    record = {
        "ts": ts,
        "context": context,
        "summary": result.get("text") if result else None,
        "cost_usd": result.get("cost_usd") if result else 0.0,
        "tokens": result.get("tokens") if result else 0,
    }

    out_path = REPORTS / "gpt_reflection.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a") as f:
        f.write(json.dumps(record) + "\n")

    summary_path = REPORTS / "gpt_summary.json"
    summary_path.write_text(json.dumps(record, indent=2))

    # Queue actionable adjustments, if present
    queue_items: List[Dict[str, Any]] = []
    summary_data = record.get("context", {})
    reflection_text = record.get("summary") or ""
    if isinstance(summary_data, dict):
        adjustments = summary_data.get("adjustments")
        if isinstance(adjustments, dict) and adjustments:
            queue_items.append(
                {
                    "ts": ts,
                    "kind": "gates",
                    "payload": adjustments,
                    "source": "reflection",
                }
            )
        council_hints = summary_data.get("council_hints")
        if isinstance(council_hints, dict) and council_hints:
            queue_items.append(
                {
                    "ts": ts,
                    "kind": "weights",
                    "payload": council_hints,
                    "source": "reflection",
                }
            )
    if queue_items:
        queue_path = REPORTS / "reflection_queue.jsonl"
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        with queue_path.open("a") as handle:
            for item in queue_items:
                handle.write(json.dumps(item) + "\n")
    return record
