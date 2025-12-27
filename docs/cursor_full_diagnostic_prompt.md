# Cursor Full Codebase Diagnostic Prompt

## Instructions

**Copy and paste the entire content below into Cursor's chat** to perform a comprehensive diagnostic of Chloe's entire codebase.

---

# CURSOR PROMPT — FULL CODEBASE DIAGNOSTIC

We want Chloe to be fully optimal in live trading and backtesting.

Please perform a deep diagnostic across the entire repository.

## OBJECTIVE

Find any logic bugs, inconsistencies, or structural issues preventing Chloe from:

1. Opening trades with correct confidence
2. Closing trades correctly (TP/SL/drop/decay)
3. Producing meaningful trades in backtest
4. Having consistent behavior between backtest and live
5. Applying regime- and threshold-based decision making properly
6. Using signal vectors correctly
7. Propagating prices correctly (entry_px, exit_px)
8. Preventing scratch-dominant churn
9. Maintaining high PF in trend_down and high_vol

## ACTIONS FOR CURSOR

### 1. Open every relevant file, especially:

- `engine_alpha/loop/autonomous_trader.py` - Main trading loop
- `engine_alpha/loop/execute_trade.py` - Trade execution
- `engine_alpha/core/confidence_engine.py` - Confidence aggregation
- `engine_alpha/core/regime.py` - Regime classification
- `engine_alpha/signals/signal_processor.py` - Signal processing
- `engine_alpha/signals/signal_fetchers.py` - Signal fetching
- `tools/backtest_harness.py` - Backtest infrastructure
- `tools/signal_return_analyzer.py` - Analysis tool
- `tools/gpt_threshold_tuner.py` - GPT tuning tool
- `config/entry_thresholds.json` - Threshold config
- `engine_alpha/loop/position_manager.py` - Position management
- `engine_alpha/loop/exit_engine.py` - Exit logic
- `engine_alpha/core/paths.py` - Path configuration

### 2. Cross-reference the logic to ensure:

- **Regime classification**: Uses the same features everywhere (slopes, ATR, HH/LL)
- **decide() function**: Uses the correct regime (price-based, not signal-based)
- **Bucket weights**: Correct per regime (REGIME_BUCKET_WEIGHTS)
- **Thresholds**: Applied only once, no double-gating
- **Neutral zone**: Consistent threshold (0.30) everywhere
- **Entries/exits**: Use same source of truth for prices
- **No leftover hacks**: No LAB_MODE, ANALYSIS_MODE, BACKTEST_MIN_CONF, etc.
- **Price extraction**: entry_px and exit_px use correct candle fields
- **_try_open()**: Receives correct arguments (symbol, timeframe, regime)
- **Live/backtest**: Produce identical logic paths

### 3. Identify ANY issues that would cause:

- 0 meaningful trades in backtest
- Scratch trade madness (too many tiny pct trades)
- Endless churn (open/close/open/close)
- Overblocking entries (regime gate too strict)
- Mismatched regimes (different classification in different places)
- Neutralization always zeroing signals (NEUTRAL_THRESHOLD too high)
- Wrong confidence weights (using COUNCIL_WEIGHTS instead of REGIME_BUCKET_WEIGHTS)
- Wrong min_conf calculations (not using compute_entry_min_conf)
- Wrong exit triggers (TP/SL thresholds incorrect)
- Missing entry_px or exit_px (fallback to 1.0)
- Bad PnL scaling (pct calculation wrong)
- Confidence rounding errors (inconsistent decimal places)

### 4. Check specific code paths:

#### Entry Logic Flow:
1. `run_step_live()` → `classify_regime()` → price-based regime
2. `get_signal_vector_live()` → signal vector
3. `decide(signal_vector, raw_registry, regime_override=price_based_regime)` → decision
4. Apply Phase 54 adjustments → effective_final_dir/conf
5. Check `regime_allows_entry(regime)` → gate
6. Check `effective_final_conf >= compute_entry_min_conf(regime, risk_band)` → threshold
7. Call `_try_open(dir, conf, now, regime)` → open

#### Exit Logic Flow:
1. `run_step_live()` → check if position exists
2. Get current bar's close → exit_price
3. Check TP/SL/drop/decay/reverse conditions
4. Call `close_now()` with entry_px, exit_px, pos_dir
5. Calculate `pct = (exit_px - entry_px) / entry_px * dir`
6. Write close event with metadata

#### Backtest Flow:
1. `backtest_harness.py` → load CSV
2. Mock `get_live_ohlcv()` → return window ending at current bar
3. Call `run_step_live()` with bar_ts and now=bar_dt
4. Write trades to backtest-specific `trades.jsonl`
5. Update equity only on closes (pnl != 0)

### 5. Provide a single consolidated list of FIXES

For each issue found:
- **File + line number**: Exact location
- **Before/after code**: Show the problematic code and the fix
- **Root cause**: Explain why this causes the problem
- **Impact**: What behavior this fixes
- **Test**: How to verify the fix works

### 6. Ensure unified logic everywhere

Verify that:
- Live and backtest use identical code paths
- No environment variable hacks change behavior
- All thresholds come from config files
- All regime classification uses same function
- All confidence aggregation uses same weights

## EXPECTED OUTPUT

A comprehensive report with:

1. **Executive Summary**: List of critical issues found
2. **Detailed Findings**: Per-file analysis with line references
3. **Code Patches**: Ready-to-apply fixes
4. **Verification Steps**: How to test each fix
5. **Consistency Matrix**: Cross-reference table showing where logic should match

## CONSTRAINTS

- Do NOT reintroduce LAB_MODE, ANALYSIS_MODE, or BACKTEST_MIN_CONF
- Do NOT change exit logic (TP/SL thresholds)
- Do NOT modify regime_allows_entry() behavior (currently only trend_down/high_vol)
- Do NOT break existing tools (pf_doctor, chloe_checkin, etc.)
- Ensure all fixes maintain backward compatibility

---

**After Cursor completes the diagnostic, review the findings and apply fixes one by one.**

