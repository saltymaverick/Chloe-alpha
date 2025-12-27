# Chloe Checkpoint Summary

**Date**: Current state after Glassnode integration + on-chain filters  
**Status**: ✅ Stable pause point - ready for production monitoring

## Quick Status Check

```bash
# Check all assets
python3 -m tools.asset_audit --all

# Check recent trades
tail -n 20 reports/trades.jsonl

# Check PF
cat reports/pf_local.json | jq .

# Check Glassnode integration (if API key added)
python3 -m tools.verify_glassnode_integration --symbol ETHUSDT
```

## Current State

### ✅ Multi-Asset Infrastructure
- 12 coins configured in `config/asset_registry.json`
- Multi-asset live runner processing all enabled symbols
- Per-symbol OHLCV CSVs being written
- Per-symbol research outputs (`reports/research/{SYMBOL}/`)

### ✅ ETHUSDT (Paper-Ready)
- **Data**: 203+ candles ✅
- **Research**: Hybrid dataset + analyzer stats ✅
- **Thresholds**: 3 regimes enabled ✅
- **PF**: ~0.93 (realistic, after cleaning bogus trade)
- **Status**: `ready_for_paper: true`, `ready_for_live: false` (need 10+ trades)

### ⏸️ Other 11 Coins
- Config OK, thresholds OK
- Collecting candles → will be research-ready after ~200 candles + nightly research

### ✅ SWARM + Dashboards
- Sentinel / loop health integrated
- Quant view, strategy view, meta-strategy view wired
- All panels functional

### ✅ Strategy Layer
- Strategy cards: `high_vol_breakout_v1`, `trend_observation_short_v1`
- Strategy selection & evaluation in **shadow mode** (logging only)
- On-chain filters implemented (evaluates `gn_*` metrics when available)

### ✅ Glassnode Integration
- Config + client + fetcher implemented
- Hybrid builder merges `gn_*` columns automatically
- Strategies can evaluate on-chain filters
- **Waiting on**: User to add API key and fetch data

### ✅ Audit Tools
- `asset_audit` provides accurate per-symbol readiness
- PF counting from `trades.jsonl` (accurate)
- Sanity checks prevent bad prices from corrupting PF

## What's Running

### Active Services
- `chloe.service` - Multi-asset live loop (if enabled)
- `chloe-nightly-research.timer` - Nightly research (if enabled)
- `chloe-swarm-audit.timer` - SWARM audits (if enabled)

### Data Collection
- Live candles: `data/ohlcv/{SYMBOL}_{TIMEFRAME}_live.csv`
- Trades: `reports/trades.jsonl`
- Research: `reports/research/{SYMBOL}/`

## Next Steps (When Ready)

### Immediate (Optional)
1. **Add Glassnode API key**:
   ```bash
   nano config/glassnode_config.json
   # Replace YOUR_GLASSNODE_API_KEY_HERE
   python3 -m tools.fetch_glassnode_data --symbol ETHUSDT
   ```

2. **Monitor ETHUSDT**:
   - Let it accumulate 10+ trades
   - Review PF and behavior
   - Consider tiny live trials if PF > 1.0 and behavior stable

### Short-Term (1-2 weeks)
1. **Other coins**:
   - Wait for ~200 candles per coin
   - Run nightly research
   - Check `ready_for_paper` status
   - Enable paper trading for promising coins

2. **Strategy validation**:
   - Review `STRATEGY-SHADOW` logs
   - Validate on-chain filter behavior
   - Consider enabling strategy enforcement

### Medium-Term (1+ month)
1. **Live preparation**:
   - Review PF across all coins
   - Identify best-performing strategies
   - Prepare wallet config for live mode
   - Start with tiny sizes ($20-50 per trade)

2. **Meta-strategy**:
   - Review meta-strategy reflections
   - Implement promising strategic ideas
   - Extend on-chain filters to more strategies

## Key Files

### Configuration
- `config/asset_registry.json` - Asset definitions
- `config/glassnode_config.json` - Glassnode API config
- `config/entry_thresholds.json` - Per-regime entry thresholds
- `config/regime_enable.json` - Regime enable/disable flags
- `config/exit_rules.json` - Per-regime exit parameters

### Research Outputs
- `reports/research/{SYMBOL}/hybrid_research_dataset.parquet` - Hybrid datasets
- `reports/research/{SYMBOL}/multi_horizon_stats.json` - Analyzer stats
- `reports/research/{SYMBOL}/strategy_strength.json` - Strategy strength
- `reports/research/{SYMBOL}/confidence_map.json` - Confidence map

### Trading
- `reports/trades.jsonl` - All trades (live + paper)
- `reports/pf_local.json` - Profit factor (rolling window)
- `reports/research/trade_outcomes.jsonl` - Trade outcomes for research

### Monitoring
- `reports/quant_monitor.json` - Quant health metrics
- `reports/swarm_sentinel_report.json` - SWARM health
- `reports/research/meta_strategy_reflections.jsonl` - Meta-strategy thoughts

## Troubleshooting

### "No trades"
- Check regime classification (should see `trend_down`/`high_vol`)
- Check entry thresholds (may be too high)
- Check quant gate logs (`grep QUANT-GATE logs/*.log`)

### "PF still weird"
- Check for bad trades: `grep "exit_px.*0\." reports/trades.jsonl`
- Sanity checks should prevent this, but verify

### "Glassnode not working"
- Check API key in `config/glassnode_config.json`
- Fetch data: `python3 -m tools.fetch_glassnode_data --symbol ETHUSDT`
- Verify cache: `ls -lh data/glassnode/ETHUSDT_glassnode.parquet`

### "Strategy not selecting"
- Check strategy scope matches symbol/regime/timeframe
- Check strategy status is not "disabled"
- Review `STRATEGY-SHADOW` logs

## Quick Commands

```bash
# Full system check
python3 -m tools.asset_audit --all

# Check single asset
python3 -m tools.asset_audit --symbol ETHUSDT

# View recent trades
tail -n 20 reports/trades.jsonl | python3 -m json.tool

# Check PF
cat reports/pf_local.json | jq .

# Monitor live loop
tail -f logs/chloe.service.log | grep -E "ENTRY|EXIT|STRATEGY-SHADOW|QUANT-GATE"

# Run nightly research manually
python3 -m engine_alpha.reflect.nightly_research

# Verify Glassnode
python3 -m tools.verify_glassnode_integration --symbol ETHUSDT
```

## Architecture Summary

```
┌─────────────────────────────────────────────────────────┐
│                    Multi-Asset Runner                    │
│              (processes all enabled assets)              │
└────────────────────┬────────────────────────────────────┘
                     │
        ┌────────────┴────────────┐
        │                         │
┌───────▼────────┐      ┌─────────▼──────────┐
│  Live Loop     │      │  Nightly Research  │
│  (per symbol)  │      │  (per symbol)      │
└───────┬────────┘      └─────────┬──────────┘
        │                         │
        │                         │
┌───────▼─────────────────────────▼──────────┐
│         Strategy Layer (Shadow Mode)        │
│  - Strategy selection                       │
│  - On-chain filter evaluation               │
│  - Entry/exit logic                         │
└───────┬─────────────────────────────────────┘
        │
┌───────▼─────────────────────────────────────┐
│         Quant Gate + Risk Management        │
│  - Sanity gates                             │
│  - Position sizing                          │
│  - Profit amplifier                         │
└───────┬─────────────────────────────────────┘
        │
┌───────▼─────────────────────────────────────┐
│         Trade Execution                      │
│  - Paper wallet (current)                   │
│  - Real wallet (when ready)                 │
└─────────────────────────────────────────────┘
```

## Status: ✅ Ready to Pause

Chloe is in a stable, production-ready state. All systems operational, data flowing, research running. Safe to let it run unattended and check back later.


