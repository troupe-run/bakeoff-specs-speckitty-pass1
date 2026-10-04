# Decision Moment `01M436RBNQT22F9AM54QER2FT9`

- **Mission:** `troupe-config-lineage-01M436R0`
- **Origin flow:** `specify`
- **Slot key:** `specify.lineage.legacy-events`
- **Input key:** `legacy_event_lineage`
- **Status:** `resolved`
- **Created:** `2026-10-04T10:18:35.575712+00:00`
- **Resolved:** `2026-10-04T10:19:49.095193+00:00`
- **Opened by:** `cli`
- **Other answer:** `false`

## Question

History recorded before this step has no actor, channel, reason or change id. How should 'troupe config history' report those older events?

## Options

- Report what is known, mark the rest unknown (recommended)
- Refuse to read a pre-lineage history
- Other

## Final answer

Out of contract; agent's choice: (A) report pre-lineage events with what is known (real 'at' from the stored event timestamp; actor unknown/null; reason null; via 'import' for import events, null for set/remove since cli vs file cannot be told apart; a stable per-event change id). Stored events are never rewritten. Recorded in the spec, not as a contract amendment.

## Rationale

_(none)_

## Change log

- `2026-10-04T10:18:35.575712+00:00` — opened
- `2026-10-04T10:19:49.095193+00:00` — resolved (final_answer="Out of contract; agent's choice: (A) report pre-lineage events with what is known (real 'at' from the stored event timestamp; actor unknown/null; reason null; via 'import' for import events, null for set/remove since cli vs file cannot be told apart; a stable per-event change id). Stored events are never rewritten. Recorded in the spec, not as a contract amendment.")
