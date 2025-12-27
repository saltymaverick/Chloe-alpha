"""
Build a structured reflection snapshot for GPT consumption.

This script aggregates trades, X-ray events, and positions into a single
clean JSON file that GPT Reflection/Tuner/Dream modes can read.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List

# We reuse the functions from exploration_audit to avoid duplication
from tools import exploration_audit as audit

# Paths
ROOT = Path(__file__).resolve().parents[1]
TRADES_PATH = ROOT / "reports" / "trades.jsonl"
XRAY_PATH = ROOT / "reports" / "xray" / "latest.jsonl"
POS_STATE_PATH = ROOT / "reports" / "position_state.json"
GPT_REPORT_DIR = ROOT / "reports" / "gpt"
GPT_REPORT_FILE = GPT_REPORT_DIR / "reflection_input.json"
RESEARCH_DIR = ROOT / "reports" / "research"
DRIFT_REPORT_PATH = RESEARCH_DIR / "drift_report.json"
CORRELATION_MATRIX_PATH = RESEARCH_DIR / "correlation_matrix.json"
ALPHA_BETA_PATH = RESEARCH_DIR / "alpha_beta.json"


def normalize_number(val: Any) -> Any:
    """
    Normalize numbers for JSON:
      - Decimals -> float
      - infinities -> "inf"
      - None stays None
    """
    if val is None:
        return None
    if isinstance(val, Decimal):
        val = float(val)
    try:
        # Handle python float inf
        if val == float("inf"):
            return "inf"
        if val == float("-inf"):
            return "-inf"
    except Exception:
        pass
    if isinstance(val, (int, float)):
        return float(val)
    return val


def build_symbol_stats(trades: List[Dict[str, Any]], xray_events: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Combine exploration_audit's per-symbol trade stats with xray-derived stats.
    """
    trade_summary = audit.summarize_trades(trades)
    xray_summary = audit.summarize_xray(xray_events)

    symbols: Dict[str, Dict[str, Any]] = {}

    all_symbols = set(trade_summary.keys()) | set(xray_summary.keys())
    for sym in sorted(all_symbols):
        ts = trade_summary.get(sym, {})
        xs = xray_summary.get(sym, {})

        sym_entry: Dict[str, Any] = {
            "exp_trades": ts.get("exploration_trades", 0),
            "exp_pf": normalize_number(ts.get("exploration_pf")),
            "exp_wins": ts.get("exploration_wins", 0),
            "exp_sum_pos": normalize_number(ts.get("exploration_sum_pos", 0.0)),
            "exp_sum_neg": normalize_number(ts.get("exploration_sum_neg", 0.0)),

            "norm_trades": ts.get("normal_trades", 0),
            "norm_pf": normalize_number(ts.get("normal_pf")),
            "norm_wins": ts.get("normal_wins", 0),
            "norm_sum_pos": normalize_number(ts.get("normal_sum_pos", 0.0)),
            "norm_sum_neg": normalize_number(ts.get("normal_sum_neg", 0.0)),

            "bars": xs.get("bars", 0),
            "exploration_bars": xs.get("exploration_bars", 0),
            "can_open_bars": xs.get("can_open_bars", 0),
        }

        symbols[sym] = sym_entry

    return symbols


def build_recent_trades(trades: List[Dict[str, Any]], max_trades: int = 50) -> List[Dict[str, Any]]:
    """
    Build a compact list of recent closed trades (normal + exploration).
    """
    recent: List[Dict[str, Any]] = []
    # Walk backwards and take only closes
    for ev in reversed(trades):
        if ev.get("type") != "close":
            continue
        symbol = ev.get("symbol")
        if not symbol:
            continue

        entry = {
            "symbol": symbol,
            "time": ev.get("ts"),
            "trade_kind": ev.get("trade_kind", "normal"),
            "dir": ev.get("dir"),
            "pct": normalize_number(ev.get("pct")),
            "entry_px": normalize_number(ev.get("entry_px")),
            "exit_px": normalize_number(ev.get("exit_px")),
            "exit_reason": ev.get("exit_reason"),
            "exit_label": ev.get("exit_label"),
            "regime": ev.get("regime"),
            "risk_band": ev.get("risk_band"),
            "logger_version": ev.get("logger_version"),
        }
        recent.append(entry)
        if len(recent) >= max_trades:
            break

    # reverse so newest at bottom if desired (optional)
    recent.reverse()
    return recent


def build_gate_stats(xray_events: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    """
    Derive simple gate behavior stats per symbol from X-ray events.
    We count how often gates blocked by regime/confidence/edge vs allowed exploration.
    """
    stats: Dict[str, Dict[str, int]] = {}

    for ev in xray_events:
        sym = ev.get("symbol")
        if not sym:
            continue
        
        gates = ev.get("gates") or {}
        
        regime_pass = bool(gates.get("regime_pass", True))
        confidence_pass = bool(gates.get("confidence_pass", True))
        edge_pass = bool(gates.get("edge_pass", True))
        exploration_pass = bool(gates.get("exploration_pass", False))

        sym_stats = stats.setdefault(sym, {
            "blocked_regime": 0,
            "blocked_confidence": 0,
            "blocked_edge": 0,
            "allowed_exploration": 0,
        })

        if not regime_pass:
            sym_stats["blocked_regime"] += 1
        if not confidence_pass:
            sym_stats["blocked_confidence"] += 1
        if not edge_pass:
            sym_stats["blocked_edge"] += 1
        if exploration_pass:
            sym_stats["allowed_exploration"] += 1

    return stats


def load_open_positions() -> List[Dict[str, Any]]:
    """
    Load open positions from position_state.json.
    Only include positions where dir != 0.
    """
    if not POS_STATE_PATH.exists():
        return []

    try:
        data = json.loads(POS_STATE_PATH.read_text())
    except Exception:
        return []

    positions_dict = data.get("positions", {})
    if not isinstance(positions_dict, dict):
        return []

    open_positions: List[Dict[str, Any]] = []
    for key_str, pos in positions_dict.items():
        if not isinstance(pos, dict):
            continue
        if pos.get("dir", 0) == 0:
            continue

        entry = {
            "symbol": pos.get("symbol"),
            "timeframe": pos.get("timeframe", "15m"),
            "trade_kind": pos.get("trade_kind", "normal"),
            "dir": pos.get("dir"),
            "entry_px": normalize_number(pos.get("entry_px")),
            "regime_at_entry": pos.get("regime"),
            "risk_band": pos.get("risk_band"),
        }
        open_positions.append(entry)

    return open_positions


def load_phase5_data() -> Dict[str, Any]:
    """
    Load Phase 5 research data (drift, correlation, alpha/beta) if available.
    
    Returns:
        Dict with drift, correlation, alpha_beta keys (empty dicts if files missing)
    """
    phase5_data: Dict[str, Any] = {}
    
    # Load drift report
    if DRIFT_REPORT_PATH.exists():
        try:
            drift_data = json.loads(DRIFT_REPORT_PATH.read_text())
            phase5_data["drift"] = drift_data.get("symbols", {})
        except Exception:
            phase5_data["drift"] = {}
    else:
        phase5_data["drift"] = {}
    
    # Load correlation matrix
    if CORRELATION_MATRIX_PATH.exists():
        try:
            corr_data = json.loads(CORRELATION_MATRIX_PATH.read_text())
            phase5_data["correlation"] = {
                "matrix": corr_data.get("matrix", {}),
                "symbols": corr_data.get("symbols", []),
            }
        except Exception:
            phase5_data["correlation"] = {}
    else:
        phase5_data["correlation"] = {}
    
    # Load alpha/beta decomposition
    if ALPHA_BETA_PATH.exists():
        try:
            ab_data = json.loads(ALPHA_BETA_PATH.read_text())
            phase5_data["alpha_beta"] = ab_data.get("symbols", {})
        except Exception:
            phase5_data["alpha_beta"] = {}
    else:
        phase5_data["alpha_beta"] = {}
    
    return phase5_data


def main() -> None:
    GPT_REPORT_DIR.mkdir(parents=True, exist_ok=True)

    # Load trades and X-ray events using the same loader as exploration_audit
    trades = audit.load_jsonl(TRADES_PATH)
    xray_events = audit.load_jsonl(XRAY_PATH)

    # Build all components
    symbols = build_symbol_stats(trades, xray_events)
    recent_trades = build_recent_trades(trades, max_trades=50)
    gate_stats = build_gate_stats(xray_events)
    open_positions = load_open_positions()
    
    # Load Phase 5 research data (drift, correlation, alpha/beta) if available
    phase5_data = load_phase5_data()
    
    # Load microstructure snapshot if available
    microstructure_path = RESEARCH_DIR / "microstructure_snapshot_15m.json"
    microstructure_data = {}
    if microstructure_path.exists():
        try:
            micro_snapshot = json.loads(microstructure_path.read_text())
            microstructure_data = micro_snapshot.get("symbols", {})
        except Exception:
            pass

    # Meta
    engine_mode = os.environ.get("ENGINE_MODE", "PAPER")
    now = datetime.now(timezone.utc).isoformat()

    snapshot: Dict[str, Any] = {
        "generated_at": now,
        "engine_mode": engine_mode,
        "summary": {
            "total_symbols": len(symbols),
            "total_trades": len([t for t in trades if t.get("type") == "close"]),
            "total_open_positions": len(open_positions),
        },
        "symbols": symbols,
        "gates": gate_stats,
        "recent_trades": recent_trades,
        "open_positions": open_positions,
    }
    
    # Add Phase 5 data if available
    if phase5_data.get("drift"):
        snapshot["drift"] = phase5_data["drift"]
    if phase5_data.get("correlation"):
        snapshot["correlation"] = phase5_data["correlation"]
    if phase5_data.get("alpha_beta"):
        snapshot["alpha_beta"] = phase5_data["alpha_beta"]
    
    # Add microstructure data if available
    if microstructure_data:
        snapshot["microstructure"] = microstructure_data

    GPT_REPORT_FILE.write_text(json.dumps(snapshot, indent=2, sort_keys=True))
    print(f"✅ Reflection snapshot written to: {GPT_REPORT_FILE}")


if __name__ == "__main__":
    main()

