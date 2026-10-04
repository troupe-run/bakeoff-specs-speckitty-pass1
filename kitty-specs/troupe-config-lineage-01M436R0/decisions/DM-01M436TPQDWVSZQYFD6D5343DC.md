# Decision Moment `01M436TPQDWVSZQYFD6D5343DC`

- **Mission:** `troupe-config-lineage-01M436R0`
- **Origin flow:** `specify`
- **Slot key:** `specify.lineage.actor-check-order`
- **Input key:** `actor_check_order`
- **Status:** `resolved`
- **Created:** `2026-10-04T10:19:52.429418+00:00`
- **Resolved:** `2026-10-04T10:19:55.907552+00:00`
- **Opened by:** `cli`
- **Other answer:** `false`

## Question

Should every troupe config command check TROUPE_ACTOR before locating/loading the configuration?

## Options

_(none)_

## Final answer

Yes: validate TROUPE_ACTOR after argument parsing and before the theatre is located or loaded, so a bad value exits 2 and nothing (not even an import or reconcile) is recorded. Safest: a command that will fail records nothing.

## Rationale

_(none)_

## Change log

- `2026-10-04T10:19:52.429418+00:00` — opened
- `2026-10-04T10:19:55.907552+00:00` — resolved (final_answer="Yes: validate TROUPE_ACTOR after argument parsing and before the theatre is located or loaded, so a bad value exits 2 and nothing (not even an import or reconcile) is recorded. Safest: a command that will fail records nothing.")
