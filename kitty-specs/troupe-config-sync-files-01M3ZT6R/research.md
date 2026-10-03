# Research: troupe configuration: sync with files

Each entry: Decision, Rationale, Alternatives considered. Step-1 research
(`kitty-specs/troupe-config-load-show-set-01M3XGPG/research.md`) still applies except R-03 (source
of truth) and R-04 (import timing), which this step extends as described in R-01 and R-07.

## R-01 Exactly-once recording and write-back suppression (DM-01M3ZTEW6H2NYB4NYVW9RB3PJ3)

- **Decision**: Use a theatre lock plus comparison. A reconcile records `diff(recorded leaves, file leaves)` and nothing else. Every session holds an exclusive theatre lock from load to its last record: `show`, `set`, `history` and each `watch` reconcile. `set` records its own events before releasing the lock.
- **Rationale**: Write-back suppression then follows from the invariant itself, with no bookkeeping. When `watch` sees a write-back, its leaves already equal the recorded configuration, so it records nothing. A hand edit is recorded by whichever reconcile takes the lock first, and every later reconcile sees no difference. The outcome the product owner requires is met: the `set` emits exactly its own events, every hand edit is reconciled, and state lives only under `.troupe/`.
- **Alternatives considered**:
  - (B) A fingerprint ignore list written by `set`. Rejected by the product owner: a hand edit saved between the write-back and `watch`'s check is lost or double-counted, and a hand edit that restores earlier bytes is suppressed.
  - Relying on eventsourcing's optimistic version check alone. Two reconciles of the same edit would both compute the same events; one save fails and would need a retry-with-recompute loop, which is more code and more failure modes than one lock.

## R-02 Lock primitive

- **Decision**: Use `fcntl.flock(fd, LOCK_EX)`, where `fd = os.open(<theatre>/.troupe, O_RDONLY)`, wrapped in a context manager `theatre_lock(state_dir)` in `troupe/lock.py`. The lock is blocking. It is released when the fd is closed, and the kernel releases it automatically if the process dies.
- **Rationale**: This creates no file, which keeps `test_history.py::test_history_creates_only_history_files_under_dot_troupe` and the step-1 "load failure creates nothing" guarantees true. `flock` on a directory fd works on Linux and macOS (C-001 platforms). Locks held by crashed processes can never block forever.
- **Alternatives considered**:
  - A `.troupe/lock` file: allowed by the product owner, but it creates a new file in every theatre and breaks two existing file-set assertions for no gain.
  - SQLite `BEGIN EXCLUSIVE` around the session: this cannot cover the file write in `set`, and it couples the lock to the store's internals.

## R-03 Observing changes: stdlib polling

- **Decision**: Every 0.25 s, `watch` reads the bytes of each watched file and of both root candidates (`troupe.yml`, `troupe.yaml`). For each it notes whether the file is absent or what its bytes are, and compares the result with the baseline. Any difference triggers a reconcile. The baseline is built from the exact texts the reconcile's load read, re-encoded as UTF-8 (which reproduces the bytes exactly, since the loader decodes strict UTF-8 without newline translation). The two root candidates are recorded as present or absent.
- **Rationale**:
  - Comparing bytes rather than mtime/size catches same-size edits within a coarse mtime tick, and editor saves that write a temp file and rename it over the original (the inode changes, the path stays the same).
  - Because the baseline comes from the load itself, an edit made after the load and before `watching` is printed is still detected. That keeps the readiness line's promise (NFR-002).
  - The worst-case detection delay is about one interval plus reconcile time, far below 2 s.
  - Configurations are small, so polling costs little. The product owner accepted this approach.
- **Alternatives considered**:
  - `watchdog` (inotify/FSEvents): adds a dependency, has platform-specific backends, needs rename/atomic-save handling, and still needs a polling fallback.
  - mtime-only polling: misses same-tick edits on coarse filesystems.
  - Reconciling on every tick without checking for changes: this would print unloadable errors repeatedly and take the lock four times a second for nothing.

## R-04 Recorded configuration on the aggregate

- **Decision**: `ConfigHistory.__init__` sets `self.leaves: dict[str, JsonScalar] = {}`. The `leaf_imported` and `leaf_set` bodies assign `leaves[path] = new`, and the `leaf_removed` body does `del leaves[path]`. `HistoryStore.recorded_leaves()` returns a copy. Persisted events are unchanged.
- **Rationale**: eventsourcing re-runs `@event` method bodies on replay, so existing step-1 databases produce the right map without migration, and `history` output is byte-identical (the product owner requires existing histories to be reported exactly as before). Dict insertion order gives the "recorded configuration's order" that D-6 uses for removes.
- **Alternatives considered**:
  - Recomputing the map from `records()` in `reconcile.py`: duplicates the event semantics outside the aggregate (TROUPE-007).
  - A separate snapshot table: new persisted state with a consistency risk.

## R-05 Unloadable configuration during `watch` (D-1)

- **Decision**: `watch` holds a `last_error: str | None`. On a tick:
  - If the configuration is currently unloadable, attempt a reconcile, whether or not the bytes changed. Retrying covers a missing include target being created, which is a file not in any baseline.
  - On `LoadError`, write `troupe: <message>` to stderr only if the message differs from `last_error`, then store it.
  - On success, clear `last_error` and rebuild the baseline.
  - `locate()` runs inside each reconcile, so renaming the root file, or having both or neither root file, is handled the same way.
- **Rationale**: The product owner left the stderr frequency to us. One line per distinct problem is informative without flooding. Every message comes from `LoadError`, which already names the file (TROUPE-003).
- **Alternatives considered**: watching the paths the failed load tried. That needs the loader to report partial reads on failure, and it still misses a newly created target.

## R-06 Signals and process shape

- **Decision**: `watch` installs SIGINT and SIGTERM handlers that set a `threading.Event`, and the loop sleeps with `event.wait(0.25)`. The flag is checked only between ticks, so a reconcile in progress (one atomic `save()`) always completes. Then `watch` returns, and the CLI exits 0 with no further stdout.
- **Rationale**: The contract says `watch` exits 0 on either signal. Python's default SIGINT raises `KeyboardInterrupt` at an arbitrary point, and replacing that behaviour avoids the traceback and the non-zero exit. Exit happens within about 0.25 s plus one reconcile (NFR-005: under 2 s).

## R-07 Reconcile-first ordering inside commands

- **Decision**: `open_session(theatre_dir, reconcile)` runs these steps:
  1. Take the lock.
  2. `locate()`.
  3. `load()`.
  4. Open the store.
  5. If the theatre has never been imported, import it. Otherwise, if `reconcile` is set, record `diff(recorded, flatten(tree))`.
  6. Yield the session; the command's own work happens inside the lock.

  `set` computes its own events from that same `tree`, so its `old` values are the post-reconcile values. Usage errors (PATH/VALUE parsing) stay before the session. A reconcile's events are saved in their own `save()` before the command's work, so a later exit 3 or 5 keeps them (D-7).
- **Rationale**: One place decides reconcile timing, as step 1 did for import. Right after an import the files equal the recorded configuration, so no reconcile is needed.
- **Note**: the CLI's early `locate()` (exit 4 before importing any command module) stays. The session locates again under the lock, so a root file renamed in between is handled.

## R-08 Supply chain (directive 051, advisory)

- **Decision**: No dependency is added, upgraded or removed. `fcntl`, `signal`, `threading` and `os` are stdlib.
- **Adversarial evidence**: No security-impacting dependency decision was made, so no squad pass is required. Recorded disposition: `deferred_with_rationale` (nothing to challenge).

## R-09 Output channel for a long-running command

- **Decision**: The CLI stays the only writer of stdout and stderr. Step-1 commands keep `run(theatre, args) -> str`. `watch` exposes `watch(theatre_dir, given_dir, announce, report, stop) -> None`. `announce(line)` writes to stdout and flushes, `report(message)` writes `troupe: <message>` to stderr, and the CLI passes both in. A `LoadError` at startup is raised before `announce` is called, so stdout stays empty and the exit code is 4.
- **Rationale**: This keeps the step-1 "stdout written in one place" discipline (cli.py docstring) and lets the readiness line be flushed exactly when `watch` is ready.

## R-10 Superseded step-1 tests

- **Decision**:
  - `tests/integration/test_set_history.py::test_set_after_hand_edit_records_the_hand_edited_value_as_old` is rewritten to expect the reconcile event, then the `set` event.
  - `tests/integration/test_history.py::test_hand_edit_after_import_produces_no_event` still holds for `history` alone (it never reconciles). It is renamed to state exactly that, and is extended so that a following `show` records the edit.
- **Rationale**: TROUPE-008/009 require spec, code and tests to change together, and a superseded behaviour's test must not silently disappear.
