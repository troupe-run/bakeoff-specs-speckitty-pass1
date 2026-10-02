---
work_package_id: WP07
title: New entries and collection rendering
dependencies:
- WP05
- WP06
requirement_refs:
- FR-011
- FR-012
- FR-016
- FR-019
subtasks:
- T030
- T031
- T032
- T033
- T034
- T035
phase: Phase 3 - Byte-surgical write-back renderers
history:
- at: '2026-10-02T06:01:37Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: ''
authoritative_surface: src/troupe/writeback/collections.py
create_intent:
- src/troupe/writeback/collections.py
- tests/unit/test_collections.py
execution_mode: code_change
model: ''
owned_files:
- src/troupe/writeback/collections.py
- tests/unit/test_collections.py
role: ''
tags: []
task_type: implement
tracker_refs: []
---

# Work Package Prompt: WP07 – New entries and collection rendering

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

Pure functions in `src/troupe/writeback/collections.py` returning `TextEdit`s (WP05) that:
1. Detect a file's indentation step.
2. Find where a new entry goes in a **block** collection (after the last entry and below trailing comment lines).
3. Render new keys / list items / intermediate mappings / collection values in block style, copying the preceding sibling's quoting.
4. Append to **flow** collections on the last entry's line; render flow values.
5. Replace a node by a node of a different kind (scalar ↔ collection, collection ↔ collection) keeping the key line's bytes.

Done when unit tests (whole-text before/after, re-parsed through `yamlcore` to confirm the new value) pass and gates pass.

## Context & Constraints

Contract text (authoritative, spec FR-011, FR-012, FR-015, FR-016, FR-019, FR-020):
- "A new key is written into the file containing the deepest existing ancestor mapping of PATH; missing intermediate mappings are created there."
- "PATH ending in the index equal to a list's length appends to that list."
- "A new key, and a new string value, copy the quoting style of the preceding sibling key or value; with no sibling, plain (or the minimal quoting the text needs)."
- "A new collection value is written in block style at the file's indentation (default 2), unless its parent is a flow collection, in which case it is written in flow style."
- "A new list item or mapping key goes after the collection's last entry *and below any comment lines that follow it* before the next less-indented line. A comment line indented less than a collection's entries ends that collection."
- "In a flow collection, a new entry is appended after the last entry, on that entry's line."
- "When a scalar is replaced by a block collection, the key's line keeps its bytes up to and including its end-of-line comment."
- End-of-line comment rule via `comments.replace_in_line` whenever an existing line's length changes (flow appends!).
- Research R-06 (indentation), R-10 (quoting). Inserted line breaks use the file's newline (`fileio.detect_newline`).
- Spans of block collections from the parser are fuzzy at the end (WP02 notes) — derive extents from the **text** using the rules below.

## Branch Strategy

- **Planning base branch**: `feat/troupe-config-load-show-set` · **Merge target**: `feat/troupe-config-load-show-set` (then merged into `main` locally at delivery).
- `spec-kitty agent action implement WP07 --agent <name>`.

## Subtasks & Detailed Guidance

### Subtask T030 – Indentation step

```python
def detect_indent(text: str) -> int
```
- Walk lines; ignore blank and comment-only lines. Track the indentation of the previous structural line. The first line whose indentation is **greater** than the previous structural line's gives `step = indent - previous_indent` (a `- ` sequence entry nested under a key counts by the `-` column). Flush sequences (`key:` then `- a` at the same column) give no information — keep scanning. Default **2**.
- Tests: 2-space file, 4-space file, file with only flush sequences → 2, file where first nesting is a block scalar body (skip block scalar content: lines after a `|`/`>` header are not structure — easiest: only consider lines that contain `key:` or start with `- `).

### Subtask T031 – Block collection extent and insertion point

```python
def entry_column(text: str, node: MappingNode | SequenceNode) -> int     # column of first key / of first "-"
def insertion_point(text: str, node: MappingNode | SequenceNode) -> int  # index where new entry lines are inserted
```
- `c = entry_column(...)`. Start at the line containing the **last entry** (its key or `-`). Scan following lines; a line belongs to the collection region if it is:
  - blank (whitespace only) — tentatively (only kept if a later line also belongs), or
  - indented more than `c` (content of the last entry, including block-scalar bodies and deeper comments), or
  - a comment line (`#` first non-space) indented **≥ c**.
  Stop at the first other line (a non-comment line indented ≤ c… i.e. a less-indented key, or a comment indented < c).
- Insertion point = immediately after the line break of the last **non-blank** region line (so trailing blank lines stay **after** the new entry and keep separating blocks).
- If that line is the last line of the file and has no line break, the insertion must be `newline + entry` at end of text (file still ends without a newline).
- Empty root document → insert at end of text at column 0 (if the text is non-empty and doesn't end with a newline, prefix a newline).

Example — new key `model.top_p 0.9`:
```yaml
model:
  name: claude
  temperature: 0.2
  # tuning notes
  #   more notes
# section: tools
tools: []
```
→ `  top_p: 0.9` inserted after `  #   more notes` and before `# section: tools` (less-indented comment ends the collection).

### Subtask T032 – Rendering new block entries

```python
def render_block_value(value: Value, indent: int, step: int, newline: str) -> list[str]   # lines for a nested collection value
def new_key_edits(file: SourceFile, mapping: MappingNode, keys: list[str], value: Value, step: int) -> list[TextEdit]
def new_item_edits(file: SourceFile, seq: SequenceNode, value: Value, step: int) -> list[TextEdit]
```
- **Key text**: `scalars.choose_style(key, preferred=<last entry's key_style if plain/single/double>, "block")` then `render_string`.
- **String value**: preferred style = the preceding sibling's **value** style when that sibling is a plain/single/double scalar (for a list: the previous item), else `None`. Non-strings: `render_nonstring`.
- **Multi-line string value**: literal block from WP06 (`blocks.literal_header`/`literal_lines`) with content indent = entry column + step.
- **Intermediate mappings**: `keys = ["b", "c"]` for missing `a.b.c` under existing `a` → `b:` at column c, `c: value` at c + step. Each intermediate key copies the sibling key style at its own level only where a sibling exists (the first level has the existing siblings; deeper levels have none → plain/minimal).
- **Collection value** (dict/list) in block parent: `key:` then `render_block_value(value, c + step, …)`. Mapping items in sequences use compact form `- k: v` with continuation lines at `-` column + 2. Nested sequences under a key are indented by `step` (consistent with R-06). Empty `{}`/`[]` values are written in flow form (`key: {}`), as block style cannot express them; record in the docstring.
- **New list item**: `" " * c + "- " + rendered` at the insertion point.
- Every new line ends with the file's newline.

### Subtask T033 – Flow collections

```python
def flow_append_edits(file: SourceFile, node: MappingNode | SequenceNode, key: str | None, value: Value) -> list[TextEdit]
def render_flow_value(value: Value) -> str
```
- Insert right after the **last entry's end** (for a mapping: after its value's end) the separator + new entry. Separator: copy the text between the previous two entries' boundaries if it is `,` + spaces on one line (normally `", "`); otherwise `", "`. Empty `[]`/`{}`: insert inside the brackets with no separator (`[c]`, `{b: 2}`).
- Flow mapping entries: `key: value` (key via `choose_style(..., context="flow")`). New collection values inside flow parents are flow (`{a: 1}`, `[x, y]`). Multi-line strings → double-quoted (WP06 `render_new_multiline` with `"flow"`).
- The line containing the insertion changes length → apply `comments.replace_in_line` semantics so a trailing comment keeps its column.
- Intermediate mappings under a flow parent → nested flow mappings `{b: {c: v}}`.

Example: `tools: [read, write]   # core` + append `search` → `tools: [read, write, search] # core`.

### Subtask T034 – Kind-changing replacement

```python
def replace_value_edits(file: SourceFile, parent: MappingNode | SequenceNode, index_or_key: str | int, old: Node, new_value: Value, step: int) -> list[TextEdit]
```
- **Scalar → block collection** (block parent): the key line keeps its bytes up to and including its end-of-line comment: remove the scalar text; if a comment follows, use `replace_in_line(line, start, end, "")` so the comment stays at its column; if no comment, also drop the space(s) between `:` and the removed value (line becomes `key:`). Then insert the block-rendered collection lines right after that line.
- **Block collection → scalar**: write ` <scalar>` after `key:` (comment on the key line keeps its column via `replace_in_line`), and delete the old entry lines (from the first entry line to the end of the last entry's content — **not** trailing comment lines after the last entry, which stay).
- **Collection → collection**: delete the old entries' lines (as above) and insert the new block rendering at the old entry column; for a flow old value in a block parent, the new value is a *new collection value* → block style (contract) — key line keeps its bytes up to and including its comment as in the scalar case.
- **Flow parent**: replace the old node span with `render_flow_value(new_value)`.
- Sequence item kind changes follow the same rules with `- ` instead of `key:`.

### Subtask T035 – Unit tests (`tests/unit/test_collections.py`)

Each test asserts the exact full resulting text and re-parses it through `yamlcore`/`loader` to confirm the new value:
- new key at end of nested mapping; below trailing comments; above a less-indented comment; before trailing blank lines; at EOF without final newline; into empty file.
- sibling key style copied (`"name": x` → new key `"top_p"`); sibling value style copied (`'a'` → new `'b'`); no sibling → plain; style not representable → fallback.
- intermediate mappings created (2 levels), indentation 4-space file.
- block list append (indented and flush styles); list of mappings append `- k: v`.
- flow list/mapping append; empty flow; comment column kept; multi-line in flow → double-quoted.
- scalar → block mapping with and without comment; block list → scalar; flow list in block parent → block list.
- CRLF file insertion uses CRLF.

## Risks & Mitigations

- Region scanning is the riskiest logic: keep it line-based and table-test it heavily.
- Compact `- k: v` entries: entry column of the inner mapping is the key column, not the `-` column — test.

## Review Guidance

- No edits outside the inserted/replaced region (compare untouched prefixes/suffixes byte-for-byte).
- Every rule sentence has a named test.

## Activity Log

- 2026-10-02T06:01:37Z – system – Prompt created.
