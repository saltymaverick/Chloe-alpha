"""
Strategy Evolver Stub - Read-only advisory tool for future strategy evolution.

This tool reads quality scores and tuning rules to provide advisory suggestions
for strategy expansion or reduction. It does NOT modify any configs or execute
any trades.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, Any, Optional

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML not installed. Install with: pip install pyyaml")
    sys.exit(1)

ROOT = Path(__file__).resolve().parents[1]
GPT_REPORT_DIR = ROOT / "reports" / "gpt"
QUALITY_SCORES_PATH = GPT_REPORT_DIR / "quality_scores.json"
TUNING_RULES_PATH = ROOT / "config" / "tuning_rules.yaml"


def safe_load_json(path: Path) -> Dict[str, Any]:
    """Load JSON file safely, returning empty dict on error."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        print(f"⚠️  Warning: Failed to parse JSON at {path}: {e}")
        return {}
    except Exception as e:
        print(f"⚠️  Warning: Error reading {path}: {e}")
        return {}


def safe_load_yaml(path: Path) -> Dict[str, Any]:
    """Load YAML file safely, returning empty dict on error."""
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        print(f"⚠️  Warning: Failed to parse YAML at {path}: {e}")
        return {}
    except Exception as e:
        print(f"⚠️  Warning: Error reading {path}: {e}")
        return {}


def get_thresholds(tuning_rules: Dict[str, Any]) -> Dict[str, float]:
    """Extract quality scoring thresholds from tuning_rules.yaml."""
    defaults = {
        "strong": 70.0,
        "medium": 40.0,
        "weak": 20.0,
    }
    
    qs_section = tuning_rules.get("quality_scoring", {})
    thresholds_section = qs_section.get("thresholds", {})
    
    return {
        "strong": float(thresholds_section.get("strong", defaults["strong"])),
        "medium": float(thresholds_section.get("medium", defaults["medium"])),
        "weak": float(thresholds_section.get("weak", defaults["weak"])),
    }


def classify_symbol(score: float, thresholds: Dict[str, float]) -> str:
    """
    Classify symbol based on quality score.
    
    Returns: "strong", "medium", or "weak"
    """
    if score >= thresholds["strong"]:
        return "strong"
    elif score >= thresholds["medium"]:
        return "medium"
    else:
        return "weak"


def get_suggestion(classification: str) -> str:
    """Get advisory suggestion based on classification."""
    if classification == "strong":
        return "Candidate for future strategy expansion (mutations), not applied."
    elif classification == "medium":
        return "Continue observation; consider gradual expansion if performance improves, not applied."
    else:  # weak
        return "Candidate for reduced exploration / watch-only, not applied."


def main() -> None:
    """Main entry point."""
    print("STRATEGY EVOLVER STUB")
    print("-" * 70)
    print()
    
    # Load quality scores
    quality_scores = safe_load_json(QUALITY_SCORES_PATH)
    
    if not quality_scores:
        print("⚠️  No quality scores found.")
        print(f"   Expected file: {QUALITY_SCORES_PATH}")
        print("   Run quality scores first: python3 -m tools.quality_scores")
        return
    
    # Load tuning rules for thresholds
    tuning_rules = safe_load_yaml(TUNING_RULES_PATH)
    thresholds = get_thresholds(tuning_rules)
    
    if not tuning_rules:
        print(f"⚠️  Using default thresholds (strong={thresholds['strong']}, "
              f"medium={thresholds['medium']}, weak={thresholds['weak']})")
        print(f"   Config file not found: {TUNING_RULES_PATH}")
    print()
    
    # Classify and sort symbols
    symbol_classifications: Dict[str, Dict[str, Any]] = {}
    
    for symbol, data in quality_scores.items():
        score = data.get("score", 0.0)
        classification = classify_symbol(score, thresholds)
        suggestion = get_suggestion(classification)
        
        symbol_classifications[symbol] = {
            "score": score,
            "classification": classification,
            "suggestion": suggestion,
        }
    
    if not symbol_classifications:
        print("⚠️  No symbols found in quality scores.")
        return
    
    # Sort by score descending
    sorted_symbols = sorted(
        symbol_classifications.items(),
        key=lambda x: x[1]["score"],
        reverse=True
    )
    
    # Print results
    for symbol, info in sorted_symbols:
        score = info["score"]
        classification = info["classification"]
        suggestion = info["suggestion"]
        
        print(f"{symbol}: score={score:.1f} ({classification})")
        print(f"  Suggestion: {suggestion}")
        print()
    
    print("=" * 70)
    print("Note: This is a read-only advisory tool. No configs were modified.")
    print("=" * 70)


if __name__ == "__main__":
    main()


