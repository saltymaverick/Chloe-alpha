
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
