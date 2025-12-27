from __future__ import annotations

from engine_alpha.reflect.hindsight_coach import run_hindsight_coach


def main() -> None:
    reviews = run_hindsight_coach()
    if not reviews:
        print("No closed trades available for hindsight review.")
        return
    print(f"Hindsight reviews written for {len(reviews)} trade(s).")


if __name__ == "__main__":
    main()

