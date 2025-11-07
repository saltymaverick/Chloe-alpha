"""
News Tone Fetcher - Phase 4
Stub GPT summarizer for news tone.
"""

import json
from pathlib import Path
from typing import Dict, Any
from datetime import datetime, timezone

from engine_alpha.core.paths import REPORTS


# Dummy news data for stub
DUMMY_NEWS = [
    "Market shows strong bullish sentiment with institutional buying pressure.",
    "Regulatory uncertainty creates market volatility and bearish tone.",
    "Positive developments in DeFi sector drive optimistic market outlook.",
    "Technical analysis suggests potential correction in near term.",
    "Market consolidation continues with neutral sentiment.",
]


def fetch_news_tone() -> Dict[str, Any]:
    """
    Stub GPT summarizer for news tone.
    
    Returns:
        Dictionary with tone and rationale
    """
    # For stub: cycle through dummy news or use static tone
    # In production, this would call GPT API
    
    # Simple stub: use deterministic tone based on timestamp
    import time
    tone = ((int(time.time()) // 3600) % 5 - 2) / 2.0  # Cycle through -1 to +1
    tone = max(-1.0, min(1.0, tone))  # Clamp to [-1, 1]
    
    # Select rationale from dummy news
    news_index = int(time.time()) % len(DUMMY_NEWS)
    rationale = DUMMY_NEWS[news_index]
    
    result = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "tone": tone,
        "rationale": rationale,
    }
    
    # Write to reports
    news_tone_path = REPORTS / "news_tone.json"
    news_tone_path.parent.mkdir(parents=True, exist_ok=True)
    with open(news_tone_path, "w") as f:
        json.dump(result, f, indent=2)
    
    return result
