"""
Risk adapter - Phase 20 (paper only)
Computes a drawdown-based risk multiplier from the equity curve.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from engine_alpha.core.paths import REPORTS

EQUITY_PATH = REPORTS / "equity_curve.jsonl"
TRADES_PATH = REPORTS / "trades.jsonl"
JSON_PATH = REPORTS / "risk_adapter.json"
LOG_PATH = REPORTS / "risk_adapter.jsonl"

# Mode detection for PAPER-only promotion rules
IS_PAPER_MODE = os.getenv("MODE", "PAPER").upper() == "PAPER"

# Risk band selection logic:
# - Inputs: drawdown (DD) computed from equity curve (peak equity vs current equity)
# - DD formula: max(0.0, 1.0 - (current_equity / peak_equity))
# - Demotion logic: band is determined by first threshold that drawdown exceeds
#   - Band A: DD < 5%, risk_mult = 1.00 (full size)
#   - Band B: DD 5-10%, risk_mult = 0.70 (reduced size)
#   - Band C: DD > 10%, risk_mult = 0.50 (defensive size)
# - Promotion logic (PAPER-only):
#   - Normal promotion: band improves naturally when DD falls below thresholds (C→B at 10%, B→A at 5%)
#   - PAPER-only PF-aware C→B: if band=C, DD < 8%, PF >= 1.05 over last 30 trades (with at least 20 trades)
#   - PAPER-only PF-aware B→A: if band=B, DD < 5%, PF >= 1.15 over last 50 trades (with at least 40 trades) AND
#                               PF >= 1.10 over last 20 trades (with at least 15 trades)
#   - Falls back to DD-only promotion if PF conditions not met but DD threshold satisfied
# - risk_mult is set from BANDS tuple and clamped to [MULT_MIN, MULT_MAX] = [0.5, 1.25]
BANDS = (
    ("A", 0.05, 1.00),  # drawdown < 5%
    ("B", 0.10, 0.70),  # drawdown 5-10%
    ("C", float("inf"), 0.50),  # drawdown > 10%
)
MULT_MIN = 0.5
MULT_MAX = 1.25


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_equity() -> List[Dict[str, float]]:
    if not EQUITY_PATH.exists():
        return []
    rows: List[Dict[str, float]] = []
    for line in EQUITY_PATH.read_text().splitlines():
        try:
            obj = json.loads(line)
            rows.append({
                "ts": obj.get("ts"),
                "equity": float(obj.get("equity", float("nan"))),
            })
        except Exception:
            continue
    return rows


def _bounded(mult: float) -> float:
    return max(MULT_MIN, min(MULT_MAX, mult))


def _compute_pf_over_last_closes(max_trades: int = 50) -> tuple[float | None, int]:
    """
    Compute PF over last close trades in reports/trades.jsonl.
    Returns (pf, count).
    If no data, returns (None, 0).
    """
    if not TRADES_PATH.exists():
        return (None, 0)
    
    try:
        lines = TRADES_PATH.read_text().splitlines()
    except Exception:
        return (None, 0)
    
    closes = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("type") != "close":
            continue
        closes.append(rec)
        if len(closes) >= max_trades:
            break
    
    if not closes:
        return (None, 0)
    
    win_sum = 0.0
    loss_sum = 0.0
    for c in closes:
        pct = c.get("pct")
        if pct is None:
            continue
        try:
            pct = float(pct)
        except Exception:
            continue
        if pct > 0:
            win_sum += pct
        elif pct < 0:
            loss_sum += abs(pct)
    
    if loss_sum > 0:
        pf = win_sum / loss_sum
    elif win_sum > 0:
        pf = float("inf")
    else:
        pf = None
    
    return (pf, len(closes))


def evaluate() -> Dict[str, object]:
    """
    Risk band evaluation function.
    
    Computes risk band (A/B/C) and risk_mult based on current drawdown from equity curve.
    
    Inputs:
    - Equity curve data (from equity_curve.jsonl)
    - Peak equity (highest equity seen in history)
    - Current equity (last equity value)
    
    Outputs:
    - band: "A", "B", or "C" (based on drawdown thresholds)
    - mult: risk multiplier (1.00 for A, 0.70 for B, 0.50 for C, clamped to [0.5, 1.25])
    - drawdown: computed as max(0.0, 1.0 - (current_equity / peak_equity))
    
    Logic:
    - Demotion-only: band determined by current drawdown level
    - No explicit promotion: band improves only when drawdown naturally recovers below thresholds
    - risk_mult is set from BANDS tuple and bounded by MULT_MIN/MULT_MAX
    """
    data = _read_equity()
    if len(data) < 1:
        result = {
            "ts": _now(),
            "equity": None,
            "peak": None,
            "drawdown": None,
            "band": None,
            "mult": 1.0,
            "reason": "no_equity_curve",
        }
        JSON_PATH.write_text(json.dumps(result, indent=2))
        return result

    peak = float("-inf")
    last_equity = data[-1]["equity"]
    for entry in data:
        eq = entry.get("equity")
        if eq is None:
            continue
        if eq > peak:
            peak = eq
    if peak <= 0 or last_equity is None:
        drawdown = 0.0
    else:
        drawdown = max(0.0, 1.0 - (last_equity / peak))

    # Band selection: find first band where drawdown < threshold
    # This implements demotion logic (band improves naturally when DD falls below thresholds)
    band = "A"
    mult = 1.0
    for name, threshold, value in BANDS:
        if drawdown < threshold:
            band = name
            mult = value
            break
    
    # PAPER-only PF-aware promotion logic
    # This adds promotion gates on top of DD-based bands for PAPER mode only
    if IS_PAPER_MODE:
        pf_last_50, count_50 = _compute_pf_over_last_closes(50)
        pf_last_30, count_30 = _compute_pf_over_last_closes(30)
        pf_last_20, count_20 = _compute_pf_over_last_closes(20)
        
        # C → B promotion: out of penalty box
        # Requires: DD < 8%, PF >= 1.05 over last 30 trades (with at least 20 trades)
        if band == "C" and drawdown < 0.08:
            if pf_last_30 is not None and count_30 >= 20 and pf_last_30 >= 1.05:
                band = "B"
                mult = max(mult, 0.70)
                if os.getenv("DEBUG_SIGNALS", "0") == "1":
                    print(f"RISK-DEBUG: PAPER promotion C→B pf_last_30={pf_last_30:.3f} count={count_30} dd={drawdown:.4%}")
            elif pf_last_30 is None:
                # Fallback to DD-only promotion ONLY when PF data is genuinely unavailable
                # (not when PF exists but fails threshold or has insufficient sample - that means stay in C)
                # This ensures we don't promote when pf exists but is bad (e.g., 0.85) or has insufficient sample (count < 20)
                band = "B"
                mult = max(mult, 0.70)
                if os.getenv("DEBUG_SIGNALS", "0") == "1":
                    print(f"RISK-DEBUG: PAPER promotion C→B as DD improved to {drawdown:.4%} (PF data unavailable: pf=None, count={count_30})")
        
        # B → A promotion: full paper trust
        # Requires: DD < 5%, PF >= 1.15 over last 50 trades (with at least 40 trades) AND
        #           PF >= 1.10 over last 20 trades (with at least 15 trades)
        if band == "B" and drawdown < 0.05:
            if (
                pf_last_50 is not None and count_50 >= 40 and pf_last_50 >= 1.15 and
                pf_last_20 is not None and count_20 >= 15 and pf_last_20 >= 1.10
            ):
                band = "A"
                mult = max(mult, 1.0)
                if os.getenv("DEBUG_SIGNALS", "0") == "1":
                    print(f"RISK-DEBUG: PAPER promotion B→A pf_last_50={pf_last_50:.3f} pf_last_20={pf_last_20:.3f} dd={drawdown:.4%}")
    
    # Clamp risk_mult to [0.5, 1.25] bounds
    mult = _bounded(mult)

    result = {
        "ts": _now(),
        "equity": last_equity,
        "peak": peak,
        "drawdown": drawdown,
        "band": band,
        "mult": mult,
        "reason": "computed",
    }

    JSON_PATH.write_text(json.dumps(result, indent=2))
    with LOG_PATH.open("a") as f:
        f.write(json.dumps(result) + "\n")

    return result
