---
work_package_id: WP01
title: YAML renderer with source tagging
dependencies: []
requirement_refs:
- FR-005
- FR-007
- FR-008
- FR-009
- FR-010
- FR-011
- NFR-001
planning_base_branch: feat/troupe-config-get-show
merge_target_branch: feat/troupe-config-get-show
branch_strategy: Planning artifacts for this mission were generated on feat/troupe-config-get-show. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/troupe-config-get-show unless the human explicitly redirects the landing branch.
base_branch: kitty/mission-troupe-config-get-show-01M411XB
base_commit: 200050117c9f845df1161ca6aed1ee76dbc3ab71
created_at: '2026-10-03T14:28:08.503682+00:00'
subtasks:
- T001
- T002
- T003
- T004
- T005
phase: Phase 1 - Foundations
history:
- at: '2026-10-03T14:30:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/troupe/yamlout.py
create_intent:
- src/troupe/yamlout.py
- tests/unit/test_yamlout.py
execution_mode: code_change
model: ''
owned_files:
- src/troupe/yamlout.py
- tests/unit/test_yamlout.py
role: implementer
tags: []
task_type: implement
tracker_refs: []
---

# Work Package Prompt: WP01 – YAML renderer with source tagging

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter (`agent_profile`, `role`, `agent`), and behave according to its guidance before parsing the rest of this prompt.

If no profile is specified, run `spec-kitty agent profile list` and select the best match for this work package's `task_type` and `authoritative_surface`.

---

## ⚠️ IMPORTANT: Review Feedback

- **Has review feedback?**: Check the `review_ref` field in the event log (via `spec-kitty agent tasks status`) or the Activity Log below.
- **You must address all feedback** before your work is complete.

---

## Objective

Create `src/troupe/yamlout.py`, a **pure** module (no I/O, no CLI, no session) that renders a loaded configuration node as block-style YAML lines. Each line records the file its scalar comes from, if it holds one. WP03 uses it for `troupe config show [PATH] [--sources]`.

Nothing in this WP changes command behaviour.

## Context

Read first:
- `kitty-specs/troupe-config-get-show-01M411XB/spec.md`: FR-005 to FR-012, Edge Cases, US2/US3 scenarios
- `kitty-specs/troupe-config-get-show-01M411XB/research.md`: R-1, D-1 to D-7 (**these are the rules; follow them exactly**)
- `kitty-specs/troupe-config-get-show-01M411XB/data-model.md`: `Line` and the rendering table
- `kitty-specs/troupe-config-get-show-01M411XB/contracts/cli.md`: "YAML output", "--sources", Example
- `src/troupe/tree.py`: node types. `ScalarNode.origin.file.path` and `TextInclude.target.path` are resolved absolute paths.
- `src/troupe/paths.py`: `unwrap` (a `YamlInclude` is transparent)
- `src/troupe/writeback/scalars.py`: `choose_style`, `render_string`, `render_nonstring`, `can_plain`
- `src/troupe/writeback/blocks.py`: `can_block`, `required_chomps`, `literal_header`, `literal_lines`, `render_new_multiline`
- `.kittify/charter/charter.md`: TROUPE-005, -006, -007

Charter rules that bite here:
- **TROUPE-007**: do not re-implement quoting or chomping. Reuse `writeback.scalars` / `writeback.blocks`. Keep layout constants (indent step 2, comment prefix `" # from "`) as named constants in `yamlout.py`.
- **TROUPE-005**: test names state what they prove. Build trees from real files via `troupe.loader.load` (use `tmp_path`), not hand-built nodes, except where a shape cannot be produced from files.

## Branch Strategy

- Planning/base branch: `feat/troupe-config-get-show`
- Final merge target: `feat/troupe-config-get-show` (delivered to `main` after acceptance)
- Execution worktrees are allocated per computed lane from `lanes.json`. Run `spec-kitty agent action implement WP01 --agent <name>` and work only in the worktree it gives you.

---

## Public API (target)

```python
INDENT_STEP: Final = 2
SOURCE_COMMENT_PREFIX: Final = " # from "

@dataclass(frozen=True)
class Line:
    text: str                 # without line break
    source: Path | None = None  # file of the scalar this line holds, else None

def render(node: Node) -> list[Line]: ...
def to_text(lines: list[Line], sources_root: Path | None) -> str: ...
def source_label(path: Path, theatre_dir: Path) -> str: ...
```

`render` accepts a node *as found* (it may be a `YamlInclude`) and unwraps transparently at every level.

---

## Subtask T001 — `Line`, `to_text`, `source_label`

**Purpose**: The output model and its two serialisations: plain, and with sources.

**Steps**:
1. `Line` as above (frozen dataclass).
2. `to_text(lines, sources_root)`:
   - Join `line.text` for each line, plus ` # from <label>` when `sources_root is not None and line.source is not None`, where `label = source_label(line.source, sources_root)`.
   - Each line ends with `"\n"`. The empty list is not expected; `render` never returns it.
3. `source_label(path, theatre_dir) -> str`: `PurePath(os.path.relpath(path, theatre_dir)).as_posix()` (D-6). Both arguments are resolved absolute paths already, so do not resolve again (no filesystem access).

**Validation**:
- `source_label(theatre/".troupe/troupe.yml", theatre) == ".troupe/troupe.yml"`.
- A file outside the theatre gives `"../shared/x.yml"`.
- `to_text` without a root never adds comments. With a root, it adds them only to lines with a `source`.

## Subtask T002 — Scalar and key rendering

**Purpose**: One-line scalars, literal blocks and keys, all reading back exactly.

**Rules** (research D-2 to D-5):
- **Non-strings** (`int`, `float`, `bool`, `None`): `scalars.render_nonstring(v)`. This gives `null`, `true`/`false`, decimal ints, `repr()` floats, and `.inf`/`-.inf`/`.nan` (D-3).
- **Strings, one line** (no `\n`), *not* from a text include: `scalars.render_string(s, scalars.choose_style(s, None, "block"))`. This gives `''` for the empty string, `'true'` for `"true"`, and so on.
- **Literal block** when `blocks.can_block(s)` and either (a) the value comes from a **text include** (always, even one-line or empty text), or (b) the string contains `"\n"`:
  - chomp = first of `("clip", "strip", "keep")` in `blocks.required_chomps(s)`;
  - header = `blocks.literal_header(s, chomp, INDENT_STEP)`, giving `|`, `|-`, `|+`, with `2` inserted when the first content line starts with a space;
  - body = `blocks.literal_lines(s, content_indent)`, where `content_indent` = the column where the key or `- ` starts, plus `INDENT_STEP`. At the root it is `INDENT_STEP`.
  - Verified by planning with ruamel: `- |2` at column 0 with content at column 2, `k: |2` at column n with content at n+2, and root `|2-` with content at column 2 all read back correctly.
- **Strings a block cannot hold** (`not can_block(s)`, e.g. containing `\r`): `render_string(s, "double")` on one line (D-4). This applies to text includes too, e.g. CRLF files.
- **Keys**: `render_string(key, choose_style(key, None, "block"))`. Then, if the chosen style is plain, verify it round-trips as a key: `yamlcore.compose(f"{rendered}: x\n", "<key check>")` must give a `RawMapping` with one pair whose key is a plain `RawScalar` with text `key`. Otherwise fall back to the next style that can represent it: `single` if `scalars.can_single(key)`, else `double`. Put this in one helper, `_render_key`.

**Edge cases to test**:
- `""` gives `''`; `"123"` gives `'123'`; `"a: b"` gives `'a: b'`; `" lead"` gives `' lead'`; `"it's"` gives `it's` (plain is fine).
- Text include `"Be brief.\n"` gives `|` + `  Be brief.`.
- `"x"` without a newline gives `|-` + `  x`.
- `""` from a text include gives `|-` and no body lines.
- `"a\n\n"` gives `|+`, `  a`, and one empty line.
- `" indented\nb\n"` gives `|2`.
- CRLF `"a\r\nb\r\n"` gives `"a\r\nb\r\n"`, double-quoted with escapes.
- Key `"true"` gives `'true':`; key `""` gives `'':`; key `"a b"` gives `a b:`.

## Subtask T003 — Collection layout

**Purpose**: The block layout of research D-1 / data-model.md.

**Steps** — implement `_emit(node, indent, lead) -> list[Line]`, where `lead` is the text already on the current line (`""`, `"key: "` style prefix handled by the caller, or `"- "` chains):
1. Unwrap with `paths.unwrap` first.
2. **Mapping entry** `key: value` at column `indent`:
   - value is a scalar: one line `" " * indent + key + ": " + scalar`. A block scalar puts its header there and its body below.
   - value is a non-empty mapping or sequence: line `key:`, then children at `indent + 2`. Sequences are indented under their key: `key:` then `  - a`.
   - value is an empty mapping or sequence: `key: {}` / `key: []`.
3. **Sequence item** at column `indent`:
   - scalar: `- value`;
   - non-empty mapping: compact, with the first entry on the `- ` line and the following entries at `indent + 2`;
   - non-empty sequence: compact `- - a`, the remaining inner items at `indent + 2`;
   - empty: `- {}` / `- []`.
   - Nested compaction must work at any depth (`- - - a`, `- k:` then nested at `indent + 4`).
4. **Root** (what `render(node)` is called with):
   - mapping: entries at column 0;
   - sequence: items at column 0;
   - scalar: bare `value`, or a block header line `|…` plus body at column 2;
   - empty mapping or list: `{}` / `[]`.
5. Order: entries and items in file order (`MappingNode.entries`, `SequenceNode.items`).

**Suggested approach**: Keep the column arithmetic in one place. The simplest robust form is a function that renders a node "after a lead prefix" and returns lines, where the first line's text is `prefix + …`. Compact items pass `prefix = "- "` with the inner content column `indent + 2`.

**Validation**: the exact-text tests in T005 for every row of the data-model table.

## Subtask T004 — Source tagging (research D-7)

**Purpose**: Exactly the lines that hold a scalar get a `source`.

**Rules**:
- A line ending with a one-line scalar (`k: v`, `- v`, `- k: v`, a bare root scalar, a double-quoted fallback) gets `source = file of that scalar`.
- A literal-block **header** line gets the scalar's file. Body lines get `None`.
- Lines that only open a collection (`k:`, `- k:` whose value is nested) get `None`. Lines whose value is `{}`/`[]` get `None`.
- The file of a `ScalarNode` is `node.origin.file.path`, which covers scalars inside YAML includes and a scalar-only YAML include root. The file of a `TextInclude` is `node.target.path`.

**Validation**: In tests, assert `[l.source for l in lines]` element-wise for a mixed fixture, not just the rendered text.

## Subtask T005 — Unit tests (`tests/unit/test_yamlout.py`)

**Purpose**: Prove every rule, and prove the output reads back as the data.

**Helpers**:
- `_load(tmp_path, files: dict[str, str | bytes]) -> Node`: write files under `tmp_path/.troupe/`, then `troupe.loader.load(root)`. Mirror how `tests/conftest.py` builds theatres; check its `make_theatre` for the layout.
- `_data(node) -> object`: the resolved plain data. Build it from the tree: `ScalarNode.value`, `TextInclude.target.text`, dicts and lists. A YAML include is transparent.
- `_parse(text) -> object`: `YAML(typ="safe", pure=True).load(text)`.

**Tests (names state the claim)**, at minimum:
- `test_render_nested_mapping_uses_two_space_indent`: exact text.
- `test_render_list_under_key_is_indented_block_sequence`: `tools: [a, b]` in the file gives `tools:\n  - a\n  - b\n`.
- `test_render_list_of_mappings_is_compact`, `test_render_list_of_lists_is_compact`.
- `test_render_empty_collections_inline`: `{}`, `[]`, including an empty YAML include target and an empty root, which gives `{}\n`.
- `test_render_text_include_as_literal_block_with_exact_chomping` (parametrised: `"a\n"`, `"a"`, `"a\n\n"`, `""`, `" a\nb\n"`).
- `test_render_multiline_string_in_file_as_literal_block`.
- `test_render_crlf_text_include_is_double_quoted`.
- `test_render_strings_that_look_like_other_types_are_quoted`.
- `test_render_keys_needing_quotes_are_quoted`.
- `test_render_float_specials_read_back_as_floats`.
- `test_render_literal_block_in_list_item_and_compact_mapping_reads_back`.
- `test_sources_mark_scalar_lines_and_block_headers_only`: element-wise `source` check.
- `test_sources_inside_yaml_include_name_included_file`; `test_text_include_source_is_included_file`.
- `test_to_text_with_sources_appends_relative_posix_path`; `test_source_label_outside_theatre_uses_dotdot`.
- `test_output_with_and_without_sources_parse_to_same_data`.
- **Parse-back property**: one parametrised test over at least 8 varied fixtures, including all edge cases above. Assert `_parse(to_text(render(node), None)) == _data(node)`, and the same with sources.

Note that ruamel safe-load gives `float('nan') != float('nan')`. Compare NaN with `math.isnan`, or keep NaN out of the generic property and give it a dedicated test.

## Definition of Done

- [ ] `src/troupe/yamlout.py` with `Line`, `render`, `to_text`, `source_label`, fully typed, with docstrings naming the FR/D rules they implement.
- [ ] No quoting or chomping logic duplicated from `writeback` (reviewer greps).
- [ ] `tests/unit/test_yamlout.py` covering every bullet above; all green.
- [ ] `uv run pytest`, `uv run mypy --strict`, `uv run ruff check`, `uv run ruff format --check` pass. Paste the output in the Activity Log.
- [ ] Subtasks marked: `spec-kitty agent tasks mark-status T001 T002 T003 T004 T005 --status done --mission troupe-config-get-show-01M411XB`.

## Risks

- **Indentation of block bodies in compact items**: off-by-two errors break read-back. The parse-back test is the guard.
- **Key quoting**: `choose_style` was written for values. The key round-trip check (T002) covers the gap.
- **NaN equality** in property tests (see T005).

## Reviewer Guidance

- Check each research D-rule against code and tests one by one.
- Check that `render` never touches the filesystem and `source_label` does not resolve paths.
- Look for at least one test that would fail if the comment were put on a block body line.

## Activity Log

- 2026-10-03T14:30:00Z – system – Prompt generated via /spec-kitty.tasks
