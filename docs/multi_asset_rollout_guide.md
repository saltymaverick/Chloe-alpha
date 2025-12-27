# Multi-Asset Rollout Guide

## Overview

This guide documents Chloe's complete 12-asset alpha portfolio and Phase 2 rollout plan.

## Master Tier Map

### 🥇 Tier 1 - Primary Alpha Engines (Edge > 5 bps)

These assets have clear positive structural edge and should enter paper trading first.

| Asset | Edge (bps) | Regime | Best Bucket | Strategy Focus |
|-------|-----------|--------|-------------|----------------|
| MATICUSDT | +18.1 | high_vol | 9 (+125.1) | High-confidence breakouts |
| BTCUSDT | +9.8 | high_vol | 0 (+65.3) | Low-confidence breakouts |
| AVAXUSDT | +8.0 | trend_down | 8 (+31.7) | SHORT collapse/continuation |
| DOGEUSDT | +6.3 | high_vol | 8 (+34.6) | Explosive breakouts |

**Activation Order:**
1. BTCUSDT (after ETHUSDT stabilizes)
2. MATICUSDT (after BTCUSDT stable)
3. AVAXUSDT (after MATICUSDT stable)
4. DOGEUSDT (after AVAXUSDT stable)

### 🥈 Tier 2 - Observation Mode (Edge 0-5 bps)

These assets have weak positive edge and require selective trading.

| Asset | Edge (bps) | Regime | Best Bucket | Strategy Focus |
|-------|-----------|--------|-------------|----------------|
| XRPUSDT | +4.7 | high_vol | 2 (+35.2) | Selective breakouts + mean-reversion |
| SOLUSDT | +2.2 | high_vol | 6 (+55.3) | Mid-confidence breakouts (very selective) |
| ETHUSDT | +1.6 | high_vol | N/A | Currently trading (benchmark) |

**Activation Order:**
5. XRPUSDT (after all Tier 1 stable)
6. SOLUSDT (after XRPUSDT stable)

### 🥉 Tier 3 - Research-Only (Edge ≤ 0 bps)

These assets have no broad structural edge and should not trade.

| Asset | Overall Edge | Best Selective Signal | Notes |
|-------|--------------|----------------------|-------|
| BNBUSDT | -0.2 bps | chop\|7: +34.0 bps | Selective buckets only |
| DOTUSDT | -0.8 bps | chop\|4: +24.2 bps | Selective buckets only |
| ADAUSDT | -4.7 bps | chop\|8: +88.0 bps | Very strong selective but negative overall |
| LINKUSDT | -6.1 bps | high_vol\|6: +34.4 bps | Selective buckets only |
| ATOMUSDT | -8.7 bps | high_vol\|8: +81.3 bps | Very strong selective but negative overall |

## Phase 2 Rollout Plan

### Phase 2.1 - Immediate Paper Trading

**Prerequisites:**
- ETHUSDT has 10+ trades
- ETHUSDT PF > 0.90
- ETHUSDT drawdown < 25%

**Activation Sequence:**
1. **BTCUSDT** - Enable in paper mode
   - Strategy: Low-confidence breakouts (bucket 0)
   - Max notional: $500/trade, $5000/day
   - Monitor for 7+ days or 10+ trades

2. **MATICUSDT** - Enable in paper mode
   - Strategy: High-confidence breakouts (bucket 8-9)
   - Max notional: $500/trade, $5000/day
   - Monitor for 7+ days or 10+ trades

3. **AVAXUSDT** - Enable in paper mode
   - Strategy: SHORT collapse/continuation (bucket 5-8)
   - Max notional: $400/trade, $4000/day
   - Monitor for 7+ days or 10+ trades

4. **DOGEUSDT** - Enable in paper mode
   - Strategy: Explosive breakouts (bucket 0, 8)
   - Max notional: $350/trade, $3500/day
   - Monitor for 7+ days or 10+ trades

### Phase 2.2 - Observation Mode

**Prerequisites:**
- All Tier 1 assets have 20+ trades each
- All Tier 1 assets PF > 0.90
- Portfolio-level risk metrics stable

**Activation Sequence:**
5. **XRPUSDT** - Enable in observation mode
   - Strategy: Selective breakouts (bucket 2, 6, 7, 8) + mean-reversion (chop\|8)
   - Max notional: $250/trade, $2500/day
   - Tight confidence filters (min_conf: 0.2)

6. **SOLUSDT** - Enable in observation mode
   - Strategy: Mid-confidence breakouts (bucket 6 only)
   - Max notional: $250/trade, $2500/day
   - Very selective (bucket 6 only)

### Phase 2.3 - Research-Only

**Never enable trading for:**
- BNBUSDT, DOTUSDT, ADAUSDT, LINKUSDT, ATOMUSDT

These assets will continue collecting data and research outputs, but should not trade until future research shows improved edge.

## Configuration Files

### `config/multi_asset_strategy_profiler.json`

Contains detailed strategy profiles for each asset:
- Regime focus
- Confidence filters
- Position sizing
- Best bucket signals

### `config/multi_asset_paper_config.json`

Contains activation status and rollout plan:
- Enabled assets
- Activation conditions
- Position limits
- Mode settings

## Dashboard Integration

The multi-asset panel (`engine_alpha/dashboard/multi_asset_panel.py`) displays:
- Tier classification
- Edge metrics
- PF and trade counts
- Activation status
- Rollout plan progress

## Risk Engine

The multi-asset risk engine (`engine_alpha/risk/multi_asset_risk_engine.py`) computes:
- Portfolio-level risk scores
- Weighted average edge
- Expected trades per day
- Volatility multipliers
- Total exposure limits

## Activation Commands

To enable an asset in paper mode:

```bash
# Edit config/multi_asset_paper_config.json
# Set "enabled": true for the asset
# Restart chloe.service
sudo systemctl restart chloe.service
```

To check activation status:

```bash
python3 -c "
from engine_alpha.config.config_loader import load_json
from pathlib import Path
import json
cfg = json.loads(Path('config/multi_asset_paper_config.json').read_text())
for asset, data in cfg.get('enabled_assets', {}).items():
    print(f\"{asset}: enabled={data.get('enabled')}, mode={data.get('mode')}\")
"
```

## Monitoring

After enabling each asset:
1. Monitor `reports/trades.jsonl` for new trades
2. Check `reports/pf_local.json` for PF updates
3. Review logs for regime/confidence distribution
4. Verify position sizing matches config
5. Confirm no unexpected behavior

## Success Criteria

An asset is considered "stable" when:
- 10+ trades executed
- PF > 0.90
- Drawdown < 25%
- No critical errors in logs
- Regime/confidence distribution matches research expectations

## Next Steps

1. Enable BTCUSDT after ETHUSDT meets stability criteria
2. Monitor BTCUSDT for 7+ days
3. Enable MATICUSDT after BTCUSDT stable
4. Continue sequential activation
5. Review portfolio-level metrics weekly


