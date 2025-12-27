"""
Recovery V2 Score Smoke Test (Phase 5H.3)
------------------------------------------

Unit smoke test for recovery_v2_score computation.
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Any

import sys
from pathlib import Path

# Add tools to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.run_recovery_v2_score import (
    _read_trades_jsonl,
    _filter_trades_by_window,
    _compute_metrics,
    compute_recovery_v2_score,
)


def test_pf_calculation() -> bool:
    """Test PF calculation with known inputs."""
    # Create test trades
    now = datetime.now(timezone.utc)
    
    test_trades = [
        {
            "ts": (now - timedelta(hours=1)).isoformat(),
            "action": "close",
            "symbol": "BTCUSDT",
            "pnl_usd": 0.10,
            "pnl_pct": 0.20,
        },
        {
            "ts": (now - timedelta(hours=2)).isoformat(),
            "action": "close",
            "symbol": "ETHUSDT",
            "pnl_usd": -0.05,
            "pnl_pct": -0.10,
        },
        {
            "ts": (now - timedelta(hours=3)).isoformat(),
            "action": "close",
            "symbol": "SOLUSDT",
            "pnl_usd": 0.15,
            "pnl_pct": 0.30,
        },
        {
            "ts": (now - timedelta(hours=4)).isoformat(),
            "action": "open",  # Should be ignored
            "symbol": "AVAXUSDT",
            "pnl_usd": 0.0,
            "pnl_pct": 0.0,
        },
    ]
    
    metrics = _compute_metrics(test_trades)
    
    # Verify expected values
    assert metrics["trades"] == 3, f"Expected 3 trades, got {metrics['trades']}"
    assert metrics["gross_profit_usd"] == 0.25, f"Expected 0.25, got {metrics['gross_profit_usd']}"
    assert metrics["gross_loss_usd"] == 0.05, f"Expected 0.05, got {metrics['gross_loss_usd']}"
    
    expected_pf = 0.25 / 0.05
    assert abs(metrics["pf"] - expected_pf) < 0.001, f"Expected PF {expected_pf}, got {metrics['pf']}"
    
    expected_win_rate = 2 / 3
    assert abs(metrics["win_rate"] - expected_win_rate) < 0.001, f"Expected win rate {expected_win_rate}, got {metrics['win_rate']}"
    
    expected_expectancy = (0.20 + (-0.10) + 0.30) / 3
    assert abs(metrics["expectancy_pct"] - expected_expectancy) < 0.001, f"Expected expectancy {expected_expectancy}, got {metrics['expectancy_pct']}"
    
    # Verify top symbols
    assert len(metrics["top_symbols_by_trades"]) > 0, "Expected top symbols by trades"
    assert len(metrics["top_symbols_by_expectancy"]) > 0, "Expected top symbols by expectancy"
    
    return True


def test_zero_loss_pf() -> bool:
    """Test PF calculation with zero losses (should return inf)."""
    now = datetime.now(timezone.utc)
    
    test_trades = [
        {
            "ts": (now - timedelta(hours=1)).isoformat(),
            "action": "close",
            "symbol": "BTCUSDT",
            "pnl_usd": 0.10,
            "pnl_pct": 0.20,
        },
        {
            "ts": (now - timedelta(hours=2)).isoformat(),
            "action": "close",
            "symbol": "ETHUSDT",
            "pnl_usd": 0.05,
            "pnl_pct": 0.10,
        },
    ]
    
    metrics = _compute_metrics(test_trades)
    
    assert metrics["pf"] == float("inf"), f"Expected inf PF for zero losses, got {metrics['pf']}"
    assert metrics["gross_loss_usd"] == 0.0, f"Expected zero loss, got {metrics['gross_loss_usd']}"
    
    return True


def test_empty_trades() -> bool:
    """Test metrics computation with empty trade list."""
    metrics = _compute_metrics([])
    
    assert metrics["trades"] == 0, "Expected 0 trades"
    assert metrics["pf"] == 0.0, "Expected 0.0 PF"
    assert metrics["win_rate"] == 0.0, "Expected 0.0 win rate"
    
    return True


def test_window_filtering() -> bool:
    """Test window filtering logic."""
    now = datetime.now(timezone.utc)
    
    test_trades = [
        {
            "ts": (now - timedelta(hours=12)).isoformat(),  # Within 24h
            "action": "close",
            "symbol": "BTCUSDT",
            "pnl_usd": 0.10,
            "pnl_pct": 0.20,
        },
        {
            "ts": (now - timedelta(hours=25)).isoformat(),  # Outside 24h
            "action": "close",
            "symbol": "ETHUSDT",
            "pnl_usd": -0.05,
            "pnl_pct": -0.10,
        },
        {
            "ts": (now - timedelta(hours=6)).isoformat(),  # Within 24h
            "action": "close",
            "symbol": "SOLUSDT",
            "pnl_usd": 0.15,
            "pnl_pct": 0.30,
        },
    ]
    
    filtered = _filter_trades_by_window(test_trades, 24)
    
    assert len(filtered) == 2, f"Expected 2 trades in 24h window, got {len(filtered)}"
    assert filtered[0]["symbol"] == "BTCUSDT" or filtered[0]["symbol"] == "SOLUSDT", "Expected BTC or SOL"
    
    return True


def test_jsonl_reading() -> bool:
    """Test JSONL file reading."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir) / "test_trades.jsonl"
        
        # Write test data
        test_trades = [
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "action": "close",
                "symbol": "BTCUSDT",
                "pnl_usd": 0.10,
                "pnl_pct": 0.20,
            },
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "action": "open",
                "symbol": "ETHUSDT",
                "pnl_usd": 0.0,
                "pnl_pct": 0.0,
            },
        ]
        
        with tmp_path.open("w", encoding="utf-8") as f:
            for trade in test_trades:
                f.write(json.dumps(trade) + "\n")
        
        # Read back
        read_trades = _read_trades_jsonl(tmp_path)
        
        assert len(read_trades) == 2, f"Expected 2 trades, got {len(read_trades)}"
        assert read_trades[0]["symbol"] == "BTCUSDT", "Expected BTCUSDT"
        assert read_trades[1]["symbol"] == "ETHUSDT", "Expected ETHUSDT"
    
    return True


def main() -> int:
    """Run all smoke tests."""
    print("Recovery V2 Score Smoke Test (Phase 5H.3)")
    print("=" * 70)
    print()
    
    tests = [
        ("PF Calculation", test_pf_calculation),
        ("Zero Loss PF", test_zero_loss_pf),
        ("Empty Trades", test_empty_trades),
        ("Window Filtering", test_window_filtering),
        ("JSONL Reading", test_jsonl_reading),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        try:
            result = test_func()
            if result:
                print(f"✅ {name}: PASSED")
                passed += 1
            else:
                print(f"❌ {name}: FAILED")
                failed += 1
        except AssertionError as e:
            print(f"❌ {name}: FAILED - {e}")
            failed += 1
        except Exception as e:
            print(f"❌ {name}: ERROR - {e}")
            failed += 1
    
    print()
    print("=" * 70)
    print(f"Results: {passed} passed, {failed} failed")
    print()
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())

