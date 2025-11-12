from pathlib import Path
import re

DASH = Path("engine_alpha/dashboard/dashboard.py")

KEEP_LABEL = "PF (Risk-weighted)"

HELPER = (
    "def _choose_weighted_pf():\n"
    "    from engine_alpha.core.paths import REPORTS\n"
    "    import json\n"
    "    live = json.loads((REPORTS/'pf_local_live.json').read_text()) if (REPORTS/'pf_local_live.json').exists() else None\n"
    "    norm = json.loads((REPORTS/'pf_local_norm.json').read_text()) if (REPORTS/'pf_local_norm.json').exists() else None\n"
    "    if live and int(live.get('count',0)) >= 30:\n"
    "        return live\n"
    "    return norm or live\n"
)

TILE_BODY = [
    "# PF tile (chooser for risk-weighted PF)\n",
    "pf_obj = _choose_weighted_pf()\n",
    "if not pf_obj or pf_obj.get('pf') is None:\n",
    "    col_pf.metric('PF (Risk-weighted)', '—', help='insufficient sample (norm until live≥30)')\n",
    "else:\n",
    "    sample = int(pf_obj.get('count', 0))\n",
    "    col_pf.metric('PF (Risk-weighted)', f\"{pf_obj['pf']:.4f}\", help=f\"sample={sample} (norm until live≥30)\")\n",
]

def find_insert_after_overview(lines):
    """
    Return (idx, indent) to insert the tile right after the Overview section header.
    Looks for `st.header("Overview")` or `st.header('Overview')`.
    If not found, return None (caller will choose a fallback).
    """
    pat = re.compile(r"""st\.header\(\s*(['"])Overview\1\s*\)""")
    for i, ln in enumerate(lines):
        if pat.search(ln):
            # compute indent from next code line
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            # indent = leading spaces on the next line, or 4 spaces by default
            nxt = lines[j] if j < len(lines) else ""
            indent = "".join(ch for ch in nxt[:len(nxt)-len(nxt.lstrip())] if ch in " \t") or "    "
            return (j, indent)
    return None

def ensure_helper(text):
    if "def _choose_weighted_pf(" in text:
        return text
    # put helper after `import streamlit as st`
    anchor = "import streamlit as st"
    ai = text.find(anchor)
    if ai < 0:
        # fallback: put helper after the last import block
        m = re.search(r"^(?:from|import)\s.+$", text, re.M)
        last = 0
        for mm in re.finditer(r"^(?:from|import)\s.+$", text, re.M):
            last = mm.end()
        if last:
            return text[:last] + "\n" + HELPER + "\n" + text[last:]
        # worst case: top of file after docstring (safe)
        return HELPER + "\n" + text
    eol = text.find("\n", ai)
    return text[:eol+1] + HELPER + "\n" + text[eol+1:]

def main():
    text = DASH.read_text()

    # 1) Remove ALL PF metrics (active & commented), keep non-PF metrics
    lines = text.splitlines(keepends=True)
    filtered = []
    for ln in lines:
        if ("PF (Risk-weighted)" in ln) and ("metric(" in ln):
            continue
        filtered.append(ln)
    text = "".join(filtered)

    # 2) Ensure helper exists
    text = ensure_helper(text)

    # 3) Compute insertion point: after Overview header, else fallback
    lines = text.splitlines(keepends=True)
    ins = find_insert_after_overview(lines)

    if ins is None:
        # fallback: put after imports + streamlit, before any heavy content
        # find first function def and insert just before it
        m = re.search(r"^\s*def\s+\w+\s*\(", text, re.M)
        if m:
            insert_idx = text[:m.start()].count("\n")
            indent = "    "
        else:
            insert_idx = len(lines) - 1
            indent = "    "
    else:
        insert_idx, indent = ins

    # 4) Insert the single tile block, indented
    tile = "".join(indent + ln if ln.strip() else ln for ln in TILE_BODY)
    lines.insert(insert_idx, tile)

    DASH.write_text("".join(lines))
    print("Enforced single PF tile near the Overview section (or fallback).")

if __name__ == "__main__":
    main()
