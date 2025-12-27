# Advanced Research (Phase 5)

## Overview

Phase 5 adds advanced research scans for deeper signal intelligence:
- **Drift Tracking**: Detects signal degradation over time
- **Correlation Analysis**: Identifies diversification opportunities
- **Alpha/Beta Decomposition**: Separates idiosyncratic vs market-driven returns

## Components

### 1. Drift Tracker

**Purpose**: Identify symbols with degrading or improving performance over time.

**How it works**:
- Splits exploration trades into early vs recent windows (default: first 5 vs last 5)
- Computes PF and average return for each window
- Compares to detect improving/degrading/stable patterns

**Output**: `reports/research/drift_report.json`

```json
{
  "generated_at": "...",
  "symbols": {
    "ETHUSDT": {
      "early_avg_pct": 0.012,
      "recent_avg_pct": 0.015,
      "early_pf": 1.2,
      "recent_pf": 1.4,
      "delta_pf": 0.2,
      "status": "improving",
      "total_trades": 15
    },
    "ATOMUSDT": {
      "early_avg_pct": 0.005,
      "recent_avg_pct": -0.003,
      "early_pf": 1.1,
      "recent_pf": 0.8,
      "delta_pf": -0.3,
      "status": "degrading",
      "total_trades": 12
    }
  }
}
```

**Usage**:
```bash
python3 -m tools.run_drift_scan
```

**Integration**: Used by Reflection v3 and Tuner v3 to inform tier assignments and tuning proposals.

### 2. Correlation Engine

**Purpose**: Understand diversification and identify highly correlated symbol pairs.

**How it works**:
- Aligns returns by timestamp across all symbols
- Computes Pearson correlation coefficient for each symbol pair
- Identifies most/least correlated pairs

**Output**: `reports/research/correlation_matrix.json`

```json
{
  "generated_at": "...",
  "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", ...],
  "matrix": {
    "BTCUSDT": {
      "BTCUSDT": 1.0,
      "ETHUSDT": 0.85,
      "SOLUSDT": 0.65
    },
    ...
  }
}
```

**Usage**:
```bash
python3 -m tools.run_correlation_scan
```

**Interpretation**:
- **High correlation (>0.8)**: Symbols move together - limited diversification benefit
- **Low correlation (<0.3)**: Symbols move independently - good diversification
- **Negative correlation**: Symbols move opposite - excellent diversification

**Integration**: Used for portfolio construction and risk management decisions.

### 3. Alpha/Beta Decomposition

**Purpose**: Separate idiosyncratic returns (alpha) from market-driven returns (beta).

**How it works**:
- Uses BTCUSDT as market benchmark
- For each symbol, computes linear regression: `pct_symbol ~ alpha + beta * pct_btc`
- Alpha = intercept (idiosyncratic return)
- Beta = slope (market sensitivity)

**Output**: `reports/research/alpha_beta.json`

```json
{
  "generated_at": "...",
  "benchmark": "BTCUSDT",
  "symbols": {
    "ETHUSDT": {
      "alpha": 0.0005,
      "beta": 1.1,
      "sample_size": 25
    },
    "ATOMUSDT": {
      "alpha": -0.0002,
      "beta": 0.8,
      "sample_size": 18
    }
  }
}
```

**Usage**:
```bash
python3 -m tools.run_alpha_beta_scan
```

**Interpretation**:
- **Alpha > 0**: Symbol outperforms market (idiosyncratic edge)
- **Alpha < 0**: Symbol underperforms market
- **Beta = 1.0**: Moves 1:1 with market
- **Beta > 1.0**: More volatile than market
- **Beta < 1.0**: Less volatile than market

**Integration**: Used to understand whether returns are strategy-driven (alpha) or market-driven (beta).

## Integration with Research Cycles

### Reflection v3

Reflection can use drift status to inform tier assignments:
- **Improving**: May promote to tier1 or keep in tier1
- **Degrading**: May demote to tier3 or keep in tier3
- **Stable**: Maintains current tier

### Tuner v3

Tuner can use drift status for multi-source agreement:
- **Degrading + Weak PF**: Strong signal to tighten thresholds
- **Improving + Strong PF**: Signal to consider loosening thresholds

### Portfolio Construction

Correlation matrix informs:
- **Diversification**: Prefer low-correlation symbols
- **Risk concentration**: Avoid over-exposure to highly correlated pairs
- **Hedging**: Use negative correlations for risk reduction

### Capital Allocation

Alpha/beta decomposition informs:
- **High alpha symbols**: Deserve more capital (idiosyncratic edge)
- **High beta symbols**: Require more capital buffer (higher volatility)
- **Low alpha symbols**: Consider reducing allocation (no edge)

## Usage in Nightly Research Cycle

All three scans can be added to `nightly_research_cycle.py`:

```python
research_steps = [
    # ... existing steps ...
    ("DriftScan", "tools.run_drift_scan", "main"),
    ("CorrelationScan", "tools.run_correlation_scan", "main"),
    ("AlphaBetaScan", "tools.run_alpha_beta_scan", "main"),
    # ... rest of steps ...
]
```

## Safety

- **Read-only**: All scans read from `trades.jsonl`, never modify configs
- **Advisory-only**: Outputs are for analysis, not automatic trading decisions
- **Non-blocking**: Scans can fail without affecting other research cycles

## Future Enhancements

- **Regime-specific correlation**: Correlation varies by market regime
- **Rolling correlation**: Track correlation changes over time
- **Factor models**: Decompose returns into multiple factors (momentum, volatility, etc.)
- **Cointegration**: Identify long-term relationships between symbols

