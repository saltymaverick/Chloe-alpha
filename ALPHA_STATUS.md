# Chloe Alpha Status

**Last Updated:** 2025-01-27  
**Audit Type:** Full Module Integrity Check

---

## Module Implementation Status

### ✅ 1️⃣ Flow Signals Module — **COMPLETE**
- **Status:** Fully implemented and wired
- **Files:**
  - ✅ `engine_alpha/signals/flow_signals.py` (6 compute functions)
  - ✅ `engine_alpha/signals/signal_registry.json` (6 flow signals registered)
  - ✅ `engine_alpha/signals/signal_fetchers.py` (wired)
  - ✅ `engine_alpha/signals/signal_processor.py` (handles flow_dict norm)
- **Tests:** ✅ `tests/test_flow_signals.py` exists
- **Notes:** Using simulated/OHLCV-derived values; ready for real on-chain data

---

### ⚠️ 2️⃣ Volatility Signals Module — **NOT IMPLEMENTED**
- **Status:** Missing
- **Files Missing:**
  - ❌ `engine_alpha/signals/vol_signals.py`
  - ❌ Volatility signals in `signal_registry.json`
- **Tests:** ❌ `tests/test_vol_signals.py` missing
- **Impact:** No volatility-based signals in the stack

---

### ⚠️ 3️⃣ Microstructure Signals Module — **NOT IMPLEMENTED**
- **Status:** Missing
- **Files Missing:**
  - ❌ `engine_alpha/signals/microstructure_signals.py`
  - ❌ Microstructure signals in `signal_registry.json`
- **Tests:** ❌ `tests/test_microstructure_signals.py` missing
- **Impact:** No funding/basis/orderbook signals

---

### ⚠️ 4️⃣ Cross-Asset Signals Module — **NOT IMPLEMENTED**
- **Status:** Missing
- **Files Missing:**
  - ❌ `engine_alpha/signals/cross_asset_signals.py`
  - ❌ Cross-asset signals in `signal_registry.json`
- **Tests:** ❌ `tests/test_cross_asset_signals.py` missing
- **Impact:** No rotation/contagion signals

---

### ⚠️ 5️⃣ Confidence Engine (Consensus Model) — **PARTIALLY IMPLEMENTED**
- **Status:** Exists but uses legacy bucket-based approach, not new Flow/Vol/Micro/Cross structure
- **Files:**
  - ✅ `engine_alpha/core/confidence_engine.py` exists
  - ⚠️ Uses old bucket system (momentum, meanrev, flow, positioning, timing)
  - ❌ No `ConfidenceState` dataclass with components/penalties breakdown
  - ❌ No `compute_confidence(raw_registry, regime_state, drift_state)` function matching spec
- **Tests:** ❌ `tests/test_confidence_engine.py` missing
- **Impact:** Confidence exists but doesn't aggregate Flow/Vol/Micro/Cross signals as designed

---

### ✅ 6️⃣ Regime Model — **IMPLEMENTED**
- **Status:** Implemented and used in main loop
- **Files:**
  - ✅ `engine_alpha/core/regime.py` exists
  - ✅ `classify_regime()` function exists
  - ✅ Used in `autonomous_trader.py` (line 706)
- **Tests:** ❌ `tests/test_regime.py` missing
- **Notes:** Uses price-based classification; may not match exact RegimeState dataclass spec

---

### ✅ 7️⃣ Drift Detection System — **IMPLEMENTED**
- **Status:** Fully implemented
- **Files:**
  - ✅ `engine_alpha/core/drift_detector.py` exists
  - ✅ `DriftState` dataclass exists
  - ✅ `compute_drift()` function implemented
- **Tests:** ❌ `tests/test_drift_detector.py` missing
- **Wiring:** ⚠️ Not verified in main decision loop
- **Notes:** Function exists but may not be called in `run_step()` or `run_step_live()`

---

### ⚠️ 8️⃣ Smart-Money Mirror Intelligence — **PARTIALLY IMPLEMENTED**
- **Status:** Infrastructure exists but may not match Module 8 spec exactly
- **Files:**
  - ✅ `engine_alpha/mirror/wallet_observer.py` exists
  - ✅ `engine_alpha/mirror/strategy_inference.py` exists
  - ✅ `engine_alpha/mirror/mirror_manager.py` exists
  - ❌ `engine_alpha/mirror/wallet_registry.json` not verified
- **Tests:** ❌ `tests/test_wallet_observer.py` missing
  - ❌ `tests/test_strategy_inference.py` missing
  - ❌ `tests/test_mirror_manager.py` missing
- **Notes:** Mirror infrastructure exists but needs verification against Module 8 spec

---

### ⚠️ 9️⃣ Validation & Metrics — **PARTIALLY IMPLEMENTED**
- **Status:** Basic PF computation exists, but missing Module 9 functions
- **Files:**
  - ✅ `engine_alpha/reflect/trade_analysis.py` exists
  - ❌ `compute_pf_by_regime()` missing
  - ❌ `compute_pf_by_confidence_band()` missing
  - ❌ `compute_pf_by_signal_cluster()` missing
  - ❌ `validate_model_state()` missing
- **Tests:** ❌ `tests/test_trade_analysis.py` missing
- **Impact:** Cannot validate model health by regime/confidence/cluster

---

### ✅ 🔟 Positioning & Risk Engine — **IMPLEMENTED**
- **Status:** Fully implemented
- **Files:**
  - ✅ `engine_alpha/core/position_manager.py` exists
  - ✅ `compute_position_size()` function implemented
  - ✅ `config/risk.yaml` updated with position_sizing config
- **Tests:** ❌ `tests/test_position_manager.py` missing
- **Wiring:** ⚠️ Not verified in main execution loop
- **Notes:** Function exists but may not be called in `execute_trade.py`

---

### ⚠️ 1️⃣1️⃣ Entry Logic — **PARTIALLY IMPLEMENTED**
- **Status:** Entry logic exists but doesn't use full stack (confidence + regime + drift + sizing)
- **Files:**
  - ✅ `engine_alpha/loop/autonomous_trader.py` has entry logic
  - ✅ `engine_alpha/loop/execute_trade.py` has `open_if_allowed()` and `gate_and_size_trade()`
  - ❌ No unified `should_enter_trade(ctx, signal_vector, raw_registry, regime_state, drift_state, confidence_state, size_multiplier, config)` function
- **Tests:** ❌ `tests/test_entry_logic.py` missing
- **Current State:** Uses `decide()` output and `open_if_allowed()` but doesn't explicitly use drift_state or new confidence_state structure

---

### ⚠️ 1️⃣2️⃣ Exit Logic — **PARTIALLY IMPLEMENTED**
- **Status:** Exit logic exists but doesn't use full stack
- **Files:**
  - ✅ `engine_alpha/loop/exit_engine.py` exists (label mapping only)
  - ✅ Exit logic in `autonomous_trader.py` (lines 566-614)
  - ❌ No unified `should_exit_trade(position, ctx, signal_vector, raw_registry, regime_state, drift_state, confidence_state, config)` function
- **Tests:** ❌ `tests/test_exit_engine.py` missing
- **Current State:** Uses confidence thresholds and time decay but doesn't explicitly use drift_state or regime_state for exits

---

## Decision Pipeline

### Current Actual Pipeline (from `autonomous_trader.py`):

```python
# run_step() / run_step_live():
1. get_signal_vector() → signal_vector, raw_registry
2. decide(signal_vector, raw_registry) → decision dict with regime, buckets, final
3. open_if_allowed() / gate_and_size_trade() → entry decision
4. Exit logic checks: take_profit, stop_loss, flip, drop, decay
```

### Intended Pipeline (from spec):

```python
1. build_signal_context() → ctx (SignalContext)
2. signal_processor.get_signal_vector(ctx) → signal_vector, raw_registry
3. classify_regime(ctx, raw_registry) → regime_state (RegimeState)
4. load_recent_trades() → recent_trades
5. compute_drift(recent_trades) → drift_state (DriftState)
6. compute_confidence(raw_registry, regime_state, drift_state) → confidence_state (ConfidenceState)
7. compute_position_size(confidence_state, volatility_estimate, drift_state, risk_config) → size_multiplier
8. should_enter_trade(...) → entry decision
9. should_exit_trade(...) → exit decision
```

### Gap Analysis:

- ❌ **SignalContext not used:** Main loop uses `get_signal_vector()` without SignalContext
- ❌ **Drift not computed:** `compute_drift()` exists but not called in main loop
- ❌ **Confidence not using new structure:** Uses old `decide()` bucket system, not Flow/Vol/Micro/Cross aggregation
- ❌ **Position sizing not integrated:** `compute_position_size()` exists but not called in execution
- ⚠️ **Regime partially integrated:** `classify_regime()` exists and is called, but may not match RegimeState spec
- ⚠️ **Entry/Exit not unified:** Logic exists but scattered, not using unified `should_enter_trade()` / `should_exit_trade()` functions

---

## Tests

### Existing Tests:
- ✅ `tests/test_flow_signals.py` — Flow signal computation
- ✅ `tests/test_structure.py` — Basic imports
- ✅ `tests/test_paths.py` — Path validation
- ✅ `tests/test_portfolio_guards.py` — Portfolio logic
- ✅ `tests/test_reports.py` — Report generation
- ✅ `tests/test_historical_loader.py` — Data loading

### Missing Tests:
- ❌ `tests/test_vol_signals.py`
- ❌ `tests/test_microstructure_signals.py`
- ❌ `tests/test_cross_asset_signals.py`
- ❌ `tests/test_confidence_engine.py`
- ❌ `tests/test_regime.py`
- ❌ `tests/test_drift_detector.py`
- ❌ `tests/test_wallet_observer.py`
- ❌ `tests/test_strategy_inference.py`
- ❌ `tests/test_mirror_manager.py`
- ❌ `tests/test_trade_analysis.py`
- ❌ `tests/test_position_manager.py`
- ❌ `tests/test_entry_logic.py`
- ❌ `tests/test_exit_engine.py`

### Test Commands:

```bash
# Run all existing tests
pytest tests/ -v

# Run flow signals tests
pytest tests/test_flow_signals.py -v

# Run structure tests
pytest tests/test_structure.py -v
```

---

## Gaps / TODO Before Live

### Critical Missing Modules:
1. **Volatility Signals (Module 2)** — Not implemented
2. **Microstructure Signals (Module 3)** — Not implemented
3. **Cross-Asset Signals (Module 4)** — Not implemented

### Partially Implemented (Need Completion):
1. **Confidence Engine (Module 5)** — Exists but uses old bucket system, needs Flow/Vol/Micro/Cross aggregation
2. **Validation & Metrics (Module 9)** — Basic PF exists, missing regime/confidence/cluster analysis
3. **Entry Logic (Module 11)** — Logic exists but not unified with full stack
4. **Exit Logic (Module 12)** — Logic exists but not unified with full stack

### Wiring Gaps:
1. **SignalContext not used in main loop** — Flow signals support it, but main loop doesn't construct it
2. **Drift detection not called** — `compute_drift()` exists but not integrated into decision pipeline
3. **Position sizing not integrated** — `compute_position_size()` exists but not called in execution
4. **Confidence engine mismatch** — Old bucket-based system doesn't match new Flow/Vol/Micro/Cross spec

### Data Sources (Expected):
- All signals currently use simulated/OHLCV-derived values
- Real data providers (Glassnode, Nansen, exchange APIs) not integrated
- Cross-asset data loaders not implemented

### Testing Gaps:
- 13 out of 14 module tests missing
- No integration tests for full decision pipeline
- No validation tests for model health

---

## Summary

### What's Actually Working:
- ✅ Flow Signals (Module 1) — Complete and wired
- ✅ Regime Model (Module 6) — Implemented and used
- ✅ Drift Detection (Module 7) — Implemented (but not wired)
- ✅ Position Manager (Module 10) — Implemented (but not wired)
- ✅ Basic entry/exit logic exists (but not unified)

### What's Missing:
- ❌ Volatility Signals (Module 2)
- ❌ Microstructure Signals (Module 3)
- ❌ Cross-Asset Signals (Module 4)
- ❌ New Confidence Engine structure (Module 5)
- ❌ Validation & Metrics functions (Module 9)
- ❌ Unified Entry/Exit functions (Modules 11-12)

### What Needs Wiring:
- ⚠️ SignalContext → main loop
- ⚠️ DriftState → confidence engine → entry/exit
- ⚠️ Position sizing → execution
- ⚠️ New confidence structure → replace old bucket system

---

## Recommendation

**Current State:** Chloe has foundational pieces (Flow signals, regime, drift detection, position sizing) but is **not yet a coherent quant system** as specified in TASKS.md.

**Before Shadow/Live:**
1. Complete missing signal modules (Vol, Micro, Cross-Asset)
2. Refactor confidence engine to use Flow/Vol/Micro/Cross aggregation
3. Wire drift detection and position sizing into main loop
4. Create unified `should_enter_trade()` and `should_exit_trade()` functions
5. Add comprehensive test suite
6. Verify full decision pipeline matches spec

**Estimated Completion:** ~60-70% of planned modules implemented, ~30-40% wiring complete.

