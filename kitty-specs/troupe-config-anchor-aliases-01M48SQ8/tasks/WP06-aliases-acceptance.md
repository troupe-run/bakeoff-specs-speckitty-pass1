---
work_package_id: WP06
title: Acceptance, history and agreement
dependencies:
- WP05
requirement_refs:
- FR-009
planning_base_branch: fix/troupe-config-anchor-aliases
merge_target_branch: fix/troupe-config-anchor-aliases
branch_strategy: Planning artifacts for this mission were generated on fix/troupe-config-anchor-aliases. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into fix/troupe-config-anchor-aliases unless the human explicitly redirects the landing branch.
subtasks:
- T026
- T027
- T028
- T029
phase: Phase 5 - Acceptance
history:
- at: '2026-10-06T15:00:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: tests/integration/test_aliases_acceptance.py
create_intent:
- tests/integration/test_aliases_acceptance.py
execution_mode: code_change
owned_files:
- tests/integration/test_aliases_acceptance.py
role: implementer
agent: claude
model: ''
tags: []
task_type: implement
tracker_refs:
- bakeoff-specs-speckitty-qht
---

# Work Package Prompt: WP06 – Acceptance, history and agreement

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter (`agent_profile`, `role`, `agent`), and behave according to its guidance before parsing the rest of this prompt.

If no profile is specified, run `spec-kitty agent profile list` and select the best match for this work package's `task_type` and `authoritative_surface`.

---

## ⚠️ IMPORTANT: Review Feedback

- **Has review feedback?**: Check the `review_ref` field in the event log (via `spec-kitty agent tasks status`) or the Activity Log below.
- **You must address all feedback** before your work is complete.

---

## Objective

Prove the remaining behaviour through the real CLI:
- C11 in history, lineage, reconcile and `watch`;
- the spec's edge cases;
- the quickstart.

Then check that the spec, the contract, the docstrings and the code agree (TROUPE-009), and run every gate. This WP adds tests only. If a test exposes a bug, fix it with a small out-of-map change to the owning source file, record a one-line rationale in the Activity Log, and say so in the handoff.

## Context

- Spec: Edge Cases, C11, C12, SC-001–SC-005, NFR-001–NFR-004.
- `contracts/cli.md`, `quickstart.md`.
- Harness: `tests/conftest.py` (`make_theatre`, `run_cli`, `snapshot`, `history_events`, `WatchProcess`, `recorded_within`, `stored_records`).
- Earlier acceptance suites to mirror: `tests/integration/test_overrides_acceptance.py`, `tests/integration/test_watch_set.py`.

## Branch Strategy

- Planning/base branch: `fix/troupe-config-anchor-aliases`; final merge target: `fix/troupe-config-anchor-aliases`, merged into `main` locally after acceptance.
- Execution worktrees are allocated per computed lane from `lanes.json`; run `spec-kitty agent action implement WP06 --agent <name>` (depends on WP05).

## Subtasks

### T026 — History, lineage, reconcile, watch (C11)

In `tests/integration/test_aliases_acceptance.py`:
- `test_hand_edit_of_anchored_value_records_every_alias_leaf`. Edit `opus` → `haiku` at the anchor by hand; the next `get` reconciles and records `set` events for all three resolved paths with file lineage (`via` as in step 4 for reconciles).
- `test_hand_edit_adding_an_alias_without_value_change_records_nothing`. Replace `settings: {model: opus}` by hand with `settings: *d` where `d` has the same content; no events.
- `test_hand_expansion_equal_to_anchor_records_nothing`. The inverse edit.
- `test_watch_records_set_at_anchor_once_per_leaf`. Run `watch`, then `set defaults.model x`; within the step-2 window exactly three events and no duplicates (use `recorded_within`, never bare sleeps as assertions).
- `test_refused_set_keeps_earlier_reconcile_events`. Hand edit plus a refused `set` through an alias: the reconcile events are saved, the `set` records nothing (step-2 D-7 rule).

### T027 — Edge cases

- `test_redefined_anchor_aliases_follow_the_latest_definition` (read and set). Expansion never adds an anchor definition.
- `test_anchor_with_no_alias_behaves_like_any_value`.
- `test_aliases_in_an_included_file_are_refused_and_expanded_in_that_file`. The include target changes; `troupe.yml` stays byte-identical.
- `test_expand_alias_with_in_include_expands_then_follows_in_include`. Construct a case where both flags matter, or show that `--in-include` has no effect on an expanded copy because it holds no include. Assert the actual behaviour in the spec Edge Case text.
- `test_undefined_alias_and_alias_before_anchor_exit_4`.
- `test_crlf_file_expansion_keeps_crlf`.
- `test_expanded_copy_reads_back_identically_with_show` (`show coder` before and after expansion only differs at PATH).

### T028 — Quickstart and agreement

1. Run every command of `kitty-specs/troupe-config-anchor-aliases-01M48SQ8/quickstart.md` on a temp theatre and paste the output. If an expectation is wrong, fix the quickstart (a planning artifact; out-of-map, with a rationale) or the code. Never fix it silently.
2. Agreement table in the handoff: each FR, NFR, A-0 and C1–C14 in `spec.md` → at least one test name that asserts it. Any gap: add the test here, or file a beads issue and report it.
3. `contracts/cli.md` exit codes and message formats match the behaviour. Check by running each refusal once and comparing stderr.
4. Module docstrings of `yamlcore.py`, `loader.py`, `merge.py`, `tree.py`, `placement.py`, `aliases.py`, `apply.py`, `collections.py` and `cli.py` cite the choices they implement, and no docstring still says anchors are refused at load.

### T029 — Gates, bug evidence, follow-ups

1. On the lane: `uv run pytest`, `uv run mypy --strict`, `uv run ruff check`, `uv run ruff format --check`; paste all output.
2. Bug evidence for `bakeoff-specs-speckitty-qht`: run the reporter's exact steps and paste the output (exit 3 with `--expand-alias`, then the expansion). Add it as a note with `bd update bakeoff-specs-speckitty-qht --notes "..."`. Do **not** close the bug; it is closed after the merge into `main`.
3. File beads issues for anything deferred, such as the known exponential-expansion risk if you judge it worth tracking, and list them in the handoff.

## Definition of Done

- `tests/integration/test_aliases_acceptance.py` exists with the tests above, all passing.
- Agreement table complete; quickstart output pasted; gaps fixed or filed.
- Four gates pass; output pasted.

## Risks

- `watch` timing flakiness: reuse the step-2 helpers and windows.
- Reconcile lineage fields: copy expectations from existing reconcile tests rather than guessing.

## Reviewer guidance

- Each test asserts what its name says, including exact event counts.
- The agreement table covers every spec id.

## Activity Log

- 2026-10-06T15:00:00Z – system – Prompt generated via /spec-kitty.tasks
