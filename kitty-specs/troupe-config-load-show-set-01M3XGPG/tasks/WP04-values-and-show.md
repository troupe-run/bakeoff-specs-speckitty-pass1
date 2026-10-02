---
work_package_id: WP04
title: VALUE parsing, scalar printing and show
dependencies:
- WP02
- WP03
requirement_refs:
- FR-004
- FR-005
- FR-009
planning_base_branch: feat/troupe-config-load-show-set
merge_target_branch: feat/troupe-config-load-show-set
branch_strategy: Planning artifacts for this mission were generated on feat/troupe-config-load-show-set. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/troupe-config-load-show-set unless the human explicitly redirects the landing branch.
subtasks:
- T016
- T017
- T018
- T019
phase: Phase 2 - Reading the configuration
history:
- at: '2026-10-02T06:01:37Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: "python-pedro"
authoritative_surface: src/troupe/values.py
create_intent:
- src/troupe/values.py
- src/troupe/commands/show.py
- tests/unit/test_values.py
- tests/integration/test_show.py
execution_mode: code_change
model: ''
owned_files:
- src/troupe/values.py
- src/troupe/commands/show.py
- tests/unit/test_values.py
- tests/integration/test_show.py
role: "implementer"
agent: "claude"
tags: []
task_type: implement
tracker_refs: []
---

# Work Package Prompt: WP04 – VALUE parsing, scalar printing and show

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter (`agent_profile`, `role`, `agent`), and behave according to its guidance before parsing the rest of this prompt.

If no profile is specified, run `spec-kitty agent profile list` and select the best match for this work package's `task_type` and `authoritative_surface`.

---

## ⚠️ IMPORTANT: Review Feedback

- **Has review feedback?**: Check the `review_ref` field in the event log (via `spec-kitty agent tasks status`) or the Activity Log below.
- **You must address all feedback** before your work is complete.

## Review Feedback

*[Populated if this WP is returned from review.]*

---

## Objectives & Success Criteria

Complete **User Story 1**: `troupe config show PATH` prints any scalar reachable through includes;
and provide `values.parse_value` for WP08's `set`.

Done when every US1 acceptance scenario in spec.md passes as a CLI test, and gates pass.

## Context & Constraints

- Spec FR-004, FR-005, FR-009, US1 scenarios 1–7; contracts/cli.md "Scalar printing".
- `yamlcore.py` (WP02) is the only ruamel importer — compose VALUE through it; resolve plain scalars with `yamlcore.resolve_plain` (YAML 1.2 core, research R-13).
- `show` must go through `session.open_session` (WP03) so the first `show` imports the theatre.

## Branch Strategy

- **Planning base branch**: `feat/troupe-config-load-show-set` · **Merge target**: `feat/troupe-config-load-show-set` (then merged into `main` locally at delivery).
- `spec-kitty agent action implement WP04 --agent <name>`.

## Subtasks & Detailed Guidance

### Subtask T016 – `parse_value` (`src/troupe/values.py`) [P]

```python
Value = Scalar | dict[str, "Value"] | list["Value"]

def parse_value(text: str) -> Value
```
- Compose `text` with `yamlcore.compose(text, source="VALUE")`; convert recursively: plain scalars via `resolve_plain`; quoted/block scalars → `str`; flow mapping → `dict` (keys: the key scalar's string text); flow sequence → `list`.
- **Single flow node only**: a block mapping/sequence at the root (`a: 1`, `- a`) or a block scalar (`|`) → `UsageError(f"VALUE is not a single YAML flow node: {text!r}")` (exit 2). Parse errors → `UsageError` naming the VALUE (map the `LoadError` that `yamlcore.compose` raises).
- Empty string → `None` (YAML empty plain scalar is null).
- Examples (test all): `0.2`→0.2; `true`→True; `null`→None; `abc`→"abc"; `"0.2"`→"0.2"; `{a: 1}`→{"a": 1}; `[a, b]`→["a","b"]; `"line one\nline two\n"` (shell passes backslash-n escapes inside double quotes) → `"line one\nline two\n"`; `yes`→"yes"; `2001-12-14`→"2001-12-14"; `-5`→-5.

### Subtask T017 – `format_scalar`

```python
def format_scalar(value: Scalar) -> str
```
- `str`: the string exactly, plus `"\n"` unless it already ends with `"\n"`.
- `bool` (check **before** int!): `true`/`false`. `None`: `null`. `int`: `str(v)`. `float`: `repr(v)` (`0.2`, `1e+20`, `inf`, `nan` — repr as specified).
- Every non-string result gets a trailing `"\n"`.

### Subtask T018 – `show PATH` (`src/troupe/commands/show.py`)

- `run(theatre, args)`: `segments = parse_path(args.path)`; `with open_session(theatre) as s:` `node = unwrap(lookup(s.tree, segments, args.path))`.
  - `ScalarNode` → `format_scalar(node.value)`.
  - `TextInclude` → `format_scalar(node.target.text)` (a text include is a string).
  - `MappingNode`/`SequenceNode` → `PathError(f"{args.path} is a mapping, not a scalar")` / list.
  - Missing → `PathError(f"{args.path} not found")` (from `lookup`).

### Subtask T019 – Tests

- `tests/unit/test_values.py`: table for `parse_value` and `format_scalar` (above lists), block-node rejection.
- `tests/integration/test_show.py` (CLI subprocess, exact stdout):
  - `test_show_float_prints_repr` (`0.2\n`); `test_show_string_appends_newline`; `test_show_string_ending_in_newline_prints_exactly` (block scalar `|`).
  - `test_show_bool_null_int` (`true`, `null`, `42`).
  - `test_show_value_inside_yaml_include`; `test_show_nested_include_relative_to_including_file`.
  - `test_show_text_include_prints_exact_file_text` (incl. CRLF bytes preserved on stdout and no extra newline when file ends with one; extra newline when it does not).
  - `test_show_list_item_by_index`; `test_show_mapping_exits_5_and_names_path`; `test_show_list_exits_5`; `test_show_missing_path_exits_5`; `test_show_through_scalar_exits_5`.
  - `test_show_missing_include_target_exits_4_naming_file`; `test_show_include_cycle_exits_4`.
  - `test_show_reads_hand_edits_after_import` (show, edit file, show again → new value).
  - `test_first_show_imports_theatre` (after `show`, `history` lists import events and no further import happens).
  - `test_show_yaml_core_schema_strings` (`yes`, `2001-12-14` print as written).
  - Every failure test asserts `out == ""`.

## Risks & Mitigations

- `bool` is a subclass of `int` — order matters in `format_scalar`.
- Shell quoting in tests: pass argv lists, never a shell string.

## Review Guidance

- All US1 scenarios covered by name; stdout exactness asserted with `==`.

## Activity Log

- 2026-10-02T06:01:37Z – system – Prompt created.
