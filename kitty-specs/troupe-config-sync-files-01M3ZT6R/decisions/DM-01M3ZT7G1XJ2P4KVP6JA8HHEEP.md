# Decision Moment `01M3ZT7G1XJ2P4KVP6JA8HHEEP`

- **Mission:** `troupe-config-sync-files-01M3ZT6R`
- **Origin flow:** `specify`
- **Slot key:** `specify.watch.invalid-edit`
- **Input key:** `watch_invalid_edit`
- **Status:** `resolved`
- **Created:** `2026-10-03T02:41:56.797027+00:00`
- **Resolved:** `2026-10-03T02:42:37.450835+00:00`
- **Opened by:** `cli`
- **Other answer:** `false`

## Question

While watch is running, a hand edit leaves the configuration unloadable (YAML syntax error mid-edit, include target missing, include cycle, or both troupe.yml and troupe.yaml present). What should watch do?

## Options

- Keep watching: report the problem on stderr naming the file, record nothing, reconcile normally once the files load again
- Stop: exit 4 naming the file, like other commands
- Other

## Final answer

Keep watching: report the problem on stderr naming the file, record nothing, reconcile normally once the files load again. Reason: the contract says watch runs until SIGINT/SIGTERM (exit 0), so exiting 4 mid-run would contradict it; recording nothing while unloadable cannot corrupt history, and reconciling against the last recorded configuration once the files load again loses no edit (TROUPE-002).

## Rationale

_(none)_

## Change log

- `2026-10-03T02:41:56.797027+00:00` — opened
- `2026-10-03T02:42:37.450835+00:00` — resolved (final_answer="Keep watching: report the problem on stderr naming the file, record nothing, reconcile normally once the files load again. Reason: the contract says watch runs until SIGINT/SIGTERM (exit 0), so exiting 4 mid-run would contradict it; recording nothing while unloadable cannot corrupt history, and reconciling against the last recorded configuration once the files load again loses no edit (TROUPE-002).")
