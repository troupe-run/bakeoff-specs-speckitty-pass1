---
work_package_id: WP09
title: 'set --include and literal writes: the US6 stories'
dependencies:
- WP08
requirement_refs:
- FR-011
- FR-012
planning_base_branch: feat/troupe-config-remote-includes
merge_target_branch: feat/troupe-config-remote-includes
branch_strategy: Planning artifacts for this mission were generated on feat/troupe-config-remote-includes. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/troupe-config-remote-includes unless the human explicitly redirects the landing branch.
subtasks:
- T042
- T043
- T044
phase: Phase 3 - Writing
history:
- at: '2026-10-07T18:00:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: tests/integration/test_set_literal.py
create_intent:
- tests/integration/test_set_literal.py
- tests/integration/test_set_include_remote.py
execution_mode: code_change
model: ''
owned_files:
- tests/integration/test_set_literal.py
- tests/integration/test_set_include_remote.py
role: implementer
tags: []
task_type: implement
tracker_refs:
- bakeoff-specs-speckitty-1j5
---

# Work Package Prompt: WP09 – `set --include` and literal writes: the US6 stories

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter (`agent_profile`, `role`, `agent`), and behave according to its guidance before parsing the rest of this prompt.

If no profile is specified, run `spec-kitty agent profile list` and select the best match for this work package's `task_type` and `authoritative_surface`.

---

## ⚠️ IMPORTANT: Review Feedback

- **Has review feedback?**: Check the `review_ref` field in the event log (via `spec-kitty agent tasks status`) or the Activity Log below.
- **You must address all feedback** before your work is complete.

---

## Objective

Prove User Story 6 ("`set` writes include-looking strings safely") end to end through the real CLI, with byte-exact files, and cover `--include` with remote targets. WP08 built the mechanics (marking, tag edits, the `--include` flag, the no-op rule). This WP is the story-level black-box proof (DIRECTIVE_036), written by someone who did not write the code.

**Any bug found here is fixed in the owning module**, which is outside this WP's files. Either:
- (a) fix it with a minimal, recorded out-of-map edit and a regression test here; or
- (b) if the fix is not small, stop, record the failing test in the Activity Log and send the WP back through review for WP08's area.

Do not weaken a test to make it pass.

## Context

- Spec: US6 scenarios 1–8, S-11, S-12, S-13; FR-011, FR-012. Contract examples in `contracts/cli.md`.
- Helpers: follow `tests/integration/test_set_existing.py` (`_set_ok` with an exact `snapshot` and `get` read-back, `_set_fails` with exit code, empty stdout, one `troupe: ` stderr line, unchanged snapshot). Copy the helper pattern into each new file; the existing files define their own helpers.
- Fixtures: `make_theatre`, `remote` (WP01).

## Branch Strategy

- Planning/base branch: `feat/troupe-config-remote-includes`. Final merge target: `feat/troupe-config-remote-includes`, which is merged into `main` locally after acceptance.
- Run `spec-kitty agent action implement WP09 --agent <name>`. It depends on WP08.

## Subtasks

### T042 — `tests/integration/test_set_literal.py` (US6)

Each test asserts the **whole file** after the write, `get` read-back, exit code and stderr. Where relevant it also asserts `history_events` (one `set` event, `new` equals the string):
1. `test_url_value_without_schema_is_written_as_literal` (US6-1): `docs: !literal https://x.example/y`, and `get docs` prints the URL. The request log is empty when the `remote` fixture is in use.
2. `test_file_value_is_written_as_literal_and_with_include_becomes_an_include` (US6-2): `b: !literal file:p.md`; then a separate theatre with `--include` gives `b: file:p.md`, and `get b` prints the content of `p.md`.
3. `test_uri_path_is_written_untagged` and `test_include_on_uri_path_exits_3` (US6-3)
4. `test_only_include_looking_strings_in_a_mapping_value_are_tagged` (US6-4), with `set agents '{coder: {docs: https://x.example/y, n: 1}}'` in both block-parent and flow-parent forms. The new mapping's exact text follows the step-1 rendering rules. Derive the expected text by running once and reviewing it by eye, then pin it: the tag must sit directly before the URL scalar.
5. `test_existing_literal_tag_is_kept_for_a_plain_string` (US6-5): `docs: !literal https://old.example` → `set docs plain-text` → `docs: !literal plain-text`.
6. `test_include_of_a_missing_url_exits_3_and_changes_nothing` (US6-6, 404)
7. `test_include_flag_on_other_subcommands_exits_2` (US6-7). WP08 has a similar test; keep this one as the story-level proof, with every subcommand.
8. `test_text_include_content_is_never_tagged` (US6-8): `prompt: file:sys.md`, `set prompt https://x` → `sys.md` is exactly `https://x`.
9. `test_setting_a_text_include_to_its_own_string_keeps_the_step1_rule` (S-11, C-003; corrected after WP08 found the original expectation contradicted S-11): `b: file:p.md` (text include) → `set b file:p.md` rewrites `p.md`'s content to `file:p.md` and leaves `troupe.yml` untouched, exactly as on step-6 `main`; nothing is tagged. A YAML include in the same situation is refused as a whole replacement (exit 3, step 1).
10. `test_literal_replaced_by_include_drops_the_tag`: `b: !literal file:p.md` → `set --include b file:p.md` gives `b: file:p.md`.
11. `test_literal_tag_is_written_in_flow_collections_and_list_appends`: `{a: 1}` gets a new key, and a list gets an appended item.
12. `test_quoted_include_looking_value_keeps_its_needed_quoting_after_the_tag` (a value with a space: `'file:my notes.md'`).

### T043 — `tests/integration/test_set_include_remote.py`

1. `test_include_of_a_remote_yaml_url_adds_a_remote_include`: `set --include team http://…/team.yaml` writes `team: http://…/team.yaml`. Then `get team.model` reads the served value, and the history records the new leaves.
2. `test_include_of_a_remote_text_url_reads_its_body`
3. `test_new_remote_include_is_fetched_once_during_the_set` (request log)
4. `test_include_of_a_url_whose_content_fails_the_schema_exits_3` (S-9 via S-12)
5. `test_after_adding_a_remote_include_its_values_are_read_only` (S-4): a follow-up `set team.model x` exits 3 and quotes the include string.

### T044 — S-13 sweep of the existing suite

- Grep the existing tests for `set` VALUEs starting `file:`, `https://` or `http://`, outside the two tests WP08 updated. For each one, confirm whether it relies on the old "becomes an include" behaviour.
- If any does and still passes by accident, or was changed without an S-13 note, record it in the Activity Log and raise it at review.
- Expected result: no other such test exists. Record the grep command and its output.

## Definition of Done

- All tests pass and all four gates pass, with output pasted.
- Every US6 acceptance scenario maps to at least one test name; put the mapping in the Activity Log.

## Risks

- **Expected texts derived from the implementation** could pin a bug. Mitigation: review each expected file by eye against the contract and the step-1 rendering rules before pinning it, and say so in the Activity Log.

## Reviewer guidance

- Byte-exact assertions on every changed file. Unchanged files are asserted via `snapshot`.
- No test is weakened. Bugs found go to the owning module, with a regression test here.

## Activity Log

- 2026-10-07T18:00:00Z – system – Prompt generated via /spec-kitty.tasks
