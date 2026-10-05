# Decision Moment `01M46FYYFFXXZE893KWDP2WJCW`

- **Mission:** `troupe-config-include-overrides-01M46FY4`
- **Origin flow:** `specify`
- **Slot key:** `specify.overrides.nested-include-target`
- **Input key:** `nested_include_override_file`
- **Status:** `resolved`
- **Created:** `2026-10-05T16:57:11.919340+00:00`
- **Resolved:** `2026-10-05T16:57:43.135152+00:00`
- **Opened by:** `cli`
- **Other answer:** `false`

## Question

When the new key's deepest existing ancestor comes from an include nested inside another include (root -> a.yaml -> b.yaml), which file receives the override?

## Options

- The file holding the nearest include reference (a.yaml), as the contract literally says
- The root file (never touch any included file)
- Other

## Final answer

The file holding the nearest include reference (a.yaml), as the contract literally says

## Rationale

_(none)_

## Change log

- `2026-10-05T16:57:11.919340+00:00` — opened
- `2026-10-05T16:57:43.135152+00:00` — resolved (final_answer="The file holding the nearest include reference (a.yaml), as the contract literally says")
