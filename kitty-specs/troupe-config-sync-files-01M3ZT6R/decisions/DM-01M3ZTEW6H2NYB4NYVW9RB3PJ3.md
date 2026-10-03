# Decision Moment `01M3ZTEW6H2NYB4NYVW9RB3PJ3`

- **Mission:** `troupe-config-sync-files-01M3ZT6R`
- **Origin flow:** `plan`
- **Slot key:** `plan.architecture.write-back-suppression`
- **Input key:** `write_back_suppression`
- **Status:** `resolved`
- **Created:** `2026-10-03T02:45:58.609043+00:00`
- **Resolved:** `2026-10-03T02:46:56.837901+00:00`
- **Opened by:** `cli`
- **Other answer:** `false`

## Question

How is a set's write-back kept from being recorded again by watch, and each hand edit recorded exactly once when watch and a command reconcile at about the same time?

## Options

- Theatre lock + compare: every reconcile and every set holds an exclusive lock on .troupe/lock across load, compare, write and record; watch only records what differs from the recorded configuration, so an already-recorded write-back produces nothing
- Fingerprint ignore list: set writes the hashes of files it wrote to a side file; watch skips changes whose bytes match
- Other

## Final answer

(A) Theatre lock + compare. Every reconcile and every set holds an exclusive flock on <theatre>/.troupe/lock across load, compare, write and record; reconcile records only leaves differing from the recorded configuration. (B) rejected by product owner: it would lose or suppress hand edits.

## Rationale

_(none)_

## Change log

- `2026-10-03T02:45:58.609043+00:00` — opened
- `2026-10-03T02:46:56.837901+00:00` — resolved (final_answer="(A) Theatre lock + compare. Every reconcile and every set holds an exclusive flock on <theatre>/.troupe/lock across load, compare, write and record; reconcile records only leaves differing from the recorded configuration. (B) rejected by product owner: it would lose or suppress hand edits.")
