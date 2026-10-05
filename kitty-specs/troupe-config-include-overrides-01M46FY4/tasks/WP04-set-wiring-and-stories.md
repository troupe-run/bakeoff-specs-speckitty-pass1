---
work_package_id: WP04
title: set wiring, verification and story tests
dependencies:
- WP02
- WP03
requirement_refs:
- FR-005
- FR-006
- FR-008
- FR-009
- FR-010
- FR-011
- FR-013
planning_base_branch: feat/troupe-config-include-overrides
merge_target_branch: feat/troupe-config-include-overrides
branch_strategy: Planning artifacts for this mission were generated on feat/troupe-config-include-overrides. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/troupe-config-include-overrides unless the human explicitly redirects the landing branch.
subtasks:
- T018
- T019
- T020
- T021
- T022
- T023
phase: Phase 3 - Wiring and stories
history:
- at: '2026-10-05T17:30:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/troupe/writeback/apply.py
create_intent:
- tests/integration/test_set_overrides.py
- tests/integration/test_set_in_include.py
execution_mode: code_change
owned_files:
- src/troupe/writeback/apply.py
- src/troupe/cli.py
- src/troupe/commands/set_value.py
- tests/integration/test_set_new_entries.py
- tests/integration/test_set_overrides.py
- tests/integration/test_set_in_include.py
role: implementer
tags: []
task_type: implement
tracker_refs: []
---

# Work Package Prompt: WP04 – `set` wiring, verification and story tests

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter (`agent_profile`, `role`, `agent`), and behave according to its guidance before parsing the rest of this prompt.

If no profile is specified, run `spec-kitty agent profile list` and select the best match for this work package's `task_type` and `authoritative_surface`.

---

## ⚠️ IMPORTANT: Review Feedback

- **Has review feedback?**: Check the `review_ref` field in the event log (via `spec-kitty agent tasks status`) or the Activity Log below.
- **You must address all feedback** before your work is complete.

---

## Objective

Make `troupe config set PATH VALUE [--reason TEXT] [--in-include]` deliver CR-A and CR-B end to end:

- `apply_set` takes `in_include`, dispatches the new `ConvertInclude` placement to WP02's `convert_include_edits`, and keeps the in-memory verification (R-5) strict except for the one allowed structural change.
- The CLI accepts `--in-include` on `set` only.
- Story tests for US2 (core), US3 and US4 with byte snapshots of the whole theatre; the two step-1 tests whose expected output changes by contract are updated.

## Context

- Spec: US2 (1–4, 8), US3 (1–6), US4 (1–6); FR-005, FR-006, FR-008–FR-011, FR-013; NFR-001–NFR-003.
- Research R-5, R-6; plan "Risks" (verifier false refusals).
- WP02: `convert_include_edits(file, parent, slot, include_origin, keys, value, step, *, path)`.
- WP03: `place(root, segments, dotted, *, in_include=False)`, `ConvertInclude(include, parent, slot, keys)`.
- Tests harness: `tests/conftest.py` (`make_theatre`, `run_cli`, `snapshot`, `history_events`), `tests/integration/test_set_new_entries.py` `_check` helper style.

## Branch Strategy

- Planning/base branch: `feat/troupe-config-include-overrides`; final merge target: `feat/troupe-config-include-overrides` (merged into `main` after acceptance).
- Execution worktrees are allocated per computed lane from `lanes.json`; run `spec-kitty agent action implement WP04 --agent <name>` (depends on WP02, WP03).

## Subtasks

### T018 — `apply.py` dispatch

1. `apply_set(root, segments, dotted, value, raw_value, *, in_include: bool = False)` passes `in_include` to `place`.
2. `_edits`: add a `ConvertInclude` branch: `file = placement.include.origin.file`, `step = detect_indent(file.text)`, `convert_include_edits(file, placement.parent, placement.slot, placement.include.origin, placement.keys, value, step, path=dotted)`.
3. Guard: in `_edits`, `assert not isinstance(<target collection>, MergedMapping)` for `AddKeys`, `AppendItem`, `ReplaceCollection`, `ReplaceScalar.parent` with a message — a merged view must never be written through (plan Risks).
4. Update the module docstring: overrides, conversion, `--in-include`.

### T019 — Verification allowance (`_same_outside`)

Current rule: kinds, flow flags, keys/order, scalar values/styles and include targets equal everywhere except at and below PATH; on the route a mapping may gain the added key and a list the appended item.

Add (R-5):
- **On the route only** (`here` is a strict prefix of `target`): an old `YamlInclude` (scalar or holder form) may be matched by a new `MergedMapping` whose `ref.target.path == old.target.path`; continue comparing `unwrap(old)` with the new merged view (which may have gained exactly the added key at the next route level, as for any mapping). Also: old `YamlInclude` with holder vs new `MergedMapping` (first override added to a `$ref`-only mapping).
- Everywhere: old `MergedMapping` must match a new `MergedMapping` with the same `ref` target path (or both `None`), then compare as mappings (it is a `MappingNode`, so the existing branch works after the `ref` check). Put the `MergedMapping` check **before** the `MappingNode` branch.
- Old `MappingNode` (not merged) vs new `MergedMapping` off the route → mismatch (refuse).
Keep `_matches` as is (a `MergedMapping` is a `MappingNode`).

### T020 — CLI

- `cli.py`: on the `set` subparser, `add_argument("--in-include", action="store_true", help="write a new key into the included file instead of an override in the including file")`. Update the module docstring's command list.
- `commands/set_value.py`: pass `in_include=args.in_include` to `apply_set`; docstring mentions it. History/lineage recording unchanged (FR-013).
- `--in-include` on `get`/`show`/`history`/`watch` must exit 2 via the existing argparse error path — test it (T023).

### T021 — Step-1 tests updated by contract

In `tests/integration/test_set_new_entries.py` (remove any `xfail` WP03 added):
- `test_new_key_goes_into_included_files_mapping` → rename to `test_new_key_under_included_mapping_becomes_override_in_including_file`; expected: `troupe.yml` = `agents:\n  coder:\n    $ref: file:agents/coder.yaml\n    limits:\n      level: 3\n`, `agents/coder.yaml` unchanged; `get agents.coder.limits.level` → `3`.
- `test_new_key_into_empty_included_file` → `test_new_key_under_empty_included_file_becomes_override`; expected `troupe.yml` = `extra:\n  $ref: file:extra.yml\n  a: 1\n`, `extra.yml` unchanged (empty).
- Add twins with `--in-include` keeping the old step-1 expectations: `test_in_include_new_key_goes_into_included_files_mapping`, `test_in_include_new_key_into_empty_included_file`.
- Comment above them: "Overrides (step 5) replaces rule 2 under set; the step-1 behaviour is now `--in-include`".

### T022 — `tests/integration/test_set_overrides.py` (US2 core + US3)

Use a `_check`-style helper: build files, run `set`, assert `(code, out, err) == (0, "", "")`, assert `snapshot(theatre)` equals the expected bytes of **every** file, and `get` of each leaf. Tests:
- `test_contract_example_converts_include_and_keeps_comment` (US2-1; exact `troupe.yml`; `coder.yaml` byte-identical; one `set` history event for `coder.temperature` with `old` null)
- `test_new_key_after_existing_overrides_needs_no_conversion` (US2-3)
- `test_new_nested_key_creates_override_mapping_and_keeps_included_siblings` (US2-4)
- `test_new_key_in_root_file_mapping_unchanged_from_step1` (US2-8)
- `test_overridden_value_changes_only_the_override` (US3-1)
- `test_not_overridden_value_changes_the_included_file` (US3-2)
- `test_append_to_included_list_goes_to_included_file` (US3-3)
- `test_new_key_inside_included_list_item_goes_to_included_file` (US3-4)
- `test_append_to_override_list_goes_to_including_file` (US3-5)
- `test_replacing_whole_include_in_either_form_exits_3_and_changes_nothing` (US3-6)
- `test_set_same_value_into_new_override_path_is_not_a_noop_but_existing_override_value_is` (no-op check: setting an overridden value to its current value writes nothing and records nothing)

### T023 — `tests/integration/test_set_in_include.py` (US4)

- `test_in_include_appends_new_key_to_included_file` (US4-1)
- `test_in_include_nested_writes_innermost_file` (US4-2; three files snapshotted)
- `test_in_include_without_include_equals_plain_set` (US4-3; compare the two theatres' snapshots)
- `test_in_include_on_overridden_existing_value_changes_override` (US4-4)
- `test_in_include_is_rejected_by_other_subcommands` (US4-5; parametrize `get`, `show`, `history`, `watch`; exit 2, empty stdout, stderr one line)
- `test_in_include_with_reason_records_lineage` (US4-6; `history` last line has the reason, `via: "cli"`)
- `test_in_include_flag_position_is_free` (`set --in-include P V`, `set P V --in-include`)

## Definition of Done

- All tests above pass; all other existing tests pass unchanged.
- No `xfail` remains in `test_set_new_entries.py`.
- Four gates pass; output pasted.

## Risks

- A verifier allowance that is too broad would let a renderer bug through — the allowance applies **only** on the route and **only** for the same `ref` target.
- `snapshot` excludes `history.sqlite` — check events separately with `history_events`.

## Reviewer guidance

- Run the contract example by hand (quickstart) and compare bytes.
- Read `_same_outside` and confirm the allowance cannot match a different target or an off-route change.
- Confirm the two changed step-1 tests are the only expectation changes.

## Activity Log

- 2026-10-05T17:30:00Z – system – Prompt generated via /spec-kitty.tasks
