#!/usr/bin/env python3
"""
CLI tool to run GPT threshold tuner.

Usage:
    python tools/run_threshold_tuner.py
"""

import sys
import yaml
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine_alpha.reflect.threshold_tuner import propose_thresholds
from engine_alpha.core.paths import CONFIG


def load_risk_config() -> dict:
    """Load risk configuration from risk.yaml."""
    config_path = CONFIG / "risk.yaml"
    if not config_path.exists():
        print(f"Error: {config_path} not found")
        sys.exit(1)
    
    with config_path.open() as f:
        return yaml.safe_load(f) or {}


def main() -> None:
    """Main entrypoint."""
    risk_config = load_risk_config()
    tuning_cfg = risk_config.get("tuning", {})
    min_trades = tuning_cfg.get("min_trades_for_tuning", 50)
    
    print("=== GPT Threshold Tuner ===")
    print(f"Minimum trades required: {min_trades}")
    print()
    
    proposal = propose_thresholds(risk_config, min_trades=min_trades)
    
    if proposal is None:
        print(f"Not enough trades to run tuning (need at least {min_trades}).")
        print("Run more trades and try again.")
        return
    
    print("=== GPT Threshold Proposal ===")
    print(f"Timestamp: {proposal.ts}")
    print()
    print("Current thresholds:")
    for key, value in proposal.current.items():
        print(f"  {key}: {value:.3f}")
    print()
    print("Suggested thresholds:")
    for key, value in proposal.suggested.items():
        change = value - proposal.current[key]
        change_str = f" ({change:+.3f})" if abs(change) > 0.001 else " (no change)"
        print(f"  {key}: {value:.3f}{change_str}")
    print()
    print("Rationale:")
    print(f"  {proposal.rationale}")
    print()
    print("Stats summary:")
    print(f"  Trade count: {proposal.stats.get('trade_count', 0)}")
    print(f"  PF_local: {proposal.stats.get('pf_local', 0.0):.3f}")
    drift_state = proposal.stats.get('drift_state', {})
    print(f"  Drift score: {drift_state.get('drift_score', 0.0):.3f}")
    print()
    print(f"Proposal saved to: {CONFIG.parent / 'reports' / 'tuning_proposals.jsonl'}")
    print()
    print("⚠️  This is a PROPOSAL only. Review and manually update risk.yaml if you approve.")


if __name__ == "__main__":
    main()

