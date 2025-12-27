#!/bin/bash
# Run research on sandbox data

python3 -m tools.sandbox.simulate_candles
python3 -m tools.sandbox.simulate_trades
python3 -m engine_alpha.reflect.nightly_research


