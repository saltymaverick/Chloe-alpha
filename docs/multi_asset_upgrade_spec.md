# Multi-Asset Upgrade Specification
## Chloe Alpha: Single-Asset → 12-Asset Engine

**Version:** 1.0  
**Date:** 2025-11-25  
**Status:** Planning Phase

---

## 🎯 Goals

1. **Multi-asset by design** – Support BTC, ETH, SOL, AVAX, LINK, MATIC, ATOM, BNB, DOT, ADA, XRP, DOGE
2. **Per-asset research & risk** – Each coin has its own PF, thresholds, strengths, confidence map
3. **Minimal duplication** – No copy/paste per symbol; use registry + loops
4. **Safety** – Easy to enable paper/live per asset, with readiness check before flipping
5. **Future-proof** – Structure becomes attach points for Glassnode/Deribit integration

---

## 🧱 Phase 0 — Lock in Single-Asset Baseline

**Status:** ✅ Complete

**Current State:**
- ETHUSDT live loop working (5m timeframe)
- Research pipeline operational
- `strategy_strength.json`, `confidence_map.json`, `regime_thresholds.json` working
- Observation mode, exits, PF, SWARM, dashboard all wired

**Action:** No changes required. ETH is the reference implementation.

**Acceptance Criteria:**
- ✅ ETH trading live in paper mode
- ✅ Research outputs generating correctly
- ✅ Dashboard showing ETH metrics
- ✅ SWARM monitoring ETH health

---

## 🧩 Phase 1 — Asset Registry + Loader

**Goal:** Create single source of truth for all assets

### 1.1 Create `config/asset_registry.json`

**Structure:**
```json
{
  "ETHUSDT": {
    "enabled": true,
    "base_timeframe": "5m",
    "exchange": "bybit",
    "risk_bucket": "core",
    "min_notional": 10,
    "quote_currency": "USDT"
  },
  "BTCUSDT": {
    "enabled": false,
    "base_timeframe": "5m",
    "exchange": "bybit",
    "risk_bucket": "core",
    "min_notional": 10,
    "quote_currency": "USDT"
  },
  "SOLUSDT": {
    "enabled": false,
    "base_timeframe": "5m",
    "exchange": "bybit",
    "risk_bucket": "aggressive",
    "min_notional": 5,
    "quote_currency": "USDT"
  },
  "AVAXUSDT": {
    "enabled": false,
    "base_timeframe": "5m",
    "exchange": "bybit",
    "risk_bucket": "aggressive",
    "min_notional": 5,
    "quote_currency": "USDT"
  },
  "LINKUSDT": {
    "enabled": false,
    "base_timeframe": "5m",
    "exchange": "bybit",
    "risk_bucket": "alt",
    "min_notional": 5,
    "quote_currency": "USDT"
  },
  "MATICUSDT": {
    "enabled": false,
    "base_timeframe": "5m",
    "exchange": "bybit",
    "risk_bucket": "alt",
    "min_notional": 5,
    "quote_currency": "USDT"
  },
  "ATOMUSDT": {
    "enabled": false,
    "base_timeframe": "5m",
    "exchange": "bybit",
    "risk_bucket": "alt",
    "min_notional": 5,
    "quote_currency": "USDT"
  },
  "BNBUSDT": {
    "enabled": false,
    "base_timeframe": "5m",
    "exchange": "bybit",
    "risk_bucket": "large_alt",
    "min_notional": 10,
    "quote_currency": "USDT"
  },
  "DOTUSDT": {
    "enabled": false,
    "base_timeframe": "5m",
    "exchange": "bybit",
    "risk_bucket": "alt",
    "min_notional": 5,
    "quote_currency": "USDT"
  },
  "ADAUSDT": {
    "enabled": false,
    "base_timeframe": "5m",
    "exchange": "bybit",
    "risk_bucket": "alt",
    "min_notional": 5,
    "quote_currency": "USDT"
  },
  "XRPUSDT": {
    "enabled": false,
    "base_timeframe": "5m",
    "exchange": "bybit",
    "risk_bucket": "spec",
    "min_notional": 5,
    "quote_currency": "USDT"
  },
  "DOGEUSDT": {
    "enabled": false,
    "base_timeframe": "5m",
    "exchange": "bybit",
    "risk_bucket": "meme",
    "min_notional": 5,
    "quote_currency": "USDT"
  }
}
```

**Fields:**
- `enabled`: Boolean flag to enable/disable trading for this asset
- `base_timeframe`: Primary timeframe for trading (e.g., "5m")
- `exchange`: Exchange venue (e.g., "bybit")
- `risk_bucket`: Risk classification (core, aggressive, alt, large_alt, spec, meme)
- `min_notional`: Minimum trade size in quote currency
- `quote_currency`: Quote currency (typically "USDT")

### 1.2 Create `engine_alpha/config/asset_loader.py`

**Functions:**
```python
from dataclasses import dataclass
from typing import List, Optional
from pathlib import Path
import json

@dataclass
class AssetConfig:
    symbol: str
    enabled: bool
    base_timeframe: str
    exchange: str
    risk_bucket: str
    min_notional: float
    quote_currency: str

def load_asset_registry() -> dict:
    """Load asset_registry.json and return raw dict."""
    pass

def get_enabled_assets() -> List[AssetConfig]:
    """Return list of AssetConfig objects for enabled assets only."""
    pass

def get_asset(symbol: str) -> Optional[AssetConfig]:
    """Get AssetConfig for a specific symbol, or None if not found."""
    pass

def get_all_assets() -> List[AssetConfig]:
    """Return all assets (enabled and disabled)."""
    pass
```

**Acceptance Criteria:**
- ✅ `python3 -m engine_alpha.config.asset_loader` prints list of enabled assets (ETHUSDT only initially)
- ✅ `get_asset("ETHUSDT")` returns AssetConfig with correct fields
- ✅ `get_asset("BTCUSDT")` returns AssetConfig even if disabled
- ✅ `get_enabled_assets()` filters to enabled=True only

---

## 🔁 Phase 2 — Multi-Asset Live Loop Driver

**Goal:** Run trading loop for all enabled assets

### 2.1 Create `engine_alpha/loop/multi_asset_runner.py`

**Structure:**
```python
from engine_alpha.config.asset_loader import get_enabled_assets
from engine_alpha.loop.autonomous_trader import run_step_live
import logging

logger = logging.getLogger(__name__)

def run_multi_asset_step():
    """
    Run one step of the trading loop for all enabled assets.
    Called by systemd service on 5m schedule.
    """
    enabled = get_enabled_assets()
    
    if not enabled:
        logger.warning("No enabled assets found in asset_registry.json")
        return
    
    for asset in enabled:
        try:
            logger.info(f"Running step for {asset.symbol} ({asset.base_timeframe})")
            run_step_live(
                symbol=asset.symbol,
                timeframe=asset.base_timeframe
            )
        except Exception as e:
            logger.error(f"Error running step for {asset.symbol}: {e}", exc_info=True)
            # Continue with next asset instead of crashing entire loop
            continue
```

### 2.2 Update Systemd Service

**File:** `/etc/systemd/system/chloe.service`

**Changes:**
- Update `ExecStart` to call `python3 -m engine_alpha.loop.multi_asset_runner`
- Keep 5m timer schedule
- Ensure error handling doesn't crash entire service

**Acceptance Criteria:**
- ✅ Logs show `run_step_live` being called for ETHUSDT only (initially)
- ✅ When `BTCUSDT.enabled=true` is set, BTC appears in logs
- ✅ Each asset's step runs independently (errors in one don't block others)
- ✅ Service continues running even if one asset fails

**Note:** At this phase, BTC will still use ETH's configs/research until Phase 4.

---

## 📊 Phase 3 — Per-Symbol PF & Risk Accounting

**Goal:** Isolate PF and risk calculations per asset

### 3.1 Per-Symbol PF Files

**Current:** `reports/pf_local.json` (single file)

**New Structure:**
```
reports/pf/
  ├── pf_ETHUSDT.json
  ├── pf_BTCUSDT.json
  ├── pf_SOLUSDT.json
  └── ...
```

**Migration:**
- Move existing `pf_local.json` → `reports/pf/pf_ETHUSDT.json`
- Update PF code to accept `symbol` parameter:
  - `load_pf(symbol: str) -> dict`
  - `update_pf(symbol: str, trades: List[dict]) -> dict`
  - `get_pf_path(symbol: str) -> Path`

**Optional:** Keep `pf_local.json` as portfolio aggregate (sum of all assets)

### 3.2 Risk Engine Awareness

**Update `engine_alpha/risk/risk_autoscaler.py`:**

```python
def compute_risk_multiplier(
    symbol: str,
    regime: str,
    confidence: float,
    # ... other params
) -> float:
    """
    Compute risk multiplier for a specific symbol.
    Uses per-symbol PF for trade sizing.
    """
    # Load per-symbol PF
    pf_local_symbol = load_pf(symbol)
    
    # Optional: Load portfolio PF as high-level clamp
    pf_portfolio = load_pf_portfolio()  # Aggregate of all assets
    
    # Use symbol-specific PF for sizing decisions
    # Use portfolio PF as safety clamp (e.g., if portfolio PF < 0.9, reduce all)
    
    return multiplier
```

**Update `engine_alpha/loop/execute_trade.py`:**
- `gate_and_size_trade()` accepts `symbol` parameter
- Passes `symbol` to `compute_quant_position_size()` and `check_sanity()`

**Acceptance Criteria:**
- ✅ Dry-run per symbol picks up correct PF file
- ✅ When BTC has trades and ETH doesn't, their PFs diverge independently
- ✅ Portfolio PF (if implemented) aggregates correctly
- ✅ Risk multipliers computed per-symbol, not globally

---

## 📚 Phase 4 — Per-Symbol Research Outputs

**Goal:** Split research pipeline by symbol while reusing existing logic

### 4.1 Hybrid Dataset Per Symbol

**Current:** `reports/research/hybrid_research_dataset.parquet`

**New Structure:**
```
reports/research/
  ├── ETHUSDT/
  │   ├── hybrid_research_dataset.parquet
  │   ├── multi_horizon_stats.json
  │   ├── strategy_strength.json
  │   └── trade_outcomes.jsonl
  ├── BTCUSDT/
  │   ├── hybrid_research_dataset.parquet
  │   └── ...
  └── ...
```

**Update `engine_alpha/reflect/research_dataset_builder.py`:**
- Accept `symbol` and `timeframe` parameters
- Write to `RESEARCH_DIR / symbol / "hybrid_research_dataset.parquet"`
- For ETH, keep current behavior but namespaced

### 4.2 Analyzer & Tuner Per Symbol

**Option A: Per-Symbol Files (Recommended)**
```
config/
  ├── confidence_map.json  # {"ETHUSDT": {...}, "BTCUSDT": {...}}
  └── regime_thresholds.json  # {"ETHUSDT": {...}, "BTCUSDT": {...}}

reports/research/
  ├── ETHUSDT/
  │   └── strategy_strength.json
  └── BTCUSDT/
      └── strategy_strength.json
```

**Option B: Single Files with Symbol Keys**
```json
{
  "ETHUSDT": {
    "chop": { "enabled": false, "entry_min_conf": 0.75 },
    "high_vol": { "enabled": true, "entry_min_conf": 0.48 }
  },
  "BTCUSDT": {
    "chop": { "enabled": false, "entry_min_conf": 0.75 },
    "high_vol": { "enabled": true, "entry_min_conf": 0.50 }
  }
}
```

**Update Functions:**
- `_lookup_conf_edge(confidence: float, symbol: str) -> float`
- `_lookup_regime_strength(regime: str, symbol: str) -> dict`
- `_load_regime_enable(symbol: str) -> dict`
- `compute_entry_min_conf(regime: str, risk_band: str, symbol: str) -> float`

### 4.3 Nightly Research Loop Per Symbol

**Update `tools/nightly_research.py`:**

**Option A: Loop Over Enabled Assets**
```python
from engine_alpha.config.asset_loader import get_enabled_assets

def main():
    enabled = get_enabled_assets()
    
    for asset in enabled:
        logger.info(f"Running nightly research for {asset.symbol}")
        run_nightly_research(
            symbol=asset.symbol,
            timeframe=asset.base_timeframe
        )
```

**Option B: CLI Flag + Systemd Per Symbol**
```python
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    args = parser.parse_args()
    
    run_nightly_research(
        symbol=args.symbol,
        timeframe=get_asset(args.symbol).base_timeframe
    )
```

**Systemd Timer:**
- Option A: Single timer runs all enabled assets
- Option B: Separate timer per symbol (more granular control)

**Acceptance Criteria:**
- ✅ ETH research continues working, now under `reports/research/ETHUSDT/`
- ✅ When BTC enabled and nightly runs, BTCUSDT research files appear
- ✅ Each symbol's research outputs are independent
- ✅ Confidence maps and thresholds load correctly per symbol

---

## 📊 Phase 5 — Dashboard + SWARM: Multi-Asset Aware

**Goal:** Update UI and monitoring for per-symbol views

### 5.1 Dashboard Updates

**File:** `engine_alpha/dashboard/quant_panel.py`

**Changes:**
```python
from engine_alpha.config.asset_loader import get_enabled_assets

def render():
    st.title("Quant View — Regimes & Confidence")
    
    # Symbol selector
    enabled = get_enabled_assets()
    symbols = sorted([asset.symbol for asset in enabled])
    
    if not symbols:
        st.warning("No enabled assets found.")
        return
    
    symbol = st.selectbox("Symbol", symbols)
    
    # Load per-symbol research outputs
    strength_path = RESEARCH_DIR / symbol / "strategy_strength.json"
    thresholds_path = CONFIG_DIR / "regime_thresholds.json"  # Load by symbol key
    conf_map_path = CONFIG_DIR / "confidence_map.json"  # Load by symbol key
    
    # ... rest of rendering logic
```

**File:** `engine_alpha/dashboard/home_panel.py`

**Changes:**
- Show per-symbol PF tiles
- Add portfolio aggregate PF tile
- Symbol selector for detailed view

**File:** `engine_alpha/dashboard/risk_panel.py`

**Changes:**
- Per-symbol risk multipliers
- Portfolio-level risk summary

### 5.2 SWARM Per-Symbol Awareness

**File:** `engine_alpha/swarm/swarm_sentinel.py`

**Changes:**
```python
from engine_alpha.config.asset_loader import get_enabled_assets

def run_sentinel_checks() -> dict:
    enabled = get_enabled_assets()
    
    results = {}
    for asset in enabled:
        results[asset.symbol] = {
            "pf": load_pf(asset.symbol),
            "avg_edge": compute_avg_edge(asset.symbol),
            "blind_spots": check_blind_spots(asset.symbol)
        }
    
    return results
```

**File:** `engine_alpha/swarm/swarm_audit_loop.py`

**Changes:**
```python
def run_audit() -> dict:
    enabled = get_enabled_assets()
    
    audit_results = {}
    for asset in enabled:
        audit_results[asset.symbol] = {
            "research_files_exist": check_research_files(asset.symbol),
            "thresholds_exist": check_thresholds(asset.symbol),
            "strengths_exist": check_strengths(asset.symbol),
            "pf_exists": check_pf(asset.symbol)
        }
    
    return audit_results
```

**File:** `engine_alpha/swarm/swarm_research_verifier.py`

**Changes:**
- Accept `symbol` parameter or loop over all enabled assets
- Verify per-symbol research outputs

**Acceptance Criteria:**
- ✅ Dashboard can switch between ETH, BTC, SOL, etc., showing correct metrics
- ✅ SWARM audit output enumerates readiness per symbol
- ✅ Home panel shows portfolio aggregate alongside per-symbol tiles
- ✅ Risk panel shows per-symbol risk multipliers

---

## 🧪 Phase 6 — Asset Readiness Auditor

**Goal:** "Infra Quant" that checks architecture & engineering before deployment

### 6.1 Create `tools/asset_audit.py`

**Responsibilities Per Symbol:**

1. **Config Check:**
   - Exists in `asset_registry.json`
   - `enabled` flag present
   - `base_timeframe`, `exchange`, `risk_bucket`, `min_notional` present

2. **Data Check:**
   - `data/ohlcv/{symbol}_{tf}_live.csv` exists and has > N rows (e.g., 200)
   - No excessive gaps in timestamps
   - Data freshness (last candle within last 2 timeframes)

3. **Research Check:**
   - `reports/research/{symbol}/hybrid_research_dataset.parquet` exists
   - Dataset has sufficient rows (e.g., > 1000)
   - `multi_horizon_stats.json` present and non-empty
   - `strategy_strength.json` present and sample counts > threshold (e.g., > 50)
   - `confidence_map.json` not all zeros

4. **Threshold Check:**
   - `regime_thresholds.json` contains this symbol
   - At least one regime enabled with sane `entry_min_conf` (0.3-0.9 range)
   - No regimes with impossible thresholds (> 1.0)

5. **Risk Check:**
   - `reports/pf/pf_{symbol}.json` exists or plan for starting PF=1.0
   - Notional caps configured for its `risk_bucket`
   - Risk multipliers computable

**Output Format:**
```json
{
  "ETHUSDT": {
    "config_ok": true,
    "data_ok": true,
    "research_ok": true,
    "thresholds_ok": true,
    "risk_ok": true,
    "ready_for_paper": true,
    "ready_for_live": false,
    "issues": []
  },
  "BTCUSDT": {
    "config_ok": true,
    "data_ok": true,
    "research_ok": false,
    "thresholds_ok": false,
    "risk_ok": false,
    "ready_for_paper": false,
    "ready_for_live": false,
    "issues": [
      "No research outputs yet (run nightly_research for BTCUSDT).",
      "No thresholds defined for BTCUSDT.",
      "No PF file for BTCUSDT (start at 1.0 after some paper trades)."
    ]
  }
}
```

**CLI Interface:**
```bash
# Audit all enabled assets
python3 -m tools.asset_audit

# Audit specific asset
python3 -m tools.asset_audit --symbol BTCUSDT

# Check readiness for live trading
python3 -m tools.asset_audit --symbol BTCUSDT --for-live
```

### 6.2 Pre-Flight Checklist

**Before Enabling Paper Trading:**
1. Run `python3 -m tools.asset_audit --symbol BTCUSDT`
2. Verify `ready_for_paper: true`
3. Review `issues` list (should be empty)
4. Set `"enabled": true` in `asset_registry.json`
5. Monitor first few trades closely

**Before Enabling Live Trading:**
1. Run `python3 -m tools.asset_audit --symbol BTCUSDT --for-live`
2. Verify `ready_for_live: true`
3. Review paper trading performance (PF > 1.0, reasonable win rate)
4. Ensure wallet limits configured appropriately
5. Set `wallet_mode: "real"` (or per-symbol real mode if implemented)

**Acceptance Criteria:**
- ✅ For ETH: All checks pass, `ready_for_paper: true`
- ✅ For new symbols: Clear "what's missing" checklist before enabling
- ✅ `ready_for_live` only flips when all checks pass AND paper performance validated
- ✅ Issues list provides actionable next steps

---

## 🧱 Implementation Order

### Phase Sequence:
1. **Phase 1** → Asset registry + loader (foundation)
2. **Phase 2** → Multi-asset runner (enables parallel trading)
3. **Phase 3** → Per-symbol PF & risk (prevents cross-contamination)
4. **Phase 4** → Per-symbol research (enables independent learning)
5. **Phase 5** → Dashboard + SWARM updates (visibility)
6. **Phase 6** → Asset readiness auditor (safety)

### Dependencies:
- Phase 2 depends on Phase 1
- Phase 3 can start after Phase 1 (PF isolation)
- Phase 4 depends on Phase 1 (symbol awareness)
- Phase 5 depends on Phases 3-4 (per-symbol data)
- Phase 6 depends on all previous phases (checks everything)

### Parallel Work:
- Phases 3 and 4 can be worked on in parallel after Phase 1
- Phase 5 can start after Phase 3 is complete (dashboard can show PF before research is split)

---

## 🎯 Success Metrics

**After Phase 1-2:**
- ✅ Multiple assets can be enabled/disabled via config
- ✅ Live loop runs for all enabled assets

**After Phase 3:**
- ✅ Per-symbol PF isolation working
- ✅ Risk multipliers computed independently

**After Phase 4:**
- ✅ Each asset has independent research outputs
- ✅ Nightly research runs per symbol

**After Phase 5:**
- ✅ Dashboard shows per-symbol metrics
- ✅ SWARM monitors all enabled assets

**After Phase 6:**
- ✅ Clear readiness checklist before enabling new assets
- ✅ Automated pre-flight checks prevent bad deployments

---

## 🔮 Future Enhancements

**Post-Phase 6:**
- Glassnode integration per symbol
- Deribit options data per symbol
- Cross-asset correlation analysis
- Portfolio-level risk management
- Per-exchange asset routing
- Dynamic asset enablement based on market conditions

---

## 📝 Notes

- **Backward Compatibility:** ETH should continue working throughout all phases
- **Testing:** Each phase should be tested with ETH first before adding new assets
- **Rollback:** Keep ability to disable assets quickly if issues arise
- **Documentation:** Update README and docs as each phase completes

---

**Next Steps:** When ready to begin, say: "Let's start Phase 1 – asset_registry.json and loader."


