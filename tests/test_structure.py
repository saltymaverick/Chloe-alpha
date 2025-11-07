import importlib
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


def test_engine_alpha_imports():
    importlib.import_module("engine_alpha")


def test_key_paths_exist():
    required = [
        BASE / "engine_alpha" / "signals" / "signal_registry.json",
        BASE / "engine_alpha" / "reflect",
        BASE / "engine_alpha" / "loop",
        BASE / "reports",
    ]
    for path in required:
        assert path.exists(), f"Missing required path: {path}"
