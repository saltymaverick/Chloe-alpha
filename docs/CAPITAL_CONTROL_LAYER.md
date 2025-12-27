# Capital Control Layer

## Overview

The Capital Control Layer provides **advisory-only** capital management scaffolding for Chloe. All modules are read-only, dry-run, and do not perform any real fund movement or exchange operations.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│           Capital Control Layer                         │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  Capital Allocation Engine                               │
│  → Computes advisory allocations per symbol              │
│  → Based on tiers, PF, quality scores, ARE               │
│                                                           │
│  Capital Buffer                                          │
│  → Calculates liquidity, emergency, volatility buffers  │
│                                                           │
│  Subaccount Manager Stub                                 │
│  → Recommends subaccount allocations                     │
│  → MAIN / EXPLORE / VAULT                                │
│                                                           │
│  Profit Consolidation Engine Stub                        │
│  → Suggests when to move profits to vault                │
│                                                           │
│  Withdrawal Adapter Stub                                 │
│  → Plans safe withdrawals (not executed)                 │
│                                                           │
└─────────────────────────────────────────────────────────┘
```

## Components

### 1. Capital Allocation Engine

**File**: `engine_alpha/capital/capital_allocation_engine.py`

**Purpose**: Compute advisory capital allocation suggestions per symbol.

**Inputs**:
- `reports/gpt/reflection_input.json` - PF and trade stats
- `reports/gpt/quality_scores.json` - Quality scores (optional)
- `reports/research/are_snapshot.json` - ARE data (optional)
- `reports/gpt/reflection_output.json` - Tier classifications
- `config/symbol_tiers.yaml` - Tier config (fallback)

**Outputs**:
- `reports/capital/allocation_advice.json`

**Logic**:
- Base allocation by tier (Tier1: 30%, Tier2: 15%, Tier3: 5%)
- Adjust by quality score (high score: +30%, low score: -50%)
- Adjust by exploration PF (strong: +20%, weak: -30%)
- Adjust by ARE long-horizon PF if available
- Normalize to sum ≤ 100%

### 2. Capital Buffer

**File**: `engine_alpha/capital/capital_buffer.py`

**Purpose**: Calculate advisory buffer requirements.

**Functions**:
- `compute_liquidity_buffer()` - 10% of equity
- `compute_emergency_buffer()` - 15% of equity
- `compute_volatility_buffer()` - Per-symbol volatility-based

**Outputs**:
- `reports/capital/buffers.json`

### 3. Subaccount Manager Stub

**File**: `engine_alpha/capital/subaccount_manager_stub.py`

**Purpose**: Recommend subaccount allocations (advisory only).

**Subaccounts**:
- `MAIN` - Tier1 symbols, high allocation Tier2
- `EXPLORE` - Tier2/Tier3 symbols, low allocation
- `VAULT` - Profit consolidation target

**Outputs**:
- `reports/capital/subaccount_recommendations.json`

### 4. Profit Consolidation Engine Stub

**File**: `engine_alpha/capital/profit_consolidation_engine_stub.py`

**Purpose**: Suggest when to consolidate profits to vault.

**Triggers**:
- Monthly PnL > threshold (default: 8%)
- Suggests moving percentage of profit (default: 50%)

**Outputs**:
- `reports/capital/consolidation_advice.json`

### 5. Withdrawal Adapter Stub

**File**: `engine_alpha/capital/withdrawal_adapter_stub.py`

**Purpose**: Plan safe withdrawals (not executed).

**Functions**:
- `validate_withdrawal()` - Check thresholds (stub)
- `generate_withdrawal_plan()` - Create advisory plan

**Outputs**:
- `reports/capital/withdrawal_plan.json`

## Integration Points

### With GPT Modules

- **Reflection**: Uses tier classifications for allocation
- **Tuner**: Can use allocation advice for size adjustments
- **Dream**: Can inform quality scores used in allocation

### With ARE

- **ARE Snapshot**: Provides long-horizon PF for allocation decisions
- **Volatility Data**: Used for volatility buffer calculations

### With Risk Engine

- Allocation advice respects risk.yaml constraints
- Buffer calculations consider risk limits

## Safety Guarantees

✅ **All operations are advisory-only**
✅ **No real fund movement**
✅ **No exchange API calls for capital operations**
✅ **Shadow mode remains active**
✅ **Human-in-the-loop required for real implementation**

## Usage

```bash
# Generate allocation advice
python3 -m engine_alpha.capital.capital_allocation_engine

# Generate buffer calculations
python3 -m engine_alpha.capital.capital_buffer

# Generate subaccount recommendations
python3 -m engine_alpha.capital.subaccount_manager_stub

# Generate consolidation advice
python3 -m engine_alpha.capital.profit_consolidation_engine_stub

# Generate withdrawal plan
python3 -m engine_alpha.capital.withdrawal_adapter_stub

# View all capital advice
python3 -m tools.capital_overview
```

## Future Integration

When ready for real capital management:

1. **Enable real operations** (with explicit flags)
2. **Wire to exchange APIs** (Bybit subaccount/withdrawal endpoints)
3. **Add human approval layer** (require confirmation for large operations)
4. **Add audit logging** (log all capital movements)
5. **Add safety limits** (max allocation per symbol, max withdrawal per day)

All future changes must maintain the advisory-first approach and require explicit enablement.


