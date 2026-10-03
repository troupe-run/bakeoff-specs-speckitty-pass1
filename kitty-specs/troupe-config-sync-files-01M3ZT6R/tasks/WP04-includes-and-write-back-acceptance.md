---
work_package_id: WP04
title: Includes, write-back non-detection, exactly-once, delivery checks
dependencies:
- WP03
requirement_refs:
- C-003
- C-004
- C-005
- FR-012
- FR-015
- FR-016
- NFR-003
- NFR-006
planning_base_branch: feat/troupe-config-sync-files
merge_target_branch: feat/troupe-config-sync-files
branch_strategy: Planning artifacts for this mission were generated on feat/troupe-config-sync-files. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/troupe-config-sync-files unless the human explicitly redirects the landing branch.
subtasks:
- T018
- T019
- T020
- T021
- T022
phase: Phase 4 - Acceptance and delivery
history:
- at: '2026-10-03T03:00:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: tests/integration/
create_intent:
- tests/integration/test_watch_includes.py
- tests/integration/test_watch_set.py
execution_mode: code_change
model: ''
owned_files:
- tests/integration/test_watch_includes.py
- tests/integration/test_watch_set.py
role: implementer
tags: []
task_type: implement
tracker_refs: []
---

# Work Package Prompt: WP04 – Includes, write-back non-detection, exactly-once, delivery checks

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter (`agent_profile`, `role`, `agent`), and behave according to its guidance before parsing the rest of this prompt.

If no profile is specified, run `spec-kitty agent profile list` and select the best match for this work package's `task_type` and `authoritative_surface`.

---

## ⚠️ IMPORTANT: Review Feedback

- **Has review feedback?**: Check the `review_ref` field in the event log (via `spec-kitty agent tasks status`) or the Activity Log below.
- **You must address all feedback** before your work is complete.

---

## Objective

Prove, black-box, the guarantees that matter most to the product owner, fix anything the proof exposes, then verify delivery:
- **User Story 3 / FR-015**: a `set` while `watch` runs records exactly the `set`'s own events; its write-back is never recorded again.
- **FR-016**: when `watch` and a command reconcile around the same time, each difference is recorded exactly once, and no events interleave.
- **User Story 4 / FR-012**: includes added or removed by hand are followed. Their leaves appear as `set` events or disappear as `remove` events, and newly included files are watched from then on.

**Requirements**: FR-012, FR-015, FR-016, NFR-003, NFR-006, C-003, C-004, C-005.

## Context

Read first:
- `kitty-specs/troupe-config-sync-files-01M3ZT6R/spec.md`: User Stories 3 and 4, FR-012, FR-015, FR-016, NFR-003, C-003
- `kitty-specs/troupe-config-sync-files-01M3ZT6R/research.md`: R-01 (why lock plus compare gives exactly-once)
- `kitty-specs/troupe-config-sync-files-01M3ZT6R/quickstart.md`
- `tests/conftest.py`: `WatchProcess`, `history_events`, `recorded_within`, `run_cli`, `snapshot` (from WP03)
- The step-1 `set` event rules: `tests/integration/test_set_history.py` (what a `set` alone must record)

## Branch Strategy

- Planning/base branch: `feat/troupe-config-sync-files`. Final merge target: `feat/troupe-config-sync-files` (then `main`; no push, no PR, per C-005).
- Execution worktrees are allocated per computed lane from `lanes.json`. Run `spec-kitty agent action implement WP04 --agent <name>`.

---

## Subtask T018 — `tests/integration/test_watch_includes.py` (User Story 4)

Fixture: a root `troupe.yml` with `model: {name: m0}`, plus a file `agents/coder.yaml` containing `name: Ada\nmodel: m1\n` that is **not yet included**.

Tests (US4 scenario numbers in parentheses):
1. `test_include_added_by_hand_is_followed_by_next_command` (1): append `agents:\n  coder: file:agents/coder.yaml\n` to the root and run `show model.name`. History gains `set agents.coder.name null→"Ada"` and `set agents.coder.model null→"m1"`, in that order.
2. `test_include_added_by_hand_is_followed_by_watch_and_then_watched` (2): with `watch` running, add the include. Both `set` events appear within 2 s. Then edit `agents/coder.yaml` (`name: Grace`); `set agents.coder.name Ada→Grace` appears within 2 s.
3. `test_include_removed_by_hand_records_removes_and_stops_watching` (4): start from the included state and remove the `agents:` lines. Within 2 s, `remove` events appear for both leaves. Then edit `agents/coder.yaml`; after 2.5 s nothing new is recorded.
4. `test_include_replaced_by_equal_inline_content_records_nothing` (5): replace `coder: file:agents/coder.yaml` with an inline `coder: {name: Ada, model: m1}`. Nothing is recorded, both through a command and through `watch`.
5. `test_nested_include_added_inside_an_included_file_is_followed`: `coder.yaml` gains `skills: file:skills.yml`. The nested leaves are recorded, and edits to `skills.yml` are then picked up by `watch`.
6. `test_text_include_added_by_hand_records_its_text_as_one_leaf`: `prompt: file:sys.md` with CRLF content gives one `set prompt` whose `new` is the exact text, with CRLF preserved.

(US4 scenario 3, a target created after its include line, is covered in WP03's `test_watch.py`.)

---

## Subtask T019 — `tests/integration/test_watch_set.py` (User Story 3)

With `watch` running on a fixture like step-1's (`model.temperature: 0.2  # creativity`, `tools: [a, b]`, a YAML include and a text include):
1. `test_set_during_watch_records_exactly_its_own_event` (1): record `n = len(history)`, run `set model.temperature 0.5`, wait until `recorded_within(edited_at=t_after_set)`. The history is exactly the first `n` events plus `set 0.2→0.5`. Stop `watch`: exit 0.
2. `test_list_replacement_during_watch_records_set_and_remove_once` (2): `set tools [c]` adds exactly `set tools.0 a→c` and `remove tools.1 b→null`.
3. `test_no_op_set_during_watch_records_nothing` (3).
4. `test_set_inside_include_and_text_include_during_watch_records_once`: the write-back lands in an included file; one event each.
5. `test_ten_sets_in_a_row_during_watch_record_exactly_ten_events`: values 1..10 in quick succession. After 2 s, exactly 10 new `set` events with the right `old`/`new` chain.
6. `test_set_without_watch_then_show_records_nothing_more` (5): run `set`, then `show`. Only the `set` event is recorded.

---

## Subtask T020 — Exactly-once under near-simultaneous reconciles (US3 scenario 4, FR-016)

Put these in `test_watch_set.py` as well:
1. `test_hand_edit_just_before_set_is_recorded_once`: with `watch` running, hand-edit `model.name` and **immediately** run `set model.temperature 0.9` (no wait).
   - Expect exactly one event for the hand edit, recorded by whichever reconcile won the lock, plus the `set`'s own event.
   - Assert on the multiset of events, not their order. The order depends on who won.
   - Repeat 5 iterations with fresh values.
2. `test_hand_edit_with_concurrent_show_and_watch_is_recorded_once`: a hand edit followed immediately by 3 parallel `show` subprocesses while `watch` runs. Exactly one event for the edit.
3. `test_events_of_one_command_are_contiguous`: with `watch` running, run `set tools [x, y, z]` while also making a hand edit to another key. The `set`'s events form one contiguous run of `seq` numbers (FR-016: never interleaved).
4. `test_history_has_no_gaps_or_duplicate_seq_after_races`: after the tests above, `seq` is 1..N with no gaps or duplicates.

**Out of contract (C-003), do not test**: a hand edit to the *same file* during a `set`'s locked section, several `watch` processes on one theatre, or two concurrent `set`s.

---

## Subtask T021 — Fix defects the acceptance tests expose

- If a test above fails, find the root cause and fix it in the module that owns that decision:
  - `reconcile.py`: reconcile rule
  - `lock.py`: lock
  - `session.py`: session order
  - `commands/watch.py`: polling
- These files belong to earlier WPs. An out-of-map edit is acceptable here **only** with a one-line rationale in the commit message and a test in this WP that failed before the fix.
- Do not weaken a test to make it pass. If a contracted guarantee truly cannot be met, stop: record the reason, file a beads issue (`bd create --type=bug ...`), and report it (charter: no silent exceptions).

---

## Subtask T022 — Delivery checks

1. Walk through `kitty-specs/troupe-config-sync-files-01M3ZT6R/quickstart.md` by hand in a temp directory. Show the commands and their output. Adjust `quickstart.md` only if it is wrong. It is a planning artifact, so if a change is needed, note it for the reviewer rather than editing outside your owned files.
2. Run every gate and show the output (TROUPE-006):
   ```bash
   uv run pytest
   uv run mypy --strict
   uv run ruff check
   uv run ruff format --check
   ```
3. Run the watch suites (`tests/integration/test_watch*.py`) 3 times in a row to show they are not flaky.
4. Check spec/code/test agreement (TROUPE-008/009). For each FR-001–FR-016, name the test(s) that prove it, in a short table in your WP completion note. Flag any FR without a test.
5. Confirm NFR-003: run `all_files(theatre)` after a full watch session and a `set`. Only configuration files and `.troupe/history.sqlite*` exist; there is no lock file and no temp file left behind.

---

## Definition of Done

- [ ] All T018–T020 tests pass reliably (3 consecutive runs shown).
- [ ] Any fix made under T021 is justified, minimal and covered by a test that failed first.
- [ ] Quickstart walk-through output shown, and all four gates pass with output shown.
- [ ] FR→test table included in the completion note.
- [ ] `spec-kitty agent tasks mark-status T018 T019 T020 T021 T022 --status done --mission troupe-config-sync-files-01M3ZT6R`.

## Risks

- Race tests are inherently timing-dependent. Assert on outcomes after a deadline, not on interleavings.
- Process start-up time on a loaded machine can be 0.5 s or more. The 2-second budget starts at the edit, and `watch` is already running, so start-up does not count against it.

## Reviewer Guidance

- Check that the tests assert *exact* event lists, or multisets for races, never "at least".
- Check that no test covers out-of-contract concurrency.
- Check the FR→test table for gaps.

## Activity Log

- 2026-10-03T03:00:00Z – system – Prompt generated via /spec-kitty.tasks
