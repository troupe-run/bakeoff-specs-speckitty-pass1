---
work_package_id: WP01
title: Recorded configuration and theatre lock
dependencies: []
requirement_refs:
- C-001
- FR-001
- FR-016
planning_base_branch: feat/troupe-config-sync-files
merge_target_branch: feat/troupe-config-sync-files
branch_strategy: Planning artifacts for this mission were generated on feat/troupe-config-sync-files. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/troupe-config-sync-files unless the human explicitly redirects the landing branch.
base_branch: kitty/mission-troupe-config-sync-files-01M3ZT6R
base_commit: 7ef2861e0d0bd96bba1ce7e39e78df22960ed319
created_at: '2026-10-03T02:57:59.747846+00:00'
subtasks:
- T001
- T002
- T003
- T004
phase: Phase 1 - Foundation
history:
- at: '2026-10-03T03:00:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/troupe/lock.py
create_intent:
- src/troupe/lock.py
- tests/unit/test_lock.py
execution_mode: code_change
model: ''
owned_files:
- src/troupe/history.py
- src/troupe/lock.py
- tests/unit/test_history_store.py
- tests/unit/test_lock.py
role: implementer
tags: []
task_type: implement
tracker_refs: []
---

# Work Package Prompt: WP01 – Recorded configuration and theatre lock

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter (`agent_profile`, `role`, `agent`), and behave according to its guidance before parsing the rest of this prompt.

If no profile is specified, run `spec-kitty agent profile list` and select the best match for this work package's `task_type` and `authoritative_surface`.

---

## ⚠️ IMPORTANT: Review Feedback

- **Has review feedback?**: Check the `review_ref` field in the event log (via `spec-kitty agent tasks status`) or the Activity Log below.
- **You must address all feedback** before your work is complete.

---

## Objective

Provide the two foundations every other WP builds on:

1. **Recorded configuration**: the history aggregate maintains a path → value map of the leaves it has recorded, rebuilt by replaying events (spec FR-001, research R-04).
2. **Theatre lock**: one exclusive, cross-process lock per theatre, which serialises every session that can change the history (spec FR-016, research R-01/R-02).

Nothing in this WP changes command behaviour yet. WP02 wires both pieces in.

## Context

Read first:
- `kitty-specs/troupe-config-sync-files-01M3ZT6R/spec.md`: Intent Summary, FR-001, FR-016, C-003
- `kitty-specs/troupe-config-sync-files-01M3ZT6R/research.md`: R-01, R-02, R-04
- `kitty-specs/troupe-config-sync-files-01M3ZT6R/data-model.md`: "Recorded configuration" and "Theatre lock"
- `src/troupe/history.py` (current aggregate and store)
- `tests/unit/test_history_store.py` (existing store tests and their style)
- `.kittify/charter/charter.md`: TROUPE-002, -005, -006, -007

Charter rules that bite here:
- **TROUPE-005**: test against the real `eventsourcing` SQLite store and real processes, with no mocks. Test names state what they prove.
- **TROUPE-007**: the lock primitive lives only in `lock.py`, and recorded-leaf semantics only in `history.py`.

## Branch Strategy

- Planning/base branch: `feat/troupe-config-sync-files`
- Final merge target: `feat/troupe-config-sync-files` (delivered to `main` after acceptance)
- Execution worktrees are allocated per computed lane from `lanes.json`. Run `spec-kitty agent action implement WP01 --agent <name>` and work only in the worktree it gives you.

---

## Subtask T001 — `ConfigHistory.leaves` and `HistoryStore.recorded_leaves()`

**Purpose**: Make the recorded configuration available without duplicating event semantics outside the aggregate.

**Steps**:
1. In `ConfigHistory.__init__` (decorated `@event("Created")`), set `self.leaves: dict[str, JsonScalar] = {}`. eventsourcing runs the body of an `@event` method both when the event is first triggered and on every replay, so state set here is rebuilt on load.
2. Give the event method bodies effects (they are currently `pass`):
   - `leaf_imported(path, new)`: `self.leaves[path] = new`
   - `leaf_set(path, old, new)`: `self.leaves[path] = new`. An existing path keeps its dict position; a new path is appended.
   - `leaf_removed(path, old)`: `self.leaves.pop(path, None)`. **Use `pop(path, None)`, not `del`.** Step-1 histories can contain a `LeafRemoved` for a path that was never recorded: a step-1 `set` diffed against the files rather than the history, so a key added by hand and then removed by `set` was recorded as removed without ever being recorded as present. Replaying such a history must not crash (TROUPE-002). Mention this in a comment.
3. Add `HistoryStore.recorded_leaves() -> dict[str, JsonScalar]`:
   - It returns a **copy** of the aggregate's `leaves`, obtained via `self._app.repository.get(HISTORY_ID)`.
   - It raises `AggregateNotFoundError` before import, matching `record()`. Document this in the docstring; callers always import first.
4. Update the module docstring: the aggregate's state is the recorded configuration (FR-001 of this mission), and replay rebuilds it, so no migration is needed.
5. Do **not** change event classes, their fields or `records()`. Persisted data and `history` output must stay byte-identical.

**Files**: `src/troupe/history.py` (~25 changed lines).

**Validation**:
- `uv run mypy --strict` passes. `self.leaves` is typed, and `recorded_leaves` returns `dict[str, JsonScalar]`.
- Existing `tests/unit/test_history_store.py` and `tests/integration/test_history.py` pass unchanged.

**Edge cases**:
- An empty import (empty configuration) gives `leaves == {}`.
- A `LeafSet` with `new=None` keeps the path with value `None`, because presence matters (see `leaves.diff`).
- NaN values: `leaves` stores whatever was recorded. Equality is handled later by `leaves.same`, not here.

---

## Subtask T002 — Unit tests for recorded leaves

**Purpose**: Prove the recorded configuration equals what the events say, both in the session that wrote them and after reopening (replay).

**Add to** `tests/unit/test_history_store.py` (follow the existing fixtures; use a real `tmp_path` store):

1. `test_recorded_leaves_after_import_equal_imported_leaves_in_order`: import `{"a": 1, "b.0": "x", "c": None}`; `recorded_leaves()` equals that dict, and its keys are in the same order.
2. `test_recorded_leaves_apply_set_and_remove_events`: import `{"a": 1, "b": 2}`, then `record([Change("set","a",1,10), Change("set","n",None,"new"), Change("remove","b",2,None)])`. Result: `{"a": 10, "n": "new"}`, with `a` before `n`.
3. `test_recorded_leaves_are_rebuilt_after_reopening_the_store`: write events, `close()`, open a new `HistoryStore` on the same dir, and get the same `recorded_leaves()`.
4. `test_replay_tolerates_remove_of_a_never_recorded_path`: import `{"a": 1}`, record `[Change("remove","ghost","x",None)]`, then reopen. `recorded_leaves() == {"a": 1}`, no exception is raised, and `records()` still lists the remove event.
5. `test_recorded_leaves_returns_a_copy`: mutating the returned dict does not affect a second call.
6. `test_records_output_unchanged_by_leaves_state`: the existing `records()` assertions for a mixed history still hold. If an existing test already proves this, do not duplicate it.

Each test asserts exactly what its name says (TROUPE-005).

---

## Subtask T003 — `theatre_lock(state_dir)` in `src/troupe/lock.py`

**Purpose**: The single cross-process mutual-exclusion primitive (research R-02). Every history-changing session holds it: `open_session` in WP02, and each `watch` reconcile in WP03.

**Design**:
```python
"""The theatre lock: one exclusive, cross-process lock per theatre (research R-01, R-02).

An advisory ``flock`` on a file descriptor of the theatre's ``.troupe`` directory itself, so no
file is ever created. The kernel releases it when the descriptor is closed or the process dies,
so a crashed command can never leave a theatre locked. Locks are per open file description:
never take the lock twice in one process (a nested acquire on a new descriptor would deadlock).
"""

@contextmanager
def theatre_lock(state_dir: Path) -> Iterator[None]:
    try:
        fd = os.open(state_dir, os.O_RDONLY)
    except OSError as err:
        raise LoadError(f"cannot lock {state_dir}: {err.strerror or err}") from err
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)   # blocking
        yield
    finally:
        os.close(fd)                      # releases the lock
```

**Notes**:
- `flock` on an `O_RDONLY` directory descriptor works on Linux and macOS (C-001 platforms). Do not use `fcntl.lockf`/`fcntl` (POSIX record locks), which are per-process and are released when *any* descriptor to the file closes.
- An error opening the directory becomes `LoadError` (exit 4) naming the directory (TROUPE-003). In practice `locate()` has already proven that the directory exists.
- `flock` can raise `OSError` (e.g. `EINTR` is retried automatically by Python ≥3.5 per PEP 475). Do not catch anything else.
- No timeout: a holder always finishes, because sessions are short and `watch` never holds the lock while sleeping.

**Files**: `src/troupe/lock.py` (new, ~40 lines).

---

## Subtask T004 — Unit tests for the lock (`tests/unit/test_lock.py`)

**Purpose**: Prove mutual exclusion across real processes, release, and no file creation.

**Tests** (real subprocesses, no mocks):
1. `test_lock_held_by_another_process_blocks_this_one`:
   - Start a child with `subprocess.Popen([sys.executable, "-c", CODE], stdin=PIPE, stdout=PIPE)`. CODE does `with theatre_lock(Path(argv)): print("locked", flush=True); sys.stdin.read()`.
   - Wait for `locked` on its stdout, using a timeout (e.g. read in a thread, or `selectors`, with a 10-second deadline).
   - In the test process, open the dir and `fcntl.flock(fd, LOCK_EX | LOCK_NB)`. Expect `BlockingIOError`.
   - Close the child's stdin, wait for it to exit, then the non-blocking `flock` succeeds.
   - Use the non-blocking probe rather than elapsed-time measurements: it is deterministic.
2. `test_lock_is_released_when_the_context_exits`: in-process, after `with theatre_lock(d): pass`, a non-blocking `flock` on a new descriptor succeeds.
3. `test_lock_is_released_when_the_holder_dies`: the child acquires the lock, prints, then `os._exit(1)` inside the context. A non-blocking probe then succeeds.
4. `test_lock_creates_no_file`: the set of entries under `state_dir` is identical before and after using the lock.
5. `test_lock_on_missing_directory_raises_load_error_naming_it`: `pytest.raises(LoadError)` with the path in `err.message`; check `exit_code == 4`.

Make sure child processes run with the project's `src` importable: use the same interpreter (`sys.executable`); `uv run pytest` installs the package. Always terminate the child in `finally`.

---

## Definition of Done

- [ ] T001–T004 implemented. `history` output for existing histories is unchanged (existing tests pass untouched).
- [ ] `recorded_leaves()` documented, typed and tested, including tolerant replay.
- [ ] `lock.py` is the only place `fcntl.flock` is used.
- [ ] Gates run and output shown: `uv run pytest`, `uv run mypy --strict`, `uv run ruff check`, `uv run ruff format --check`.
- [ ] Subtasks marked: `spec-kitty agent tasks mark-status T001 T002 T003 T004 --status done --mission troupe-config-sync-files-01M3ZT6R`.

## Risks

- Changing event method bodies changes nothing persisted, but a typo in a body runs on every replay. Tests 2–4 of T002 cover all three event kinds.
- Lock tests that use sleeps would be flaky; use the non-blocking probe.

## Reviewer Guidance

- Check `pop(path, None)` in `leaf_removed` and the comment explaining why.
- Check that `recorded_leaves` returns a copy.
- Check that no file appears under `.troupe/` because of the lock.
- Check that no test mocks `eventsourcing` or `fcntl`.

## Activity Log

- 2026-10-03T03:00:00Z – system – Prompt generated via /spec-kitty.tasks
