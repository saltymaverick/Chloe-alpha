# Pro-Quant Mode: Risk Management & Monitoring

Chloe's pro-quant risk management and monitoring system provides enterprise-grade safety layers, position sizing, and real-time health monitoring.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Live Trading Loop                        │
│  (autonomous_trader.py)                                     │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│              gate_and_size_trade()                          │
│  (execute_trade.py)                                         │
│  • Sanity gates                                             │
│  • Edge checks                                              │
│  • Risk autoscaler                                          │
│  • Profit Amplifier multiplier                              │
└────────────────────┬────────────────────────────────────────┘
                     │
         ┌───────────┴───────────┐
         ▼                       ▼
┌──────────────────┐    ┌──────────────────┐
│  sanity_gates    │    │ risk_autoscaler  │
│  check_sanity()  │    │ compute_risk_    │
│                  │    │ multiplier()     │
└──────────────────┘    └──────────────────┘
         │                       │
         └───────────┬───────────┘
                     ▼
         ┌──────────────────────┐
         │ position_manager      │
         │ compute_quant_        │
         │ position_size()       │
         └──────────────────────┘
```

## Components

### 1. Sanity Gates (`engine_alpha/risk/sanity_gates.py`)

**Purpose**: Global safety layer that checks if trading is even allowed.

**Function**: `check_sanity(regime, confidence) -> SanityDecision`

**Checks**:
- **PF_local guard**: Hard block if PF < 0.85, warn if PF < 0.95
- **Regime strength guard**: Block if regime has strong negative strength (with sufficient data)
- **Blind spot guard**: Block if blind spots flagged + low confidence

**Returns**:
```python
SanityDecision(
    allow_trade: bool,
    severity: str,  # "ok", "warn", "hard_block"
    reason: str
)
```

### 2. Risk Auto-Scaler (`engine_alpha/risk/risk_autoscaler.py`)

**Purpose**: Position sizing based on multiple risk factors.

**Function**: `compute_risk_multiplier(ctx: RiskContext) -> float`

**Factors**:
- **PF_local**: Scale up if PF > 1.2, scale down if PF < 0.95
- **Drawdown**: Clamp to 0.5x if DD > 20%, 0.7x if DD > 10%
- **Edge**: Scale up if edge > 0.001, scale down if edge < 0
- **Volatility**: Scale down in high vol (0.6x if vol > 0.8)
- **Confidence**: Scale up if conf > 0.8, scale down if conf < 0.5

**Returns**: Multiplier in range [0.2, 2.0]

### 3. Quant Position Sizing (`engine_alpha/loop/position_manager.py`)

**Function**: `compute_quant_position_size(base_notional, regime, confidence, volatility_norm) -> float`

**Process**:
1. Loads `pf_local.json` for PF and drawdown
2. Looks up expected edge from `confidence_map.json` (by confidence bucket)
3. Looks up regime edge from `strategy_strength.json`
4. Combines edges: `(conf_edge + regime_edge) / 2.0`
5. Creates `RiskContext` and calls `compute_risk_multiplier()`
6. Returns `base_notional * multiplier`

### 4. Gate & Size Trade (`engine_alpha/loop/execute_trade.py`)

**Function**: `gate_and_size_trade(symbol, side, regime, confidence, base_notional, volatility_norm) -> (bool, float, str)`

**Process**:
1. **Sanity gate**: Calls `check_sanity()` - hard blocks if unsafe
2. **Edge check**: Blocks if combined edge < -0.0005
3. **Quant sizing**: Calls `compute_quant_position_size()`
4. **PA multiplier**: Applies Profit Amplifier multiplier from `gates.yaml`
5. Returns `(allow_trade, final_notional, reason)`

### 5. Quant Monitor Tiles (`engine_alpha/reports/quant_monitor.py`)

**Function**: `build_quant_monitor_tiles()`

**Outputs**:

**`reports/loop_health.json`**:
```json
{
  "pf_local": 1.05,
  "drawdown": 0.02,
  "avg_edge": 0.0003,
  "blind_spots": 0
}
```

**`reports/council_snapshot.json`**:
```json
{
  "top_regimes": [
    {
      "regime": "trend_down",
      "strength": 0.0012,
      "edge": 0.0008,
      "hit_rate": 0.55,
      "weighted_count": 150.0
    }
  ],
  "worst_regimes": [...]
}
```

## Integration

### In `autonomous_trader.py`

Add before calling `open_if_allowed()`:

```python
from engine_alpha.loop.execute_trade import gate_and_size_trade

# ... after computing effective_final_conf, price_based_regime, etc.

# Estimate volatility (0-1 normalized)
# You can use ATR normalized by price, or a simple rolling std
volatility_norm = 0.5  # TODO: compute from recent bars

# Base notional from config (e.g., 1% of equity)
base_notional = 0.01  # TODO: load from config

allow, notional, reason = gate_and_size_trade(
    symbol=symbol,
    side="long" if effective_final_dir > 0 else "short",
    regime=price_based_regime,
    confidence=effective_final_conf,
    base_notional=base_notional,
    volatility_norm=volatility_norm,
)

if not allow:
    if DEBUG_SIGNALS:
        print(f"QUANT-GATE: Trade blocked: {reason}")
    return  # Skip placing order

if DEBUG_SIGNALS:
    print(f"QUANT-GATE: Trade allowed (notional={notional:.4f}): {reason}")

# Proceed with open_if_allowed() - the notional can be used for position sizing
# if your execution layer supports it
```

## Configuration Files

### Required (with defaults)

- **`reports/pf_local.json`**: 
  ```json
  {"pf": 1.0, "drawdown": 0.0}
  ```
  Defaults to PF=1.0 if missing.

- **`config/gates.yaml`**: 
  ```yaml
  profit_amplifier:
    enabled: true
    multiplier: 1.0
  ```
  Defaults to multiplier=1.0 if missing.

### Optional (for edge lookup)

- **`config/confidence_map.json`**: Maps confidence buckets to expected returns
- **`reports/research/strategy_strength.json`**: Regime strength and edge stats
- **`reports/research/blind_spots.jsonl`**: Blind spot flags (one JSON per line)

## Monitoring

### Dashboard Integration

Read the JSON tiles directly:

```python
import json
from pathlib import Path

# Loop health
with open("reports/loop_health.json") as f:
    health = json.load(f)
    print(f"PF: {health['pf_local']:.2f}")
    print(f"DD: {health['drawdown']:.2%}")
    print(f"Edge: {health['avg_edge']:.5f}")
    print(f"Blind spots: {health['blind_spots']}")

# Council snapshot
with open("reports/council_snapshot.json") as f:
    council = json.load(f)
    print("Top regimes:", council['top_regimes'])
    print("Worst regimes:", council['worst_regimes'])
```

### Nightly Updates

The quant monitor tiles are automatically rebuilt at the end of `nightly_research.py`:

```bash
python3 -m engine_alpha.reflect.nightly_research
```

## Testing

### Test Sanity Gates

```python
from engine_alpha.risk.sanity_gates import check_sanity

# Test with low PF
decision = check_sanity(regime="trend_down", confidence=0.60)
assert not decision.allow_trade  # Should block if PF < 0.85

# Test with good conditions
decision = check_sanity(regime="trend_down", confidence=0.70)
assert decision.allow_trade  # Should allow
```

### Test Risk Autoscaler

```python
from engine_alpha.risk.risk_autoscaler import RiskContext, compute_risk_multiplier

ctx = RiskContext(
    pf_local=1.2,
    drawdown=0.05,
    edge=0.001,
    volatility=0.3,
    confidence=0.75,
)

mult = compute_risk_multiplier(ctx)
assert 0.2 <= mult <= 2.0
```

## Safety Guarantees

1. **Hard blocks**: Trades are blocked if:
   - PF_local < 0.85
   - Regime strength < -0.001 (with sufficient data)
   - Blind spots + confidence < 0.5

2. **Position sizing**: Always clamped to [0.2x, 2.0x] base notional

3. **Edge checks**: Trades blocked if combined edge < -0.0005

4. **Monitoring**: Tiles update automatically after nightly research

## Future Enhancements

- Volatility estimation from recent bars
- Dynamic base notional from equity curve
- More sophisticated PA multiplier logic
- Real-time dashboard integration
- Alert system for blind spots / low PF


