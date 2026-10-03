---
work_package_id: WP03
title: show [PATH] [--sources]
dependencies:
- WP01
- WP02
requirement_refs:
- C-002
- C-003
- C-004
- FR-003
- FR-004
- FR-005
- FR-006
- FR-009
- FR-010
- FR-011
- FR-012
- FR-013
- FR-014
- FR-015
- NFR-001
- NFR-002
- NFR-003
planning_base_branch: feat/troupe-config-get-show
merge_target_branch: feat/troupe-config-get-show
branch_strategy: Planning artifacts for this mission were generated on feat/troupe-config-get-show. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/troupe-config-get-show unless the human explicitly redirects the landing branch.
subtasks:
- T011
- T012
- T013
- T014
- T015
phase: Phase 2 - show
history:
- at: '2026-10-03T14:30:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/troupe/commands/show.py
create_intent:
- tests/integration/test_show_sources.py
execution_mode: code_change
model: ''
owned_files:
- src/troupe/commands/show.py
- tests/integration/test_show.py
- tests/integration/test_show_sources.py
role: implementer
tags: []
task_type: implement
tracker_refs: []
---

# Work Package Prompt: WP03 – `show [PATH] [--sources]`

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter (`agent_profile`, `role`, `agent`), and behave according to its guidance before parsing the rest of this prompt.

If no profile is specified, run `spec-kitty agent profile list` and select the best match for this work package's `task_type` and `authoritative_surface`.

---

## ⚠️ IMPORTANT: Review Feedback

- **Has review feedback?**: Check the `review_ref` field in the event log (via `spec-kitty agent tasks status`) or the Activity Log below.
- **You must address all feedback** before your work is complete.

---

## Objective

Turn `troupe config show` into the reader for anything:

- `show PATH` on a scalar prints exactly what `get PATH` prints (FR-004).
- `show PATH` on a mapping or list, or `show` with no PATH, prints block-style YAML through the WP01 renderer (FR-005/FR-006).
- `--sources` appends `# from <file>` to every scalar line (FR-009 to FR-011). On a scalar PATH it prints the scalar as YAML with its comment (FR-012, DM 01M411YHFR2PMJEJWMHX4KN9C4).

Then run the whole acceptance walk-through and the gates for the mission.

## Context

Read first:
- `kitty-specs/troupe-config-get-show-01M411XB/spec.md`: US2, US3, Edge Cases, FR-003 to FR-015
- `kitty-specs/troupe-config-get-show-01M411XB/contracts/cli.md`: the whole file, including the Example (use it verbatim as a test)
- `kitty-specs/troupe-config-get-show-01M411XB/research.md`: D-6, D-7, D-9
- `src/troupe/yamlout.py` (from WP01): `render`, `to_text`, `Line`
- `src/troupe/commands/get.py`, `src/troupe/values.py` (`scalar_of`, `format_scalar`), `src/troupe/cli.py` (from WP02)
- `tests/integration/test_get.py` (from WP02): style reference
- `.kittify/charter/charter.md`: TROUPE-001, -003, -005, -006, -009

## Branch Strategy

- Planning/base branch: `feat/troupe-config-get-show`
- Final merge target: `feat/troupe-config-get-show` (delivered to `main` after acceptance)
- Execution worktrees are allocated per computed lane from `lanes.json`. Run `spec-kitty agent action implement WP03 --agent <name>` and work only in the worktree it gives you.

### Pre-authorised out-of-map edit

`src/troupe/cli.py` is owned by WP02, which this WP depends on, so there is no parallel conflict. This WP may edit **only the `show` subparser lines** and the module docstring's `show` mention (T012). Record that in the Activity Log with a one-line rationale. If T015's agreement check finds a planning-doc mismatch in `kitty-specs/troupe-config-get-show-01M411XB/` (spec, contract), fix it in the same change and note it (TROUPE-009).

---

## Subtask T011 — Rewrite `src/troupe/commands/show.py`

**Steps**:
1. Read `args.path` (may be `None`) and `args.sources` (bool).
2. If PATH is given, `segments = parse_path(path)` before loading, which keeps exit 2 for empty segments.
3. `with open_session(theatre, reconcile=True) as session:`
   - node = `session.tree` if PATH is omitted, else `lookup(session.tree, segments, path)`.
   - Missing path gives `PathError` (exit 5), unchanged wording.
4. Decide what to print:
   - `scalar = scalar_of(node)`. If `scalar is not None and not args.sources`, return `format_scalar(scalar.value)`: identical to `get`.
   - Otherwise return `yamlout.to_text(yamlout.render(node), session.theatre.directory if args.sources else None)`.
   - Use the theatre directory from the session (`session.theatre.directory`, resolved). Do not use the `--theatre` argument as given, because source labels are relative to the resolved theatre directory.
5. Render inside or after the `with`. The tree is fully loaded either way, but rendering inside keeps it under the lock with no cost; either is fine.
6. Docstring: cite FR-004 to FR-006, FR-009 to FR-014 and DM 01M411YHFR2PMJEJWMHX4KN9C4, and state that `show` never writes configuration files.

## Subtask T012 — Parser for `show`

**Steps** (out-of-map edit in `src/troupe/cli.py`, see above):
1. `show = commands.add_parser("show", help="print PATH, or the whole configuration, as YAML")`
2. `show.add_argument("path", metavar="PATH", nargs="?", default=None)`
3. `show.add_argument("--sources", action="store_true", help="end every line holding a scalar with '# from <file>'")`
4. Keep `show` in the `_add_theatre_option` loop. Check that `show --sources --theatre DIR`, `show PATH --sources` and `show --theatre DIR PATH` all parse.

## Subtask T013 — Rewrite `tests/integration/test_show.py`

The step-1 scalar tests now live in `test_get.py` (WP02). Replace this file's contents with `show` tests (names state the claim):

- `test_show_scalar_prints_exactly_what_get_prints`: parametrised over int, float (`1e20`, `.inf`, `.nan`), bool, null, plain string, string ending in `\n`, text include, CRLF text include. Compare with a real `get` run byte for byte.
- `test_show_mapping_prints_block_yaml` (spec US2 scenario 1, exact bytes).
- `test_show_flow_list_prints_block_sequence` (US2 scenario 2: `- a\n- b\n`).
- `test_show_whole_configuration_includes_text_include_as_literal_block` (US2 scenario 3).
- `test_show_without_path_parses_back_to_resolved_configuration` (US2 scenario 5, NFR-001). Use a rich fixture (the old `test_show.py` FIXTURE is a good start: nested includes, a flow list, a literal block, float, bool, null). Parse with `YAML(typ="safe", pure=True)` and compare with the expected Python data written out by hand in the test.
- `test_show_keys_in_file_order`.
- `test_show_whole_yaml_include_prints_its_content`.
- `test_show_empty_root_prints_empty_mapping` (`{}\n`).
- `test_show_missing_path_exits_5_naming_path` (US2 scenario 6, empty stdout).
- `test_show_path_through_scalar_exits_5`; `test_show_invalid_path_exits_2_and_creates_nothing`.
- `test_show_unloadable_configuration_exits_4_naming_file` (missing include target).
- `test_show_reads_hand_edits_and_records_them_first` (FR-013: hand-edit, `show`, then `history` has the `set` event).
- `test_show_changes_no_configuration_file` (FR-014/C-003: `snapshot` before and after, for `show`, `show PATH` and `show --sources`).
- `test_help_lists_show_with_sources_option`.

## Subtask T014 — `tests/integration/test_show_sources.py`

- `test_sources_example_from_contract`: build the theatre from `contracts/cli.md` "Example" and assert stdout equals the documented output **exactly**.
- `test_sources_scalars_in_yaml_include_name_included_file` (US3 scenario 1).
- `test_sources_text_include_comment_on_block_header_only` (US3 scenario 2: no body line contains `# from`).
- `test_sources_list_items` (US3 scenario 3).
- `test_sources_scalar_path_prints_yaml_scalar_with_comment` (US3 scenario 4: `8080 # from .troupe/server.yml\n`). Add a text-include scalar PATH case: header `| # from …`, then the body.
- `test_sources_collection_lines_have_no_comment`: every line that ends with `:` or is `{}`/`[]` has no comment, and every other non-body line has exactly one.
- `test_sources_output_parses_to_same_data_as_plain_show` (US3 scenario 5).
- `test_sources_paths_are_relative_to_theatre_with_slashes`: an include in a nested dir `.troupe/agents/coder.yaml`.
- `test_sources_include_outside_theatre_uses_dotdot`: e.g. `server: file:../../shared/server.yml` from `.troupe/troupe.yml`, with the target created outside the theatre dir (use `tmp_path` structure), giving `# from ../shared/server.yml`.
- `test_sources_theatre_given_as_relative_path_still_labels_relative_to_theatre`: run with `cwd` set and `--theatre .` or a relative path.

## Subtask T015 — Walk-through, gates and agreement

1. Run every command in `kitty-specs/troupe-config-get-show-01M411XB/quickstart.md` by hand. Paste the outputs into the Activity Log and confirm they match `contracts/cli.md`.
2. Check spec FR-001 to FR-015 against code and tests: each FR has at least one test that fails if the behaviour breaks. List the FR → test mapping in the Activity Log.
3. Run all gates and paste the outputs: `uv run pytest`, `uv run mypy --strict`, `uv run ruff check`, `uv run ruff format --check`.
4. `grep -rn '"show"' tests/` must show only `test_show*.py` and the parametrised reconcile-first test.

## Definition of Done

- [ ] `show` behaves per contract in every case listed. `get` and `show` on a scalar are byte-identical.
- [ ] `--sources` output matches the contract example exactly.
- [ ] No configuration file is modified by `show` (tested).
- [ ] cli.py edit limited to the `show` subparser, and noted.
- [ ] All gates green with output shown; FR → test mapping recorded.
- [ ] `spec-kitty agent tasks mark-status T011 T012 T013 T014 T015 --status done --mission troupe-config-get-show-01M411XB`.

## Risks

- **Source label base**: using the as-given `--theatre` string instead of the resolved theatre directory breaks labels under symlinks or relative paths. Tested in T014.
- **Scalar + `--sources`** must go through the renderer, not `format_scalar`.
- **Parse-back with NaN**: compare NaN specially if it is in a fixture.

## Reviewer Guidance

- Run the contract example by hand.
- Check that every spec US2/US3 scenario has a test with the same expected bytes as the spec.
- Confirm the out-of-map edit is limited to the `show` subparser.

## Activity Log

- 2026-10-03T14:30:00Z – system – Prompt generated via /spec-kitty.tasks
