---
work_package_id: WP02
title: get command
dependencies: []
requirement_refs:
- C-001
- FR-001
- FR-002
- FR-003
- FR-013
- FR-014
- FR-015
- NFR-002
- NFR-004
planning_base_branch: feat/troupe-config-get-show
merge_target_branch: feat/troupe-config-get-show
branch_strategy: Planning artifacts for this mission were generated on feat/troupe-config-get-show. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/troupe-config-get-show unless the human explicitly redirects the landing branch.
subtasks:
- T006
- T007
- T008
- T009
- T010
phase: Phase 1 - Foundations
history:
- at: '2026-10-03T14:30:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/troupe/commands/get.py
create_intent:
- src/troupe/commands/get.py
- tests/integration/test_get.py
execution_mode: code_change
model: ''
owned_files:
- src/troupe/commands/get.py
- src/troupe/cli.py
- src/troupe/values.py
- tests/unit/test_values.py
- tests/integration/test_get.py
- tests/integration/test_cli_basics.py
- tests/integration/test_reconcile_first.py
- tests/integration/test_set_blocks.py
- tests/integration/test_set_existing.py
- tests/integration/test_set_new_entries.py
- tests/integration/test_watch_includes.py
- tests/integration/test_watch_set.py
- tests/integration/test_history.py
role: implementer
tags: []
task_type: implement
tracker_refs: []
---

# Work Package Prompt: WP02 – `get` command

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter (`agent_profile`, `role`, `agent`), and behave according to its guidance before parsing the rest of this prompt.

If no profile is specified, run `spec-kitty agent profile list` and select the best match for this work package's `task_type` and `authoritative_surface`.

---

## ⚠️ IMPORTANT: Review Feedback

- **Has review feedback?**: Check the `review_ref` field in the event log (via `spec-kitty agent tasks status`) or the Activity Log below.
- **You must address all feedback** before your work is complete.

---

## Objective

Add `troupe config get PATH`. It prints a scalar byte-for-byte as step-1/2 `show PATH` did. On a mapping or list it exits 5 with one stderr line that names PATH and mentions `config show`. Make `get` the value reader in the existing test helpers.

**Do not change `show` in this WP.** Leave `src/troupe/commands/show.py`, the `show` subparser and `tests/integration/test_show.py` alone; they belong to WP03. `show` must keep working unchanged until WP03 rewrites it.

## Context

Read first:
- `kitty-specs/troupe-config-get-show-01M411XB/spec.md`: US1, FR-001 to FR-003, FR-013 to FR-015, NFR-002, NFR-004
- `kitty-specs/troupe-config-get-show-01M411XB/research.md`: D-9, "get refusal wording"
- `kitty-specs/troupe-config-get-show-01M411XB/contracts/cli.md`: exit codes and scalar printing
- `src/troupe/commands/show.py`: the logic `get` inherits
- `src/troupe/cli.py`: parser, `COMMAND_MODULES`, `_add_theatre_option`
- `src/troupe/values.py`: `format_scalar`
- `tests/integration/test_show.py` and `tests/conftest.py`: test style and the `make_theatre`/`run_cli` helpers
- `.kittify/charter/charter.md`: TROUPE-003, -005, -006, -007, -009

## Branch Strategy

- Planning/base branch: `feat/troupe-config-get-show`
- Final merge target: `feat/troupe-config-get-show` (delivered to `main` after acceptance)
- Execution worktrees are allocated per computed lane from `lanes.json`. Run `spec-kitty agent action implement WP02 --agent <name>` and work only in the worktree it gives you.

---

## Subtask T006 — `values.scalar_of(node)`

**Purpose**: One place that decides "is this node a scalar, and what is its value?" `get` uses it here, and `show` will use it in WP03.

**Steps**:
1. In `src/troupe/values.py` add:
   ```python
   @dataclass(frozen=True)
   class ScalarValue:
       value: Scalar

   def scalar_of(node: Node) -> ScalarValue | None: ...
   ```
   - `None` is a valid scalar value (YAML null), so a bare `Scalar | None` return could not distinguish "not a scalar". The wrapper `ScalarValue` makes "null scalar" (`ScalarValue(None)`) and "section" (`None`) distinct.
   - Input is the node *as found* or unwrapped. Call `paths.unwrap` inside, so a scalar-only YAML include counts as a scalar.
   - `ScalarNode` gives `ScalarValue(node.value)`; `TextInclude` gives `ScalarValue(node.target.text)`; a mapping or sequence gives `None`.
   - Check for import cycles: `values.py` imports `troupe.paths` and `troupe.tree`. `paths` must not import `values`; currently it does not.
2. Unit tests in `tests/unit/test_values.py`:
   - `test_scalar_of_null_scalar_is_a_scalar_with_none_value`
   - `test_scalar_of_text_include_is_its_text`
   - `test_scalar_of_mapping_and_list_is_none`
   - `test_scalar_of_unwraps_yaml_include_with_scalar_root`

## Subtask T007 — `src/troupe/commands/get.py`

**Purpose**: The command module, with the same `run(theatre, args) -> str` interface as the others.

**Steps**:
1. Create `get.py` from the current `show.py` logic: `parse_path` first (exit 2 before loading), then `open_session(theatre, reconcile=True)`, then `lookup`, then `scalar_of`.
2. If it is a scalar, return `format_scalar(value)`.
3. Otherwise raise `PathError(SECTION_REFUSAL.format(path=path, kind=kind))`, with one module constant:
   ```python
   SECTION_REFUSAL: Final = "{path} is a {kind}, not a scalar; use 'troupe config show {path}'"
   ```
   `kind` is `"mapping"` or `"list"`. The stderr line becomes `troupe: server is a mapping, not a scalar; use 'troupe config show server'`.
4. Module docstring cites spec FR-001/FR-002/FR-013 and notes that it replaces the step-1 `show` behaviour.

**Edge cases**: a whole YAML include whose root is a mapping is reported as a mapping. A path through a text include or scalar is a PathError from `walk`, unchanged.

## Subtask T008 — CLI registration

**Steps** (in `src/troupe/cli.py`):
1. Add `"get": "get"` to `COMMAND_MODULES`.
2. Add the subparser: `get = commands.add_parser("get", help="print the scalar at PATH")` with `path` positional, and include it in the `_add_theatre_option` loop.
3. Place `get` before `show` in the subcommand list so `--help` reads naturally.
4. Do **not** touch the `show` subparser; WP03 changes it.
5. Update the module docstring's command list.

**Validation**:
- `uv run troupe config --help` lists `get`.
- `uv run troupe config get` exits 2.
- `get x --sources` exits 2, as an unknown argument through `_Parser.error`.

## Subtask T009 — `tests/integration/test_get.py`

**Purpose**: Every step-1/2 `show` scalar behaviour, proven for `get` (NFR-004).

**Steps**:
1. Copy every test from `tests/integration/test_show.py` into `test_get.py`. Rename `test_show_*` to `test_get_*`, and point the helper `_show` → `_get` at `run_cli("config", "get", …)`. **Do not edit `test_show.py`**; WP03 rewrites it.
2. Change the three refusal tests (`…_list_exits_5`, `…_mapping_exits_5_and_names_path`, `…_whole_yaml_include_exits_5_as_mapping`) to also assert that stderr contains `config show` and the path. Name them accordingly, e.g. `test_get_mapping_exits_5_naming_path_and_pointing_to_config_show`.
3. Add `test_get_with_sources_option_is_a_usage_error` (exit 2, empty stdout).
4. Keep the reconcile-first (`…_reads_hand_edits_after_import`, `test_first_get_imports_theatre`) and read-only (`…_changes_no_configuration_file`) tests.

## Subtask T010 — Helpers and `test_cli_basics.py`

**Steps**:
1. In each of these files, change value-reading helper calls from `"show"` to `"get"`, and rename local helpers (`_show` → `_get`) where they exist:
   - `tests/integration/test_reconcile_first.py` (line ~43; also the parametrize at ~211: `["show", "set"]` → `["get", "show", "set"]`, so `show` reconcile-first stays covered — check the test body works for `show` with a PATH. It does; `show` on a scalar is unchanged.)
   - `test_set_blocks.py`, `test_set_existing.py`, `test_set_new_entries.py`, `test_watch_includes.py`, `test_watch_set.py` (both the `run_cli` and the `sys.executable -m troupe` call), `test_history.py`.
2. `tests/integration/test_cli_basics.py`:
   - The test at ~line 43 (`config show` without PATH → usage error) must use `get`. Once WP03 lands, `show` without PATH is valid.
   - The help test (~line 55) must also check `get` is listed.
   - The other `show a.b` uses there, theatre resolution and env tests, switch to `get`. They test theatre location, not `show`.
3. Run the full suite; everything must be green, including the untouched `test_show.py`.

## Definition of Done

- [ ] `get` works per contract; `show` is byte-identical to before (untouched).
- [ ] The refusal message is in one constant in `get.py`; `scalar_of` is in `values.py`.
- [ ] All tests above exist and pass; no test still calls `show` merely to read a value, except `test_show.py` and the parametrised reconcile-first test.
- [ ] Gates: `uv run pytest`, `uv run mypy --strict`, `uv run ruff check`, `uv run ruff format --check`. Paste the output in the Activity Log.
- [ ] `spec-kitty agent tasks mark-status T006 T007 T008 T009 T010 --status done --mission troupe-config-get-show-01M411XB`.

## Risks

- Editing the `show` subparser here would conflict with WP03 and break `show` before its rewrite. Don't.
- `None` as a valid scalar (T006): a plain `Scalar | None` return would make `get stop` (null) look like a section.

## Reviewer Guidance

- Diff `test_get.py` against `test_show.py`: same cases, plus the refusal hint and the `--sources` usage error.
- Confirm `src/troupe/commands/show.py` and `tests/integration/test_show.py` are unchanged in this WP.

## Activity Log

- 2026-10-03T14:30:00Z – system – Prompt generated via /spec-kitty.tasks
