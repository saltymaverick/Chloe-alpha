"""
Generate fake OHLCV candles for testing the live loop and dashboard.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "ohlcv" / "ETHUSDT_1h_live.csv"


def generate(num=100):
    now = datetime.now(timezone.utc)
    ts = [now - timedelta(hours=num-i) for i in range(num)]
    
    # Random walk price
    prices = 2000 + np.cumsum(np.random.randn(num) * 10)
    
    df = pd.DataFrame({
        "ts": [t.isoformat() for t in ts],
        "symbol": "ETHUSDT",
        "timeframe": "1h",
        "open": prices,
        "high": prices + np.random.rand(num) * 10,
        "low": prices - np.random.rand(num) * 10,
        "close": prices + np.random.randn(num),
        "volume": np.random.rand(num) * 100,
    })
    
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    print(f"Wrote fake candles to {OUT}")


if __name__ == "__main__":
    generate()


