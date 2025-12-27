# tools/dry_run_trade.py

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import argparse
import json

from engine_alpha.loop.execute_trade import gate_and_size_trade

ROOT_DIR = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT_DIR / "reports"
RESEARCH_DIR = REPORTS_DIR / "research"
CONFIG_DIR = ROOT_DIR / "config"


@dataclass
class DryRunSignal:
    symbol: str
    regime: str
    direction: int   # +1 long, -1 short
    side: str        # "long" or "short"
    confidence: float
    volatility_norm: float
    base_notional: float


def load_example_from_current_env() -> DryRunSignal:
    """
    Minimal example based on what you're currently seeing:
    trend_down / trend_up with conf ~0.67, dir=-1 (short).
    You can edit this or override via CLI flags.
    """
    return DryRunSignal(
        symbol="ETHUSDT",
        regime="trend_down",
        direction=-1,
        side="short",
        confidence=0.67,
        volatility_norm=0.5,   # middle-of-the-road vol
        base_notional=100.0,   # arbitrary test notional
    )


def main():
    parser = argparse.ArgumentParser(
        description="Chloe dry-run trade decision (no side effects).",
        epilog="""
Examples:
  # Default: trend_down short at 0.67 confidence
  python3 -m tools.dry_run_trade

  # Test high_vol long with high confidence
  python3 -m tools.dry_run_trade --regime high_vol --dir 1 --conf 0.9 --base 150

  # Test observation regime with different confidence
  python3 -m tools.dry_run_trade --regime trend_up --dir -1 --conf 0.65 --base 100

NOTE: This tool only tests gate_and_size_trade(). It does NOT check:
  - Regime enablement flags (regime_thresholds.json)
  - Entry threshold requirements
  - Position manager state
  - Live loop conditions

It answers: "Would the quant gate allow this trade, and at what size?"
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--symbol", default="ETHUSDT")
    parser.add_argument("--regime", default="trend_down")
    parser.add_argument("--dir", type=int, default=-1, help="+1 for long, -1 for short")
    parser.add_argument("--conf", type=float, default=0.67)
    parser.add_argument("--base", type=float, default=100.0)
    parser.add_argument("--vol", type=float, default=0.5)
    args = parser.parse_args()

    side = "long" if args.dir > 0 else "short"

    sig = DryRunSignal(
        symbol=args.symbol,
        regime=args.regime,
        direction=args.dir,
        side=side,
        confidence=args.conf,
        volatility_norm=args.vol,
        base_notional=args.base,
    )

    allow, notional, reason = gate_and_size_trade(
        symbol=sig.symbol,
        side=sig.side,
        regime=sig.regime,
        confidence=sig.confidence,
        base_notional=sig.base_notional,
        volatility_norm=sig.volatility_norm,
    )

    print("=== Chloe Dry-Run Trade Decision ===")
    print(f"Symbol:           {sig.symbol}")
    print(f"Regime:           {sig.regime}")
    print(f"Direction:        {sig.direction} ({sig.side})")
    print(f"Confidence:       {sig.confidence:.4f}")
    print(f"Volatility_norm:  {sig.volatility_norm:.3f}")
    print(f"Base notional:    {sig.base_notional:.4f}")
    print("---- Result ----")
    print(f"ALLOW_TRADE:      {allow}")
    print(f"Final notional:   {notional:.4f}")
    print(f"Gate reason:      {reason}")
    print("\nNOTE: This is a pure dry run. No orders placed, no logs written, no learning/calibration touched.")


if __name__ == "__main__":
    main()

