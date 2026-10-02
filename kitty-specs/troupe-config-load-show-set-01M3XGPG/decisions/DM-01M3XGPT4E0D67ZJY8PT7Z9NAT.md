# Decision Moment `01M3XGPT4E0D67ZJY8PT7Z9NAT`

- **Mission:** `troupe-config-load-show-set-01M3XGPG`
- **Origin flow:** `specify`
- **Slot key:** `specify.state.hand-edit-drift`
- **Input key:** `hand_edit_drift`
- **Status:** `resolved`
- **Created:** `2026-10-02T05:17:04.015005+00:00`
- **Resolved:** `2026-10-02T05:17:41.928389+00:00`
- **Opened by:** `cli`
- **Other answer:** `false`

## Question

When someone hand-edits the YAML files after the theatre was imported, should show/set treat the files on disk as the source of truth (event store records only commands' changes; no reconcile events), or should the stored projection win?

## Options

- Files on disk are truth; set diffs against current files; no reconcile events (recommended)
- Projection is truth; show ignores hand edits
- Other

## Final answer

A: files on disk are the source of truth; show and set always read current files; the stored projection is only the change history; hand edits appear in show but emit no event; a later set records old as the value currently in the file.

## Rationale

_(none)_

## Change log

- `2026-10-02T05:17:04.015005+00:00` — opened
- `2026-10-02T05:17:41.928389+00:00` — resolved (final_answer="A: files on disk are the source of truth; show and set always read current files; the stored projection is only the change history; hand edits appear in show but emit no event; a later set records old as the value currently in the file.")
