#!/usr/bin/env python3
"""
Live bridge diagnostic - Phase 12
Runs exchange health checks for ETHUSDT/BTCUSDT.
"""

from __future__ import annotations

import json

from engine_alpha.core.paths import REPORTS
from engine_alpha.loop.live_bridge import run_health


def main():
    symbols = ["ETHUSDT", "BTCUSDT"]
    result = run_health(symbols)

    snapshot_path = REPORTS / "feeds_snapshot.json"
    with snapshot_path.open("w") as f:
        json.dump(result, f, indent=2)

    for exchange in ("binance", "bybit"):
        data = result.get(exchange, {})
        time_info = data.get("time", {})
        clock_skew = time_info.get("clock_skew_ms", "N/A")
        print(f"{exchange.title()} clock skew: {clock_skew} ms")
        symbols_info = data.get("symbols", {}).get("symbols", {})
        for symbol, info in symbols_info.items():
            status = "ok" if info.get("ok") else info.get("error", "fail")
            latency = info.get("latency_ms", "-")
            print(f"  {symbol}: {status} (latency={latency} ms)")
        account = data.get("account", {})
        if account.get("ok"):
            print(f"  Account: ok")
        else:
            print(f"  Account: {account.get('reason', account.get('error', 'not available'))}")

    print(f"Snapshot written to {snapshot_path}")


if __name__ == "__main__":
    main()
