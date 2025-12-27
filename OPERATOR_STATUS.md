# OPERATOR_STATUS.md - Chloe Health Dashboard Spec

## Purpose

Single-page status report that answers: **"Is Chloe safe to let run, and at what risk?"**

Run via: `python tools/operator_status.py` or `python -m engine_alpha.tools.operator_status`

Outputs: Console report + `reports/operator_status.json` (machine-readable)

---

## Required Metrics

### 1. PF & Performance

**PF_local (Paper + Live)**
- Last 50 trades (paper)
- Last 50 trades (live, if any)
- Overall PF_local (all trades)
- Win rate, avg win, avg loss

**PF_by_regime**
- TREND_UP: PF, trades, win_rate
- TREND_DOWN: PF, trades, win_rate
- CHOP: PF, trades, win_rate
- HIGH_VOL: PF, trades, win_rate
- Any regime with PF < 0.8 flagged

**PF_by_confidence_band**
- [0.0-0.3]: PF, trades
- [0.3-0.6]: PF, trades
- [0.6-0.8]: PF, trades
- [0.8-1.0]: PF, trades
- Flag if high-confidence bands (0.6-1.0) have PF < low-confidence bands

---

### 2. Drift & Calibration

**DriftState**
- `drift_score` (0-1, current)
- `pf_local` (recent window)
- `confidence_return_corr` (recent window)
- Trend: improving / stable / degrading

**Drift History** (last 10 windows)
- Show drift_score over time
- Flag if drift_score > 0.7 for > 3 consecutive windows

---

### 3. Confidence Behavior

**ConfidenceState Distribution** (last 100 decisions)
- Mean confidence
- Std dev
- Min/Max
- Distribution histogram (buckets: 0-0.3, 0.3-0.6, 0.6-0.8, 0.8-1.0)

**Component Breakdown** (averages)
- Flow component
- Volatility component
- Microstructure component
- Cross-asset component

**Penalty Activity**
- Regime penalty: % of time < 1.0, avg value
- Drift penalty: % of time < 1.0, avg value

**Calibration Check**
- Confidence → Return correlation (should be positive)
- High-confidence trades should outperform low-confidence trades

---

### 4. Trade Frequency & Size

**Entry Activity**
- Total entry attempts (last 100 ticks)
- Entries accepted (should_enter_trade returned True)
- Entry rejection reasons breakdown:
  - Low confidence
  - High drift
  - Zero size
  - Neutral signals

**Size Distribution**
- size_multiplier histogram
- Avg size_multiplier for entries
- Max size_multiplier observed

**Exit Activity**
- Total exits (last 100 ticks)
- Exit reasons breakdown:
  - Confidence drop
  - Drift spike
  - Regime flip
  - Legacy (drop/decay/flip)

---

### 5. Model State Verdict

**MODEL_STATE: HEALTHY / UNHEALTHY / WATCH**

**HEALTHY** if:
- PF_local ≥ 1.0
- High-confidence band PF ≥ 1.05
- confidence_return_corr > 0.2
- drift_score < 0.5
- No regime with catastrophic PF (< 0.7) and > 10 trades

**UNHEALTHY** if:
- PF_local < 0.9
- High-confidence band PF < 1.0
- confidence_return_corr < 0
- drift_score > 0.8 for > 3 windows
- Any regime with PF < 0.5 and > 5 trades

**WATCH** if:
- PF_local between 0.9-1.0
- High-confidence band PF between 1.0-1.05
- drift_score between 0.5-0.8
- confidence_return_corr between 0-0.2

---

## Output Format

### Console Output (Human-Readable)

```
╔══════════════════════════════════════════════════════════════╗
║              CHLOE OPERATOR STATUS DASHBOARD                 ║
╚══════════════════════════════════════════════════════════════╝

📊 PERFORMANCE
  PF_local (last 50): 1.23
  PF_local (all): 1.15
  Win rate: 58%
  Avg win: +2.1% | Avg loss: -1.4%

📈 PF BY REGIME
  TREND_UP:    PF=1.32, trades=45, win_rate=62%
  TREND_DOWN:  PF=1.18, trades=38, win_rate=55%
  CHOP:        PF=0.95, trades=12, win_rate=50% ⚠️
  HIGH_VOL:    PF=1.05, trades=8, win_rate=56%

📊 PF BY CONFIDENCE BAND
  [0.0-0.3]:  PF=0.85, trades=5
  [0.3-0.6]:  PF=1.05, trades=18
  [0.6-0.8]:  PF=1.22, trades=42 ✅
  [0.8-1.0]:  PF=1.35, trades=35 ✅

🔍 DRIFT & CALIBRATION
  drift_score: 0.18 (LOW)
  pf_local: 1.23
  confidence_return_corr: 0.34 ✅
  Trend: STABLE

🎯 CONFIDENCE BEHAVIOR
  Mean confidence: 0.68
  Std dev: 0.18
  Distribution: [0-0.3: 8%] [0.3-0.6: 25%] [0.6-0.8: 42%] [0.8-1.0: 25%]
  
  Components (avg):
    Flow: 0.72
    Volatility: 0.58
    Microstructure: 0.45
    Cross-asset: 0.38
  
  Penalties:
    Regime penalty < 1.0: 12% of time (avg: 0.92)
    Drift penalty < 1.0: 8% of time (avg: 0.88)

📈 TRADE ACTIVITY
  Entry attempts: 100
  Entries accepted: 23 (23%)
  Rejections:
    Low confidence: 52
    High drift: 8
    Zero size: 12
    Neutral signals: 5
  
  Size distribution:
    Avg size_multiplier: 0.85
    Max observed: 1.8x
    [0.0-0.5: 45%] [0.5-1.0: 35%] [1.0-1.5: 15%] [1.5+: 5%]

╔══════════════════════════════════════════════════════════════╗
║  MODEL_STATE: ✅ HEALTHY                                     ║
║                                                              ║
║  Ready for paper trading. Monitor drift_score and          ║
║  CHOP regime performance.                                    ║
╚══════════════════════════════════════════════════════════════╝
```

### JSON Output (`reports/operator_status.json`)

```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "model_state": "HEALTHY",
  "performance": {
    "pf_local_last50": 1.23,
    "pf_local_all": 1.15,
    "win_rate": 0.58,
    "avg_win_pct": 0.021,
    "avg_loss_pct": -0.014
  },
  "pf_by_regime": {
    "TREND_UP": {"pf": 1.32, "trades": 45, "win_rate": 0.62},
    "TREND_DOWN": {"pf": 1.18, "trades": 38, "win_rate": 0.55},
    "CHOP": {"pf": 0.95, "trades": 12, "win_rate": 0.50, "flag": "low_pf"},
    "HIGH_VOL": {"pf": 1.05, "trades": 8, "win_rate": 0.56}
  },
  "pf_by_confidence_band": {
    "0.0-0.3": {"pf": 0.85, "trades": 5},
    "0.3-0.6": {"pf": 1.05, "trades": 18},
    "0.6-0.8": {"pf": 1.22, "trades": 42},
    "0.8-1.0": {"pf": 1.35, "trades": 35}
  },
  "drift": {
    "drift_score": 0.18,
    "pf_local": 1.23,
    "confidence_return_corr": 0.34,
    "trend": "STABLE"
  },
  "confidence": {
    "mean": 0.68,
    "std": 0.18,
    "distribution": {
      "0.0-0.3": 0.08,
      "0.3-0.6": 0.25,
      "0.6-0.8": 0.42,
      "0.8-1.0": 0.25
    },
    "components_avg": {
      "flow": 0.72,
      "volatility": 0.58,
      "microstructure": 0.45,
      "cross_asset": 0.38
    },
    "penalties": {
      "regime": {"pct_below_1": 0.12, "avg_when_below": 0.92},
      "drift": {"pct_below_1": 0.08, "avg_when_below": 0.88}
    }
  },
  "trade_activity": {
    "entry_attempts": 100,
    "entries_accepted": 23,
    "rejections": {
      "low_confidence": 52,
      "high_drift": 8,
      "zero_size": 12,
      "neutral_signals": 5
    },
    "size_distribution": {
      "avg": 0.85,
      "max": 1.8,
      "histogram": {
        "0.0-0.5": 0.45,
        "0.5-1.0": 0.35,
        "1.0-1.5": 0.15,
        "1.5+": 0.05
      }
    }
  },
  "flags": [
    "CHOP regime PF below 1.0 (0.95)"
  ],
  "recommendations": [
    "Monitor CHOP regime performance",
    "Consider raising entry_min_confidence if drift increases"
  ]
}
```

---

## Implementation Notes

- Use `engine_alpha/reflect/trade_analysis.py` for PF calculations
- Use `engine_alpha/core/drift_detector.py` for drift metrics
- Load recent trades from `reports/trades.jsonl`
- Load recent decisions from loop logs (if available) or compute on-the-fly
- Cache expensive computations (e.g., PF by regime) for performance
- Update `reports/operator_status.json` on each run
- Add `--json-only` flag for machine-readable output
- Add `--verbose` flag for detailed breakdowns

---

## Usage

```bash
# Full console report + JSON
python tools/operator_status.py

# JSON only (for scripts/dashboards)
python tools/operator_status.py --json-only

# Verbose (include all metrics)
python tools/operator_status.py --verbose
```

---

## Integration

- Can be called from cron/periodic jobs
- Can be integrated into monitoring dashboards
- Can trigger alerts if MODEL_STATE becomes UNHEALTHY
- Can be used in CI/CD to gate deployments

