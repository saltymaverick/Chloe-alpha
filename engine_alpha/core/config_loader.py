from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[2]
ENGINE_CONFIG_PATH = ROOT / "config" / "engine_config.json"
ENGINE_CONFIG_BAK_PATH = ROOT / "config" / "engine_config.json.bak"


def _read_config(path: Path) -> Dict[str, Any]:
    raw = path.read_text()
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError(f"{path} must be a JSON object (dict), got {type(obj)}")
    return obj


def load_engine_config(strict: bool = False) -> Dict[str, Any]:
    """
    Always returns a dict. If strict=True, raises on error instead of fallback.
    Fallback order: main -> .bak -> {}.
    """
    try:
        return _read_config(ENGINE_CONFIG_PATH)
    except Exception as e1:
        if strict:
            raise
        print(f"[config_loader] WARN: failed to read {ENGINE_CONFIG_PATH}: {e1}")
        try:
            if ENGINE_CONFIG_BAK_PATH.exists():
                cfg = _read_config(ENGINE_CONFIG_BAK_PATH)
                print(f"[config_loader] WARN: using backup {ENGINE_CONFIG_BAK_PATH}")
                return cfg
        except Exception as e2:
            print(f"[config_loader] WARN: failed to read backup {ENGINE_CONFIG_BAK_PATH}: {e2}")
        return {}


def atomic_write_engine_config(cfg: Dict[str, Any]) -> None:
    """
    Writes engine_config.json atomically and updates .bak.
    """
    if not isinstance(cfg, dict):
        raise ValueError("cfg must be a dict")

    ENGINE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    tmp = ENGINE_CONFIG_PATH.with_suffix(".json.tmp")
    data = json.dumps(cfg, indent=2, sort_keys=True)

    # Write temp
    tmp.write_text(data)

    # Backup current -> .bak (best-effort)
    try:
        if ENGINE_CONFIG_PATH.exists():
            ENGINE_CONFIG_BAK_PATH.write_text(ENGINE_CONFIG_PATH.read_text())
    except Exception as e:
        print(f"[config_loader] WARN: failed to write backup: {e}")

    # Atomic replace
    os.replace(str(tmp), str(ENGINE_CONFIG_PATH))

