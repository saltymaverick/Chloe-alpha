#!/usr/bin/env python3
"""
Nightly research loop: analyze historical performance and tune thresholds.

This script:
1. Runs multi-horizon signal return analyzer over the full CSV
2. Optionally calls GPT threshold tuner to propose adjustments
3. Optionally applies new thresholds and restarts Chloe

Designed to be run via systemd timer (e.g., daily at 2 AM UTC).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))


def run_analyzer(
    csv_path: Path,
    symbol: str = "ETHUSDT",
    timeframe: str = "1h",
    horizons: list[int] = [1, 2, 4],
    window: int = 200,
    output_path: Path | None = None,
) -> Path:
    """Run signal return analyzer and return output path."""
    if output_path is None:
        timestamp = datetime.utcnow().strftime("%Y%m%d")
        output_path = repo_root / "reports" / "analysis" / f"eth_1h_multi_{timestamp}.json"
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    horizons_str = ",".join(map(str, horizons))
    
    cmd = [
        sys.executable,
        "-m",
        "tools.signal_return_analyzer",
        "--symbol",
        symbol,
        "--timeframe",
        timeframe,
        "--csv",
        str(csv_path),
        "--horizons",
        horizons_str,
        "--window",
        str(window),
        "--output",
        str(output_path),
    ]
    
    print(f"Running analyzer: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"❌ Analyzer failed:")
        print(result.stderr)
        sys.exit(1)
    
    print(f"✅ Analyzer complete: {output_path}")
    return output_path


def run_threshold_tuner(
    summary_path: Path,
    apply: bool = False,
    model: str = "gpt-4o",
) -> None:
    """Run GPT threshold tuner on analyzer summary."""
    cmd = [
        sys.executable,
        "-m",
        "tools.gpt_threshold_tuner",
        "--summary",
        str(summary_path),
        "--model",
        model,
    ]
    
    if apply:
        cmd.append("--apply")
    
    print(f"\nRunning threshold tuner: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=repo_root, capture_output=False)
    
    if result.returncode != 0:
        print(f"❌ Threshold tuner failed (exit code {result.returncode})")
        sys.exit(1)
    
    print("✅ Threshold tuner complete")


def restart_chloe() -> None:
    """Restart Chloe service to pick up new thresholds."""
    print("\nRestarting Chloe service...")
    result = subprocess.run(
        ["sudo", "systemctl", "restart", "chloe.service"],
        capture_output=True,
        text=True,
    )
    
    if result.returncode != 0:
        print(f"❌ Service restart failed:")
        print(result.stderr)
        sys.exit(1)
    
    print("✅ Chloe service restarted")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Nightly research: analyze historical performance and tune thresholds"
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,  # Will use research dataset if None
        help="Path to OHLCV CSV file (default: use hybrid research dataset)",
    )
    parser.add_argument(
        "--symbol",
        default="ETHUSDT",
        help="Trading symbol",
    )
    parser.add_argument(
        "--timeframe",
        default="1h",
        help="Timeframe",
    )
    parser.add_argument(
        "--horizons",
        default="1,2,4",
        help="Comma-separated list of horizons (e.g., '1,2,4')",
    )
    parser.add_argument(
        "--window",
        type=int,
        default=200,
        help="Signal window size",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output path for analyzer (default: reports/analysis/eth_1h_multi_YYYYMMDD.json)",
    )
    parser.add_argument(
        "--tune",
        action="store_true",
        help="Run GPT threshold tuner after analyzer",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply threshold adjustments (requires --tune)",
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="Restart Chloe service after tuning (requires --apply)",
    )
    parser.add_argument(
        "--model",
        default="gpt-4o",
        help="GPT model for threshold tuner",
    )
    args = parser.parse_args()
    
    if not args.csv.exists():
        print(f"❌ CSV file not found: {args.csv}")
        sys.exit(1)
    
    if args.apply and not args.tune:
        print("❌ --apply requires --tune")
        sys.exit(1)
    
    if args.restart and not args.apply:
        print("❌ --restart requires --apply")
        sys.exit(1)
    
    print("=" * 80)
    print("NIGHTLY RESEARCH LOOP (HYBRID MODE)")
    print("=" * 80)
    
    # Step 0: Build hybrid research dataset (if CSV not explicitly provided)
    csv_path = args.csv
    if csv_path is None:
        print("\n🔨 Building hybrid research dataset...")
        
        # Build research dataset (base CSV + live candles)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.build_research_dataset",
                "--base",
                str(repo_root / "data" / "ohlcv" / "ETHUSDT_1h_merged.csv"),
                "--live",
                str(repo_root / "data" / "live" / "ETHUSDT_1h.jsonl"),
                "--output",
                str(repo_root / "data" / "research" / "ETHUSDT_1h_research.csv"),
            ],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        
        if result.returncode != 0:
            print(f"⚠️  Research dataset build failed (non-fatal):")
            print(result.stderr)
            # Fall back to base CSV
            csv_path = repo_root / "data" / "ohlcv" / "ETHUSDT_1h_merged.csv"
            print(f"   Falling back to base CSV: {csv_path}")
        else:
            csv_path = repo_root / "data" / "research" / "ETHUSDT_1h_research.csv"
            print(f"✅ Research dataset ready: {csv_path}")
        
        # Build trade outcomes (optional, non-fatal)
        print("\n🔨 Building trade outcomes...")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.build_trade_outcomes",
                "--input",
                str(repo_root / "reports" / "trades.jsonl"),
                "--output",
                str(repo_root / "reports" / "live_learning" / "trades_compact.jsonl"),
            ],
            cwd=repo_root,
            capture_output=False,
        )  # Non-fatal if no trades yet
    
    if not csv_path.exists():
        print(f"❌ CSV file not found: {csv_path}")
        sys.exit(1)
    
    print(f"\nCSV: {csv_path}")
    print(f"Symbol: {args.symbol}")
    print(f"Timeframe: {args.timeframe}")
    print(f"Horizons: {args.horizons}")
    print(f"Window: {args.window}")
    print(f"Tune: {args.tune}")
    print(f"Apply: {args.apply}")
    print(f"Restart: {args.restart}")
    print("=" * 80)
    
    # Step 1: Run analyzer
    summary_path = run_analyzer(
        csv_path=csv_path,
        symbol=args.symbol,
        timeframe=args.timeframe,
        horizons=[int(h) for h in args.horizons.split(",")],
        window=args.window,
        output_path=args.output,
    )
    
    # Step 2: Optionally run threshold tuner
    if args.tune:
        run_threshold_tuner(
            summary_path=summary_path,
            apply=args.apply,
            model=args.model,
        )
    
    # Step 3: Optionally restart service
    if args.restart:
        restart_chloe()
    
    # Step 4: Optional meta-strategy reflection (low frequency, non-blocking)
    print("\n🧭 Meta-strategy reflection...")
    try:
        from engine_alpha.reflect.meta_strategy_reflection import run_meta_strategy_reflection
        meta_path = run_meta_strategy_reflection()
        print(f"  -> Meta-strategy reflection appended to {meta_path}")
    except Exception as e:
        print(f"  ⚠️  Meta-strategy reflection failed (non-fatal): {e}")
    
    print("\n" + "=" * 80)
    print("✅ NIGHTLY RESEARCH COMPLETE")
    print("=" * 80)
    print(f"\nSummary saved to: {summary_path}")
    if args.tune:
        print("Threshold tuning: ✅")
    if args.apply:
        print("Thresholds applied: ✅")
    if args.restart:
        print("Service restarted: ✅")


if __name__ == "__main__":
    main()

