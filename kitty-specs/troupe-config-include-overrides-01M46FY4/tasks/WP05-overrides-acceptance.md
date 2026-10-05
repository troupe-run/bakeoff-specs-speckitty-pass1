---
work_package_id: WP05
title: 'Acceptance: edges, history and delivery'
dependencies:
- WP04
requirement_refs:
- FR-006
- FR-012
- FR-013
planning_base_branch: feat/troupe-config-include-overrides
merge_target_branch: feat/troupe-config-include-overrides
branch_strategy: Planning artifacts for this mission were generated on feat/troupe-config-include-overrides. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/troupe-config-include-overrides unless the human explicitly redirects the landing branch.
subtasks:
- T024
- T025
- T026
- T027
phase: Phase 3 - Wiring and stories
history:
- at: '2026-10-05T17:30:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: reviewer-renata
authoritative_surface: tests/integration/test_overrides_acceptance.py
create_intent:
- tests/integration/test_overrides_acceptance.py
execution_mode: code_change
owned_files:
- tests/integration/test_overrides_acceptance.py
role: implementer
tags: []
task_type: implement
tracker_refs: []
---

# Work Package Prompt: WP05 – Acceptance: edges, history and delivery

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter (`agent_profile`, `role`, `agent`), and behave according to its guidance before parsing the rest of this prompt.

If no profile is specified, run `spec-kitty agent profile list` and select the best match for this work package's `task_type` and `authoritative_surface`.

---

## ⚠️ IMPORTANT: Review Feedback

- **Has review feedback?**: Check the `review_ref` field in the event log (via `spec-kitty agent tasks status`) or the Activity Log below.
- **You must address all feedback** before your work is complete.

---

## Objective

Prove end to end, through the real CLI, the scenarios and agent choices not covered by WP04, and confirm that spec, contract, quickstart and code agree before acceptance. This WP adds one test file. If a test exposes a bug, fix it in the owning module with a one-line out-of-map rationale in the commit message (or file a beads issue and report it if the fix is not small); never weaken a test to pass.

## Context

- Spec: all D-n, US2-2/5/6/7, Edge Cases, SC-001–SC-005.
- `contracts/cli.md`, `quickstart.md`.
- Harness: `tests/conftest.py` (`make_theatre`, `run_cli`, `snapshot`, `history_events`, `WatchProcess`, `recorded_within`).

## Branch Strategy

- Planning/base branch: `feat/troupe-config-include-overrides`; final merge target: `feat/troupe-config-include-overrides` (merged into `main` after acceptance).
- Execution worktrees are allocated per computed lane from `lanes.json`; run `spec-kitty agent action implement WP05 --agent <name>` (depends on WP04).

## Subtasks

### T024 — Conversion acceptance (`tests/integration/test_overrides_acceptance.py`)

Byte-snapshot every file before/after:
- `test_four_space_file_converts_with_four_space_indentation` (US2-2)
- `test_nested_include_override_lands_in_nearest_including_file` (US2-5: `troupe.yml` and `models/base.yaml` byte-identical; `agents/coder.yaml` = `model:\n  $ref: file:models/base.yaml\n  temperature: 0.3\n`)
- `test_flow_parent_include_converts_in_flow_style` (US2-6, D-3)
- `test_list_item_include_converts_in_place` (US2-7, D-4)
- `test_quoted_include_string_is_moved_verbatim` (D-5)
- `test_override_value_that_is_itself_an_include_is_converted_in_place` (`coder: {$ref: file:a.yaml, model: file:m.yaml}` with `a.yaml` having `model: {x: 1}` → `set coder.model.y 2` converts `model:` in `troupe.yml`)
- `test_crlf_including_file_keeps_crlf_after_conversion`

### T025 — Refusal acceptance

For each: exit code, empty stdout, one-line stderr naming PATH/file, **no file changed** (snapshot) and **no event recorded** (count before/after):
- `test_ref_segment_in_path_is_refused` (D-6; also `get coder.$ref` → exit 5)
- `test_replacing_partly_overridden_mapping_is_refused` (D-10)
- `test_replacing_one_sided_mapping_under_merge_is_written_in_its_file` (D-10 counterpart)
- `test_multiline_include_string_conversion_is_refused` (D-11; block scalar and wrapped quoted string)
- `test_malformed_ref_makes_every_command_exit_4` (D-1; `get`, `show`, `set`)

### T026 — History, reconcile and watch

- `test_override_set_records_exactly_one_event_with_cli_lineage` (FR-013: `op: set`, `path`, `old: null`, `via: "cli"`; no events for unchanged merged leaves)
- `test_hand_written_conversion_without_value_change_records_nothing` (edit `troupe.yml` by hand from scalar form to `$ref`-only mapping form; next `get` records nothing)
- `test_hand_added_override_records_set_for_changed_leaf_only`
- `test_watch_records_set_written_override_once` (start `watch`, run `set` creating an override, wait; exactly one event; mirrors step-2 "recorded exactly once")

### T027 — Delivery checks

1. Run every command of `kitty-specs/troupe-config-include-overrides-01M46FY4/quickstart.md` on a temp theatre; paste output; fix the quickstart (planning artifact, out-of-map with rationale) if any expectation is wrong.
2. Check agreement: each FR and D-n in `spec.md` → at least one test name (list them in the handoff as a table); `contracts/cli.md` exit codes match behaviour; module docstrings in `loader.py`, `merge.py`, `placement.py`, `apply.py`, `collections.py` cite the D-n they implement.
3. Run the four gates on the lane: `uv run pytest`, `uv run mypy --strict`, `uv run ruff check`, `uv run ruff format --check`; paste output.

## Definition of Done

- `tests/integration/test_overrides_acceptance.py` exists with the tests above, all passing.
- FR/D → test table in the handoff; no gaps (or gaps filed as beads issues and reported).
- Four gates pass; output pasted.

## Risks

- `watch` timing: reuse `recorded_within` with the step-2 window; never use bare sleeps as assertions.

## Reviewer guidance

- Every refusal test checks both files and history are untouched.
- The FR/D table is complete and each referenced test asserts what its name says.

## Activity Log

- 2026-10-05T17:30:00Z – system – Prompt generated via /spec-kitty.tasks
