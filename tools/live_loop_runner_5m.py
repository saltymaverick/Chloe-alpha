from engine_alpha.loop.autonomous_trader import run_step_live
if __name__ == "__main__":
    out = run_step_live(symbol="ETHUSDT", timeframe="5m", limit=300)
    print(out)
