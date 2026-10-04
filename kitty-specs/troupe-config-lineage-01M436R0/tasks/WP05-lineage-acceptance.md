---
work_package_id: WP05
title: End-to-end lineage acceptance
dependencies:
- WP04
requirement_refs:
- C-001
- FR-001
- FR-002
- FR-004
- FR-006
- FR-008
- FR-009
- FR-010
- FR-011
- FR-012
- FR-013
- FR-014
- NFR-002
- NFR-004
- NFR-005
planning_base_branch: feat/troupe-config-lineage
merge_target_branch: feat/troupe-config-lineage
branch_strategy: Planning artifacts for this mission were generated on feat/troupe-config-lineage. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/troupe-config-lineage unless the human explicitly redirects the landing branch.
subtasks:
- T019
- T020
- T021
- T022
- T023
phase: Phase 4 - Acceptance
history:
- at: '2026-10-04T10:28:42Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: tests/integration/test_lineage_
create_intent:
- tests/integration/test_lineage_cli.py
- tests/integration/test_lineage_changes.py
- tests/integration/test_lineage_pre_lineage.py
execution_mode: code_change
model: ''
owned_files:
- tests/integration/test_lineage_cli.py
- tests/integration/test_lineage_changes.py
- tests/integration/test_lineage_pre_lineage.py
role: implementer
tags: []
task_type: implement
tracker_refs: []
---

# Work Package Prompt: WP05 – End-to-end lineage acceptance

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter (`agent_profile`, `role`, `agent`), and behave according to its guidance before parsing the rest of this prompt.

If no profile is specified, run `spec-kitty agent profile list` and select the best match for this work package's `task_type` and `authoritative_surface`.

---

## ⚠️ IMPORTANT: Review Feedback

- **Has review feedback?**: Check the `review_ref` field in the event log (via `spec-kitty agent tasks status`) or the Activity Log below.
- **You must address all feedback** before your work is complete.

---

## Objective

Prove every acceptance scenario and edge case in `spec.md` through the **real CLI and `troupe config history` output**: real files, real subprocesses, the real store. Then walk the quickstart, run all gates, and confirm that spec, contract and code agree (TROUPE-009, DIRECTIVE_010).

If a test reveals a code defect, **do not** fix the source in this WP. Report it in the handoff with the failing test, so the owning WP can be reopened. The exception is a trivial fix the reviewer agrees to; record it as an out-of-map edit.

## Context

- `kitty-specs/troupe-config-lineage-01M436R0/spec.md`: all User Stories, Edge Cases, SC-001 to SC-006
- `kitty-specs/troupe-config-lineage-01M436R0/contracts/cli.md`, `quickstart.md`
- `tests/conftest.py`: `run_cli(..., env=...)`, `history_events`, `core`, `snapshot`, `all_files`, `WatchProcess`, `recorded_within`, `make_theatre`
- `tests/fixtures/pre_lineage/` (WP02) and its README: copy, never use in place
- `tests/integration/test_history.py` (WP04): reuse its record validator if you can import it cleanly; otherwise, write a local `assert_lineage_shape(line)` that checks the same contract rules

## Branch Strategy

- Planning/base branch: `feat/troupe-config-lineage`; final merge target: `feat/troupe-config-lineage`.
- Execution worktrees are allocated per computed lane from `lanes.json`; implement with `spec-kitty agent action implement WP05 --agent <name>` (depends on WP04).

## Subtasks

### T019 — `tests/integration/test_lineage_cli.py` (US1 + edge cases)

Each test builds a theatre with `make_theatre`, imports it with one `history` run, then:
- `test_agent_set_with_reason_is_attributed_to_the_agent_via_cli` (US1-1).
- `test_human_actor_without_reason_has_null_reason` (US1-2).
- `test_unset_actor_is_the_login_name` (US1-3): set `LOGNAME`/`USER` to `bob` in `env`. Also add a variant that removes `LOGNAME`, `USER`, `LNAME` and `USERNAME` and expects `pwd.getpwuid(os.getuid()).pw_name`. That is the same fallback `getpass` uses, computed independently.
- `test_empty_reason_is_stored_as_empty_string` (edge case).
- `test_reason_with_quotes_newlines_and_non_ascii_round_trips` (edge case).
- `test_actor_id_is_everything_after_the_first_colon` (`human:alice:x` → id `alice:x`).
- `test_refused_set_keeps_its_reconcile_but_not_its_reason`: hand-edit, then `set` a path that exits 3 or 5 with `--reason`. Find a refusal case in `tests/integration/test_set_*`. Assert that the file event is present, there is no `cli` event, and the reason appears nowhere.
- `test_noop_set_with_reason_records_nothing` (US1-6).
- `test_invalid_actor_exits_2_and_history_is_unchanged` (US1-4, SC-006): compare `history` before and after for each invalid value.

### T020 — `tests/integration/test_lineage_changes.py`: grouping (US2, US3)

Group helper: `by_change(events) -> dict[str, list[dict]]`, preserving order.
- `test_first_command_imports_as_one_change_with_unknown_actor` (US2-1). Run it once with `history` and once with `get` as the first command.
- `test_hand_edit_is_recorded_via_file_with_unknown_actor_even_when_troupe_actor_is_set` (US2-2).
- `test_set_replacing_several_leaves_is_one_change_sharing_actor_via_at_reason` (US3-1). Use a mapping or list VALUE such as `set tools '[a, b, c]'` that changes three or more leaves.
- `test_reconcile_and_set_in_one_command_are_two_changes` (US3-2).
- `test_import_and_set_on_a_new_theatre_are_two_changes` (US3-3).
- `test_change_ids_are_never_reused_across_commands` (US3-4, SC-003): run about 10 producers, a mix of set, hand edit + get, and set with no actor. The number of distinct change ids equals the number of producers that recorded something, and every group is uniform in `actor`, `via`, `at` and `reason`.

### T021 — `watch` reconciles (US2-3, FR-011)

In `test_lineage_changes.py`:
- `test_each_watch_reconcile_is_its_own_change`:
  - Start a `WatchProcess` and `wait_ready()`.
  - Edit one value, wait with `recorded_within`, then edit another value and wait again.
  - Stop the watcher.
  - The two edits have different `change` ids, both `via: "file"`, unknown actor, `reason` null.
  
  Run with `TROUPE_ACTOR=agent:x` in the watcher env to prove it is not used.
- `test_watch_rejects_invalid_actor_before_announcing`: `WatchProcess` (or `run_cli`) with `TROUPE_ACTOR=robot:x` → exit 2, no `watching` line on stdout.

Follow the timing patterns already used in `tests/integration/test_watch*.py`. Don't use bare sleeps without deadlines.

### T022 — `tests/integration/test_lineage_pre_lineage.py` (US4)

Copy `tests/fixtures/pre_lineage/troupe.yml` to `<theatre>/.troupe/troupe.yml` and `history.sqlite` to `<theatre>/.troupe/history.sqlite`.
- `test_pre_lineage_history_prints_known_fields_and_marks_the_rest_unknown` (US4-2): `history` output, parsed, equals `expected_history.jsonl` line by line. Use `history`, which does not reconcile.
- `test_reading_pre_lineage_history_does_not_modify_stored_rows` (NFR-004, C-005): compare raw `stored_events` rows with `sqlite3` before and after `history`.
- `test_new_set_on_pre_lineage_history_has_full_lineage_and_a_fresh_change` (US4-3): `TROUPE_ACTOR=human:alice set model.temperature 0.9`. The old lines are unchanged and still equal the oracle. The new line has via `cli`, a UUID change, and actor alice. The old rows are byte-identical.
- `test_history_survives_restart_byte_identical` (US4-1, SC-004): two `history` runs in separate processes after a mix of producers give identical stdout.

### T023 — Quickstart, agreement, gates

1. Run every command in `kitty-specs/troupe-config-lineage-01M436R0/quickstart.md` in a scratch theatre and check that the outline expectations hold. Paste a trimmed transcript in the handoff. If the quickstart is wrong, report it; don't silently change behaviour.
2. Agreement check. Walk FR-001 to FR-014, NFR-001 to NFR-005 and C-001 to C-005, and list for each the test or tests that prove it, in a table in the handoff. Any requirement without a test is a defect to report.
3. Full gates: `uv run pytest`, `uv run mypy --strict`, `uv run ruff check`, `uv run ruff format --check`. Paste the output.

## Definition of Done

- Every acceptance scenario and edge case in the spec has a named, passing test proving it.
- The requirement-to-test table is complete; quickstart verified.
- All four gates pass, with output pasted in the handoff.

## Risks

- `watch` timing: use the existing helpers' deadlines.
- Login name expectations must not depend on the developer's shell. Always set or strip the variables explicitly in `env`.

## Reviewer guidance

- Each test name states the scenario it proves, and its body asserts exactly that.
- The pre-lineage tests copy the fixture, and the row-identity checks compare raw bytes.

## Activity Log

- 2026-10-04T10:28:42Z – system – Prompt generated via /spec-kitty.tasks
