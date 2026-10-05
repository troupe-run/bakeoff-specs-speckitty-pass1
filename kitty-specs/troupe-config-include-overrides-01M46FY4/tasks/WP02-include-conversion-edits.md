---
work_package_id: WP02
title: Include conversion edits
dependencies: []
requirement_refs:
- FR-006
planning_base_branch: feat/troupe-config-include-overrides
merge_target_branch: feat/troupe-config-include-overrides
branch_strategy: Planning artifacts for this mission were generated on feat/troupe-config-include-overrides. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/troupe-config-include-overrides unless the human explicitly redirects the landing branch.
subtasks:
- T008
- T009
- T010
- T011
- T012
phase: Phase 1 - Foundations
history:
- at: '2026-10-05T17:30:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/troupe/writeback/collections.py
create_intent: []
execution_mode: code_change
owned_files:
- src/troupe/writeback/collections.py
- tests/unit/test_collections.py
role: implementer
tags: []
task_type: implement
tracker_refs: []
---

# Work Package Prompt: WP02 – Include conversion edits

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter (`agent_profile`, `role`, `agent`), and behave according to its guidance before parsing the rest of this prompt.

If no profile is specified, run `spec-kitty agent profile list` and select the best match for this work package's `task_type` and `authoritative_surface`.

---

## ⚠️ IMPORTANT: Review Feedback

- **Has review feedback?**: Check the `review_ref` field in the event log (via `spec-kitty agent tasks status`) or the Activity Log below.
- **You must address all feedback** before your work is complete.

---

## Objective

Add one renderer to `src/troupe/writeback/collections.py`:

```python
def convert_include_edits(
    file: SourceFile,
    parent: Collection | None,
    slot: str | int | None,
    include: Origin,
    keys: list[str],
    value: Value,
    step: int,
    *,
    path: str,
) -> list[TextEdit]:
    """Turn the scalar-form include at ``include`` into mapping form with one new override.

    ``keys`` are the override path below the include (``keys[:-1]`` intermediate mappings, the
    last gets ``value``). ``parent``/``slot`` locate the include in ``file`` (``None`` when the
    include is the whole document).
    """
```

It is the text half of FR-006 (spec D-2…D-5, D-11). It takes spans and a **concrete** parent collection; it never walks the tree and never decides *whether* to convert (WP03 decides). It must not depend on WP01's types (only `Origin`, `SourceFile`, `MappingNode`, `SequenceNode`, which already exist), so it can be built in parallel.

## Context

- Spec: Intent Summary worked example; D-2, D-3, D-4, D-5, D-11; US2 scenarios 1, 2, 6, 7.
- Research R-7.
- Contract text: `coder: file:agents/coder.yaml  # c` → `coder:  # c` / `  $ref: file:agents/coder.yaml` / `  temperature: 0.3`.
- Existing helpers in this module to reuse: `detect_indent`, `entry_column`, `_Renderer` / `render_block_value`, `_nest`, `render_flow_value`, `_line_start`, `_line_end`, `_minimal_edit`, `_check_open_end`; `writeback.fileio.detect_newline`; `writeback.comments.replace_in_line`; step-1 FR-015 quoting via `_quote_style`/`_block_key`.

## Branch Strategy

- Planning/base branch: `feat/troupe-config-include-overrides`; final merge target: `feat/troupe-config-include-overrides` (merged into `main` after acceptance).
- Execution worktrees are allocated per computed lane from `lanes.json`; run `spec-kitty agent action implement WP02 --agent <name>`.

## Subtasks

### T008 — Block-mapping parent

Input line shapes (`s, e` = include span; `K` = key column = `entry_column(text, parent)`; `I` = `K + step`):

1. **Value on the key's line** — `coder: file:agents/coder.yaml  # c`:
   - Delete `text[key_end:e]` where `key_end` is the position right after the key's `:` indicator — i.e. remove the separator whitespace and the include string, **keep** `text[e:line_end]` verbatim (the gap and the comment, D-5). Result line: `coder:  # c`. Without a comment: `coder:` (keep any trailing whitespace bytes after the value as they are).
   - Find the `:` robustly: it is the last `:` before `s` on that line that follows the key span — use the parent entry's `key_origin.end` from `parent.get(slot)` and skip spaces to the `:`.
   - Insert right after that line's line break: `" " * I + "$ref: " + text[s:e] + nl`, then the override lines rendered as a block mapping at indent `I` for `_nest(keys[1:], value)` under key `keys[0]` (reuse the step-1 new-key renderer so quoting, multi-line literal blocks and nested collections follow FR-015–FR-017 exactly as for any new key).
2. **Value on a following line** — `coder:\n  file:agents/coder.yaml\n`:
   - Replace `text[s:e]` with `"$ref: " + text[s:e]` in place (the value's own column becomes the mapping's column), then insert the override lines after that line at the value's column.
3. Newline: `nl = detect_newline(text)` (CRLF files stay CRLF).
4. Placement of the inserted lines is **immediately after** the line holding the include (before any following comment lines or entries) — the new keys belong to this mapping, which ends there.

### T009 — Flow parent (mapping or sequence)

`agents: {coder: file:x.yaml}` → `agents: {coder: {$ref: file:x.yaml, t: 1}}` (D-3); `list: [file:a.yaml]` → `list: [{$ref: file:a.yaml, k: 1}]`.
- Replacement for `text[s:e]`: `"{$ref: " + text[s:e] + ", " + <flow entries of _nest(keys, value)> + "}"`, where the flow entries are `render_flow_value(_nest(keys, value))` without its outer braces (factor a helper rather than slicing strings if cleaner).
- If the line length changes and the line has an end-of-line comment, keep its column per step-1 FR-020 using `comments.replace_in_line` (one space if the value reaches it).
- A multi-line string value inside flow follows the step-1 rule (double-quoted flow scalar) — `render_flow_value` already does this; assert in a test.

### T010 — Block list item and document root

- **Block list item** `- file:a.yaml  # c` (parent is a block `SequenceNode`): replace `text[s:e]` with `"$ref: " + text[s:e]` (comment column per FR-020 via `replace_in_line`), then insert the override lines after that line at the item's content column (`s`'s column, i.e. dash column + the existing gap) (D-4). Result: `- $ref: file:a.yaml  # c` / `  k: 1`.
- **Document root** (`parent is None`; the whole file is `file:other.yaml`): replace `text[s:e]` with `"$ref: " + text[s:e]` at column 0 and insert override lines at column 0.

### T011 — Refusals and formatting rules

- **D-11**: if `text[s:e]` contains a line break, or the include scalar is a block scalar (`|`/`>`; detect from the first character of the span), raise `WriteRefused(f"{path}: the include at {file.path} line {n} spans several lines; cannot convert it to mapping form without rewriting it; no file changed")`.
- The include string's bytes (`text[s:e]`, including quotes and escapes) are moved **verbatim** (D-5): `"file:x.yaml"` stays double-quoted after `$ref: `.
- `$ref` is always written plain and first (D-2).
- Indentation step is the caller's `step` (from `detect_indent`), so a 4-space file gets 4-space nesting (US2-2).
- Call `_check_open_end`-style protections already used by `new_key_edits` where a new block scalar could absorb following lines.

### T012 — Unit tests (`tests/unit/test_collections.py`)

Use real texts loaded with the real loader (`troupe.loader.load` on files from `make_theatre`) to get spans and concrete parents, apply the edits with `troupe.writeback.apply_edits`, and compare **exact** strings. Required tests:
- `test_convert_block_include_keeps_comment_gap_on_key_line` (contract example, byte-exact)
- `test_convert_block_include_without_comment`
- `test_convert_block_include_in_four_space_file_indents_four`
- `test_convert_block_include_with_value_on_next_line`
- `test_convert_block_include_with_intermediate_keys_creates_nested_override`
- `test_convert_block_include_with_collection_and_multiline_values_uses_step1_renderers`
- `test_convert_include_in_flow_mapping_writes_flow_mapping_form`
- `test_convert_include_in_flow_list_writes_flow_mapping_item`
- `test_convert_block_list_item_include`
- `test_convert_document_root_include`
- `test_convert_keeps_quoted_include_bytes_verbatim`
- `test_convert_crlf_file_keeps_crlf`
- `test_convert_multiline_include_string_is_refused` (wrapped double-quoted string and a `|` block) — assert `WriteRefused` and exit code 3.
- `test_convert_changes_no_other_line` (diff of old/new text lines: only the include line changes and the new lines are inserted after it).

## Definition of Done

- `convert_include_edits` exported, typed, documented with D-n/R-7 references.
- No other module changed; existing collections tests unchanged and green.
- Four gates pass; output pasted in the review handoff.

## Risks

- Contract example keeps the *gap* (block mapping) whereas FR-020 keeps the *column* (value changed in place) — the two cases are different on purpose; document why in the docstring.
- Off-by-one with BOM at file start (`_bom_offset`) for document-root includes.

## Reviewer guidance

- Verify the contract example byte-for-byte.
- Verify nothing outside the include line and the inserted lines changes.
- Verify D-11 refusal raises before any edit is produced.

## Activity Log

- 2026-10-05T17:30:00Z – system – Prompt generated via /spec-kitty.tasks
