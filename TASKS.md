# 🧩 TASKS.md — Chloe Quant System Implementation Tasks

This file defines every required task for building Chloe into a full quant-grade predictive engine.

Each section = a module. Each bullet = an atomic task Cursor can execute.

---

## 1️⃣ Flow Signals Module ✅ COMPLETE

**Files:**
- `engine_alpha/signals/signal_registry.json` ✅
- `engine_alpha/signals/signal_fetchers.py` ✅
- `engine_alpha/signals/flow_signals.py` ✅ (new)
- `engine_alpha/signals/signal_processor.py` ✅

**Tasks:**
- ✅ Add flow signals to registry:
  - `whale_accumulation_velocity`
  - `net_exchange_inflow`
  - `exchange_reserve_delta`
  - `perp_oi_trend`
  - `cvd_spot_vs_perp`
  - `large_wallet_bid_ask_dominance`
- ✅ Create `flow_signals.py` with 6 `compute_*` functions returning:
  ```python
  {
    "raw": float,
    "z_score": float,
    "direction_prob": {"up": float, "down": float},
    "confidence": float,
    "drift": float
  }
  ```
- ✅ Wire each function into `signal_fetchers.py`
- ✅ Integrate outputs into `signal_processor.get_signal_vector()`
- ✅ Add unit tests in `tests/test_flow_signals.py`

**Status:** Module 1 complete. All 6 flow signals are implemented, wired into the signal processor, and tested. Currently using simulated/OHLCV-derived values with clear TODOs for real on-chain data providers (Glassnode, Nansen, exchange APIs).

---

## 2️⃣ Volatility Signals Module ✅ COMPLETE

**Files:**
- `engine_alpha/signals/vol_signals.py` ✅ (new)
- `engine_alpha/signals/signal_registry.json` ✅
- `engine_alpha/signals/signal_fetchers.py` ✅
- `engine_alpha/signals/signal_processor.py` ✅

**Tasks:**
- ✅ Add vol signals to registry:
  - `vol_compression_percentile`
  - `vol_expansion_probability`
  - `regime_transition_heat`
  - `vol_clustering_score`
  - `realized_vs_implied_gap`
- ✅ Implement `vol_signals.py` with 5 `compute_*` functions returning:
  ```python
  {
    "raw": float,
    "z_score": float,
    "direction_prob": {"up": float, "down": float},
    "confidence": float,
    "drift": float
  }
  ```
- ✅ Add dispatch in `signal_fetchers.py`
- ✅ Integrate into `signal_processor` (handles flow_dict norm)
- ✅ Add `tests/test_vol_signals.py`

**Status:** Module 2 complete. All 5 volatility signals are implemented, wired into the signal processor, and tested. Currently using OHLCV-derived realized volatility with clear TODOs for real implied volatility data (Deribit, options APIs).

---

## 3️⃣ Microstructure Signals Module ✅ COMPLETE

**Files:**
- `engine_alpha/signals/microstructure_signals.py` ✅ (new)
- `engine_alpha/signals/signal_registry.json` ✅
- `engine_alpha/signals/signal_fetchers.py` ✅
- `engine_alpha/signals/signal_processor.py` ✅

**Tasks:**
- ✅ Add microstructure signals to registry:
  - `funding_rate_z`
  - `perp_spot_basis`
  - `liquidation_heat_proximity`
  - `orderbook_imbalance`
  - `oi_price_divergence`
- ✅ Implement `microstructure_signals.py` with 5 `compute_*` functions returning:
  ```python
  {
    "raw": float,
    "z_score": float,
    "direction_prob": {"up": float, "down": float},
    "confidence": float,
    "drift": float
  }
  ```
- ✅ Wire into `signal_fetchers.py`
- ✅ Integrate into `signal_processor` (handles flow_dict norm)
- ✅ Add `tests/test_microstructure_signals.py`

**Status:** Module 3 complete. All 5 microstructure signals are implemented, wired into the signal processor, and tested. Currently uses simulated/stubbed derivatives and orderbook metrics via SignalContext.derivatives and .microstructure, with clear TODOs for real exchange feeds (funding, OI, orderbook, liquidations).

---

## 4️⃣ Cross-Asset Signals Module ✅ COMPLETE

**Files:**
- `engine_alpha/signals/cross_asset_signals.py` ✅ (new)
- `engine_alpha/signals/signal_registry.json` ✅
- `engine_alpha/signals/signal_fetchers.py` ✅
- `engine_alpha/signals/signal_processor.py` ✅

**Tasks:**
- ✅ Add cross-asset signals to registry:
  - `btc_eth_vol_lead_lag`
  - `sol_l1_rotation_score`
  - `eth_ecosystem_momentum`
  - `stablecoin_flow_pressure`
  - `sector_risk_score`
- ✅ Implement `cross_asset_signals.py` with 5 `compute_*` functions returning:
  ```python
  {
    "raw": float,
    "z_score": float,
    "direction_prob": {"up": float, "down": float},
    "confidence": float,
    "drift": float
  }
  ```
- ✅ Ensure context includes multi-asset reference data (uses SignalContext.cross_asset)
- ✅ Add dispatch in `signal_fetchers.py`
- ✅ Integrate into `signal_processor` (handles flow_dict norm)
- ✅ Add `tests/test_cross_asset_signals.py`

**Status:** Module 4 complete. All 5 cross-asset signals are implemented, wired into the signal processor, and tested. Currently uses simplified multi-asset structures via SignalContext.cross_asset, with clear TODOs for real cross-asset feeds (Kaiko, Glassnode, exchange APIs).

---

## 5️⃣ Confidence Engine (Consensus Model) ✅ COMPLETE

**Files:**
- `engine_alpha/core/confidence_engine.py` ✅
- `engine_alpha/loop/autonomous_trader.py` ✅
- `engine_alpha/core/position_manager.py` ✅

**Tasks:**
- ✅ Create `ConfidenceState` dataclass with confidence, components, penalties
- ✅ Implement `compute_confidence` that:
  - Groups signals by category (flow, volatility, microstructure, cross_asset)
  - Computes group scores using average confidence + z-score boost
  - Applies base weights: Flow=0.40, Vol=0.25, Micro=0.20, Cross=0.15
  - Applies Regime penalty (CHOP regime penalizes trend-following confidence)
  - Applies Drift penalty: `penalty_drift = max(0.0, 1.0 - alpha * drift_score)` with alpha=1.0
  - Returns `ConfidenceState` with final confidence ∈ [0, 1] + component breakdown
- ✅ Wire into main decision loop (`run_step` and `run_step_live`)
- ✅ Update `position_manager.compute_position_size` to accept `ConfidenceState` (backward compatible with dict)
- ✅ Add `tests/test_confidence_engine.py` with 9 test cases

**Status:** Module 5 complete. Confidence engine now aggregates Flow/Vol/Micro/Cross signals with regime and drift penalties. Runs alongside old `decide()` function for backward compatibility. New `ConfidenceState` is computed in main loop and available for entry/exit decisions and position sizing.

**Weights:**
- Flow: 0.40 (highest)
- Volatility: 0.25 (medium)
- Microstructure: 0.20 (medium/low)
- Cross-Asset: 0.15 (medium/low)

**Penalties:**
- Regime: CHOP regime applies 0.7-1.0 penalty based on signal directionality; trend regimes have minimal penalty (1.0)
- Drift: `penalty_drift = max(0.0, 1.0 - 1.0 * drift_score)`, clamped to [0, 1]

---

## 6️⃣ Regime Model

**Files:**
- `engine_alpha/core/regime.py`

**Tasks:**
- Define regimes: `TREND_UP`, `TREND_DOWN`, `CHOP`, `HIGH_VOL`, `EXPANSION`, `CONTRACTION`
- Implement `classify_regime(context)`
- Produce:
  ```python
  { "primary": str, "secondary": [...], "scores": {...} }
  ```
- Integrate regime outputs into confidence engine, entry, exit
- Add `tests/test_regime.py`

---

## 7️⃣ Drift Detection System

**Files:**
- `engine_alpha/core/drift_detector.py` (new)
- PF + trade logs

**Tasks:**
- Implement drift metrics:
  - rolling PF_local
  - confidence-return correlation
  - drift_score (0–1)
- Provide `compute_drift(trade_history)`
- Integrate drift into:
  - confidence engine
  - position sizing
  - entry gating
- Add `tests/test_drift_detector.py`

---

## 8️⃣ Smart-Money Mirror Intelligence

**Files:**
- `engine_alpha/mirror/wallet_registry.json`
- `engine_alpha/mirror/wallet_observer.py`
- `engine_alpha/mirror/strategy_inference.py`
- `engine_alpha/mirror/mirror_manager.py`
- `engine_alpha/mirror/mirror_memory.jsonl`

**Tasks:**
- Implement wallet registry schema
- Build wallet observer to ingest trades (simulated or real feed)
- Implement strategy inference:
  - entry timing
  - hold duration
  - rotation patterns
  - size scaling
- Build mirror manager:
  - candidate evaluation rules (PF ≥ 1.10, stability, etc.)
  - translation of wallet trades → Chloe trades
- Add `tests/test_mirror_manager.py`

---

## 9️⃣ Validation & Metrics

**Files:**
- `engine_alpha/reflect/trade_analysis.py`
- `engine_alpha/reports/*.json`

**Tasks:**
- Extend trade analysis:
  - PF by regime
  - PF by confidence band
  - PF by signal cluster
- Add confidence calibration curves
- Create `validate_model_state()`:
  ```python
  { "pf_local": float, "is_valid": bool, "issues": [...] }
  ```
- Integrate validator into tuning/evolution
- Add `tests/test_trade_analysis.py`

---

## 🔟 Positioning & Risk Engine ✅ COMPLETE

**Files:**
- `engine_alpha/core/position_manager.py` ✅
- `engine_alpha/config/risk.yaml` ✅

**Tasks:**
- ✅ Implement position sizing function using ConfidenceState + volatility + drift
- ✅ Add risk config with confidence bands, volatility adjustment, drift penalty
- ✅ Add `tests/test_position_manager.py`

**Status:** Module 10 complete. Position sizing now uses ConfidenceState + volatility + drift. Integrated into main decision pipeline.

---

## 1️⃣1️⃣ Entry Logic ✅ COMPLETE

**Files:**
- `engine_alpha/loop/entry_logic.py` ✅
- `engine_alpha/loop/autonomous_trader.py` ✅

**Tasks:**
- ✅ Implement unified `should_enter_trade()`:
  - Uses ConfidenceState + RegimeState + DriftState + size_multiplier
  - Confidence threshold check
  - Drift threshold check
  - Size multiplier check
  - Regime check (optional)
- ✅ Route all entries through this function
- ✅ Add tests: `tests/test_entry_logic.py` with 5 test cases

**Status:** Module 11 complete. Entry decisions now use unified quant stack. All new entries go through `should_enter_trade()`.

**Key Thresholds:**
- `entry_min_confidence`: 0.60 (default, configurable)
- `max_drift_for_entries`: 0.5 (default, configurable)

---

## 1️⃣2️⃣ Exit Logic ✅ COMPLETE

**Files:**
- `engine_alpha/loop/exit_logic.py` ✅
- `engine_alpha/loop/autonomous_trader.py` ✅

**Tasks:**
- ✅ Implement unified `should_exit_trade()`:
  - Uses ConfidenceState + RegimeState + DriftState
  - Confidence decay check
  - Regime flip check (unfavorable for position)
  - Drift spike check (safety exit)
  - Signal direction flip (optional)
- ✅ Integrate into loop for open positions
- ✅ Add tests: `tests/test_exit_logic.py` with 4 test cases

**Status:** Module 12 complete. Exit decisions now use unified quant stack. All exits go through `should_exit_trade()`.

**Key Thresholds:**
- `exit_min_confidence`: 0.30 (default, configurable)
- `max_drift_for_open_positions`: 0.7 (default, configurable)
- `regime_flip_exit_enabled`: True (default, configurable)

---

## ✅ Full Wiring Summary

**Entry/exit decisions now use ConfidenceState + RegimeState + DriftState + position sizing. All new trades go through `should_enter_trade()` / `should_exit_trade()`.**

**Final per-tick decision pipeline:**
1. Build SignalContext (ctx)
2. Get signal_vector + raw_registry from signal_processor
3. Compute RegimeState from classify_regime
4. Load recent trades and compute DriftState
5. Compute ConfidenceState (Flow/Vol/Micro/Cross + regime + drift penalties)
6. Compute position size_multiplier from ConfidenceState + volatility + drift
7. Call should_enter_trade() → returns {enter, direction, size_multiplier, reason}
8. If enter=True, execute entry with size_multiplier
9. For open positions, call should_exit_trade() → returns {exit, reason}
10. If exit=True, execute exit

---

## 1️⃣3️⃣ GPT Threshold Tuner ✅ COMPLETE

**Files:**
- `engine_alpha/reflect/threshold_tuner.py` ✅
- `tools/run_threshold_tuner.py` ✅
- `config/risk.yaml` ✅ (thresholds + tuning sections added)

**Tasks:**
- ✅ Add thresholds section to risk.yaml:
  - entry_min_confidence: 0.60
  - exit_min_confidence: 0.30
  - max_drift_for_entries: 0.50
  - max_drift_for_open_positions: 0.70
- ✅ Add tuning section to risk.yaml:
  - min_trades_for_tuning: 50
  - lookback_trades: 150
  - max_change_per_step (safety limits)
- ✅ Implement threshold_tuner.py with:
  - build_stats_for_tuning() (PF, PF_by_regime, PF_by_confidence_band, drift)
  - build_gpt_prompt() (structured prompt for GPT)
  - call_gpt_for_thresholds() (wired to engine_alpha.core.gpt_client.query_gpt)
  - propose_thresholds() (main entrypoint with clamping)
- ✅ Add CLI tool tools/run_threshold_tuner.py
- ✅ Log proposals to reports/tuning_proposals.jsonl
- ✅ Add tests/test_threshold_tuner.py with 7 test cases

**Status:** Module 13 complete. GPT threshold tuner analyzes recent trades (50-150 trade cadence) and proposes threshold updates via GPT. Proposals are logged to JSONL for human review. Changes are clamped within max_change_per_step safety limits. GPT is wired via engine_alpha.core.gpt_client.query_gpt.

**Mode:** GPT proposes → Human approves. No auto-apply yet.

**Artifacts:**
- Proposals log: `reports/tuning_proposals.jsonl`
- CLI command: `python tools/run_threshold_tuner.py`
- GPT client: Wired (uses engine_alpha.core.gpt_client.query_gpt)

---

## 🎯 Completion Criteria

Chloe is considered **"Phase 2 ready"** when:

- ✅ All modules above are implemented
- ✅ All tests pass
- ✅ PF_local ≥ 1.00 on forward trades
- ✅ Drift remains stable
- ✅ Confidence correlates with expected forward returns
- ✅ Regime gating proven effective
- ✅ Position sizing behaves predictably

---

## 📋 Next Steps

If you want:
- 📌 A version formatted as GitHub Issues (one issue per module)
- 📌 A version rewritten as Cursor `.cursor/rules` tasks
- 📌 A Gantt-style build timeline
- 📌 A "quant integration order" (which modules to implement first)

Just ask: "Give me the GitHub issue version" or "Give me the Cursor tasks version."

