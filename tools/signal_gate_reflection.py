from __future__ import annotations

from engine_alpha.config.assets import get_enabled_assets
from engine_alpha.reflect.signal_gate_reflection import run_signal_gate_reflection


def main() -> None:
    assets = get_enabled_assets()
    symbols = [asset.symbol for asset in assets] if assets else [
        "ETHUSDT",
        "BTCUSDT",
        "SOLUSDT",
        "DOGEUSDT",
        "AVAXUSDT",
        "XRPUSDT",
        "ADAUSDT",
        "DOTUSDT",
        "LINKUSDT",
        "ATOMUSDT",
        "BNBUSDT",
    ]
    result = run_signal_gate_reflection(symbols, use_gpt=True)
    print("SIGNAL & GATE REFLECTION")
    print("========================")
    print(result.get("explanation", "No explanation generated."))


if __name__ == "__main__":
    main()

