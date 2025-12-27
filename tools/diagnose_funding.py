from __future__ import annotations

import argparse

from engine_alpha.data.funding_rates import get_funding_bias


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect live perp funding bias for a symbol.")
    parser.add_argument("--symbol", default="ETHUSDT", help="Spot symbol, e.g., ETHUSDT")
    args = parser.parse_args()

    bias = get_funding_bias(args.symbol)
    print(f"Funding bias for {args.symbol.upper()}: {bias:.6f}")


if __name__ == "__main__":
    main()

