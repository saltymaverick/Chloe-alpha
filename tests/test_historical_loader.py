from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone

from engine_alpha.core.paths import DATA
from engine_alpha.data.historical_loader import load_ohlcv


def test_load_csv_round_trip():
    data_dir = DATA / "ohlcv"
    data_dir.mkdir(parents=True, exist_ok=True)
    csv_path = data_dir / "tmp_ETHUSDT_1h.csv"

    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(10):
        ts = start + timedelta(hours=i)
        rows.append(
            {
                "ts": ts.isoformat().replace("+00:00", "Z"),
                "open": 100 + i,
                "high": 100 + i + 1,
                "low": 100 + i - 1,
                "close": 100 + i + 0.5,
                "volume": 10 + i,
            }
        )

    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["ts", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerows(rows)

    cfg = {
        "source": "csv",
        "csv_glob": str(data_dir / "{symbol}_{timeframe}.csv"),
    }
    loaded = load_ohlcv("tmp_ETHUSDT", "1h", rows[0]["ts"], (start + timedelta(hours=10)).isoformat().replace("+00:00", "Z"), cfg)
    assert len(loaded) == 10
    assert set(loaded[0].keys()) == {"ts", "open", "high", "low", "close", "volume"}
