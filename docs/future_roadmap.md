# FUTURE ROADMAP — ALPHA CHLOE QUANT SYSTEM

*(Official master roadmap — persistent, developer-facing)*  

---

## 0. Purpose

This document defines all features, enhancements, and major architectural upgrades planned for Chloe’s evolution beyond the current Phase‑0 paper loop.  
It acts as the single source of truth for Cursor, GPT, and future developer tooling.

---

## 1. Market Data & Signal Layer Upgrades

### 1.1 Funding Bias (Perp Funding Signal)
**Status:** High priority — **not implemented yet**

- Aggregate perp funding from Bybit → Binance Futures → OKX.  
- Compute:
  - Raw funding rate  
  - Funding divergence (funding vs spot drift)  
  - Multi-exchange funding spread  
  - Crowding detection (positive funding + long bias vs negative + short bias)  
- Integrate into decision engine:
  - Modifies dir/conf heuristics  
  - Influences edge scoring  
  - Appears in reflections  
  - Used by opportunist scanner  

### 1.2 Expanded Multi-Timeframe Signal Model
**Status:** Option A enabled

- Add higher-timeframe (HTF) signal computation (1h / 4h):
  - Returns: `RET_1H`, `RET_4H`  
  - Volatility: `REALVOL_1H`, `REALVOL_4H`  
  - Trend: `SLOPE_1H`, `SLOPE_4H`  
  - RSI / MACD for HTFs  
  - HTF regime confirmation  
  - HTF–LTF trend alignment map  
- Integrate with:
  - Dir/conf scoring  
  - Reflections  
  - Staleness analyst  
  - Market-state panel  

### 1.3 Multi-timeframe Feed Layer
**Status:** Not implemented yet

- Extend live OHLCV fetch to 1h and 4h  
- HTF aggregation + regime detection  
- HTF influence on LTF entry gates  

---

## 2. Regime & Gating Intelligence

### 2.1 Adaptive Regime Allow-Lists
- Current: All coins can trade `trend_up`, `trend_down`, `high_vol` (DOGE includes `chop`).  
- Future: Allow automatic gating based on:
  - Volatility slope  
  - Number of trend-confirmed signals  
  - HTF alignment  
  - Funding bias  
  - Breadth scores  

### 2.2 Quant-Prioritized Soft Mode (Dynamic Loosen Flags)
- Soft mode toggles automatically when:
  - Long inactivity  
  - Major regime shift  
  - Low-volatility environments  
  - GPT reflection consensus  
- Integrates with:
  - Observation mode  
  - Confidence thresholds  
  - Edge floors  
  - Dynamic size factors  

---

## 3. Universe & Opportunist Layer

### 3.1 Dynamic Universe (Option D)
- Maintain EWMAs for volatility/liquidity per symbol  
- Rank top coins daily  
- Replace static fallback universe  
- Expand universe based on:
  - New listings  
  - High-volume movers  
  - Trending social sentiment (future option)  

### 3.2 Opportunist Scanner (Volatility Hunter)
**Status:** Scaffold built, full implementation pending

- Scan Bybit → Binance → OKX for movers  
- Filter via liquidity + realized vol  
- Micro-research: trend/volatility/funding/sentiment snapshot  
- Paper-only small entries  
- Feed opportunist trades into reflections  
- Auto-adjust main universe  

---

## 4. Reflections & Intelligence Layer

### 4.1 Signal-Informed Reflections
- Inject full signal context:
  - All LTF/HTF signals  
  - Funding  
  - Market-state summary  
  - Staleness patterns  
  - Recent gate failures  

### 4.2 Meta-Reflections
- Already built; next steps:
  - Forward-looking recommendations  
  - Risk/bias identification  
  - Multi-timeframe trend commentary  
  - Auto-summarized universe movement  

### 4.3 GPT-Assisted Autonomous Feedback
**Status:** Not built (approved)

- Use all signals + reflections to propose:
  - Threshold adjustments  
  - Regime allow-list changes  
  - Portfolio tilts  
  - Universe additions/removals  
- Add guardrails before any changes touch live configs.  

---

## 5. Multi-Asset Strategy Evolution

### 5.1 HTF Strategy Layer
- Introduce dedicated HTF strategies:
  - Trend-following  
  - Breakout  
  - Mean reversion  
  - Volatility compression expansions  

### 5.2 Strategy Evolver / Mutator
**Status:** Planned for Build 9+**

- Clone strategies, mutate thresholds  
- Score via PF/local research  
- Archive lineages  
- Promote/demote via overseer  

### 5.3 Mirror Intelligence Tools
- Observe “smart wallets,” infer patterns  
- Compete/shadow/replicate  
- Save memory logs  
- Feed evolution engine  

---

## 6. Future Research Tools

### 6.1 Full Multi-Timeframe Analyzer
- 15m / 1h / 4h data fusion  
- HTF regime boundaries  
- Strategy scorecards per timeframe  
- Confidence recalibration per TF  

### 6.2 Market Breadth Engine
- Track major movers, cross-asset correlations, vol-of-vol  
- Stable/BTC dominance effects  
- Trend breadth score  

### 6.3 Risk Macros
- Synthetic VIX-style index  
- Stablecoin inflow/outflow tracker  
- Liquidity conditions, funding crowding, OI shifts  

---

## 7. Memory & Data Integration

### 7.1 Historical Reflections Compression
- Daily summarization  
- “Context pack” for GPT  
- Temporal memory shaping  

### 7.2 Signal History Learning
- Analyze signal behavior over last N bars  
- Detect patterns linked to profitable trades  
- Feed tuner proposals with pattern memory  

---

## 8. Miscellaneous Future Enhancements
- Per-asset health scoring  
- Feed rotation/health fallback for MATIC  
- Improved OHLCV smoothing  
- Long-term bias tracking  
- Funding regime maps  
- Volatility cluster detection  
- HTF / ML-based signal forecasting (optional future extension)  

---

**📌 End of Roadmap**


