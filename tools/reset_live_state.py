from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    st = Path("reports/live_loop_state.json")
    if st.exists() and st.read_text().strip():
        try:
            obj = json.loads(st.read_text())
        except Exception:
            obj = {}
        obj["ts"] = "1970-01-01T00:00:00Z"
        st.write_text(json.dumps(obj, indent=2))
        print("state reset")
    else:
        print("no state file or empty")


if __name__ == "__main__":
    main()

