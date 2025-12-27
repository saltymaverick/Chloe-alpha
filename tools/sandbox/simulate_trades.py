"""
Generate fake trade records for testing dashboard and PF tools.
"""

from pathlib import Path
import json
from datetime import datetime, timezone
import random

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports" / "trades.jsonl"


def simulate(n=10):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    
    for _ in range(n):
        rec = {
            "id": random.randint(10000, 99999),
            "ts": datetime.now(timezone.utc).isoformat(),
            "symbol": "ETHUSDT",
            "side": random.choice(["long", "short"]),
            "entry_price": random.uniform(1800, 2200),
            "exit_price": random.uniform(1800, 2200),
            "pnl_pct": random.uniform(-0.03, 0.03),
            "regime_at_entry": "trend_up",
            "confidence_at_entry": random.random(),
        }
        with OUT.open("a") as f:
            f.write(json.dumps(rec) + "\n")
    
    print(f"Fake trades appended to {OUT}")


if __name__ == "__main__":
    simulate()


