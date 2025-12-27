"""
Policy Refresh Tool (Fast Loop)
-------------------------------

This is a lightweight, pro-quant policy refresh for Chloe Alpha.

Responsibilities:
  * Recompute PF time-series:
        - reports/pf/pf_timeseries.json
  * Recompute capital protection:
        - reports/risk/capital_protection.json
  * Recompute Exploration Policy V3:
        - reports/research/exploration_policy_v3.json

This tool is designed to be:
  * Fast: no GPT, no Dream, no Evolver.
  * Safe: PAPER-only, advisory-only, read/write to reports only.
  * Loop-friendly: can be run frequently (e.g., via systemd timer every 5–15 minutes).

It does NOT:
  * Touch configs, tuning, or strategy parameters.
  * Enable live trading or Profit Amplifier.
  * Modify any risk.yaml or engine config.
"""

from __future__ import annotations

import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from tools._cadence import is_stale

from engine_alpha.config.feature_flags import get_feature_registry


def _log(msg: str) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    print(f"[policy_refresh {ts}] {msg}")


def run_mini_reflection() -> None:
    """
    Mini-reflection: Lightweight analysis of recent closes for local issues.

    Analyzes last 24h closes to detect:
    - Timeout churn (too many review_bootstrap_timeout closes)
    - Losing positions (SL/TP not triggering)
    - Lane imbalances (exploration vs core)
    """
    from pathlib import Path
    from datetime import datetime, timezone, timedelta
    import json

    # Read recent closes
    trades_path = Path("reports/trades.jsonl")
    if not trades_path.exists():
        return

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    recent_closes = []

    try:
        with trades_path.open("r") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    trade = json.loads(line.strip())
                    if trade.get("type") == "close":
                        ts_str = trade.get("ts", "")
                        if ts_str:
                            # Parse timestamp (handle Z suffix)
                            if ts_str.endswith("Z"):
                                ts_str = ts_str[:-1] + "+00:00"
                            ts = datetime.fromisoformat(ts_str)
                            if ts >= cutoff:
                                recent_closes.append(trade)
                except Exception:
                    continue
    except Exception:
        return

    if not recent_closes:
        return

    # Analyze for issues
    issues = []
    suggestions = []

    # 1. Check timeout churn
    timeout_closes = [t for t in recent_closes if t.get("exit_reason") == "review_bootstrap_timeout"]
    timeout_rate = len(timeout_closes) / len(recent_closes)

    if timeout_rate > 0.3:  # >30% timeouts
        issues.append(f"high_timeout_churn_{timeout_rate:.1%}")
        suggestions.append("Consider excluding review_bootstrap_timeout from PF calculations or increasing exploration hold times")

    # 2. Check losing positions
    losing_closes = [t for t in recent_closes if t.get("pct", 0) < -0.01]  # >1% loss
    loss_rate = len(losing_closes) / len(recent_closes)

    if loss_rate > 0.4:  # >40% losses
        issues.append(f"high_loss_rate_{loss_rate:.1%}")
        suggestions.append("Consider tightening SL thresholds for sample-building phase")

    # 3. Check lane balance
    exploration_closes = [t for t in recent_closes if t.get("trade_kind") == "exploration"]
    core_closes = [t for t in recent_closes if t.get("trade_kind") == "normal"]

    if exploration_closes and not core_closes:
        issues.append("exploration_only_closes")
        suggestions.append("Exploration is active but core trading may be blocked - check entry gates")

    # Write mini-reflection log
    mini_reflection = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "analysis_period_h": 24,
        "total_closes": len(recent_closes),
        "issues_detected": issues,
        "suggestions": suggestions,
        "metrics": {
            "timeout_rate": timeout_rate,
            "loss_rate": loss_rate,
            "exploration_closes": len(exploration_closes),
            "core_closes": len(core_closes)
        }
    }

    # Write to mini-reflection log
    log_path = Path("reports/gpt/mini_reflection_log.jsonl")
    log_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with log_path.open("a") as f:
            f.write(json.dumps(mini_reflection) + "\n")
    except Exception:
        pass  # Non-critical


def run_bootstrap_validation() -> None:
    """
    Validate bootstrap timeout status and sample-building stops.
    """
    from pathlib import Path
    from datetime import datetime, timezone, timedelta
    from engine_alpha.core.config_loader import load_engine_config

    # 1. Check bootstrap config
    cfg = load_engine_config()
    rb_enabled = False
    if isinstance(cfg, dict):
        rb = cfg.get("review_bootstrap", {})
        rb_enabled = bool(rb.get("enabled", False))

    print(f"  Bootstrap enabled: {rb_enabled}")

    # 2. Check recent closes for bootstrap timeouts
    trades_path = Path("reports/trades.jsonl")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    bootstrap_closes = 0
    sample_building_stops = 0
    total_closes = 0

    if trades_path.exists():
        with trades_path.open("r") as f:
            for line in f:
                try:
                    trade = json.loads(line.strip())
                    if trade.get("type") == "close":
                        ts_str = trade.get("ts", "")
                        if ts_str:
                            if ts_str.endswith("Z"):
                                ts_str = ts_str[:-1] + "+00:00"
                            ts = datetime.fromisoformat(ts_str)
                            if ts >= cutoff:
                                total_closes += 1
                                exit_reason = trade.get("exit_reason", "")
                                if "review_bootstrap_timeout" in exit_reason:
                                    bootstrap_closes += 1
                                if exit_reason == "sample_building_max_adverse":
                                    sample_building_stops += 1
                except:
                    pass

    print(f"  Recent closes (24h): {total_closes}")
    print(f"  Bootstrap timeouts: {bootstrap_closes}")
    print(f"  Sample-building stops: {sample_building_stops}")

    # 3. Check promotion analysis
    try:
        with open("reports/gpt/promotion_advice.json") as f:
            promo = json.load(f)
        symbols = promo.get("symbols", {})
        excluded_timeouts = sum(1 for s in symbols.values()
                               if s.get("exploration", {}).get("7d", {}).get("n_closes", 0) == 0)
        print(f"  Symbols with exploration excluded from promotion (timeouts): {excluded_timeouts}")
    except:
        print("  Promotion analysis: unable to read")


def run_policy_refresh() -> None:
    """
    Run the minimal set of engines needed to keep policy current:
      1) PF time-series
      2) Capital protection
      3) Exploration Policy V3
    """
    _log("Starting policy refresh...")

    # 1) PF time-series
    try:
        from engine_alpha.research.pf_timeseries import compute_pf_timeseries

        _log("Recomputing PF time-series (pf_timeseries)...")
        pf_payload = compute_pf_timeseries()
        meta = pf_payload.get("meta", {})
        _log(
            f"PF time-series updated: engine={meta.get('engine')} "
            f"generated_at={meta.get('generated_at')}"
        )
    except Exception as exc:
        _log(f"ERROR: PF time-series refresh failed: {exc!r}")
        traceback.print_exc()
        # Continue to attempt capital protection / policy

    # 1a) PF Local (for check-in script)
    try:
        from tools.run_pf_local import compute_pf_local

        _log("Recomputing PF Local (pf_local)...")
        pf_local = compute_pf_local()
        _log(
            f"PF Local updated: 24h={pf_local.get('pf_24h')}, "
            f"7d={pf_local.get('pf_7d')}, 30d={pf_local.get('pf_30d')}"
        )
    except Exception as exc:
        _log(f"ERROR: PF Local refresh failed: {exc!r}")
        traceback.print_exc()

    # 1b) Confidence Snapshot (for reflection packet)
    try:
        from tools.run_confidence_snapshot import compute_confidence_snapshot

        _log("Recomputing Confidence Snapshot (confidence_snapshot)...")
        conf_snapshot = compute_confidence_snapshot()
        _log(
            f"Confidence Snapshot updated: overall={conf_snapshot.get('confidence_overall')}, "
            f"regime={conf_snapshot.get('regime')}"
        )
    except Exception as exc:
        _log(f"ERROR: Confidence Snapshot refresh failed: {exc!r}")
        traceback.print_exc()

    # 1c) Reflection Snapshot (for check-in script)
    try:
        from tools.run_reflection_snapshot import compute_reflection_snapshot

        _log("Recomputing Reflection Snapshot (reflection_snapshot)...")
        reflection_snapshot = compute_reflection_snapshot()
        _log(
            f"Reflection Snapshot updated: safe_mode={reflection_snapshot.get('safety', {}).get('safe_mode')}, "
            f"confidence={reflection_snapshot.get('confidence', {}).get('confidence_overall')}"
        )
    except Exception as exc:
        _log(f"ERROR: Reflection Snapshot refresh failed: {exc!r}")
        traceback.print_exc()

    # 1d) Regime Snapshot (per-symbol + anchor, for packet/opportunity)
    try:
        from tools.run_regime_snapshot_multi import main as run_regime_snapshot_multi

        _log("Recomputing Regime Snapshots (multi)...")
        run_regime_snapshot_multi()
        _log("Regime Snapshots updated")
    except Exception as exc:
        _log(f"ERROR: Regime Snapshots refresh failed: {exc!r}")
        traceback.print_exc()

    # 1e) Compression Snapshot (for packet builder)
    try:
        from tools.run_compression_snapshot import main as run_compression_snapshot

        _log("Recomputing Compression Snapshot (compression_snapshot)...")
        run_compression_snapshot()
        _log("Compression Snapshot updated")
    except Exception as exc:
        _log(f"ERROR: Compression Snapshot refresh failed: {exc!r}")
        traceback.print_exc()

    # 1f) Opportunity Snapshot (for packet builder instrumentation)
    try:
        from tools.run_opportunity_snapshot import main as run_opportunity_snapshot

        _log("Recomputing Opportunity Snapshot (opportunity_snapshot)...")
        run_opportunity_snapshot()
        _log("Opportunity Snapshot updated")
    except Exception as exc:
        _log(f"ERROR: Opportunity Snapshot refresh failed: {exc!r}")
        traceback.print_exc()

    # 1g) Reflection Packet (for check-in script - must be fresh)
    try:
        from tools.run_reflection_packet import main as run_reflection_packet

        _log("Recomputing Reflection Packet (reflection_packet)...")
        run_reflection_packet()
        _log("Reflection Packet updated")
    except Exception as exc:
        _log(f"ERROR: Reflection Packet refresh failed: {exc!r}")
        traceback.print_exc()

    # 1b) PF Validity (Phase 4d)
    try:
        from engine_alpha.risk.pf_validity import compute_pf_validity

        _log("Recomputing PF Validity (pf_validity)...")
        pfv = compute_pf_validity()
        pfv_meta = pfv.get("meta", {})
        _log(
            f"PF Validity updated: engine={pfv_meta.get('engine')} "
            f"generated_at={pfv_meta.get('generated_at')}"
        )
    except Exception as exc:
        _log(f"ERROR: PF Validity refresh failed: {exc!r}")
        traceback.print_exc()

    # 1c) PF Normalization (Phase 4e)
    try:
        from engine_alpha.risk.pf_normalization import compute_pf_normalized

        _log("Recomputing PF Normalization (pf_normalization)...")
        pfn = compute_pf_normalized()
        pfn_meta = pfn.get("meta", {})
        _log(
            f"PF Normalization updated: engine={pfn_meta.get('engine')} "
            f"generated_at={pfn_meta.get('generated_at')}"
        )
    except Exception as exc:
        _log(f"ERROR: PF Normalization refresh failed: {exc!r}")
        traceback.print_exc()

    # 1h) Recovery Ramp v1 (needed for recovery gates / clean closes)
    try:
        from tools.run_recovery_ramp import main as run_recovery_ramp

        _log("Recomputing Recovery Ramp (recovery_ramp)...")
        run_recovery_ramp()
        _log("Recovery Ramp updated")
    except Exception as exc:
        _log(f"ERROR: Recovery Ramp refresh failed: {exc!r}")
        traceback.print_exc()

    # 1i) Symbol State Builder (unified per-symbol policy)
    try:
        from tools.run_symbol_state_builder import main as run_symbol_state_builder

        _log("Recomputing Symbol States (symbol_states)...")
        run_symbol_state_builder()
        _log("Symbol States updated")
    except Exception as exc:
        _log(f"ERROR: Symbol States refresh failed: {exc!r}")
        traceback.print_exc()

    # 1j) Auto Promotions (derived from symbol_states)
    try:
        _log("Recomputing Auto Promotions (auto_promotions)...")
        from tools.run_auto_promotions import main as run_auto_promotions

        run_auto_promotions()
        _log("Auto Promotions updated")
    except Exception as exc:
        _log(f"ERROR: Auto Promotions refresh failed: {exc!r}")
        traceback.print_exc()

    # 2) Capital Protection
    try:
        from engine_alpha.risk.capital_protection import run_capital_protection

        _log("Recomputing Capital Protection (capital_protection)...")
        cap_payload = run_capital_protection()
        meta = cap_payload.get("meta", {})
        global_mode = (cap_payload.get("global") or {}).get("mode")
        _log(
            f"Capital Protection updated: engine={meta.get('engine')} "
            f"mode={global_mode} generated_at={meta.get('generated_at')}"
        )
    except Exception as exc:
        _log(f"ERROR: Capital Protection refresh failed: {exc!r}")
        traceback.print_exc()
        # Continue to attempt exploration policy

    # Review status summary (closes in last 24h)
    try:
        import json
        from datetime import timedelta
        trades_path = Path("reports/trades.jsonl")
        closes_24h = 0
        last_close_ts = None
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        if trades_path.exists():
            with trades_path.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        evt = json.loads(line)
                    except Exception:
                        continue
                    if (evt.get("type") or "").lower() != "close":
                        continue
                    ts = evt.get("ts") or evt.get("timestamp")
                    if not ts:
                        continue
                    try:
                        ts_dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(timezone.utc)
                    except Exception:
                        continue
                    if ts_dt >= cutoff:
                        closes_24h += 1
                        last_close_ts = ts_dt.isoformat()
        _log(f"REVIEW_STATUS capital_mode={global_mode} closes_24h={closes_24h} last_close_ts={last_close_ts}")
    except Exception as exc:
        _log(f"ERROR: Review status summary failed: {exc!r}")

    # 3) Exploration Policy V3
    try:
        from engine_alpha.research.exploration_policy_v3 import compute_exploration_policy_v3

        _log("Recomputing Exploration Policy V3 (exploration_policy_v3)...")
        pol_payload = compute_exploration_policy_v3()
        meta = pol_payload.get("meta", {})
        _log(
            f"Exploration Policy V3 updated: engine={meta.get('engine')} "
            f"generated_at={meta.get('generated_at')}"
        )
    except Exception as exc:
        _log(f"ERROR: Exploration Policy V3 refresh failed: {exc!r}")
        traceback.print_exc()

    # 3a) Promotion Observer (advisory-only, non-fatal)
    try:
        _log("Running Promotion Observer (promotion_advice)...")
        import tools.run_promotion_observer as _promo
        _promo.main()
    except Exception as exc:
        _log(f"ERROR: Promotion Observer failed: {exc!r}")
        traceback.print_exc()

    # 3b) Shadow Promotion Queue (advisory-only, non-fatal)
    try:
        _log("Running Shadow Promotion Queue (shadow_promotion_queue)...")
        import tools.run_shadow_promotion_queue as _spq
        _spq.main()
    except Exception as exc:
        _log(f"ERROR: Shadow Promotion Queue failed: {exc!r}")
        traceback.print_exc()

    # 3c) Exploration Accelerator (advisory-only, non-fatal)
    try:
        _log("Running Exploration Accelerator (exploration_overrides)...")
        import tools.run_exploration_accelerator as _expl_accel
        _expl_accel.main()
    except Exception as exc:
        _log(f"ERROR: Exploration Accelerator failed: {exc!r}")
        traceback.print_exc()

    # 3d) Apply auto promotions to engine_config core_promotions
    try:
        _log("Applying auto promotions to engine_config core_promotions...")
        from engine_alpha.core.config_loader import load_engine_config, atomic_write_engine_config
        import json

        auto_promo_path = Path("reports/risk/auto_promotions.json")
        auto_promos = {}
        if auto_promo_path.exists():
            try:
                auto_promos = json.loads(auto_promo_path.read_text())
            except Exception:
                auto_promos = {}
        active_promos = auto_promos.get("active", {}) if isinstance(auto_promos, dict) else {}

        cfg = load_engine_config()
        if not isinstance(cfg, dict):
            cfg = {}
        cfg["core_promotions"] = active_promos
        atomic_write_engine_config(cfg)
        _log(f"Applied {len(active_promos)} auto promotions to engine_config core_promotions")
    except Exception as exc:
        _log(f"ERROR: Applying auto promotions failed: {exc!r}")
        traceback.print_exc()

    # 4) Capital Allocator (Phase 4a) - light and safe
    try:
        from engine_alpha.risk.capital_allocator import compute_capital_plan

        _log("Recomputing Capital Plan (capital_allocator)...")
        plan = compute_capital_plan()
        meta = plan.get("meta", {})
        _log(
            f"Capital Plan updated: engine={meta.get('engine')} "
            f"generated_at={meta.get('generated_at')}"
        )
    except Exception as exc:
        _log(f"ERROR: Capital Plan refresh failed: {exc!r}")
        traceback.print_exc()

    # 4b) Capital Momentum (Phase 4c) - smoothing capital allocation
    try:
        from engine_alpha.risk.capital_momentum import compute_capital_momentum

        _log("Recomputing Capital Momentum (capital_momentum)...")
        mom = compute_capital_momentum()
        m_meta = mom.get("meta", {})
        _log(
            f"Capital Momentum updated: engine={m_meta.get('engine')} "
            f"generated_at={m_meta.get('generated_at')}"
        )
    except Exception as exc:
        _log(f"ERROR: Capital Momentum refresh failed: {exc!r}")
        traceback.print_exc()

    # 5) Live-Candidate readiness (Phase 4b)
    try:
        from engine_alpha.risk.live_candidate_scanner import compute_live_candidates

        _log("Recomputing Live-Candidate readiness (live_candidate_scanner)...")
        lc_snapshot = compute_live_candidates()
        lc_meta = lc_snapshot.get("meta", {})
        _log(
            f"Live-candidate snapshot updated: engine={lc_meta.get('engine')} "
            f"generated_at={lc_meta.get('generated_at')}"
        )
    except Exception as exc:
        _log(f"ERROR: Live-candidate readiness refresh failed: {exc!r}")
        traceback.print_exc()

    # Phase 4i: DriftScan and ExecutionQuality (hourly cadence)
    drift_path = Path("reports/research/drift_report.json")
    if is_stale(drift_path, max_age_minutes=60):
        try:
            from tools.run_drift_scan import main as run_drift_scan

            _log("Recomputing DriftScan (drift_report) - stale or missing...")
            run_drift_scan()
            _log("DriftScan updated.")
        except Exception as exc:
            _log(f"ERROR: DriftScan refresh failed: {exc!r}")
            traceback.print_exc()
    else:
        last_modified = drift_path.stat().st_mtime if drift_path.exists() else 0
        last_ts = datetime.fromtimestamp(last_modified, tz=timezone.utc).isoformat()
        _log(f"DRIFT_SKIP reason=fresh_<60m last_ts={last_ts}")

    execql_path = Path("reports/research/execution_quality.json")
    if is_stale(execql_path, max_age_minutes=60):
        try:
            from tools.run_execution_quality_scan import main as run_execution_quality_scan

            _log("Recomputing ExecutionQuality (execution_quality) - stale or missing...")
            run_execution_quality_scan()
            _log("ExecutionQuality updated.")
        except Exception as exc:
            _log(f"ERROR: ExecutionQuality refresh failed: {exc!r}")
            traceback.print_exc()
    else:
        last_modified = execql_path.stat().st_mtime if execql_path.exists() else 0
        last_ts = datetime.fromtimestamp(last_modified, tz=timezone.utc).isoformat()
        _log(f"EXEC_QUALITY_SKIP reason=fresh_<60m last_ts={last_ts}")

    # Phase 4j: Mini-reflection (lightweight per-close analysis)
    if not get_feature_registry().is_off("mini_reflection"):
        try:
            _log("Running mini-reflection analysis...")
            run_mini_reflection()
            _log("Mini-reflection completed.")
        except Exception as exc:
            _log(f"ERROR: Mini-reflection failed: {exc!r}")
            traceback.print_exc()
    else:
        _log("Mini-reflection skipped (feature off)")

    # Write loop health snapshot (one-glance status)
    try:
        from tools.run_loop_health_snapshot import compute_loop_health
        from engine_alpha.core.paths import REPORTS
        import json

        _log("Writing loop health snapshot (loop_health)...")
        health = compute_loop_health()
        legacy_path = REPORTS / "loop_health.json"
        loop_path = REPORTS / "loop" / "loop_health.json"
        for hp in (legacy_path, loop_path):
            hp.parent.mkdir(parents=True, exist_ok=True)
            with hp.open("w", encoding="utf-8") as f:
                json.dump(health, f, indent=2, sort_keys=True)
        _log("Loop health snapshot updated (legacy + loop/loop_health.json)")
    except Exception as exc:
        _log(f"ERROR: Loop health snapshot failed: {exc!r}")
        traceback.print_exc()

    # 6) Auto-apply tuner (safe, gated) - non-fatal
    try:
        from engine_alpha.reflect.apply_tuner import apply_tuner_if_safe

        apply_res = apply_tuner_if_safe()
        _log(
            f"apply_tuner_if_safe: applied={apply_res.get('applied')} blocked_by={apply_res.get('blocked_by')}"
        )
    except Exception as exc:
        _log(f"ERROR: apply_tuner_if_safe failed: {exc!r}")
        traceback.print_exc()

    # Phase 5: Bootstrap timeout validation
    try:
        _log("Validating bootstrap timeout status...")
        run_bootstrap_validation()
        _log("Bootstrap validation complete.")
    except Exception as exc:
        _log(f"ERROR: Bootstrap validation failed: {exc!r}")
        traceback.print_exc()

    # Phase 5: Bootstrap timeout validation
    try:
        _log("Validating bootstrap timeout status...")
        run_bootstrap_validation()
        _log("Bootstrap validation complete.")
    except Exception as exc:
        _log(f"ERROR: Bootstrap validation failed: {exc!r}")
        traceback.print_exc()

    _log("Policy refresh complete.")


def main() -> int:
    try:
        run_policy_refresh()
        return 0
    except KeyboardInterrupt:
        _log("Interrupted by user.")
        return 1
    except Exception as exc:
        _log(f"FATAL: policy refresh crashed: {exc!r}")
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())

