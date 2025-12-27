"""
Mutation Engine - Propose strategy mutations for future evaluation.

All mutations are PROPOSALS ONLY - no automatic application.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
GPT_REPORT_DIR = ROOT / "reports" / "gpt"
ARE_REPORT_DIR = ROOT / "reports" / "research"
EVOLVER_OUTPUT_DIR = ROOT / "reports" / "evolver"


def safe_load_json(path: Path) -> Dict[str, Any]:
    """Load JSON file safely."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


class MutationCore:
    """Core mutation engine for proposing strategy parameter changes."""
    
    def __init__(self):
        self.evolver_output: Dict[str, Any] = {}
        self.quality_scores: Dict[str, Dict[str, Any]] = {}
        self.are_snapshot: Dict[str, Any] = {}
    
    def load_inputs(self) -> Dict[str, Any]:
        """
        Load all input files.
        
        Returns:
            Dict with loaded data summary
        """
        # Load evolver output
        evolver_path = EVOLVER_OUTPUT_DIR / "evolver_output.json"
        self.evolver_output = safe_load_json(evolver_path)
        
        # Load quality scores
        quality_path = GPT_REPORT_DIR / "quality_scores.json"
        self.quality_scores = safe_load_json(quality_path)
        
        # Load ARE snapshot
        are_path = ARE_REPORT_DIR / "are_snapshot.json"
        self.are_snapshot = safe_load_json(are_path)
        
        return {
            "evolver_symbols": len(self.evolver_output.get("symbols", {})),
            "quality_symbols": len(self.quality_scores),
            "are_symbols": len(self.are_snapshot.get("symbols", {})),
        }
    
    def propose_mutations(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Propose mutations for all symbols.
        
        Returns:
            Dict mapping symbol -> list of mutation proposals
        """
        all_mutations: Dict[str, List[Dict[str, Any]]] = {}
        symbols_evaluations = self.evolver_output.get("symbols", {})
        
        for symbol, evaluation in symbols_evaluations.items():
            mutations = self._propose_for_symbol(symbol, evaluation)
            if mutations:
                all_mutations[symbol] = mutations
        
        return all_mutations
    
    def _propose_for_symbol(
        self,
        symbol: str,
        evaluation: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Propose mutations for a single symbol."""
        mutations: List[Dict[str, Any]] = []
        
        tier = evaluation.get("tier", "tier2")
        promotion_candidate = evaluation.get("promotion_candidate", False)
        demotion_candidate = evaluation.get("demotion_candidate", False)
        quality_score = self.quality_scores.get(symbol, {}).get("score")
        
        # Get ARE stats for stability check
        are_long = self.are_snapshot.get("symbols", {}).get(symbol, {}).get("long", {})
        are_exp_pf = are_long.get("exp_pf") if are_long else None
        
        # Promotion candidates: positive mutations
        if promotion_candidate:
            mutations.append({
                "param": "entry_conf_min",
                "delta": -0.02,
                "reason": f"Promotion candidate: strong performance (tier={tier})",
            })
            mutations.append({
                "param": "exploration_cap",
                "delta": 1,
                "reason": f"Promotion candidate: increase exploration capacity",
            })
        
        # Strong Tier1: slight positive adjustments
        elif tier == "tier1" and quality_score is not None and quality_score >= 70:
            mutations.append({
                "param": "entry_conf_min",
                "delta": -0.01,
                "reason": f"Strong performer (quality={quality_score:.1f}): slight relaxation",
            })
            mutations.append({
                "param": "exploration_cap",
                "delta": 1,
                "reason": f"Strong performer: increase exploration capacity",
            })
        
        # Demotion candidates: negative mutations
        elif demotion_candidate:
            mutations.append({
                "param": "entry_conf_min",
                "delta": 0.02,
                "reason": f"Demotion candidate: tighten entry criteria (tier={tier})",
            })
            mutations.append({
                "param": "exploration_cap",
                "delta": -1,
                "reason": f"Demotion candidate: reduce exploration capacity",
            })
        
        # Weak Tier3: conservative mutations
        elif tier == "tier3":
            mutations.append({
                "param": "entry_conf_min",
                "delta": 0.02,
                "reason": f"Weak performer (tier3): tighten entry criteria",
            })
            mutations.append({
                "param": "exploration_cap",
                "delta": -1,
                "reason": f"Weak performer: reduce exploration capacity",
            })
        
        # Promising Tier2: cautious positive
        elif tier == "tier2" and quality_score is not None and quality_score >= 50:
            mutations.append({
                "param": "entry_conf_min",
                "delta": -0.01,
                "reason": f"Promising performer (quality={quality_score:.1f}): slight relaxation",
            })
        
        return mutations
    
    def save_output(self, mutations: Dict[str, List[Dict[str, Any]]]) -> Path:
        """
        Save mutations to JSON file.
        
        Args:
            mutations: Dict from propose_mutations()
        
        Returns:
            Path to saved file
        """
        output = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mutations": mutations,
            "summary": {
                "total_symbols": len(mutations),
                "total_mutations": sum(len(m) for m in mutations.values()),
            },
        }
        
        EVOLVER_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = EVOLVER_OUTPUT_DIR / "mutations.json"
        output_path.write_text(json.dumps(output, indent=2, sort_keys=True))
        
        return output_path
