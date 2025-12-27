# Chloe Alpha — Quant Trading Engine

Chloe Alpha is a GPT-augmented, SWARM-supervised, hybrid self-learning quant engine designed for crypto markets.

---

## 🔷 Features

- **Live trading loop** (paper or real)
- **Risk-aware execution engine** with sanity gates
- **Dynamic position sizing** (PF, volatility, confidence, edge)
- **Weighted self-learning research pipeline**
- **Adaptive thresholds** (regime × confidence)
- **SWARM supervisory system** (sentinel, audit, challenger)
- **Mirror trader** / wallet inference mode
- **Streamlit multi-panel dashboard**
- **Modular, multi-asset architecture**

---

## 📁 Project Structure

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

## 🚀 Run Chloe

### Paper mode:
```bash
python3 -m engine_alpha.loop.autonomous_trader
```

### Nightly research:
```bash
python3 -m engine_alpha.reflect.nightly_research
```

---

## 📊 Dashboard

```bash
streamlit run engine_alpha/dashboard/dashboard.py
```

Panels include:
- **Overview** — PF, DD, SWARM status
- **Live Blotter** — Recent trades
- **Research** — Strategy strength, confidence map
- **SWARM** — Supervisory monitoring
- **Risk** — Exposure, multipliers
- **Wallet** — Mode & credentials
- **Operator** — CLI reference
- **System** — File freshness

---

## 🐝 SWARM (Supervisory Layer)

Run manually:
```bash
python3 -m engine_alpha.swarm.swarm_sentinel
python3 -m engine_alpha.swarm.swarm_audit_loop
python3 -m engine_alpha.swarm.swarm_research_verifier
```

---

## 🔑 Wallet Modes

```bash
python3 -m tools.wallet_cli status
python3 -m tools.wallet_cli set paper
python3 -m tools.wallet_cli set real
```

---

## ⚠️ Safety

- **Dashboard is read-only.**
- **SWARM monitors Chloe continuously.**
- **Real trading requires explicit confirmation.**

---

## 🧩 For Developers

### Development Workflow

1. **Clone & Setup:**
   ```bash
   git clone git@github.com:saltymaverick/Chloe-alpha.git
   cd Chloe-alpha

   # Run setup script (configures hooks, creates .env)
   ./tools/setup-hooks.sh

   # Set up Python environment
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Development Loop:**
   ```bash
   # Make changes
   git checkout -b feature/your-feature
   # Edit code...
   git add .
   git commit -m "feat: describe your changes"
   git push origin feature/your-feature
   ```

3. **Code Quality:**
   ```bash
   # Format code
   black .
   isort .

   # Lint
   flake8 .

   # Run tests
   python3 -m pytest
   ```

4. **Environment Setup:**
   ```bash
   # Copy template (never commit real values)
   cp .env_template .env
   # Edit .env with your API keys
   ```

### Security Notes
- **Never commit secrets** (.env, API keys, private keys)
- **Use .env for local development**
- **Production secrets** go in systemd environment files
- **GitHub Actions** runs on code only (no secrets)

### Branch Strategy
- `main`: Production-ready code
- `feature/*`: New features
- `hotfix/*`: Urgent fixes
- Tags: `phase-X.Y` for releases

See:
- `docs/developer_onboarding.md`
- `docs/quant_research_handbook.md`
- `docs/dashboard_spec.md`

---

## 📚 Documentation

- **Dashboard Spec:** `docs/dashboard_spec.md`
- **Developer Onboarding:** `docs/developer_onboarding.md`
- **Quant Research Handbook:** `docs/quant_research_handbook.md`
- **Wallet Setup:** `docs/wallet_setup.md`
- **Pro-Quant Mode:** `docs/pro_quant_mode.md`

---

**Chloe Alpha — Production Quant Engine**


