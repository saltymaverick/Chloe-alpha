from __future__ import annotations

from engine_alpha.reflect.decision_explainer import (
    explain_no_trade_for_symbol,
    load_latest_blocks,
    load_latest_signals,
    run_decision_explainer,
)


def main() -> None:
    symbols = [
        "ETHUSDT",
        "BTCUSDT",
        "SOLUSDT",
        "DOGEUSDT",
        "AVAXUSDT",
        "DOTUSDT",
        "ADAUSDT",
        "LINKUSDT",
        "BNBUSDT",
        "XRPUSDT",
        "ATOMUSDT",
    ]

    blocks = load_latest_blocks()
    snapshots = load_latest_signals()

    print("WHY NO TRADE (LIVE GATE VIEW)")
    print("=============================")
    for sym in symbols:
        explanation = explain_no_trade_for_symbol(sym, blocks.get(sym), snapshots.get(sym, {}))
        print(f"\n{sym}:\n  {explanation}")

    # Also trigger the GPT explainer (optional)
    result = run_decision_explainer(symbols=symbols, use_gpt=True)
    print("\n--- GPT Narrative ---")
    print(result.get("explanation", "No explanation available."))


if __name__ == "__main__":
    main()

