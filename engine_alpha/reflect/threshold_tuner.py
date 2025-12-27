"""
GPT Threshold Tuner - Module 13

GPT-driven threshold tuning that proposes (but doesn't auto-apply) threshold updates
based on recent trading performance.

Mode: GPT proposes → Human approves. No automatic mutation of risk.yaml yet.
"""

from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
import json
import re
from pathlib import Path

from engine_alpha.core.paths import REPORTS
from engine_alpha.reflect.trade_analysis import pf_from_trades, _read_trades
from engine_alpha.core.drift_detector import compute_drift, DriftState
from engine_alpha.core.gpt_client import query_gpt


TUNING_LOG_PATH = REPORTS / "tuning_proposals.jsonl"


@dataclass
class ThresholdProposal:
    """A GPT proposal for threshold updates."""
    ts: str
    current: Dict[str, float]
    suggested: Dict[str, float]
    rationale: str
    stats: Dict[str, Any]


def load_recent_trades(limit: int) -> List[Dict[str, Any]]:
    """
    Helper to load the most recent `limit` trades from the main trade log.
    
    Args:
        limit: Maximum number of trades to load
    
    Returns:
        List of trade dicts
    """
    trades_path = REPORTS / "trades.jsonl"
    all_trades = _read_trades(trades_path)
    return all_trades[-limit:] if len(all_trades) > limit else all_trades


def compute_pf_by_regime(trades: List[Dict[str, Any]]) -> Dict[str, float]:
    """Compute PF by regime."""
    from collections import defaultdict
    
    by_regime = defaultdict(lambda: {"wins": [], "losses": []})
    
    for trade in trades:
        if trade.get("type") != "close":
            continue
        
        regime = trade.get("regime", "unknown")
        pct = float(trade.get("pct", 0.0))
        
        if pct > 0:
            by_regime[regime]["wins"].append(pct)
        elif pct < 0:
            by_regime[regime]["losses"].append(abs(pct))
    
    result = {}
    for regime, data in by_regime.items():
        wins = data["wins"]
        losses = data["losses"]
        total_trades = len(wins) + len(losses)
        
        if total_trades == 0:
            continue
        
        pf = pf_from_trades([{"pct": w} for w in wins] + [{"pct": -l} for l in losses])
        result[regime] = pf
    
    return result


def compute_pf_by_confidence_band(trades: List[Dict[str, Any]], bands: List[tuple]) -> Dict[str, float]:
    """Compute PF by confidence band."""
    from collections import defaultdict
    
    by_band = defaultdict(lambda: {"wins": [], "losses": []})
    
    for trade in trades:
        if trade.get("type") != "close":
            continue
        
        confidence = float(trade.get("confidence", 0.0))
        pct = float(trade.get("pct", 0.0))
        
        # Find band
        band_label = None
        for min_conf, max_conf in bands:
            if min_conf <= confidence < max_conf:
                band_label = f"{min_conf:.1f}-{max_conf:.1f}"
                break
        
        if band_label is None:
            continue
        
        if pct > 0:
            by_band[band_label]["wins"].append(pct)
        elif pct < 0:
            by_band[band_label]["losses"].append(abs(pct))
    
    result = {}
    for band_label, data in by_band.items():
        wins = data["wins"]
        losses = data["losses"]
        total_trades = len(wins) + len(losses)
        
        if total_trades == 0:
            continue
        
        pf = pf_from_trades([{"pct": w} for w in wins] + [{"pct": -l} for l in losses])
        result[band_label] = pf
    
    return result


def build_stats_for_tuning(trades: List[Dict[str, Any]], risk_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute stats used to inform GPT:
      - pf_local
      - pf_by_regime
      - pf_by_confidence_band
      - drift_state
      - trade_count
    """
    closed_trades = [t for t in trades if t.get("type") == "close"]
    
    if not closed_trades:
        return {
            "trade_count": 0,
            "pf_local": 0.0,
            "pf_by_regime": {},
            "pf_by_confidence_band": {},
            "drift_state": {
                "drift_score": 1.0,
                "pf_local": 0.0,
                "confidence_return_corr": None,
            },
        }
    
    # PF local
    pf_local = pf_from_trades(closed_trades)
    
    # PF by regime
    pf_by_regime = compute_pf_by_regime(closed_trades)
    
    # PF by confidence band
    bands = [(0.0, 0.3), (0.3, 0.6), (0.6, 0.8), (0.8, 1.0)]
    pf_by_confidence = compute_pf_by_confidence_band(closed_trades, bands)
    
    # Drift state
    try:
        drift_state_obj = compute_drift(closed_trades, window=len(closed_trades))
        drift_state = {
            "drift_score": drift_state_obj.drift_score,
            "pf_local": drift_state_obj.pf_local,
            "confidence_return_corr": drift_state_obj.confidence_return_corr,
        }
    except Exception:
        drift_state = {
            "drift_score": 1.0,
            "pf_local": 0.0,
            "confidence_return_corr": None,
        }
    
    return {
        "trade_count": len(closed_trades),
        "pf_local": pf_local,
        "pf_by_regime": pf_by_regime,
        "pf_by_confidence_band": pf_by_confidence,
        "drift_state": drift_state,
    }


def build_gpt_prompt(
    stats: Dict[str, Any],
    current_thresholds: Dict[str, float],
    risk_config: Dict[str, Any],
) -> str:
    """
    Build a clear, structured prompt asking GPT to propose updated thresholds
    within the max_change_per_step limits, and to explain why.
    """
    tuning_cfg = risk_config.get("tuning", {})
    max_changes = tuning_cfg.get("max_change_per_step", {})
    
    prompt = f"""You are analyzing Chloe's trading performance and proposing threshold adjustments.

RECENT TRADING STATS:
- Total closed trades: {stats['trade_count']}
- PF_local: {stats['pf_local']:.3f}
- PF by regime: {json.dumps(stats['pf_by_regime'], indent=2)}
- PF by confidence band: {json.dumps(stats['pf_by_confidence_band'], indent=2)}
- Drift state:
  - drift_score: {stats['drift_state']['drift_score']:.3f} (0=good, 1=bad)
  - pf_local: {stats['drift_state']['pf_local']:.3f}
  - confidence_return_corr: {stats['drift_state']['confidence_return_corr']}

CURRENT THRESHOLDS:
- entry_min_confidence: {current_thresholds['entry_min_confidence']:.2f}
- exit_min_confidence: {current_thresholds['exit_min_confidence']:.2f}
- max_drift_for_entries: {current_thresholds['max_drift_for_entries']:.2f}
- max_drift_for_open_positions: {current_thresholds['max_drift_for_open_positions']:.2f}

SAFETY LIMITS (maximum change per tuning cycle):
- entry_min_confidence: ±{max_changes.get('entry_min_confidence', 0.10):.2f}
- exit_min_confidence: ±{max_changes.get('exit_min_confidence', 0.10):.2f}
- max_drift_for_entries: ±{max_changes.get('max_drift_for_entries', 0.20):.2f}
- max_drift_for_open_positions: ±{max_changes.get('max_drift_for_open_positions', 0.20):.2f}

TASK:
Analyze the performance stats and propose updated thresholds within the safety limits.
Consider:
- If PF_local < 1.0: consider raising entry_min_confidence or lowering max_drift_for_entries
- If high-confidence bands (0.6-1.0) have PF < 1.0: raise entry_min_confidence
- If drift_score is high: lower max_drift_for_entries and max_drift_for_open_positions
- If exits are too frequent: consider lowering exit_min_confidence slightly
- If entries are too rare: consider lowering entry_min_confidence slightly

Respond with a JSON object containing:
{{
  "entry_min_confidence": <float>,
  "exit_min_confidence": <float>,
  "max_drift_for_entries": <float>,
  "max_drift_for_open_positions": <float>,
  "rationale": "<explanation of why these changes were proposed>"
}}

Ensure all values are within the safety limits relative to current thresholds.
"""
    return prompt


def parse_gpt_response(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse GPT response text into threshold dict.
    
    Handles JSON blocks, extracts JSON from markdown code blocks, etc.
    """
    if not text:
        return None
    
    # Try to extract JSON from markdown code blocks
    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if json_match:
        text = json_match.group(1)
    
    # Try to find JSON object in text
    json_match = re.search(r'\{[^{}]*"entry_min_confidence"[^{}]*\}', text, re.DOTALL)
    if json_match:
        text = json_match.group(0)
    
    try:
        parsed = json.loads(text)
        
        # Validate required fields
        required_fields = [
            "entry_min_confidence",
            "exit_min_confidence",
            "max_drift_for_entries",
            "max_drift_for_open_positions",
            "rationale",
        ]
        
        if not all(field in parsed for field in required_fields):
            return None
        
        # Validate types
        for field in ["entry_min_confidence", "exit_min_confidence", "max_drift_for_entries", "max_drift_for_open_positions"]:
            parsed[field] = float(parsed[field])
        
        parsed["rationale"] = str(parsed.get("rationale", ""))
        
        return parsed
    except Exception:
        return None


def call_gpt_for_thresholds(prompt: str) -> Optional[Dict[str, Any]]:
    """
    Call GPT with the given prompt and parse the response into threshold dict.
    
    Returns:
        Dict with entry_min_confidence, exit_min_confidence, max_drift_for_entries,
        max_drift_for_open_positions, rationale, or None if GPT call fails
    """
    try:
        response = query_gpt(prompt, "threshold_tuning")
        if not response:
            return None
        
        text = response.get("text", "")
        if not text:
            return None
        
        return parse_gpt_response(text)
    except Exception as e:
        # Log error but don't crash
        print(f"GPT call failed: {e}")
        return None


def clamp_threshold_change(
    current: float,
    suggested: float,
    max_change: float,
) -> float:
    """Clamp suggested threshold change within max_change limit."""
    change = suggested - current
    clamped_change = max(-max_change, min(max_change, change))
    return current + clamped_change


def save_proposal(proposal: ThresholdProposal) -> None:
    """
    Append the proposal to reports/tuning_proposals.jsonl as a JSON line.
    """
    TUNING_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    proposal_dict = {
        "ts": proposal.ts,
        "current": proposal.current,
        "suggested": proposal.suggested,
        "rationale": proposal.rationale,
        "stats": proposal.stats,
    }
    
    with open(TUNING_LOG_PATH, "a") as f:
        f.write(json.dumps(proposal_dict) + "\n")


def propose_thresholds(
    risk_config: Dict[str, Any],
    min_trades: Optional[int] = None,
) -> Optional[ThresholdProposal]:
    """
    Main entrypoint:
      - load recent trades
      - if there aren't enough trades, return None
      - compute stats
      - build GPT prompt
      - call GPT for suggestions
      - enforce max_change_per_step from risk_config
      - construct ThresholdProposal
      - save to JSONL
      - return proposal
    """
    tuning_cfg = risk_config.get("tuning", {})
    
    if not tuning_cfg.get("enabled", True):
        return None
    
    # Get min_trades requirement
    if min_trades is None:
        min_trades = tuning_cfg.get("min_trades_for_tuning", 50)
    
    lookback = tuning_cfg.get("lookback_trades", 150)
    
    # Load recent trades
    trades = load_recent_trades(limit=lookback)
    closed_trades = [t for t in trades if t.get("type") == "close"]
    
    if len(closed_trades) < min_trades:
        return None
    
    # Get current thresholds
    thresholds_cfg = risk_config.get("thresholds", {})
    current_thresholds = {
        "entry_min_confidence": float(thresholds_cfg.get("entry_min_confidence", 0.60)),
        "exit_min_confidence": float(thresholds_cfg.get("exit_min_confidence", 0.30)),
        "max_drift_for_entries": float(thresholds_cfg.get("max_drift_for_entries", 0.50)),
        "max_drift_for_open_positions": float(thresholds_cfg.get("max_drift_for_open_positions", 0.70)),
    }
    
    # Compute stats
    stats = build_stats_for_tuning(trades, risk_config)
    
    # Build GPT prompt
    prompt = build_gpt_prompt(stats, current_thresholds, risk_config)
    
    # Call GPT
    gpt_response = call_gpt_for_thresholds(prompt)
    if not gpt_response:
        return None
    
    # Enforce max_change_per_step limits
    max_changes = tuning_cfg.get("max_change_per_step", {})
    suggested_thresholds = {}
    
    for key in current_thresholds:
        suggested_value = float(gpt_response.get(key, current_thresholds[key]))
        max_change = float(max_changes.get(key, 0.10))
        suggested_thresholds[key] = clamp_threshold_change(
            current_thresholds[key],
            suggested_value,
            max_change,
        )
    
    # Create proposal
    proposal = ThresholdProposal(
        ts=datetime.now(timezone.utc).isoformat(),
        current=current_thresholds,
        suggested=suggested_thresholds,
        rationale=gpt_response.get("rationale", ""),
        stats=stats,
    )
    
    # Save to JSONL
    save_proposal(proposal)
    
    return proposal

