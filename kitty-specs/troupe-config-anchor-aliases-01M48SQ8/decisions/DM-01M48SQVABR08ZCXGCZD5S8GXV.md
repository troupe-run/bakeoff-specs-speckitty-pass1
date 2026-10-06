# Decision Moment `01M48SQVABR08ZCXGCZD5S8GXV`

- **Mission:** `troupe-config-anchor-aliases-01M48SQ8`
- **Origin flow:** `specify`
- **Slot key:** `specify.aliases.merge-keys`
- **Input key:** `merge_keys_read`
- **Status:** `resolved`
- **Created:** `2026-10-06T14:26:33.931221+00:00`
- **Resolved:** `2026-10-06T14:27:52.051461+00:00`
- **Opened by:** `cli`
- **Other answer:** `false`

## Question

Files may contain YAML merge keys (coder: {<<: *d, model: x}). How should troupe read them, and what should set do for a value that arrives through <<?

## Options

- Read with YAML merge semantics (local keys win); set of a merged-in value exits 3 like any alias; --expand-alias on it exits 3 (would need to rewrite <<)
- Read with merge semantics; set of a merged-in value adds a local key beside << (no << written, nobody else changes)
- Refuse files containing << at load (exit 4)
- Other

## Final answer

Agent choice (product owner: out of contract beyond 'merge keys are never written' and 'through an alias -> exit 3, stderr mentions --expand-alias'). Option A: read << with standard YAML merge semantics (keys written in the mapping win; for << [*a, *b] earlier sources win). A value arriving through << is reached through an alias: set exits 3 and stderr mentions --expand-alias; set --expand-alias on it also exits 3 because expanding would mean writing a merge key; stderr says so. Adding a key that does not exist yet directly under the mapping holding << is an ordinary write (no << written). Why: refusing cannot lose data (TROUPE-002), never writes <<, and keeps the reporter's requirement that nobody else changes silently; option B would override a shared value without the explicit opt-in the reporter asked for.

## Rationale

_(none)_

## Change log

- `2026-10-06T14:26:33.931221+00:00` — opened
- `2026-10-06T14:27:52.051461+00:00` — resolved (final_answer="Agent choice (product owner: out of contract beyond 'merge keys are never written' and 'through an alias -> exit 3, stderr mentions --expand-alias'). Option A: read << with standard YAML merge semantics (keys written in the mapping win; for << [*a, *b] earlier sources win). A value arriving through << is reached through an alias: set exits 3 and stderr mentions --expand-alias; set --expand-alias on it also exits 3 because expanding would mean writing a merge key; stderr says so. Adding a key that does not exist yet directly under the mapping holding << is an ordinary write (no << written). Why: refusing cannot lose data (TROUPE-002), never writes <<, and keeps the reporter's requirement that nobody else changes silently; option B would override a shared value without the explicit opt-in the reporter asked for.")
