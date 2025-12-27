"""
Pre-Candle Intelligence (PCI) - Logging Helper
Phase 3.1: Extract PCI snapshot for trade log enrichment

Pure utility module for extracting PCI data from signal vectors.
No behavior changes, logging only.
"""

from typing import Dict, Any, Optional


def extract_pci_snapshot(signal_dict: Dict[str, Any], include_features: bool = False) -> Optional[Dict[str, Any]]:
    """
    Extract compact PCI snapshot from signal vector dict.
    
    Args:
        signal_dict: Signal vector dict (from get_signal_vector_live or get_signal_vector)
                    Should contain "pre_candle" key if PCI is enabled
        include_features: If True, include full features dict (default: False, scores only)
    
    Returns:
        Dict with "scores" (and optionally "features"), or None if PCI not present
    """
    if not signal_dict:
        return None
    
    pre_candle = signal_dict.get("pre_candle")
    if not pre_candle:
        return None
    
    if not isinstance(pre_candle, dict):
        return None
    
    snapshot = {
        "scores": pre_candle.get("scores", {}),
    }
    
    if include_features:
        snapshot["features"] = pre_candle.get("features", {})
    
    # Only return if we have at least scores
    if snapshot.get("scores"):
        return snapshot
    
    return None
