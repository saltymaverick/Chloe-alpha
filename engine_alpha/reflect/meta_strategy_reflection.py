"""
Meta-Strategy Reflection Module

This module provides Chloe with a "macro brain" that reflects on broader market behavior
and strategic patterns, beyond simple parameter tuning.

Unlike threshold tuning (which adjusts entry_min_conf, enables/disables regimes), this module
identifies high-level patterns and proposes strategic ideas:

- "High-vol is the only regime with edge; maybe specialize in volatility breakouts"
- "Trend-down shorts behave like mean-reversion; stop treating as trend strategy"
- "Winning trades cluster around certain times; consider time-of-day filter"

Initially advisory only - writes structured reflections to JSONL log.
Later can be wired into strategy_evolver.py or manual review workflow.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Any, Optional
import json
import logging
from datetime import datetime, timezone

from engine_alpha.core.paths import REPORTS, CONFIG
from engine_alpha.core.gpt_client import query_gpt

logger = logging.getLogger(__name__)

RESEARCH_DIR = REPORTS / "research"
PF_PATH = REPORTS / "pf_local.json"
STRENGTH_PATH = RESEARCH_DIR / "strategy_strength.json"
CONF_MAP_PATH = CONFIG / "confidence_map.json"
THR_PATH = CONFIG / "regime_thresholds.json"
SWARM_SENTINEL_PATH = RESEARCH_DIR / "swarm_sentinel_report.json"
OBS_MODE_PATH = CONFIG / "observation_mode.json"

META_STRATEGY_LOG = RESEARCH_DIR / "meta_strategy_reflections.jsonl"


def _load_json(path: Path) -> Dict[str, Any]:
    """Safely load JSON file, returning empty dict if missing or malformed."""
    if not path.exists():
        return {}
    try:
        with path.open("r") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning(f"Failed to load {path}: {e}")
        return {}


@dataclass
class MetaContext:
    """Structured context for meta-strategy reflection."""
    pf_local: Dict[str, Any]
    strategy_strength: Dict[str, Any]
    confidence_map: Dict[str, Any]
    regime_thresholds: Dict[str, Any]
    swarm_sentinel: Dict[str, Any]
    observation_mode: Dict[str, Any]


def build_meta_context() -> MetaContext:
    """Build structured context from all available research outputs."""
    pf = _load_json(PF_PATH)
    strengths = _load_json(STRENGTH_PATH)
    conf_map = _load_json(CONF_MAP_PATH)
    thr = _load_json(THR_PATH)
    sentinel = _load_json(SWARM_SENTINEL_PATH)
    obs_mode = _load_json(OBS_MODE_PATH)

    return MetaContext(
        pf_local=pf,
        strategy_strength=strengths,
        confidence_map=conf_map,
        regime_thresholds=thr,
        swarm_sentinel=sentinel,
        observation_mode=obs_mode,
    )


def default_meta_prompt(context: MetaContext) -> Dict[str, Any]:
    """
    Build a structured prompt for Chloe's GPT brain to reflect on strategy.
    
    Returns a dict with 'role', 'task', and 'context' keys.
    """
    """
    Build a structured prompt for Chloe's GPT brain.
    
    This defines what 'meta-strategy reflection' means - looking at patterns
    beyond simple threshold adjustments.
    """
    # Format context for readability
    pf_summary = f"PF: {context.pf_local.get('pf', 'N/A'):.4f}, Trades: {context.pf_local.get('count', 0)}"
    
    # Regime summary
    regime_summary = []
    for regime, info in context.strategy_strength.items():
        edge = info.get("edge", 0.0)
        strength = info.get("strength", 0.0)
        count = info.get("weighted_count", 0.0)
        enabled = context.regime_thresholds.get(regime, {}).get("enabled", True)
        entry_min = context.regime_thresholds.get(regime, {}).get("entry_min_conf", "N/A")
        regime_summary.append(
            f"  - {regime}: edge={edge:+.5f}, strength={strength:+.6f}, samples={count:.0f}, "
            f"enabled={enabled}, entry_min_conf={entry_min}"
        )
    
    # Confidence bucket summary
    conf_summary = []
    for bucket, info in sorted(context.confidence_map.items(), key=lambda x: int(x[0])):
        exp_ret = info.get("expected_return", 0.0)
        count = info.get("weighted_count", 0.0)
        conf_summary.append(f"  Bucket {bucket}: expected_return={exp_ret:+.5f}, samples={count:.0f}")
    
    # Observation mode summary
    obs_regimes = context.observation_mode.get("observation_regimes", [])
    obs_edge_floor = context.observation_mode.get("edge_floor", -0.0015)
    obs_size_factor = context.observation_mode.get("size_factor", 0.5)
    
    task_text = (
        "You are Chloe's higher-level quant brain. "
        "You are NOT tuning simple thresholds here. "
        "Instead, you are reflecting on broader market behavior and Chloe's own performance "
        "to propose strategic ideas.\n\n"
        "You have access to:\n"
        "- pf_local: summary of Chloe's recent performance (PF, drawdown, etc.).\n"
        "- strategy_strength: per-regime edge, strength, and weighted sample sizes.\n"
        "- confidence_map: expected returns per confidence bucket.\n"
        "- regime_thresholds: which regimes are enabled and how strict they are.\n"
        "- swarm_sentinel: high-level health signals (critical flags, blind spots, etc.).\n\n"
        "Your job:\n"
        "1. Identify big-picture patterns (e.g., 'only high_vol has edge', 'trend regimes are weak', "
        "'chop is dead', 'confidence is over-trusted at mid buckets').\n"
        "2. Propose 2–4 concrete strategic ideas or experiments, for example:\n"
        "   - 'Specialized high_vol breakout strategy with time-of-day filter.'\n"
        "   - 'Mean-reversion micro-strategy inside high_vol pullbacks.'\n"
        "   - 'Skip low-confidence trend_down trades entirely and focus only on extreme confidence levels.'\n"
        "   - 'Introduce a macro or BTC regime filter to gate all ETH trades.'\n"
        "3. For each idea, output a structured object with:\n"
        "   - name: short, descriptive strategy name.\n"
        "   - intuition: why this might work given the current data.\n"
        "   - conditions: when it should apply (regimes, confidence ranges, volatility conditions, etc.).\n"
        "   - sketch: rough implementation outline (signals/conditions, not code).\n"
        "   - risk: key risks, how to size it, and when to shut it down.\n"
        "4. Do NOT simply restate current thresholds or suggest trivial tweaks. "
        "Think at the level of new approaches, filters, or structural changes.\n"
    )
    
    return {
        "role": "meta_strategy_reflection",
        "task": task_text,
        "context": asdict(context),
    }


def _think(prompt_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Wrapper for GPT call that matches chloe_core.think() interface.
    
    If chloe_core.think() exists, use it. Otherwise, use query_gpt().
    """
    try:
        from engine_alpha.core.chloe_core import think
        # If think() exists, use it with the prompt dict
        return think(prompt_dict)
    except ImportError:
        # Fallback to query_gpt with formatted prompt
        task = prompt_dict.get("task", "")
        context_str = json.dumps(prompt_dict.get("context", {}), indent=2)
        full_prompt = f"{task}\n\nContext:\n{context_str}"
        
        result = query_gpt(full_prompt, purpose="meta_strategy_reflection")
        if result is None:
            return {"error": "GPT call failed or budget exhausted"}
        
        # Try to parse JSON response
        text = result.get("text", "")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw_text": text, "tokens": result.get("tokens")}


def run_meta_strategy_reflection() -> Path:
    """
    Run a single meta-strategy reflection pass.
    
    Writes a JSONL record to META_STRATEGY_LOG.
    
    Returns:
        Path to the log file
    """
    ctx = build_meta_context()
    prompt = default_meta_prompt(ctx)
    
    # Call Chloe's GPT-powered brain
    reflection = _think(prompt)
    
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "prompt": prompt,
        "reflection": reflection,
    }
    
    META_STRATEGY_LOG.parent.mkdir(parents=True, exist_ok=True)
    with META_STRATEGY_LOG.open("a") as f:
        f.write(json.dumps(record) + "\n")
    
    return META_STRATEGY_LOG


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    out = run_meta_strategy_reflection()
    print(f"Meta-strategy reflection written to: {out}")

