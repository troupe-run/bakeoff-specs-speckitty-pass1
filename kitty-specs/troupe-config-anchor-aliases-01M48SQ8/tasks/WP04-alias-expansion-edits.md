---
work_package_id: WP04
title: Expansion text
dependencies:
- WP02
requirement_refs:
- FR-005
- FR-006
planning_base_branch: fix/troupe-config-anchor-aliases
merge_target_branch: fix/troupe-config-anchor-aliases
branch_strategy: Planning artifacts for this mission were generated on fix/troupe-config-anchor-aliases. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into fix/troupe-config-anchor-aliases unless the human explicitly redirects the landing branch.
subtasks:
- T016
- T017
- T018
- T019
phase: Phase 3 - Write rules
history:
- at: '2026-10-06T15:00:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/troupe/writeback/aliases.py
create_intent:
- src/troupe/writeback/aliases.py
- tests/unit/test_alias_expansion.py
execution_mode: code_change
owned_files:
- src/troupe/writeback/aliases.py
- tests/unit/test_alias_expansion.py
role: implementer
agent: claude
model: ''
tags: []
task_type: implement
tracker_refs:
- bakeoff-specs-speckitty-qht
---

# Work Package Prompt: WP04 – Expansion text

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter (`agent_profile`, `role`, `agent`), and behave according to its guidance before parsing the rest of this prompt.

If no profile is specified, run `spec-kitty agent profile list` and select the best match for this work package's `task_type` and `authoritative_surface`.

---

## ⚠️ IMPORTANT: Review Feedback

- **Has review feedback?**: Check the `review_ref` field in the event log (via `spec-kitty agent tasks status`) or the Activity Log below.
- **You must address all feedback** before your work is complete.

---

## Objective

Create `src/troupe/writeback/aliases.py` with one public, pure function:

```python
def expand_edits(
    file: SourceFile,
    alias: AliasNode,
    parent: MappingNode | SequenceNode,
    slot: str | int,
    step: int,
    *,
    path: str,
) -> list[TextEdit]:
```

It returns the edits that replace one **written** alias (`*name`) in `file` with a **block-style copy** of its anchored node. It puts the end-of-line comment `# expanded from *<name> by troupe`, with two spaces before `#`, on the key's line (or the dash's line for a list item). Nothing else in the file changes. This is the contract's expansion rule plus spec C7, C8 and C9. `apply.py` (WP05) applies the edits, reloads and sets the value in the copy. This WP does not set values.

Worked example (contract):

```yaml
# before                     # after expand_edits on coder.settings
defaults: &d                 defaults: &d
  model: opus                  model: opus
coder:                       coder:
  settings: *d                 settings:  # expanded from *d by troupe
reviewer:                        model: opus
  settings: *d               reviewer:
                               settings: *d
```

## Context

- Spec: US4, FR-005, FR-006, C7, C8, C9; Worked example.
- Research: **R-7** (read fully).
- Building blocks to reuse, without changing them (they belong to WP05 or are shared):
  - `writeback.TextEdit`;
  - `collections.entry_column`, `collections.detect_indent` (the caller passes `step`), `collections._sequence_offset` (private; copy the tiny logic, or ask in the handoff to make it public in WP05; do not edit `collections.py`);
  - `comments.find_comment_start`;
  - `scalars.render_scalar`, `scalars.render_string`, `scalars.choose_style`;
  - `blocks.render_new_multiline`, `blocks.choose_chomp`;
  - `fileio.detect_newline`.
- WP02 types: `AliasNode` (`origin` is the `*name` token, `name`, `target`, `anchored`), and `Anchor` on nodes. Spans of anchored nodes exclude the anchor (WP01 R-2).

## Branch Strategy

- Planning/base branch: `fix/troupe-config-anchor-aliases`; final merge target: `fix/troupe-config-anchor-aliases`, merged into `main` locally after acceptance.
- Execution worktrees are allocated per computed lane from `lanes.json`; run `spec-kitty agent action implement WP04 --agent <name>` (depends on WP02; parallel with WP03).

## Subtasks

### T016 — C9 refusals

Raise `WriteRefused` (exit 3) with messages starting `{path}: ` and naming `*{name}`, the file and line, and ending `; no file changed`:
1. **Flow parent** (`parent.flow`): `... the alias *d at {file} line {n} is inside a flow collection; a block-style copy cannot be written there; no file changed`.
2. **Not on the key's or dash's line.** For a mapping parent, the key's line is the line of `entry.key_origin.start`. For a block sequence, it is the line of the item's `-`; there is no `_dash_pos` import, so search backwards from `alias.origin.start` over spaces for `-`. If `alias.origin.start` is on another line (`settings:` then `*d` on the next line), refuse: `... is not on its key's line; moving it would rewrite a line you did not ask to change; no file changed`.
3. **Existing end-of-line comment** after the alias on that line (`find_comment_start(line, col_after_alias)` is not `None`): `... its line already has a comment; troupe's comment would replace it; no file changed`.
4. Anything other than blanks between the head (`key:` or `-`) and the alias token, such as a tag (impossible after C2) or anything unexpected → refuse with a generic "cannot expand byte-surgically" message. This mirrors `collections._refuse_properties`.

### T017 — Copy rendering (C8)

Render the anchored content `content = unwrap(alias.target)` (`paths.unwrap`; `target` may itself be an alias for chained aliases, so unwrap it). The output is a list of lines without line breaks; join them with the file's newline.

- **Mapping content**: for each entry, `key` text is `entry.key_origin.source` if single-line (quoting kept), else `render_string(key, choose_style(key, None, "block"))`. Then:
  - the value is an `AliasNode` (inner alias, C7: stays an alias) → `key: *{name}`;
  - a non-empty mapping or sequence (block or flow in the original) → `key:` plus nested block lines at `indent + step` for mappings, or at `indent + seq_offset` for sequences, where `seq_offset` follows the flush/indented rule of `collections._sequence_offset` for the *parent* mapping where the alias sits;
  - an empty mapping or sequence → `key: {}` / `key: []`;
  - a scalar → `key: {scalar_text}`, where `scalar_text` is `node.origin.source` if the span is on one line and the style is plain, single or double (written form kept, anchor excluded by R-2). Otherwise:
    - a multi-line string becomes a literal block via `render_new_multiline(value, "block", indent + step, step)`, with header `|` or `|-` on the key line;
    - a non-string uses `render_scalar(value, None, "block")`;
  - a zero-width null (`a:`) → `key:` with nothing after it, as written.
- **Sequence content**: each item at the dash column, `- ` + scalar text, `- *name` for an inner alias, or compact form for collections (`- k: v`, continuation lines at dash + 2), matching `collections._Renderer.item`.
- **Scalar content** (`model: *m`): no lines below. The scalar text goes on the head line (T018).
- **Never write an anchor** (`&x`). Spans exclude anchors, and nested anchored nodes are rendered from content only. **Never copy comments**: render node by node, never by copying text ranges.
- **Text and YAML includes**: impossible (C3); `assert`.

### T018 — Head-line edit and the comment

Let `head_end` be the index just after the key's `:` (mapping; reuse the same logic as `collections._anchor(...).head_end` by reimplementation, since the original is private) or just after the `-` (sequence). Let `alias_end = alias.origin.end`. Produce:

1. **Collection copy** (`model:` block lines below):
   - `TextEdit(head_end, alias_end, "  # expanded from *d by troupe")`. The bytes between `head_end` and the alias are blanks only (T016), so the result reads `settings:  # expanded from *d by troupe`.
   - an insertion `TextEdit(line_end_after_alias, ..., newline + "\n".join(copy_lines))` placed **after the line's existing line break**, so the copy lines follow the head line. Take care with a file whose last line has no final break: keep "no final break" exactly as `collections._insert_lines` does. Study it, and replicate it or keep the copy's last line without a break.
   - indentation: mapping keys at `entry_column(text, parent) + step` under a key; under a dash, at the dash column + 2 (compact convention, the item's content column). A list copy under a key goes at the key column + `seq_offset`.
2. **Scalar copy**: `TextEdit(alias.origin.start, alias_end, scalar_text + "  # expanded from *m by troupe")`, giving `model: opus  # expanded from *m by troupe`. For a list item: `- opus  # expanded from *m by troupe`.
3. **List item collection copy**: `-  # expanded from *d by troupe`, a dash, two spaces and the comment, with the copy lines below at dash column + 2 (spec US4-4).
4. **Name in the comment**: `alias.name` exactly (contract: `*<name>`).
5. **CRLF files**: use `fileio.detect_newline(text)` for every inserted break.

### T019 — Unit tests (`tests/unit/test_alias_expansion.py`)

Load fixture texts from `tmp_path` with `loader.load`. Find the alias node by walking (`paths.walk`, `found.nodes[i]`) and the parent with `placement.concrete_parent`, which is read-only use of WP03's module; if WP03 is not merged in your lane, find the parent by walking the concrete mapping yourself. Call `expand_edits`, apply with `writeback.apply_edits` and compare the **whole** new text:
- `test_worked_example_expands_coder_settings_exactly` (contract example, byte-for-byte).
- `test_flow_anchored_mapping_is_copied_in_block_style` (`defaults: &d {model: opus, t: 1}`).
- `test_scalar_alias_becomes_its_scalar_with_comment` (C4).
- `test_list_item_alias_puts_comment_on_dash_line` (US4-4).
- `test_inner_alias_stays_an_alias_in_the_copy` (C7).
- `test_inner_anchor_and_comments_are_not_copied` (C8).
- `test_quoted_scalars_keep_their_written_quoting` (C8).
- `test_multiline_string_in_anchored_node_becomes_literal_block`.
- `test_four_space_file_indents_copy_by_four`.
- `test_crlf_file_keeps_crlf_in_copy`.
- `test_file_without_final_newline_stays_without`.
- `test_alias_in_flow_collection_is_refused`, `test_alias_line_with_comment_is_refused`, `test_alias_on_next_line_is_refused` (C9).
- `test_expanded_text_reloads_to_the_same_resolved_values`: after the edits, `leaves.flatten(load(new))` equals `flatten(load(old))` for every fixture above (the copy is faithful), and the other aliases are still `AliasNode`s.

## Definition of Done

- `writeback/aliases.py` exists with `expand_edits` and a module docstring citing C7–C9 and R-7.
- All tests above pass; the full suite passes; four gates pass with output pasted.
- No other source file is edited. If a private helper in `collections.py` should become public, say so in the handoff for WP05 instead of editing it.

## Risks

- **Insertion at the end of the file / last line without a break.** Reuse the existing conventions; tests pin them.
- **Indentation of nested sequences.** Copy the flush/indented rule; a mismatch only looks wrong but still loads, so tests must compare whole text.

## Reviewer guidance

- Compare whole texts in the tests, not fragments.
- Verify the comment text exactly: two spaces, `# expanded from *<name> by troupe`.

## Activity Log

- 2026-10-06T15:00:00Z – system – Prompt generated via /spec-kitty.tasks
