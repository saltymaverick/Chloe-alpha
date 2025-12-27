# Multi-Asset Rollout Plan

**Status:** Phase 0 - ETHUSDT Only

This document defines the phased rollout plan for enabling multi-asset trading in Chloe.

---

## 🧭 Phase 0 — Right Now (Current State)

**Goal:** Let ETHUSDT and BTCUSDT prove themselves in paper trading.

**Status:**
- ✅ All 12 assets have:
  - CryptoDataDownload backtest data
  - Live candles collecting
  - Hybrid research datasets
  - Analyzer stats and thresholds
- ✅ ETHUSDT and BTCUSDT are trading in paper mode
- ✅ ETHUSDT PF ≈ 0.93 from 4 trades (fine for a baby bot)
- ✅ BTCUSDT is the first Tier 1 asset to join ETH
- ⚠️ MATICUSDT is **research-only** due to live feed unavailability/staleness

**Action:** Both assets trading in paper mode:
- Keep ETH and BTC in paper mode
- Let all 12 assets keep collecting data + nightly research
- BTCUSDT is the first Tier 1 asset to activate alongside ETH
- MATICUSDT thresholds and backtests exist but will not be used for live decisions until feed is fixed

**Tier 1 rollout order (for Phase 1):**
1. BTCUSDT — cleanest high-vol volatility engine (✅ enabled)
2. AVAXUSDT — trend_down short-collapse engine
3. DOGEUSDT — explosive high-volatility engine
4. MATICUSDT — strongest high-vol breakout engine (research-only until feed fixed)

---

## 🧭 Phase 1 — ETH + BTC Proving Ground

**Goal:** ETH and BTC hit 10–20 trades each in paper and look sane.

**Readiness Criteria:**
```bash
python3 -m tools.asset_audit --symbol ETHUSDT --for-live
python3 -m tools.asset_audit --symbol BTCUSDT --for-live
tail -n 20 reports/trades.jsonl
cat reports/pf_local.json | jq .
```

**You'll know you're ready when:**
- ETHUSDT: `total_trades >= 10` (ideally 15-20)
- BTCUSDT: `total_trades >= 10` (ideally 15-20)
- Both assets: `pf_val >= 1.0` (ideally ≥ 1.05 over time)
- Trades look reasonable:
  - No weird exits
  - No insane slippage
  - Regime & strategy fields look right
  - Exit reasons make sense

**During this phase:**
- ✅ ETHUSDT and BTCUSDT are trading in paper
- ✅ Let AVAX/DOGE/XRP/SOL just gather data & refine research
- ⚠️ MATICUSDT remains research-only until feed is fixed

**ETH and BTC are your baseline sanity check.**

---

## 🧭 Phase 2 — Turn on Remaining Tier 1 Assets (One by One)

**Goal:** Enable remaining Tier 1 assets in paper, one at a time.

**Prerequisites:**
- ETH and MATIC have ~10–20 trades each and look stable in behavior
- Even if PF isn't amazing yet, behavior is consistent

**Tier 1 Assets (enable in this order):**
1. **BTCUSDT** – cleanest high-vol volatility engine (low-confidence buckets 0,1,2) ✅ **ENABLED**
2. **AVAXUSDT** – trend_down short collapse engine (buckets 5,6,7,8)
3. **DOGEUSDT** – explosive high-volatility engine (buckets 0,2,6,8)
4. **MATICUSDT** – strongest high-vol breakout engine (high-confidence buckets 4,6,8,9) ⚠️ **RESEARCH-ONLY** (feed unavailable)

**How to enable:**
```bash
# BTCUSDT is already enabled (Phase 0)

# After BTC looks good, enable AVAXUSDT
python3 -m tools.enable_trading AVAXUSDT

# After AVAX looks good, enable DOGEUSDT
python3 -m tools.enable_trading DOGEUSDT

# MATICUSDT: Once feed is fixed and diagnose_ohlcv confirms freshness,
#            add MATICUSDT back to config/trading_enablement.json
```

**What happens:**
- Asset remains enabled in `asset_registry.json` (for data collection)
- Asset gets added to `config/trading_enablement.json` (for actual trading)
- Multi-asset runner will start executing trades for that asset

**Wait between assets:** Let each asset accumulate 5-10 trades before enabling the next.

---

## 🧭 Phase 3 — Tier 2 Observation

**Goal:** Enable Tier 2 assets with strict observation mode constraints.

**Prerequisites:**
- Tier 1 has been paper trading for a while
- Behavior looks good across Tier 1 assets

**Tier 2 Assets:**
- **XRPUSDT** – high_vol + chop (buckets 2,6,7,8)
- **SOLUSDT** – high_vol (buckets 5,6)
- **ETHUSDT** – remains trading as benchmark/calibration

**Constraints:**
- Strictly their best regime (high_vol for both)
- Narrow confidence buckets only
- Reduced size (observation mode: `size_factor = 0.5`)
- ETH stays trading as benchmark

**Enable with:**
```bash
python3 -m tools.enable_trading XRPUSDT
python3 -m tools.enable_trading SOLUSDT
```

---

## 🧭 Phase 4 — Live Mode (Much Later)

**Goal:** Transition proven assets to live trading.

**Prerequisites (ALL must be true):**
For a given symbol (e.g., BTCUSDT):
- `asset_audit --symbol BTCUSDT --for-live` says `ready_for_live: true`
- Per-coin trades:
  - `total_trades >= 20`
  - `pf_val >= 1.05`
  - Drawdown within comfort zone
- Strategy behavior looks sane in logs:
  - No insane swings
  - No weird trades in chop
  - Exits make sense
- SWARM hasn't flagged systemic issues

**Then — and only then:**
1. Set up Bybit subaccount with small capital
2. Set strict per-symbol `max_notional` (e.g., $50–$100/trade initially)
3. Keep most assets paper-only until BTC or ETH prove live performance
4. Monitor closely for first 10-20 live trades

---

## 📊 Current Status

**Phase:** Phase 0

**Trading Enabled:**
- ETHUSDT (paper only)
- BTCUSDT (paper only) — first Tier 1 asset

**Data Collection Enabled:**
- All 12 assets (BTC, ETH, SOL, AVAX, LINK, MATIC, ATOM, BNB, DOT, ADA, XRP, DOGE)

**Tier 1 Rollout Order:**
1. BTCUSDT ✅ (enabled)
2. AVAXUSDT (next)
3. DOGEUSDT
4. MATICUSDT ⚠️ (research-only until feed fixed)

**Feed Health:**
- MATICUSDT: Live OHLCV feed unavailable/stale (Binance returns stale data, OKX returns no data)
- Research/backtest/hybrid datasets are valid and continue to be generated
- Once feed is fixed and `diagnose_ohlcv --symbol MATICUSDT` confirms freshness, MATIC can be re-enabled for paper trading by adding it back to `enabled_for_trading` in `config/trading_enablement.json`

**Next Milestone:**
- Wait for ETHUSDT and BTCUSDT to accumulate 10-20 trades each
- Check readiness with `asset_audit`
- Proceed to Phase 1 when ready, then enable remaining Tier 1 assets one by one

---

## 🛠️ Tools

- `tools/asset_audit.py` - Check asset readiness
- `tools/enable_trading.py` - Enable asset for trading (Phase 2+)
- `tools/check_rollout_readiness.py` - Check if ready for next phase

---

## 📝 Notes

- **Data collection ≠ Trading:** Assets can be enabled for data collection (`asset_registry.json`) but not trading (`trading_enablement.json`)
- **Research continues:** All assets continue nightly research regardless of trading status
- **Safety first:** Each phase requires proof before moving to the next
- **No rush:** Better to wait and verify than rush and regret


