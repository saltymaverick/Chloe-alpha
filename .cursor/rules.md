

<!-- BEGIN PF_TILE_NORMALIZE RULES v1 -->
### Scoped Template Operation: PF Tile Normalizer (v1)

**Trigger:** Only when the user explicitly types `PF_TILE_NORMALIZE`.

**Scope:** Only the following file paths may be created or modified (if they exist in this repo):
- Python/Streamlit: `dashboard/*`, `engine_alpha/dashboard/*`
- React/TS: `components/tiles/PfTile.tsx`, `components/tiles/pfData.ts`, `app/**/Dashboard*.tsx`, `dashboard/**/*.tsx`

**Write Limits (per run):**
- Create/modify **at most 2 files total**.
- **No** tests, scripts, hooks, dependencies, or directory-wide refactors.
- **No renames or deletes** outside the files touched above.

**Idempotency:**
- Add header at file top: Python `# @cursor-guard:pf-tile:v1`, TS/TSX `// @cursor-guard:pf-tile:v1`.
- On subsequent runs, modify **only** inside explicit regions:
  - Python: `# region pf-tile` … `# endregion pf-tile`
  - TS/TSX: `// region pf-tile` … `// endregion pf-tile`

**Behavior (must enforce exactly):**
- Ensure exactly one PF tile **in the edited file** with `id="pf-tile-main"`, label `Profit Factor`.
- Canonical data keys: `pf_value`, `pf_window`, `trades_count`, `source` (`"live"` or `"norm"`), `updated_at`. Optional `delta_pf`.
- Chooser (file-based only):
  - Use `reports/pf_local_live.json` if it has `trades_count ≥ 30` → `source: "live"`.
  - Otherwise use `reports/pf_local_norm.json` → `source: "norm"`.
  - If both missing: value `—`, `source: "none"`.
- Presentation (deterministic):
  - Value: fixed 2 decimals (or `—`).
  - Color bands: PF ≥ 1.10 → green; 1.00 ≤ PF < 1.10 → amber; PF < 1.00 → red.
  - Subtext: `${source.toUpperCase()} • ${pf_window || 'local'} • ${trades_count} trades`
  - Updated: `Updated ${updated_at}` (ISO8601 → local, minute precision).
  - Trend arrow shown **only** if `delta_pf` exists; otherwise omitted.

**Non-negotiables:**
- Do not modify files outside the allowed list.
- Do not add tests, scripts, hooks, or global styles.
- No environment variables for chooser; strictly `reports/*.json`.
- Must be deterministic and idempotent.
<!-- END PF_TILE_NORMALIZE RULES v1 -->

<!-- BEGIN DASHBOARD_SAFE v1 -->
### Scoped Operation: DASHBOARD_SAFE (v1)

**Trigger:** Only when the user explicitly types `DASHBOARD_SAFE`.

**Scope (allowed paths only):**
- `engine_alpha/dashboard/**`
- `dashboard/**`
- `components/tiles/**`

**Write limits (per run):**
- Create/modify **at most 3 files total**.
- **No** renames, deletes, tests, scripts, hooks, or dependency changes.
- May insert region markers and adjust imports used by the edited blocks.

**Idempotency:**
- Add header markers at file top:
  - Python `# @cursor-guard:dashboard-safe:v1`
  - TS/TSX `// @cursor-guard:dashboard-safe:v1`
- On subsequent runs, modify **only** inside:
  - Python: `# region ...` … `# endregion ...`
  - TS/TSX: `// region ...` … `// endregion ...`

**Permitted fixes (dashboard-only):**
- Normalize/insert canonical tiles (PF, Bias, Confidence) **in the open file**, or one adjacent helper file.
- Small, local import cleanup tied to that change.
- No global refactors.

**Non-negotiables:**
- Do not touch files outside Scope.
- Do not add tests, hooks, or global styles.
- Deterministic & idempotent output.
<!-- END DASHBOARD_SAFE v1 -->


<!-- BEGIN FULL_REPAIR v1 -->
### Scoped Operation: FULL_REPAIR (v1)

**Trigger:** Only when the user explicitly types `FULL_REPAIR`.

**Goal:** Repo-wide coherence repair: imports, package structure, dashboard rendering, runtime fallbacks, deterministic tiles, and log adapters.

**Scope (allowed paths):**
- All tracked files **except**: `venv/**`, `.git/**`, `node_modules/**`, `reports/**` (read-only), `data/**` (read-only), `logs/**` (read-only), `__pycache__/**`, `dist/**`, `build/**`.

**Write limits (per run):**
- Modify/create **≤ 50 files**; no mass renames.
- **No** new dependencies, no scripts/hooks, no secret files.
- May create missing `__init__.py` files and small helper modules *only within* `engine_alpha/**` or `dashboard/**`.

**Idempotency & hygiene:**
- Add file header markers where code is rewritten:
  - Python: `# @cursor-guard:full-repair:v1`
  - TS/TSX: `// @cursor-guard:full-repair:v1`
- Prefer editing within `region … / endregion …` blocks if present.
- Leave unrelated styles/assets untouched.

**Required checks & repairs:**
1) **Package/imports**
   - Ensure `engine_alpha/**` is a proper package (add `__init__.py` where missing).
   - Normalize intra-project imports to `from engine_alpha...`.
   - Remove dead/duplicate imports.

2) **Dashboard runtime**
   - Wrap Streamlit render functions to **skip** when ScriptRunContext is missing (no warnings in `python -m` runs).
   - Ensure all tiles (PF, Bias, Confidence, Status, Council, Last Signal, Trade Activity, Equity chart) are **called** in `overview_tab()` exactly once.

3) **Tiles (canonical rules)**
   - PF chooser: `live` when `trades_count ≥ 30`, else `norm`, else `none`. 2-decimal display; color bands as specified.
   - Bias/Confidence read tolerant keys (case-insensitive; accept `SCI` and nested `metrics`).
   - Status tile: tolerant keys for `rec/sci/pa/errors`; show timestamp (minute precision).
   - Council Snapshot expander: tolerant keys; show top votes, active strategies, errors (max 5).

4) **Equity chart**
   - Loader accepts `timestamp/updated_at/ts/time`.
   - Render with **pandas + `st.line_chart`**, fallback to native list if pandas missing.
   - Chart should render if there’s **≥ 1** point; if absent, show clear “no data” caption.

5) **Trades adapter**
   - Last Signal / Trade Activity must accept your log format: `ts`, `type`, `dir`, `pct`, and optional `symbol/pair/market`.
   - Derive side from `dir` when `side` missing.

6) **Reports policy**
   - Do **not** write to `reports/**` during repair (read-only).
   - Keep `.gitignore` ignoring `reports/`.

**Non-negotiables:**
- No external network access, no dependency changes, no secrets exposure.
- Deterministic, idempotent output; produce a summary of files changed.
<!-- END FULL_REPAIR v1 -->
