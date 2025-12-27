# Developer Onboarding — Chloe Alpha Quant Engine

Welcome to the Chloe Alpha codebase. This document gives new engineers a full, high-level understanding of how the system works, how to work inside it, and how not to break anything.

---

## 🌐 Architecture Overview

Chloe Alpha is a multi-layer, AI-augmented quant trading engine composed of:

- **Core trading loop** (`engine_alpha/loop/`)
- **Signal + regime engine** (`engine_alpha/signals/`, `engine_alpha/core/regime.py`)
- **Risk management** (`engine_alpha/risk/`)
- **GPT-powered reflection + learning** (`engine_alpha/reflect/`)
- **Hybrid Self-Learning research pipeline** (`nightly_research.py`)
- **Weighted analyzer + tuner** (`engine_alpha/tools/`)
- **Mirror engine** (smart wallet inference)
- **SWARM supervision** (`engine_alpha/swarm/`)
- **Dashboard (Streamlit)** (`engine_alpha/dashboard/`)
- **Exchange adapters** (`engine_alpha/exchange/`)
- **Wallet management** (`engine_alpha/config/wallets/`)

Chloe operates in two modes:
- **PAPER** (default, safe)
- **REAL** (requires API keys & explicit switching)

SWARM monitors everything Chloe does.

---

## 🧩 Directory Structure

```
engine_alpha/
  core/          # Decision logic, confidence engine, regime classification
  loop/          # Trading loop, execution, position management
  reflect/       # Research, learning, GPT reflection
  risk/          # PF, DD, sanity gates, risk autoscaler
  swarm/         # Supervisory layer (sentinel, audit, challenger)
  dashboard/     # Streamlit quant dashboard
  exchange/      # Paper & real exchange clients
  config/        # Wallets, thresholds, gates
  signals/       # Signal fetchers, processors
  tools/         # CLI tools, analyzers, tuners
reports/         # PF, health, trade logs
reports/research/ # Research outputs, SWARM logs
data/ohlcv/      # Historical & live OHLCV
logs/            # Application logs
```

---

## 🚀 How to Run Chloe (Paper Mode)

### Start live trading loop:
```bash
python3 -m engine_alpha.loop.autonomous_trader
```

### Run nightly research manually:
```bash
python3 -m engine_alpha.reflect.nightly_research
```

### Run SWARM checks:
```bash
python3 -m engine_alpha.swarm.swarm_sentinel
python3 -m engine_alpha.swarm.swarm_audit_loop
python3 -m engine_alpha.swarm.swarm_research_verifier
```

---

## 📊 Running the Dashboard

```bash
streamlit run engine_alpha/dashboard/dashboard.py
```

This launches a multi-panel interface:
- **Home** — Overview metrics
- **Live** — Trade blotter
- **Research** — Strategy strength, confidence map
- **SWARM** — Supervisory status
- **Risk** — PF, DD, exposure
- **Wallet** — Mode & credentials
- **Operator** — CLI reference
- **System** — File freshness

---

## 🔑 Wallet Modes

Check:
```bash
python3 -m tools.wallet_cli status
```

Switch:
```bash
python3 -m tools.wallet_cli set paper
python3 -m tools.wallet_cli set real
```

**Never switch to real mode until testing is complete.**

---

## 🧪 Developer Testing

Use the sandbox (`tools/sandbox/`) to simulate:
- Fake candles
- Fake trades
- SWARM checks
- Research runs

(Sandbox details included below.)

---

## 🛑 DON'Ts (Critical)

- **Do not modify** risk logic.
- **Do not modify** sanity gates.
- **Do not change** SWARM behavior.
- **Do not change** JSON schemas inside `reports/`.
- **Do not modify** any file paths used by SWARM or research.

---

## ✔️ DOs

- **Add** dashboard panels.
- **Add** new visualizations.
- **Add** new test utilities.
- **Add** new signals (with caution).
- **Improve** research logic only as directed.

---

Welcome to the project.

Chloe is a real quant engine — treat her like production software.


