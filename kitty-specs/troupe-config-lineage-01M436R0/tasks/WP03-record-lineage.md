---
work_package_id: WP03
title: Record lineage in the store and every producer
dependencies:
- WP01
- WP02
requirement_refs:
- C-005
- FR-003
- FR-005
- FR-006
- FR-007
- FR-008
- FR-009
- FR-010
- FR-011
- FR-012
- FR-013
- FR-014
- NFR-001
- NFR-002
planning_base_branch: feat/troupe-config-lineage
merge_target_branch: feat/troupe-config-lineage
branch_strategy: Planning artifacts for this mission were generated on feat/troupe-config-lineage. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/troupe-config-lineage unless the human explicitly redirects the landing branch.
subtasks:
- T009
- T010
- T011
- T012
- T013
- T014
- T015
phase: Phase 2 - Recording
history:
- at: '2026-10-04T10:28:42Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/troupe/history.py
create_intent:
- tests/integration/test_lineage_recording.py
execution_mode: code_change
model: ''
owned_files:
- src/troupe/history.py
- src/troupe/session.py
- src/troupe/reconcile.py
- src/troupe/cli.py
- src/troupe/commands/set_value.py
- src/troupe/commands/get.py
- src/troupe/commands/show.py
- tests/unit/test_history_store.py
- tests/unit/test_reconcile.py
- tests/conftest.py
- tests/integration/test_lineage_recording.py
role: implementer
tags: []
task_type: implement
tracker_refs: []
---

# Work Package Prompt: WP03 – Record lineage in the store and every producer

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter (`agent_profile`, `role`, `agent`), and behave according to its guidance before parsing the rest of this prompt.

If no profile is specified, run `spec-kitty agent profile list` and select the best match for this work package's `task_type` and `authoritative_surface`.

---

## ⚠️ IMPORTANT: Review Feedback

- **Has review feedback?**: Check the `review_ref` field in the event log (via `spec-kitty agent tasks status`) or the Activity Log below.
- **You must address all feedback** before your work is complete.

---

## Objective

After this WP:

- Every event saved to a theatre's history carries lineage (actor, via, at, reason, change). The lineage is built **once per producer**: one import, one file reconcile, or one command's own work. All of a producer's events are saved in one atomic `save()`.
- Events recorded before this step are upgraded with their lineage **when they are read**, through eventsourcing's upcasting hook. Stored rows are never rewritten.
- Every `troupe config` command checks `TROUPE_ACTOR` after argument parsing and **before** the theatre is located. An invalid value exits 2 and records nothing.
- `troupe config set PATH VALUE --reason TEXT` stores TEXT as the reason of the set's own events.

**Out of scope:** the `history` output format. `commands/history.py` keeps printing the five step-1 keys until WP04. Keeping it unchanged is what keeps the existing integration tests green in this WP.

## Context

Read first:
- `kitty-specs/troupe-config-lineage-01M436R0/spec.md`: Intent Summary, FR-003, FR-005 to FR-014, NFR-001, NFR-002, C-003, C-005, Edge Cases
- `kitty-specs/troupe-config-lineage-01M436R0/research.md`: **D-1, D-2, D-7** (storage, upcast, plumbing)
- `kitty-specs/troupe-config-lineage-01M436R0/data-model.md`: event v2 table and the six invariants
- `kitty-specs/troupe-config-lineage-01M436R0/contracts/cli.md`
- `src/troupe/lineage.py` (WP01): use **only** its API to build actors and lineages and to map fields
- `tests/fixtures/pre_lineage/` (WP02): the real step-3 database and the `expected_history.jsonl` oracle
- Current code: `src/troupe/history.py`, `session.py`, `reconcile.py`, `cli.py`, `commands/*.py`
- eventsourcing: `.venv/lib/python3.12/site-packages/eventsourcing/persistence.py`, `Mapper.to_domain_event`. It decodes the state (datetimes already become `datetime` objects), sets `originator_id`/`originator_version`, then calls `cls.upcast_v{n}_v{n+1}(state)` while the stored `class_version` (default 1) is below the class's `class_version`.

## Branch Strategy

- Planning/base branch: `feat/troupe-config-lineage`; final merge target: `feat/troupe-config-lineage`.
- Execution worktrees are allocated per computed lane from `lanes.json`; implement with `spec-kitty agent action implement WP03 --agent <name>` (depends on WP01, WP02).

## Subtasks

### T009 — Event classes v2 and `upcast_v1_v2` (`src/troupe/history.py`)

**Hard constraint (plan Risks):** do **not** rename, move or nest the event classes differently. Stored rows are found by topic (`troupe.history:ConfigHistory.LeafImported` and so on). The WP02 fixture test proves this.

For each of `LeafImported`, `LeafSet`, `LeafRemoved`:

```python
class LeafSet(Aggregate.Event):
    class_version = 2

    path: str
    old: JsonScalar
    new: JsonScalar
    actor_kind: str
    actor_id: str | None
    via: str | None
    at: str
    reason: str | None
    change: str

    @staticmethod
    def upcast_v1_v2(state: dict[str, Any]) -> None:
        _upcast_pre_lineage(state, via=None)          # "import" for LeafImported
```

```python
def _upcast_pre_lineage(state: dict[str, Any], via: Via | None) -> None:
    """Give a step-1..3 event its lineage when it is read (DM 01M436RBNQT22F9AM54QER2FT9, D-2)."""
    seq = state["originator_version"] - 1
    state.update(pre_lineage_fields(seq, via, state["timestamp"]))
```

- The `@event(...)` methods must take every event field: `def leaf_set(self, path, old, new, actor_kind, actor_id, via, at, reason, change)`. Their bodies are unchanged and ignore the lineage, so replaying `leaves` is unaffected.
- Check by experiment, and record the finding in a code comment, that eventsourcing stores `class_version: 2` in new rows' state and that an old row reaches `upcast_v1_v2` with `timestamp` already a `datetime`. The `Created` event and the aggregate itself stay at version 1. There are no snapshots.
- Update the module docstring: lineage is stored per event (FR-012), old events are upcast on read, and the database is never rewritten (C-005).

### T010 — Store API takes `Lineage`; `HistoryRecord.lineage`

- `import_leaves(self, leaves: dict[str, JsonScalar], lineage: Lineage) -> None`: every `leaf_imported(...)` call gets `**lineage_fields(lineage)`. The empty-leaves case still creates the aggregate.
- `record(self, changes: list[Change], lineage: Lineage) -> None`: same. It still does nothing for `[]`.
- Both still issue **one** `save()` (NFR-001). Docstrings: "every event saved by one call shares `lineage`; call once per producer".
- `HistoryRecord` gains `lineage: Lineage` as its last attribute. `records()` builds it with `lineage_from_fields(e.actor_kind, e.actor_id, e.via, e.at, e.reason, e.change)`.
- Do not add any lineage logic of your own here; it all goes through `troupe.lineage` (TROUPE-007).

### T011 — Import lineage in `session.py`; file lineage in `reconcile.py`

- `session.open_session`: `store.import_leaves(flatten(tree), import_lineage())`. Signature unchanged. Update the docstring: an import is its own change, attributed to the unknown actor via `import`.
- `reconcile.reconcile(store, tree)`: `store.record(changes, file_lineage())`. Each call is its own change, which covers the reconcile-first step of every command and **each** `watch` reconcile (FR-011) without touching `watch.py`. Update the docstring.
- The CLI actor must never reach these two places (FR-005). They take no actor parameter.

### T012 — `cli.py`: actor resolution and `Command.run(theatre, args, actor)`

- In `main`, right after `args = build_parser().parse_args(argv)` and **before** computing the theatre or calling `locate`: `actor = resolve_actor(os.environ)`. A `UsageError` from it goes through the existing `except TroupeError` path: one `troupe: ...` stderr line, exit 2, empty stdout (spec DM 01M436TPQDWVSZQYFD6D5343DC).
- `watch` is validated too (the actor is resolved before the `watch` branch) but needs no actor of its own.
- `Command` protocol becomes `def run(self, theatre: Theatre, args: argparse.Namespace, actor: Actor) -> str: ...`, and `main` passes `actor`.
- Update `commands/get.py` and `commands/show.py` to accept `actor: Actor` (unused, documented as such).
- **Out-of-map edit, recorded:** `commands/history.py` belongs to WP04, but its `run` signature must change here for the protocol to stay consistent. Change **only** the signature (`actor: Actor`, unused) and note it in your handoff. Do not touch its output.
- Update the `cli.py` module docstring: `TROUPE_ACTOR` is resolved once, here, before the theatre is located.

### T013 — `set --reason TEXT` and the set's own lineage

- Parser: `set_.add_argument("--reason", metavar="TEXT", default=None, help="record TEXT as the reason for this change")`. Only `set` gets it, so `--reason` on any other command is an argparse error, which is already `UsageError` with exit 2.
- `commands/set_value.run(theatre, args, actor)`: after `write_files` succeeds, `session.history.record(changes, cli_lineage(actor, args.reason))`.
  - A no-op `set` returns before this line and records nothing (FR-014).
  - A refused or failed write raises before it, so the set records nothing, while the reconcile already saved in `open_session` is kept as its own change (D-7 of step 2, FR-014).
- Update the module docstring's step 5 to mention lineage.

### T014 — Unit tests

**`tests/unit/test_history_store.py`.** Update existing calls to pass a lineage; use a small local helper that calls `cli_lineage(Actor("human", "t"), None)` or `import_lineage()`. Existing `HistoryRecord(...)` equality assertions must still check the five original fields. Compare `(r.seq, r.op, r.path, r.old, r.new)` tuples, or build expected records with the actual lineage. Do not weaken them. Add:
- `test_lineage_is_persisted_and_read_back_after_reopen`: a lineage with every field set, including a reason containing a newline and non-ASCII text → `_reopened(...)` records carry an equal `Lineage`.
- `test_every_event_saved_by_one_call_shares_its_lineage` and `test_separate_calls_have_separate_changes`.
- `test_import_events_carry_the_import_lineage`.
- `test_pre_lineage_history_is_read_with_the_recorded_upcast`: copy `tests/fixtures/pre_lineage/history.sqlite` into a temporary state dir, open a `HistoryStore`, and compare `records()` with `expected_history.jsonl`. Map each record to the oracle's dict shape in the test.
- `test_reading_and_appending_to_a_pre_lineage_history_leaves_old_rows_byte_identical`:
  - read all `stored_events` rows (`originator_version`, `topic`, `state`) with `sqlite3` before;
  - open the store, read `records()`, then `record([...], file_lineage())`, then close;
  - read the rows again: every old row is byte-identical, and exactly the new rows were added, with `class_version` 2 in their state (C-005, NFR-004).
- `test_appended_events_after_pre_lineage_have_full_lineage_and_a_new_change`.

**`tests/unit/test_reconcile.py`.** Update `_imported` to pass `import_lineage()`. Add `test_reconcile_records_its_changes_as_one_file_change_with_unknown_actor` and `test_each_reconcile_is_its_own_change`.

### T015 — Hermetic test env + `tests/integration/test_lineage_recording.py`

**`tests/conftest.py`:**
- `_child_env` removes `TROUPE_ACTOR` from the inherited environment, as it already does for `TROUPE_THEATRE`. Otherwise a developer's shell value would leak into every test. Update the `run_cli` docstring. `WatchProcess` already uses `_child_env`.
- Add `CORE_KEYS: Final = ("seq", "op", "path", "old", "new")` and `def core(events)`, which projects parsed history objects onto `CORE_KEYS`. WP04/WP05 use it. It is harmless now.
- Add `def stored_records(theatre: Path) -> list[HistoryRecord]`, which opens `HistoryStore(theatre / ".troupe")`, returns `records()` and closes the store. WP03 uses it to see lineage before the output exists. It is real code reading the real store, not a stand-in.

**`tests/integration/test_lineage_recording.py`** (real CLI subprocesses):
- `test_invalid_troupe_actor_exits_2_naming_the_variable_for_every_command`: parametrize over the commands `get model.name`, `show`, `set model.name x`, `history`, `watch`, and over the values `""`, `alice`, `human:`, `agent:`, `Human:alice`, `robot:x`. Assert:
  - the exit code is 2;
  - stdout is empty;
  - stderr is exactly one line starting with `troupe: TROUPE_ACTOR: invalid value`;
  - `snapshot(theatre)` is unchanged and no `.troupe/history.sqlite` was created (`all_files`).
- `test_invalid_troupe_actor_is_reported_before_a_missing_or_broken_configuration`: with no theatre, or a broken `troupe.yml`, the exit code is 2, not 4.
- `test_invalid_troupe_actor_records_nothing_in_an_imported_theatre`: import first, hand-edit, run `get` with a bad actor → exit 2, and `stored_records` is unchanged (the hand edit is not reconciled).
- `test_reason_option_is_rejected_on_commands_other_than_set`: `get x --reason r` → exit 2.
- `test_set_records_cli_lineage_with_actor_and_reason`: `TROUPE_ACTOR=agent:planner`, `--reason "raise limit"` → the last stored record has `Actor("agent","planner")`, via `cli` and the reason.
- `test_set_without_troupe_actor_uses_login_name`: env `LOGNAME=bob`, `USER=bob` (remove `LNAME`/`USERNAME`) → `Actor("human","bob")`.
- `test_reconcile_before_set_and_import_are_separate_changes`: on a never-imported theatre, run `get` (import), hand-edit, then `set` → three distinct `change` values across import / file / cli events. Within each group every event shares the same `change` and `at`, and file events have the unknown actor even though `TROUPE_ACTOR` is set.
- `test_noop_set_records_nothing`: set to the current value with `--reason` → no new records.

## Definition of Done

- All behaviours above are implemented, with only the listed files changed, plus the recorded signature-only edit to `commands/history.py`.
- `history` output is byte-identical to before for a fresh theatre: the existing tests in `tests/integration/test_history.py` pass unchanged.
- `uv run pytest`, `uv run mypy --strict`, `uv run ruff check`, `uv run ruff format --check` all pass; paste their output in the review handoff.

## Risks

- **Topics**: any rename breaks old histories. The upcast fixture test catches this.
- **`@event` method arity**: a missing field shows up as a `TypeError` when the event is constructed. Keep a single helper that expands `lineage_fields`.
- **Hidden env coupling**: `TROUPE_ACTOR` in the developer shell; fixed by `_child_env`.
- **WAL**: when comparing raw rows, close every store first so SQLite has checkpointed.

## Reviewer guidance

- Check that `resolve_actor` runs before `locate`, and that no code path outside `lineage.py` builds an `Actor` or a change id.
- Check that import/reconcile code paths have no access to the CLI actor.
- Check that the existing history-store assertions on the five original fields are no weaker than before.
- Check that the `commands/history.py` change is signature-only.

## Activity Log

- 2026-10-04T10:28:42Z – system – Prompt generated via /spec-kitty.tasks
