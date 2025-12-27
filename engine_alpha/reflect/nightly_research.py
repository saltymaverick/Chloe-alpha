"""
Nightly research orchestration - Hybrid Self-Learning Mode (Multi-Asset)

Orchestrates the full research pipeline:
1. Build trade outcomes (per symbol)
2. Build hybrid dataset (per symbol)
3. Run weighted analyzer (per symbol, with data sufficiency checks)
4. Run weighted GPT tuner with guardrails (per symbol)

Supports multi-asset: loops over enabled assets from asset_registry.json.
"""

from pathlib import Path
import sys
import logging
from typing import List, Optional

from engine_alpha.reflect.trade_outcome_builder import build_trade_outcomes
from engine_alpha.reflect.research_dataset_builder import build_hybrid_research_dataset
from engine_alpha.metrics.scorecard_builder import (
    build_asset_scorecards,
    build_strategy_scorecards,
)
from engine_alpha.metrics.drift_monitor import build_regime_drift_report
from engine_alpha.swarm.swarm_redflag import aggregate_red_flags
from engine_alpha.reflect.meta_strategy_review import run_meta_strategy_review
from engine_alpha.overseer.quant_overseer import build_overseer_report
from engine_alpha.overseer.staleness_analyst import build_staleness_report
from engine_alpha.overseer.asset_scoring import build_asset_scores
from engine_alpha.overseer.market_state_summarizer import summarize_market_state
from engine_alpha.reflect.activity_reflection import run_activity_reflection
from engine_alpha.reflect.activity_meta_reflection import run_meta_reflection
from engine_alpha.reflect.signal_gate_reflection import run_signal_gate_reflection

ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))
REPORTS_DIR = ROOT_DIR / "reports"
RESEARCH_DIR = REPORTS_DIR / "research"
SCORECARD_DIR = REPORTS_DIR / "scorecards"
SCORECARD_DIR.mkdir(parents=True, exist_ok=True)

# Import weighted analyzer and tuner
try:
    from engine_alpha.tools.weighted_analyzer import run_analyzer
except ImportError:
    run_analyzer = None

try:
    from engine_alpha.tools.weighted_tuner import run_gpt_tuner_for_symbol
except ImportError:
    run_gpt_tuner_for_symbol = None

# Import asset registry
try:
    from engine_alpha.config.assets import get_enabled_assets, get_asset
except ImportError:
    get_enabled_assets = None
    get_asset = None

logger = logging.getLogger(__name__)

# Data sufficiency thresholds
MIN_CANDLES_FOR_ANALYSIS = 200  # Minimum candles needed to run analyzer (matches asset_audit threshold)
MIN_TRADES_FOR_TUNING = 10      # Minimum trades needed to tune thresholds


def _check_data_sufficiency(
    hybrid_path: Path,
    symbol: str,
    min_candles: int = MIN_CANDLES_FOR_ANALYSIS,
) -> tuple[bool, int]:
    """
    Check if dataset has enough data for analysis.
    
    Returns:
        (sufficient, num_rows)
    """
    if not hybrid_path.exists():
        return False, 0
    
    try:
        import pandas as pd
        df = pd.read_parquet(hybrid_path)
        num_rows = len(df)
        sufficient = num_rows >= min_candles
        return sufficient, num_rows
    except Exception as e:
        logger.warning(f"Failed to check data sufficiency for {symbol}: {e}")
        return False, 0


def _count_trades_for_symbol(symbol: str) -> int:
    """Count closed trades for a specific symbol."""
    try:
        import pandas as pd
        outcome_path = ROOT_DIR / "reports" / "research" / "trade_outcomes.jsonl"
        if not outcome_path.exists():
            return 0
        
        count = 0
        with outcome_path.open("r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    import json
                    rec = json.loads(line)
                    if rec.get("symbol") == symbol:
                        count += 1
                except Exception:
                    continue
        return count
    except Exception:
        return 0


def run_nightly_research_for_symbol(
    symbol: str,
    timeframe: str,
    static_dataset_path: Path = None,
    run_analysis: bool = True,
    run_tuning: bool = False,
) -> dict:
    """
    Run nightly research for a single symbol.
    
    Returns:
        dict with status info: {"symbol", "candles", "trades", "analyzer_ran", "tuner_ran", "skipped_reason"}
    """
    RESEARCH_DIR = ROOT_DIR / "reports" / "research"
    
    status = {
        "symbol": symbol,
        "candles": 0,
        "trades": 0,
        "analyzer_ran": False,
        "tuner_ran": False,
        "skipped_reason": None,
    }
    
    print(f"\n{'='*80}")
    print(f"NIGHTLY RESEARCH: {symbol} @ {timeframe}")
    print(f"{'='*80}")
    
    # Build trade outcomes (all symbols, but we'll filter by symbol later)
    print(f"\n📊 Building trade outcomes for {symbol}...")
    try:
        outcome_path = build_trade_outcomes()
        status["trades"] = _count_trades_for_symbol(symbol)
        print(f"  ✅ Trade outcomes at {outcome_path} ({status['trades']} trades for {symbol})")
    except Exception as e:
        print(f"  ⚠️  Trade outcome build failed: {e}")
        outcome_path = None
    
    # Update Glassnode metrics (if configured)
    print(f"\n🔗 Updating Glassnode metrics for {symbol}...")
    try:
        from engine_alpha.data.glassnode_fetcher import fetch_glassnode_metrics_for_symbol
        gn_df = fetch_glassnode_metrics_for_symbol(symbol, days_back=365)
        if not gn_df.empty:
            print(f"  ✅ Glassnode metrics updated ({len(gn_df.columns)-1} metrics, {len(gn_df)} rows)")
        else:
            print(f"  ℹ️  No Glassnode metrics available for {symbol} (not configured or fetch failed)")
    except Exception as e:
        print(f"  ⚠️  Glassnode fetch failed for {symbol}: {e}")
        # Non-fatal: continue without Glassnode data
    
    # Build hybrid dataset (symbol-aware)
    print(f"\n🧪 Building hybrid research dataset for {symbol}...")
    try:
        # Use per-symbol directory structure (matches asset_audit expectations)
        from engine_alpha.reflect.research_dataset_builder import _hybrid_path
        hybrid_path = _hybrid_path(symbol)
        hybrid_path, num_rows = build_hybrid_research_dataset(
            symbol=symbol,
            timeframe=timeframe,
            static_dataset_path=static_dataset_path,
            output_path=hybrid_path,  # Per-symbol output
        )
        
        # Check data sufficiency
        sufficient, num_rows_check = _check_data_sufficiency(hybrid_path, symbol)
        status["candles"] = num_rows_check if num_rows_check > 0 else num_rows
        
        if not sufficient:
            status["skipped_reason"] = f"Insufficient data: {num_rows} candles < {MIN_CANDLES_FOR_ANALYSIS} required"
            print(f"  ⚠️  {status['skipped_reason']}")
            print(f"  ℹ️  Dataset built but skipping analyzer/tuner until more data accumulates")
            return status
        
        print(f"  ✅ Hybrid dataset at {hybrid_path} ({num_rows} rows)")
    except Exception as e:
        print(f"  ❌ Hybrid dataset build failed: {e}")
        status["skipped_reason"] = f"Dataset build failed: {e}"
        import traceback
        traceback.print_exc()
        return status
    
    # Run analyzer (if sufficient data)
    if run_analysis and run_analyzer:
        print(f"\n📈 Running weighted multi-horizon analyzer for {symbol}...")
        try:
            from engine_alpha.tools.weighted_analyzer import run_analyzer_for_symbol
            analyzer_out = run_analyzer_for_symbol(symbol, hybrid_path, timeframe=timeframe)
            status["analyzer_ran"] = True
            status["analyzer_path"] = analyzer_out
            print(f"  ✅ Analyzer stats at {analyzer_out}")
        except Exception as e:
            print(f"  ⚠️  Analyzer failed: {e}")
            import traceback
            traceback.print_exc()
    
    # Run tuner (if sufficient trades)
    if run_tuning and run_gpt_tuner_for_symbol and status["analyzer_ran"]:
        if status["trades"] < MIN_TRADES_FOR_TUNING:
            print(f"\n  ⚠️  Skipping tuner: {status['trades']} trades < {MIN_TRADES_FOR_TUNING} required")
            status["skipped_reason"] = f"Insufficient trades: {status['trades']} < {MIN_TRADES_FOR_TUNING}"
        else:
            print(f"\n🧠 Running weighted GPT tuner for {symbol}...")
            try:
                analyzer_path = status.get("analyzer_path")
                if not analyzer_path:
                    analyzer_path = RESEARCH_DIR / symbol / "multi_horizon_stats.json"
                thr_path = run_gpt_tuner_for_symbol(
                    symbol=symbol,
                    stats_path=Path(analyzer_path),
                )
                status["tuner_ran"] = True
                print(f"  ✅ Thresholds updated at {thr_path}")
            except Exception as e:
                print(f"  ⚠️  GPT tuner failed: {e}")
                import traceback
                traceback.print_exc()
    
    return status


def run_nightly_research(
    symbol: str = None,
    timeframe: str = None,
    static_dataset_path: Path = None,
    run_analysis: bool = True,
    run_tuning: bool = False,
    multi_asset: bool = True,
):
    """
    Run the full nightly research pipeline.
    
    Args:
        symbol: Trading symbol (if None and multi_asset=True, loops over enabled assets)
        timeframe: Timeframe (if None, uses asset's base_timeframe)
        static_dataset_path: Path to base historical dataset (CSV or Parquet)
        run_analysis: Whether to run multi-horizon analyzer
        run_tuning: Whether to run GPT tuner (requires run_analysis=True)
        multi_asset: If True and symbol=None, loops over enabled assets from registry
    """
    print("=" * 80)
    print("NIGHTLY RESEARCH (HYBRID MODE - MULTI-ASSET)")
    print("=" * 80)
    
    # Determine which assets to process
    assets_to_process = []
    
    if symbol:
        # Single symbol mode
        sym = symbol.upper()
        asset_tf = timeframe
        if asset_tf is None and get_asset:
            cfg = get_asset(sym)
            if cfg:
                asset_tf = cfg.base_timeframe
        assets_to_process = [{"symbol": sym, "timeframe": asset_tf or "15m"}]
    elif multi_asset and get_enabled_assets:
        # Multi-asset mode: loop over enabled assets
        enabled = get_enabled_assets()
        if not enabled:
            print("\n⚠️  No enabled assets found in asset_registry.json")
            print("   Falling back to ETHUSDT @ 15m")
            assets_to_process = [{"symbol": "ETHUSDT", "timeframe": "15m"}]
        else:
            assets_to_process = [
                {"symbol": a.symbol, "timeframe": a.base_timeframe}
                for a in enabled
            ]
            print(f"\n📋 Processing {len(assets_to_process)} enabled asset(s):")
            for a in assets_to_process:
                print(f"   - {a['symbol']} @ {a['timeframe']}")
    else:
        # Fallback to ETHUSDT
        assets_to_process = [{"symbol": "ETHUSDT", "timeframe": "15m"}]
    
    enabled_symbols_for_reflection: List[str] = []
    # Process each asset
    results = []
    for asset in assets_to_process:
        sym = asset["symbol"]
        tf = asset["timeframe"]
        enabled_symbols_for_reflection.append(sym)
        
        # Try to find static dataset for this symbol
        static_path = static_dataset_path
        if static_path is None:
            # Look for merged CSV for this symbol
            merged_path = ROOT_DIR / "data" / "ohlcv" / f"{sym}_{tf}_merged.csv"
            if merged_path.exists():
                static_path = merged_path
        
        status = run_nightly_research_for_symbol(
            symbol=sym,
            timeframe=tf,
            static_dataset_path=static_path,
            run_analysis=run_analysis,
            run_tuning=run_tuning,
        )
        results.append(status)
        
        # Small delay between assets to avoid overwhelming system
        import time
        time.sleep(1)
    
    # Global steps (run once, not per symbol)
    print("\n" + "=" * 80)
    print("GLOBAL RESEARCH STEPS")
    print("=" * 80)
    
    # Build quant monitor tiles (aggregate across all symbols)
    print("\n📊 Building quant monitor tiles...")
    try:
        from engine_alpha.reports.quant_monitor import build_quant_monitor_tiles
        build_quant_monitor_tiles()
        print("  ✅ Quant monitor tiles updated")
    except Exception as e:
        print(f"  ⚠️  Quant monitor failed: {e}")
        import traceback
        traceback.print_exc()
    
    # SWARM research verifier
    print("\n🧪 SWARM research verifier...")
    try:
        from engine_alpha.swarm.swarm_research_verifier import verify_research_outputs
        verify_result = verify_research_outputs()
        if verify_result.analyzer_ok and verify_result.strengths_ok:
            print("  ✅ Research outputs verified")
        else:
            print(f"  ⚠️  Research verification issues: {verify_result.notes}")
    except Exception as e:
        print(f"  ⚠️  Research verifier failed: {e}")
        import traceback
        traceback.print_exc()
    
    # SWARM sentinel snapshot
    print("\n🛡️  SWARM sentinel snapshot...")
    try:
        from engine_alpha.swarm.swarm_sentinel import run_sentinel_checks
        sentinel_result = run_sentinel_checks()
        if sentinel_result.critical:
            print(f"  🚨 CRITICAL: {sentinel_result.warnings}")
        elif sentinel_result.warnings:
            print(f"  ⚠️  Warnings: {sentinel_result.warnings}")
        else:
            print("  ✅ Sentinel checks passed")
    except Exception as e:
        print(f"  ⚠️  Sentinel failed: {e}")
        import traceback
        traceback.print_exc()
    
    # Meta-strategy reflection (runs once, uses aggregate context)
    print("\n🧭 Meta-strategy reflection...")
    try:
        from engine_alpha.reflect.meta_strategy_reflection import run_meta_strategy_reflection
        meta_path = run_meta_strategy_reflection()
        print(f"  ✅ Meta-strategy reflection appended to {meta_path}")
    except Exception as e:
        print(f"  ⚠️  Meta-strategy reflection failed (non-fatal): {e}")
        import traceback
        traceback.print_exc()

    # Signal & gate reflection
    print("\n🩻 Signal & gate reflection...")
    if not enabled_symbols_for_reflection:
        enabled_symbols_for_reflection = ["ETHUSDT"]
    try:
        sg_result = run_signal_gate_reflection(enabled_symbols_for_reflection, use_gpt=True)
        log_path = RESEARCH_DIR / "signal_gate_reflections.jsonl"
        print(f"  ✅ Signal/gate reflection appended to {log_path}")
        preview = sg_result.get("explanation")
        if preview:
            print("  --- Reflection preview ---")
            print(preview[:400])
            if len(preview) > 400:
                print("  ... (truncated)")
    except Exception as e:
        print(f"  ⚠️  Signal/gate reflection failed (non-fatal): {e}")
        import traceback
        traceback.print_exc()

    # Performance scorecards
    print("\n📒 Building performance scorecards...")
    try:
        asset_scores_path = build_asset_scorecards(
            trades_path=REPORTS_DIR / "trades.jsonl",
            pf_path=REPORTS_DIR / "pf_local.json",
            output_path=SCORECARD_DIR / "asset_scorecards.json",
        )
        build_strategy_scorecards(
            trades_path=REPORTS_DIR / "trades.jsonl",
            output_path=SCORECARD_DIR / "strategy_scorecards.json",
        )
        print(f"  ✅ Scorecards updated at {asset_scores_path.parent}")
    except Exception as e:
        print(f"  ⚠️  Scorecard build failed: {e}")
        import traceback
        traceback.print_exc()

    # Regime drift monitor
    print("\n🌊 Regime drift monitor...")
    try:
        drift_path = build_regime_drift_report(
            stats_root=RESEARCH_DIR,
            history_root=RESEARCH_DIR / "history",
            output_path=RESEARCH_DIR / "regime_drift_report.json",
        )
        print(f"  ✅ Drift report at {drift_path}")
    except Exception as e:
        print(f"  ⚠️  Drift monitor failed: {e}")
        import traceback
        traceback.print_exc()

    # SWARM red-flag aggregation
    print("\n🚨 Aggregating SWARM red flags...")
    try:
        redflag_path = aggregate_red_flags(
            pf_path=REPORTS_DIR / "pf_local.json",
            asset_scorecards_path=SCORECARD_DIR / "asset_scorecards.json",
            drift_report_path=RESEARCH_DIR / "regime_drift_report.json",
            verifier_log_path=RESEARCH_DIR / "swarm_research_verifier.jsonl",
            output_path=RESEARCH_DIR / "swarm_red_flags.json",
        )
        print(f"  ✅ Red-flag snapshot updated at {redflag_path}")
    except Exception as e:
        print(f"  ⚠️  Red-flag aggregation failed: {e}")
        import traceback
        traceback.print_exc()

    # Meta-strategy self-critique
    print("\n🧠 Meta-strategy review...")
    try:
        review_path = run_meta_strategy_review(
            reflections_path=RESEARCH_DIR / "meta_strategy_reflections.jsonl",
            asset_scorecards_path=SCORECARD_DIR / "asset_scorecards.json",
            drift_report_path=RESEARCH_DIR / "regime_drift_report.json",
            output_path=RESEARCH_DIR / "meta_strategy_review.jsonl",
            trading_enablement_path=ROOT_DIR / "config" / "trading_enablement.json",
        )
        if review_path:
            print(f"  ✅ Meta-strategy review appended to {review_path}")
        else:
            print("  ℹ️  No reflections to review yet.")
    except Exception as e:
        print(f"  ⚠️  Meta-strategy review failed: {e}")
        import traceback
        traceback.print_exc()

    # Quant Overseer report
    print("\n🗂️  Quant Overseer report...")
    try:
        overseer_path = build_overseer_report()
        print(f"  ✅ Overseer report written to {overseer_path}")
    except Exception as e:
        print(f"  ⚠️  Overseer report failed: {e}")
        import traceback
        traceback.print_exc()

    # Staleness analyst snapshot
    print("\n🧊 Staleness analyst...")
    try:
        staleness = build_staleness_report()
        assets_count = len(staleness.get("assets", {}))
        print(f"  ✅ Staleness report updated ({assets_count} assets)")
    except Exception as e:
        print(f"  ⚠️  Staleness analyst failed: {e}")
        import traceback
        traceback.print_exc()

    # Asset scoring snapshot
    print("\n📊 Asset scoring...")
    try:
        scores = build_asset_scores()
        print(f"  ✅ Asset scores updated ({len(scores.get('assets', {}))} assets)")
    except Exception as e:
        print(f"  ⚠️  Asset scoring failed: {e}")
        import traceback
        traceback.print_exc()

    # Market state summary
    print("\n🌐 Market state summary...")
    try:
        market_report = summarize_market_state()
        print(f"  ✅ Market state snapshot updated ({len(market_report.get('assets', {}))} assets)")
    except Exception as e:
        print(f"  ⚠️  Market state summarizer failed: {e}")
        import traceback
        traceback.print_exc()

    # Activity reflection (GPT or fallback)
    print("\n🧠 Activity reflection...")
    try:
        reflection = run_activity_reflection()
        print(f"  ✅ Activity reflection appended ({reflection.get('ts', 'unknown')})")
    except Exception as e:
        print(f"  ⚠️  Activity reflection failed: {e}")
        import traceback
        traceback.print_exc()

    # Meta activity reflection
    print("\n🧠 Meta activity reflection...")
    try:
        meta_result = run_meta_reflection()
        print(f"  ✅ Meta reflection appended ({meta_result.get('ts', 'unknown')})")
    except Exception as e:
        print(f"  ⚠️  Meta activity reflection failed: {e}")
        import traceback
        traceback.print_exc()
    
    # Summary
    print("\n" + "=" * 80)
    print("✅ NIGHTLY RESEARCH COMPLETE")
    print("=" * 80)
    print("\n📊 Summary:")
    for r in results:
        status_icon = "✅" if r["analyzer_ran"] else "⏸️"
        print(f"  {status_icon} {r['symbol']}: {r['candles']} candles, {r['trades']} trades")
        if r["skipped_reason"]:
            print(f"     ⚠️  {r['skipped_reason']}")
        if r["tuner_ran"]:
            print(f"     🧠 Tuner ran successfully")


def run_nightly_research_for_all(
    static_dataset_root: Optional[Path] = None,
    run_analysis: bool = True,
    run_tuning: bool = False,
) -> None:
    """
    Loop over all enabled assets and run nightly research per symbol.
    """
    if not get_enabled_assets:
        print("⚠️  Asset registry not available, falling back to ETHUSDT")
        run_nightly_research(
            symbol="ETHUSDT",
            timeframe="1h",
            static_dataset_path=static_dataset_root,
            run_analysis=run_analysis,
            run_tuning=run_tuning,
            multi_asset=False,
        )
        return
    
    assets = get_enabled_assets()
    if not assets:
        print("⚠️  No enabled assets found in asset_registry.json")
        print("   Falling back to ETHUSDT @ 1h")
        run_nightly_research(
            symbol="ETHUSDT",
            timeframe="1h",
            static_dataset_path=static_dataset_root,
            run_analysis=run_analysis,
            run_tuning=run_tuning,
            multi_asset=False,
        )
        return
    
    print(f"\n📋 Processing {len(assets)} enabled asset(s):")
    for a in assets:
        print(f"   - {a.symbol} @ {a.base_timeframe}")
    
    for asset in assets:
        s = asset.symbol
        tf = asset.base_timeframe
        
        static_path = None
        if static_dataset_root is not None:
            # Look for per-symbol static dataset (try Parquet first, then CSV)
            # Parquet format: {SYMBOL}_{TIMEFRAME}.parquet (from CryptoDataDownload converter)
            static_path = static_dataset_root / f"{s}_{tf}.parquet"
            if not static_path.exists():
                static_path = static_dataset_root / f"{s.lower()}_{tf.lower()}.parquet"
            if not static_path.exists():
                # Fallback to CSV format: {SYMBOL}_{TIMEFRAME}_merged.csv
                static_path = static_dataset_root / f"{s}_{tf}_merged.csv"
            if not static_path.exists():
                static_path = static_dataset_root / f"{s.lower()}_{tf.lower()}_merged.csv"
            if not static_path.exists():
                static_path = None
        
        try:
            run_nightly_research(
                symbol=s,
                timeframe=tf,
                static_dataset_path=static_path,
                run_analysis=run_analysis,
                run_tuning=run_tuning,
                multi_asset=False,  # Already looping here
            )
        except Exception as e:
            print(f"  ⚠️  Error during nightly research for {s}: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    # Check for CryptoDataDownload Parquet files first, then fallback to CSV
    backtest_dir = ROOT_DIR / "data" / "research_backtest"
    ohlcv_dir = ROOT_DIR / "data" / "ohlcv"
    
    # Prefer research_backtest (CryptoDataDownload Parquet files)
    static_dataset_root = None
    if backtest_dir.exists() and any(backtest_dir.glob("*.parquet")):
        static_dataset_root = backtest_dir
        print(f"📁 Using static datasets from: {backtest_dir}")
    elif ohlcv_dir.exists():
        # Fallback to ohlcv directory (legacy CSV format)
        static_dataset_root = ohlcv_dir
        print(f"📁 Using static datasets from: {ohlcv_dir}")
    
    # Run for all enabled assets
    run_nightly_research_for_all(
        static_dataset_root=static_dataset_root,
        run_analysis=True,
        run_tuning=False,  # Set to True to enable GPT tuning
    )

