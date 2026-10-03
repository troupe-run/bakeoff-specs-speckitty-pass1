---
work_package_id: WP02
title: Reconcile and reconcile-first commands
dependencies:
- WP01
requirement_refs:
- C-002
- FR-002
- FR-003
- FR-004
- FR-005
- FR-006
- FR-007
- NFR-004
- NFR-007
planning_base_branch: feat/troupe-config-sync-files
merge_target_branch: feat/troupe-config-sync-files
branch_strategy: Planning artifacts for this mission were generated on feat/troupe-config-sync-files. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/troupe-config-sync-files unless the human explicitly redirects the landing branch.
subtasks:
- T005
- T006
- T007
- T008
- T009
- T010
phase: Phase 2 - Reconcile (User Story 1)
history:
- at: '2026-10-03T03:00:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/troupe/reconcile.py
create_intent:
- src/troupe/reconcile.py
- tests/unit/test_reconcile.py
- tests/integration/test_reconcile_first.py
execution_mode: code_change
model: ''
owned_files:
- src/troupe/reconcile.py
- src/troupe/session.py
- src/troupe/commands/show.py
- src/troupe/commands/set_value.py
- src/troupe/commands/history.py
- tests/unit/test_reconcile.py
- tests/integration/test_reconcile_first.py
- tests/integration/test_history.py
- tests/integration/test_set_history.py
role: implementer
tags: []
task_type: implement
tracker_refs: []
---

# Work Package Prompt: WP02 – Reconcile and reconcile-first commands

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter (`agent_profile`, `role`, `agent`), and behave according to its guidance before parsing the rest of this prompt.

If no profile is specified, run `spec-kitty agent profile list` and select the best match for this work package's `task_type` and `authoritative_surface`.

---

## ⚠️ IMPORTANT: Review Feedback

- **Has review feedback?**: Check the `review_ref` field in the event log (via `spec-kitty agent tasks status`) or the Activity Log below.
- **You must address all feedback** before your work is complete.

---

## Objective

Implement **reconcile** once and make `show` and `set` reconcile first, while `history` never reconciles. After this WP, edits made while nothing was running are picked up by the next command (User Story 1).

This WP **deliberately changes step-1 behaviour**. Step 1 said hand edits never produce events (step-1 FR-008/FR-022, DM 01M3XGPT4E0D67ZJY8PT7Z9NAT); this mission supersedes that. Spec, code and tests must change together (TROUPE-008/009).

**Requirements**: FR-002, FR-003, FR-004, FR-005, FR-006, FR-007, NFR-004, NFR-007, C-002.

## Context

Read first:
- `kitty-specs/troupe-config-sync-files-01M3ZT6R/spec.md`: Intent Summary, D-5/D-6/D-7, User Story 1, FR-002–FR-007, Edge Cases
- `kitty-specs/troupe-config-sync-files-01M3ZT6R/research.md`: R-01, R-07, R-10
- `kitty-specs/troupe-config-sync-files-01M3ZT6R/data-model.md`: Reconcile, Watched files, Session
- `src/troupe/session.py`, `src/troupe/leaves.py` (`flatten`, `diff`, `same`; reuse them, do not reimplement), `src/troupe/commands/*.py`, `src/troupe/tree.py`
- WP01 output: `HistoryStore.recorded_leaves()`, `troupe.lock.theatre_lock`

## Branch Strategy

- Planning/base branch: `feat/troupe-config-sync-files`. Final merge target: `feat/troupe-config-sync-files` (then `main`).
- Execution worktrees are allocated per computed lane from `lanes.json`. Run `spec-kitty agent action implement WP02 --agent <name>`.

---

## Subtask T005 — `src/troupe/reconcile.py`

**Purpose**: The one named place for the reconcile rule (TROUPE-007), plus the watched-files rule `watch` will use in WP03.

**Contents**:
```python
"""Reconcile: bring the recorded configuration in line with the files (FR-002, FR-003).

The rule: record ``diff(recorded leaves, leaves of the files)`` and nothing else. Because a
``set`` records its own events in the same locked session as its write-back, a reconcile that
later sees the write-back finds no difference: write-backs are never recorded twice (FR-015,
research R-01). Reconcile only reads files; it never writes them (NFR-004).
"""

def reconcile(store: HistoryStore, tree: Node) -> list[Change]:
    """Record one event per leaf that differs between the history and ``tree``; return them.

    Ordering (D-6) is ``leaves.diff``'s: ``set`` in file document order, then ``remove`` in
    recorded order. All events are saved in one atomic ``save()``; nothing is saved for ``[]``.
    Call only under the theatre lock and only after the theatre has been imported.
    """
    changes = diff(store.recorded_leaves(), flatten(tree))
    store.record(changes)
    return changes


def watched_files(tree: Node) -> dict[Path, bytes]:
    """Return every file the load read, mapped to its bytes as loaded (research R-03).

    That is the origin file of every node plus every include target (YAML and text, any depth).
    ``SourceFile.text`` is strict-UTF-8-decoded without newline translation, so encoding it back
    gives exactly the bytes that were read.
    """
```
- `watched_files` walks the tree:
  - `ScalarNode`/`MappingNode`/`SequenceNode`: `origin.file`. For a `MappingNode`, recurse into `entry.value`; for a `SequenceNode`, into items.
  - `YamlInclude`: `origin.file`, `target`, recurse into `root`.
  - `TextInclude`: `origin.file`, `target`.
- Key the result by `SourceFile.path` (already resolved). `SourceFile` has `eq=False`, so never key by the object.
- An empty root document still yields the root file, because the empty `MappingNode` has an origin in it.

**Files**: `src/troupe/reconcile.py` (new, ~60 lines).

---

## Subtask T006 — `open_session(theatre, *, reconcile)` in `src/troupe/session.py`

**Purpose**: The single place that decides *when* a command imports or reconciles (research R-07), all under the theatre lock.

**New behaviour**:
```python
@contextmanager
def open_session(theatre: Theatre, *, reconcile: bool) -> Iterator[Session]:
    with theatre_lock(theatre.state_dir):
        current = locate(theatre.directory)   # root may have been renamed since the CLI located it
        tree = load(current.config_file)      # LoadError → exit 4, nothing created or recorded
        store = HistoryStore(current.state_dir)
        try:
            if not store.is_imported():
                store.import_leaves(flatten(tree))
            elif reconcile:
                reconciliation.reconcile(store, tree)
            yield Session(current, tree, store)
        finally:
            store.close()
```
- Make `reconcile` a **required keyword**, with no default, so no caller can forget the decision.
- To avoid the name clash between the parameter and the function, import the module (`from troupe import reconcile as reconciliation`) or rename at import. Pick one and keep it readable.
- Order matters:
  - The lock comes first, so a concurrent `watch` reconcile cannot interleave.
  - Load comes before `HistoryStore(...)`, so a load failure still creates no history file (existing test `test_load_failure_creates_no_history_file`).
  - The reconcile's `save()` completes before `yield`, so its events survive a later exit 3/5 (D-7).
- Right after an import the files equal the recorded configuration, so do not reconcile after importing.
- Rewrite the module docstring. Remove "Importing is not reconciling: once imported, later hand edits never produce events". State the new rule: import on first command; otherwise reconcile when asked; `history` never asks; everything runs under the theatre lock.

---

## Subtask T007 — Command wiring

- `commands/show.py`: `open_session(theatre, reconcile=True)`.
- `commands/set_value.py`: `open_session(theatre, reconcile=True)`.
  - The `set`'s own changes are still `diff(flatten(session.tree), flatten(plan.tree))`. `session.tree` is now the reconciled state, so `old` values are current file values (FR-007).
  - Writing files and `session.history.record(changes)` both stay **inside** the `with` block, so the whole `set` is under the lock. This is what makes FR-015 hold in WP04.
  - Update the docstring's "Order" list: step 2 becomes "open the session: lock, load, import or reconcile".
- `commands/history.py`: `open_session(theatre, reconcile=False)`. Add a docstring sentence: `history` never reconciles (FR-005); it reports what has been recorded.
- Usage errors (`parse_path`, `parse_value`) stay **before** `open_session` (Edge Cases: exit 2 before anything is loaded or reconciled).

---

## Subtask T008 — `tests/unit/test_reconcile.py`

Use real files: build theatres with `tmp_path`, `load()` them, and use a real `HistoryStore`. Tests:
1. `test_reconcile_records_nothing_when_files_equal_recorded_configuration`
2. `test_reconcile_records_changed_value_as_set_with_old_and_new`
3. `test_reconcile_orders_sets_in_document_order_then_removes_in_recorded_order`: recorded `a, b, c, d`; files `d: changed`, `a: changed`, `e: new`, with `b` and `c` absent. Expect `set d`, `set a`, `set e` (file order) and then `remove b`, `remove c`.
4. `test_formatting_and_comment_only_edits_record_nothing`: parametrize over pairs of file texts with equal leaves:
   - indentation change
   - trailing comment added
   - `0.2` → `0.20`
   - `'a'` → `a` → `"a"`
   - block list ↔ flow list
   - block mapping ↔ flow mapping
   - blank lines
   - include `file:x.yaml` replaced by the same content inline
5. `test_type_change_with_same_text_is_recorded`: `"1"` → `1`; also `1` → `1.0` and `true` → `"true"`.
6. `test_value_set_to_null_is_a_set_not_a_remove`: `a: 1` → `a: null` gives `set a 1→None`; `a` deleted gives `remove a`.
7. `test_reconcile_never_writes_files`: snapshot bytes and mtimes of all files before and after a reconcile with changes; they are identical.
8. `test_watched_files_cover_root_yaml_includes_and_text_includes_at_any_depth`: root → `a.yaml` → `b.yml` → `t.md` (text). All four paths are present, with bytes equal to `read_bytes()`, including a CRLF file and a BOM file.
9. `test_watched_files_of_empty_root_contain_the_root`.

---

## Subtask T009 — Rewrite superseded step-1 tests (research R-10)

Rewrite these; do not delete them:
1. `tests/integration/test_set_history.py::test_set_after_hand_edit_records_the_hand_edited_value_as_old`
   - Rename to `test_set_after_hand_edit_records_the_hand_edit_then_the_set`.
   - Keep `assert _history(theatre) == IMPORT` after the hand edit. It is still true, because `history` never reconciles; update its comment to say so.
   - After the `set`, the last two events are:
     - `_event(7, "set", "model.name", "gpt", "hand")`: the reconcile
     - `_event(8, "set", "model.name", "hand", "set")`: the set's own event
   - Check the fixture's import count before trusting these seq numbers. Keep the file-bytes assertion.
   - Update the module docstring line "(hand edits included)" to describe the new rule.
2. `tests/integration/test_history.py::test_hand_edit_after_import_produces_no_event`
   - Rename to `test_history_does_not_reconcile_a_hand_edit`. Keep its current assertions.
   - Extend it: run `show a`, then `history`. Expect the imported events plus `{"seq":3,"op":"set","path":"a","old":1,"new":100}`, `{"seq":4,"op":"set","path":"c","old":null,"new":3}` and `{"seq":5,"op":"remove","path":"b","old":2,"new":null}`, in that order.
3. Run the full suite. Any other test that implicitly relied on "hand edits never produce events" must be rewritten the same way, with its name stating the new behaviour. List each one in your WP summary.

---

## Subtask T010 — `tests/integration/test_reconcile_first.py`

Black-box via `run_cli` from `tests/conftest.py`. Parse `history` output as JSON Lines. Map each spec scenario to a test; the number in the name comment is the US1 scenario:
1. Hand-edit `model.temperature` 0.2 → 0.5; `show` prints `0.5\n`; `history` ends with exactly one `set` 0.2→0.5. (1)
2. A key added by hand gives `set` with `old: null`. (2)
3. A list item deleted by hand gives `remove tools.1`. (3)
4. Formatting-only and comment-only edits followed by `show` record nothing. (4) One integration case is enough; T008 covers the variety.
5. A text-include target edited gives one `set prompt` with the old and new texts. (5)
6. `history` after a hand edit records nothing; `show` then records it; a second `history` shows it. (6)
7. Hand edit, then `set` to a third value gives the reconcile event followed by the `set` event. (7)
8. Hand edit, then a `set` refused with exit 3 (e.g. replacing a whole YAML include), and separately a `set` failing with exit 5. The reconcile events are kept, no `set` event is recorded, and every file is byte-identical (`snapshot`). (8, D-7)
9. A hand edit making the config unloadable (bad YAML; both root files): `show` and `set` exit 4, stdout is empty, stderr names the file, and `history` is unchanged. Restore the files afterwards and `history` still shows nothing new until a reconcile. (9)
10. Two consecutive `show`s after one hand edit record it once. (10)
11. Usage error first: `set "a..b" 1` with a pending hand edit exits 2 and records nothing.
12. NFR-004: across tests 1–7 and 10, `snapshot(theatre)` equals the hand-edited bytes; the reconcile wrote nothing.
13. Existing histories: a theatre imported and `set` under the old code path (simulate by running the step-1 sequence: `history`, `set`, then a hand edit) reconciles correctly on `show`. This is a smoke test that replaying older histories works.

---

## Definition of Done

- [ ] `reconcile.py`, `session.py` and the command changes implemented as above. `reconcile` is a required keyword.
- [ ] All step-1 tests pass, or are rewritten per T009 with names stating the new behaviour (none deleted).
- [ ] New unit and integration tests pass, and each test name matches its assertions.
- [ ] Gates run and output shown: `uv run pytest`, `uv run mypy --strict`, `uv run ruff check`, `uv run ruff format --check`.
- [ ] `spec-kitty agent tasks mark-status T005 T006 T007 T008 T009 T010 --status done --mission troupe-config-sync-files-01M3ZT6R`.

## Risks

- Taking the lock around the whole session: never call `open_session` inside another `open_session` in the same process. A nested `flock` on a new descriptor deadlocks.
- The lock is taken before `locate`. `theatre.state_dir` exists because the CLI's `locate` already succeeded. If `.troupe` vanished in between, `theatre_lock` raises `LoadError` (exit 4), which is fine.

## Reviewer Guidance

- Check that reconcile ordering comes from `leaves.diff`, not a new sort.
- Check that `history` passes `reconcile=False`.
- Check that the D-7 test asserts that the reconcile events are *kept*.
- Check that superseded tests were rewritten, not deleted, and that the session docstring no longer claims hand edits never produce events.

## Activity Log

- 2026-10-03T03:00:00Z – system – Prompt generated via /spec-kitty.tasks
