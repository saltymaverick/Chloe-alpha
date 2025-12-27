"""
GPT Reflection Runner - Triggered on close events only.

Builds compact prompts from reflection packets and calls GPT for analysis
and parameter tuning suggestions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine_alpha.core.gpt_client import query_gpt, get_cfg as get_gpt_cfg
from engine_alpha.core.paths import CONFIG, REPORTS
from engine_alpha.core.atomic_io import atomic_write_json
import json
import logging

logger = logging.getLogger(__name__)


def load_engine_config() -> Dict[str, Any]:
    """
    Load engine config with safe defaults.
    
    Returns:
        Engine config dict
    """
    config_path = CONFIG / "engine_config.json"
    defaults = {
        "enable_gpt_reflection": False,
        "gpt_reflection_on_close_only": True,
        "gpt_reflection_min_closed_trades": 1,
    }
    
    if not config_path.exists():
        return defaults
    
    try:
        with config_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            # Merge with defaults
            for key in defaults:
                if key not in data:
                    data[key] = defaults[key]
            return data
    except Exception:
        pass
    
    return defaults


GPT_STATE_PATH = REPORTS / "gpt_state.json"


def _load_gpt_state() -> Dict[str, Any]:
    """Load GPT state (last trade log offset)."""
    default_state = {
        "last_gpt_trade_log_offset": 0,
        "last_run_ts": None,
    }
    
    if not GPT_STATE_PATH.exists():
        # Create default state file on first access
        try:
            _save_gpt_state(default_state)
        except Exception:
            pass
        return default_state
    
    try:
        with GPT_STATE_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            # Ensure required keys exist
            if "last_gpt_trade_log_offset" not in data:
                data["last_gpt_trade_log_offset"] = 0
            if "last_run_ts" not in data:
                data["last_run_ts"] = None
            return data
    except Exception:
        pass
    
    return default_state


def _save_gpt_state(state: Dict[str, Any]) -> None:
    """Save GPT state."""
    try:
        atomic_write_json(GPT_STATE_PATH, state)
    except Exception:
        pass


def should_run_gpt(packet: Dict[str, Any], cfg: Dict[str, Any]) -> bool:
    """
    Determine if GPT reflection should run.
    
    Args:
        packet: Reflection packet dict
        cfg: Engine config dict
        
    Returns:
        True if GPT should run, False otherwise
    """
    # Check if GPT reflection is enabled
    if not cfg.get("enable_gpt_reflection", False):
        logger.info("REFLECTION_SKIP reason=disabled_in_config")
        return False

    # Gate: Only run once per tick (even if multiple samples processed)
    # Check if GPT already ran this tick
    if packet.get("meta", {}).get("gpt_ran_this_tick", False):
        logger.debug("GPT skip: already ran this tick")
        return False

    # Check if we should only run on close events
    if cfg.get("gpt_reflection_on_close_only", True):
        self_trust = packet.get("primitives", {}).get("self_trust", {})
        samples_processed = self_trust.get("samples_processed", 0)
        min_trades = cfg.get("gpt_reflection_min_closed_trades", 1)

        if samples_processed < min_trades:
            logger.info(f"REFLECTION_SKIP reason=close_gated samples_processed={samples_processed} min_trades={min_trades}")
            return False
        
        # Gate: Only run if trade log offset advanced (new closes processed)
        # This prevents GPT from running repeatedly on the same historical data
        gpt_state = _load_gpt_state()
        last_gpt_offset = gpt_state.get("last_gpt_trade_log_offset", 0)
        
        # Get current offset from self-trust state
        from engine_alpha.core.self_trust import load_state
        st_state = load_state()
        current_offset = st_state.get("last_byte_offset", 0)
        
        # Only run if offset advanced (new closes were processed)
        if current_offset <= last_gpt_offset:
            logger.debug(f"GPT skip: offset unchanged (current={current_offset} <= last_gpt={last_gpt_offset})")
            return False
    
    return True


def _build_reflection_prompt(packet: Dict[str, Any]) -> str:
    """
    Build a compact prompt from reflection packet.
    
    Args:
        packet: Reflection packet dict
        
    Returns:
        Prompt string
    """
    primitives = packet.get("primitives", {})
    self_trust = primitives.get("self_trust", {})
    opportunity = primitives.get("opportunity", {})
    invalidation = primitives.get("invalidation", {})
    compression = primitives.get("compression", {})
    decay = primitives.get("decay", {})
    
    # Build compact summary
    prompt_parts = [
        f"Trading system snapshot at {packet.get('ts')}",
        f"Symbol: {packet.get('symbol')}, Timeframe: {packet.get('timeframe')}",
        "",
        "PRIMITIVES:",
        f"- Self-trust score: {self_trust.get('self_trust_score')} (n={self_trust.get('n_samples', 0)})",
        f"- Opportunity eligible: {opportunity.get('eligible')}, density_ewma: {opportunity.get('density_ewma')}",
        f"- Thesis health: {invalidation.get('thesis_health_score')}, soft invalidation: {invalidation.get('soft_invalidation_score')}",
        f"- Compression score: {compression.get('compression_score')}, is_compressed: {compression.get('is_compressed')}",
        f"- Confidence decayed: {decay.get('confidence_decayed')}, refreshed: {decay.get('confidence_refreshed')}",
        "",
        "ISSUES:",
        ", ".join(packet.get("meta", {}).get("issues", [])) or "None",
        "",
        "TASK:",
        "1. Provide a short diagnosis (1-2 sentences)",
        "2. List 3-8 bullet observations",
        "3. Propose parameter changes as JSON ONLY (no prose):",
        "   - decay.confidence_half_life_s",
        "   - decay.pci_half_life_s",
        "   - compression.threshold_score",
        "   - opportunity.min_confidence",
        "   - opportunity.max_soft_invalidation",
        "",
        "For each proposed change, include:",
        "- key: parameter path",
        "- current: current value (if known)",
        "- proposed: new value",
        "- reason: brief explanation",
        "- confidence: 0.0-1.0",
        "",
        "OUTPUT FORMAT (JSON only):",
        "{",
        '  "diagnosis": "...",',
        '  "observations": ["...", "..."],',
        '  "proposed_changes": [',
        '    {"key": "...", "current": X, "proposed": Y, "reason": "...", "confidence": 0.0-1.0}',
        '  ]',
        "}",
    ]
    
    return "\n".join(prompt_parts)


def _parse_gpt_response(text: str) -> Dict[str, Any]:
    """
    Parse GPT response into structured format.
    
    Args:
        text: GPT response text
        
    Returns:
        Parsed dict with diagnosis, observations, proposed_changes
    """
    result = {
        "diagnosis": "",
        "observations": [],
        "proposed_changes": [],
    }
    
    # Try to extract JSON from response
    try:
        # Look for JSON block
        json_start = text.find("{")
        json_end = text.rfind("}") + 1
        
        if json_start >= 0 and json_end > json_start:
            json_str = text[json_start:json_end]
            parsed = json.loads(json_str)
            
            if isinstance(parsed, dict):
                result["diagnosis"] = parsed.get("diagnosis", "")
                result["observations"] = parsed.get("observations", [])
                # Validate and filter proposed_changes
                raw_changes = parsed.get("proposed_changes", [])
                if isinstance(raw_changes, list):
                    # Filter to only allowed keys
                    from engine_alpha.reflect.gpt_tuner_diff import ALLOWED_PARAM_KEYS
                    validated_changes = []
                    for change in raw_changes:
                        if isinstance(change, dict):
                            key = change.get("key")
                            if key and key in ALLOWED_PARAM_KEYS:
                                validated_changes.append(change)
                            elif key:
                                logger.debug(f"GPT proposed unknown key '{key}', rejecting")
                    result["proposed_changes"] = validated_changes
                else:
                    result["proposed_changes"] = []
        else:
            # Fallback: try parsing entire text as JSON
            parsed = json.loads(text.strip())
            if isinstance(parsed, dict):
                result.update(parsed)
    except Exception:
        # If JSON parsing fails, extract diagnosis and observations from text
        lines = text.split("\n")
        diagnosis_lines = []
        observations = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith("- ") or line.startswith("* "):
                observations.append(line[2:].strip())
            elif "diagnosis" in line.lower() or "summary" in line.lower():
                continue
            elif len(line) > 20 and not line.startswith("{"):
                diagnosis_lines.append(line)
        
        if diagnosis_lines:
            result["diagnosis"] = " ".join(diagnosis_lines[:2])
        result["observations"] = observations[:8]
    
    return result


def run_gpt_reflection(packet: Dict[str, Any], cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Run GPT reflection on reflection packet.
    
    Args:
        packet: Reflection packet dict
        cfg: Engine config dict
        
    Returns:
        Reflection result dict or None if failed
    """
    gpt_cfg = get_gpt_cfg()
    model = gpt_cfg.get("model", "gpt-4o-mini")
    
    # Build prompt
    prompt = _build_reflection_prompt(packet)
    
    # Call GPT
    response = query_gpt(prompt, purpose="reflection_analysis")
    
    if response is None:
        return None
    
    text = response.get("text", "")
    if not text:
        return None
    
    # Parse response
    parsed = _parse_gpt_response(text)
    
    # Build result
    result = {
        "ts": packet.get("ts"),
        "symbol": packet.get("symbol"),
        "timeframe": packet.get("timeframe"),
        "model": model,
        "inner_ok": packet.get("meta", {}).get("inner_ok"),
        "issues": packet.get("meta", {}).get("issues", []),
        "observations": parsed.get("observations", []),
        "proposed_changes": parsed.get("proposed_changes", []),
        "diagnosis": parsed.get("diagnosis", ""),
        "raw_text": text,
        "tokens": response.get("tokens"),
    }
    
    # Update GPT state: record the trade log offset we processed
    try:
        from engine_alpha.core.self_trust import load_state
        from datetime import datetime, timezone
        st_state = load_state()
        current_offset = st_state.get("last_byte_offset", 0)
        gpt_state = {
            "last_gpt_trade_log_offset": current_offset,
            "last_run_ts": datetime.now(timezone.utc).isoformat(),
        }
        _save_gpt_state(gpt_state)
        logger.info(f"GPT reflection completed, offset saved: {current_offset}")
    except Exception:
        pass  # Don't fail on state update
    
    return result

