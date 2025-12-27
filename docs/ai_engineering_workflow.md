# AI Engineering Workflow for Chloe

## Overview

This document describes how to use AI (Cursor + GPT) to perform comprehensive diagnostics and improvements on Chloe's codebase.

## Three-Tier Approach

### Tier 1: Data-Driven Analysis ✅ COMPLETE

**What it does:**
- `tools/signal_return_analyzer.py` processes all historical candles through Chloe's actual logic
- Produces aggregated statistics by regime × confidence bin
- GPT reads the summary and proposes threshold adjustments

**Status:** ✅ Implemented and ready to use

**Usage:**
```bash
# 1. Analyze historical data
python3 -m tools.signal_return_analyzer \
  --csv data/ohlcv/ETHUSDT_1h_merged.csv \
  --output reports/analysis/conf_ret_summary.json

# 2. Get GPT recommendations
python3 -m tools.gpt_threshold_tuner \
  --summary reports/analysis/conf_ret_summary.json

# 3. Apply if good
python3 -m tools.gpt_threshold_tuner \
  --summary reports/analysis/conf_ret_summary.json \
  --apply
```

### Tier 2: Automated Logic Auditing ✅ COMPLETE

**What it does:**
- `tools/chloe_logic_auditor.py` performs static analysis
- Checks for code patterns, inconsistencies, leftover hacks
- Cross-references logic across modules

**Status:** ✅ Implemented

**Usage:**
```bash
# Run automated audit
python3 -m tools.chloe_logic_auditor --repo-root .

# Save JSON report
python3 -m tools.chloe_logic_auditor --repo-root . --output reports/audit_report.json
```

### Tier 3: Full AI Codebase Diagnostic 🔄 READY TO USE

**What it does:**
- Uses Cursor's AI to read ALL files
- Performs deep semantic analysis
- Identifies logic bugs, inconsistencies, structural issues
- Provides code patches

**Status:** ✅ Prompt ready (see `docs/cursor_full_diagnostic_prompt.md`)

**Usage:**
1. Open Cursor
2. Copy entire content from `docs/cursor_full_diagnostic_prompt.md`
3. Paste into Cursor chat
4. Let Cursor analyze the entire codebase
5. Review findings and apply fixes

## What Each Tier Catches

### Tier 1 (Data Analysis)
- ✅ Performance issues (low PF in certain confidence ranges)
- ✅ Threshold optimization opportunities
- ✅ Regime-specific edge detection

### Tier 2 (Static Audit)
- ✅ Code pattern issues (LAB_MODE hacks)
- ✅ Import inconsistencies
- ✅ Function call mismatches
- ✅ Hardcoded thresholds
- ✅ Missing config loading

### Tier 3 (AI Diagnostic)
- ✅ Logic flow bugs
- ✅ Semantic inconsistencies
- ✅ Cross-module integration issues
- ✅ Edge cases and race conditions
- ✅ Architecture-level problems

## Recommended Workflow

1. **Run Tier 1** (data analysis + GPT tuning)
   - Get optimized thresholds
   - Understand performance by regime

2. **Run Tier 2** (automated audit)
   - Catch obvious code issues
   - Find leftover hacks
   - Verify consistency

3. **Run Tier 3** (AI diagnostic)
   - Deep dive into logic
   - Find subtle bugs
   - Get comprehensive fixes

4. **Apply fixes** from all tiers

5. **Re-run backtests** to verify improvements

6. **Deploy** to live/paper

## Next Steps

To enable full AI engineering:

1. **Run the analyzer** (if not done):
   ```bash
   python3 -m tools.signal_return_analyzer --csv data/ohlcv/ETHUSDT_1h_merged.csv
   ```

2. **Run the auditor**:
   ```bash
   python3 -m tools.chloe_logic_auditor --repo-root .
   ```

3. **Run Cursor diagnostic**:
   - Open `docs/cursor_full_diagnostic_prompt.md`
   - Copy entire prompt
   - Paste into Cursor
   - Review findings

4. **Apply fixes** systematically

5. **Verify** with backtests

## Advanced: Self-Tuning Chloe

Future enhancement: Build an autonomous tuning loop that:
- Runs backtests automatically
- Analyzes results
- Calls GPT for recommendations
- Applies thresholds
- Re-runs backtests
- Iterates until convergence

This would require:
- `tools/auto_tuner.py` - Orchestrates the loop
- `tools/backtest_runner.py` - Runs backtests programmatically
- `tools/performance_evaluator.py` - Evaluates if improvements are real
- `config/tuning_config.yaml` - Configures the tuning loop

**Status:** Not yet implemented (future work)


