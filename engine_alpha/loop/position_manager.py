# engine_alpha/loop/position_manager.py
_position = {"dir": 0, "entry_px": None, "bars_open": 0}

def get_open_position():
    return dict(_position) if _position["dir"] != 0 else None

def set_position(p):
    global _position
    _position = dict(p)

def clear_position():
    global _position
    _position = {"dir": 0, "entry_px": None, "bars_open": 0}
