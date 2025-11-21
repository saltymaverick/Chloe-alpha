#!/usr/bin/env bash

# tools/patch_guardrails_pf_tile.sh

# Adds/updates a scoped "PF Tile Normalizer (v1)" rule block inside your repository guard rails.

# Idempotent: re-running replaces only the block between the BEGIN/END markers.

# Usage:

#   bash tools/patch_guardrails_pf_tile.sh                 # autodetect rules file

#   bash tools/patch_guardrails_pf_tile.sh path/to/rules.md

# Env:

#   DRY_RUN=1   # preview changes (prints unified diff) but do not write

#   BACKUP=0    # disable backup creation (default 1 = create backup)



set -euo pipefail



# ---------- config ----------

MARK_START="<!-- BEGIN PF_TILE_NORMALIZE RULES v1 -->"

MARK_END="<!-- END PF_TILE_NORMALIZE RULES v1 -->"



read -r -d '' BLOCK_CONTENT <<'EOF'

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

EOF



# ---------- helpers ----------

backup_file() {

  local file="$1"

  local ts

  ts="$(date -u +%Y%m%dT%H%M%SZ)"

  cp -p -- "$file" "${file}.bak.${ts}"

}



detect_rules_file() {

  # Preference order; override by passing a path as $1

  if [[ $# -gt 0 ]]; then

    echo "$1"

    return 0

  fi

  local candidates=(

    ".cursor/rules.md"

    ".cursor/rules.txt"

    ".cursorrules"

    ".github/CURSOR_GUARDRAILS.md"

    "GUARDRAILS.md"

    "docs/guardrails.md"

    "docs/CURSOR_RULES.md"

  )

  for f in "${candidates[@]}"; do

    if [[ -f "$f" ]]; then

      echo "$f"

      return 0

    fi

  done

  # Default location if none found

  echo ".cursor/rules.md"

  return 0

}



insert_or_replace_block() {

  local file="$1"

  local tmp

  tmp="$(mktemp)"

  # If markers exist, replace; else append with spacing.

  if grep -qF "$MARK_START" "$file" 2>/dev/null; then

    # Replace block between markers using awk

    awk -v start="$MARK_START" -v end="$MARK_END" -v repl="$BLOCK_CONTENT" '

      BEGIN{printing=1}

      {

        if ($0==start) {

          print repl

          printing=0

          skip=1

          next

        }

        if ($0==end) {

          printing=1

          next

        }

        if (printing) print

      }

    ' "$file" > "$tmp"

  else

    # Ensure file exists, then append with a blank line

    if [[ ! -f "$file" ]]; then

      mkdir -p "$(dirname "$file")"

      : > "$file"

    fi

    { cat "$file"; echo ""; echo "$BLOCK_CONTENT"; } > "$tmp"

  fi

  mv "$tmp" "$file"

}



show_diff() {

  local old="$1"

  local new="$2"

  if command -v diff >/dev/null 2>&1; then

    diff -u --label "$old (old)" --label "$old (new)" "$old" "$new" || true

  else

    echo "diff not found; showing new content:"

    cat "$new"

  fi

}



# ---------- main ----------

RULES_FILE="$(detect_rules_file "${1:-}")"

mkdir -p "$(dirname "$RULES_FILE")"



# Work on a temp copy to enable DRY_RUN and diff

ORIG_TMP="$(mktemp)"

NEW_TMP="$(mktemp)"



if [[ -f "$RULES_FILE" ]]; then

  cp -p -- "$RULES_FILE" "$ORIG_TMP"

else

  : > "$ORIG_TMP"

fi



# Prepare new content in NEW_TMP

cp -p -- "$ORIG_TMP" "$NEW_TMP"

# We need to run insertion on NEW_TMP, so copy content to a temp file location then replace

TMP_WORK="$(mktemp)"

cp -p -- "$NEW_TMP" "$TMP_WORK"

# Write BLOCK into TMP_WORK

if grep -qF "$MARK_START" "$TMP_WORK" 2>/dev/null; then

  awk -v start="$MARK_START" -v end="$MARK_END" -v repl="$BLOCK_CONTENT" '

    BEGIN{printing=1}

    {

      if ($0==start) { print repl; printing=0; next }

      if ($0==end) { printing=1; next }

      if (printing) print

    }

  ' "$TMP_WORK" > "$NEW_TMP"

else

  { cat "$TMP_WORK"; echo ""; echo "$BLOCK_CONTENT"; } > "$NEW_TMP"

fi

rm -f "$TMP_WORK"



# DRY RUN?

if [[ "${DRY_RUN:-0}" == "1" ]]; then

  show_diff "$ORIG_TMP" "$NEW_TMP"

  echo

  echo "DRY_RUN=1 → No changes written. Target file would be: $RULES_FILE"

  exit 0

fi



# Write back, with optional backup

if [[ "${BACKUP:-1}" == "1" && -f "$RULES_FILE" ]]; then

  backup_file "$RULES_FILE"

fi

mv "$NEW_TMP" "$RULES_FILE"



echo "Updated guard rails at: $RULES_FILE"

echo "Block markers: $MARK_START … $MARK_END"
































