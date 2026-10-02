---
work_package_id: WP06
title: 'Block scalars: literal and folded'
dependencies:
- WP05
requirement_refs:
- FR-017
- FR-018
planning_base_branch: feat/troupe-config-load-show-set
merge_target_branch: feat/troupe-config-load-show-set
branch_strategy: Planning artifacts for this mission were generated on feat/troupe-config-load-show-set. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/troupe-config-load-show-set unless the human explicitly redirects the landing branch.
subtasks:
- T025
- T026
- T027
- T028
- T029
phase: Phase 3 - Byte-surgical write-back renderers
history:
- at: '2026-10-02T06:01:37Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: ''
authoritative_surface: src/troupe/writeback/blocks.py
create_intent:
- src/troupe/writeback/blocks.py
- tests/unit/test_blocks.py
execution_mode: code_change
model: ''
owned_files:
- src/troupe/writeback/blocks.py
- tests/unit/test_blocks.py
role: ''
tags: []
task_type: implement
tracker_refs: []
---

# Work Package Prompt: WP06 – Block scalars: literal and folded

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

Pure functions (in `src/troupe/writeback/blocks.py`) that produce `TextEdit`s (from
`troupe.writeback`, WP05) for multi-line strings:

1. Replacing a plain/quoted scalar by a multi-line string → **literal block** (`|`, `|-`, `|+`).
2. Replacing the value of an existing block scalar (`|` or `>`) → keep its indicator and chomping unless the new value's trailing newlines require a different chomping.
3. **Folded (`>`)** values: unchanged paragraphs keep bytes; changed paragraphs re-wrapped greedily at their old width; refusal (exit 3) for more-indented lines.
4. Rendering a multi-line string for a **new key** (literal block) or inside a **flow** parent (double-quoted).

Done when unit tests cover every contract sentence below and gates pass. WP08 wires these into `set`.

## Context & Constraints

Contract text (authoritative, spec FR-017/FR-018):
- "A multi-line string replacing a plain or quoted scalar is written as a literal block (`|`, with `|-` when the value has no trailing newline). A block scalar keeps its indicator and chomping unless the value's trailing newlines require a different chomping."
- "A new key whose value is a multi-line string is written as a literal block in the same way, unless its parent is a flow collection, where it is written as a double-quoted flow scalar."
- "**Folded (`>`) values:** paragraphs whose text is unchanged keep their bytes. A changed paragraph is re-wrapped, greedily by word, at the width of the longest content line of that paragraph before the change (a single word longer than the width takes a line of its own). A paragraph with no counterpart in the old value is wrapped at the width of the value's longest old content line. A change that would put a more-indented line into a folded value → exit 3."
- "End-of-line comments: when a changed value's length changes, the comment on that line is moved back to its previous column" — applies to the **header line** when `0.2` becomes `|` etc. Use `comments.replace_in_line` (WP05).
- "Multi-line string" = a `str` containing `\n` (after VALUE parsing).
- Research R-11. File newline (`fileio.detect_newline`) is used for every inserted line break.

## Branch Strategy

- **Planning base branch**: `feat/troupe-config-load-show-set` · **Merge target**: `feat/troupe-config-load-show-set` (then merged into `main` locally at delivery).
- `spec-kitty agent action implement WP06 --agent <name>`.

## Subtasks & Detailed Guidance

### Subtask T025 – Literal block rendering and chomping

```python
Chomp = Literal["strip", "clip", "keep"]

def required_chomps(value: str) -> set[Chomp]     # 0 trailing "\n" → {"strip"}; 1 → {"clip","keep"}; ≥2 → {"keep"}
def literal_lines(value: str, content_indent: int) -> list[str]   # body lines without line breaks
def literal_header(value: str, chomp: Chomp) -> str               # "|", "|-", "|+", plus indentation indicator if needed
```
- Body: strip the trailing newlines accounted for by chomping, split on `"\n"`; non-empty lines get `" " * content_indent` prefix; empty lines are written as **empty** (no trailing spaces). For `keep` with k ≥ 2 trailing newlines, append k−1 empty lines.
- If the first line starts with a space, add an explicit indentation indicator (`|2-` style: digit = indentation **relative to the parent** = file indent step) — YAML would otherwise mis-detect the indentation.
- If the value contains characters a block scalar cannot hold (control characters other than tab, U+FEFF), the caller must fall back to double-quoted: provide `can_block(value) -> bool`.
- **Content indent** = the parent's column + file indent step (step from WP07's indentation detection, passed in as an `int`; default 2). Parent column: for `key: value`, the key's column; for a sequence item `- value`, the column of `-`.

### Subtask T026 – Existing block scalars: header parse and content replacement

```python
@dataclass
class BlockScalar:
    indicator: Literal["|", ">"]
    chomp: Chomp
    indent_indicator: int | None
    header_start: int; header_end: int          # indices of the header token within file text
    content_start: int; content_end: int        # start of first content line … end of last content line incl. its line break
    content_indent: int
    lines: list[str]                            # raw content lines (without line breaks)

def parse_block(text: str, header_start: int, parent_indent: int) -> BlockScalar
def replace_literal(block: BlockScalar, text: str, new_value: str, newline: str) -> list[TextEdit]
```
- Parse the header from the file text at the scalar's origin start (`|`/`>` then optional `-`/`+` and digit in either order). Content lines run from the next line while lines are empty/whitespace-only or indented ≥ content indent; content indent = indicator digit + parent indent, or the first non-empty line's indent.
- For `clip`/`strip`, trailing empty lines are **not** content (they stay as they are); for `keep` they are content.
- Chomping: keep `block.chomp` if it is in `required_chomps(new_value)`; else switch to the one required (`clip` preferred over `keep` for one newline). Only the chomp character in the header changes; apply the comment-column rule to the header line when its length changes.
- Literal (`|`) replacement: replace the content lines with `literal_lines(new_value, block.content_indent)`.
- New value **without** `\n` replacing a block scalar: still written as a block (indicator kept, `strip` chomping) — the contract keeps block style; record this choice in the module docstring.

### Subtask T027 – Folded paragraphs and greedy re-wrap

```python
def folded_paragraphs(lines: list[str], content_indent: int) -> list[Paragraph]   # Paragraph(text, line_range, width)
def replace_folded(block: BlockScalar, text: str, new_value: str, newline: str) -> list[TextEdit]
def greedy_wrap(paragraph: str, width: int) -> list[str]
```
- Folding semantics: within a paragraph, a single line break between non-empty lines folds to one space; `n` empty lines between paragraphs = `n` newlines in the value. So split the new value body (after chomping) with `re.split(r"(\n+)", body)` into paragraphs and separators; a separator of `k` newlines ↔ `k` blank lines... careful: `"a\nb"` in the **value** means one blank line between paragraphs `a` and `b` in the folded text (a single `\n` in a folded value needs one empty line). So `k` newlines in the value ↔ `k` empty lines in the file.
- Match paragraphs by position. Unchanged text → copy original lines verbatim (bytes kept). Changed → `greedy_wrap(text, old_paragraph.width)` where width = longest old content line of that paragraph (excluding the indentation). Extra new paragraphs → width = longest old content line of the whole value. Removed paragraphs → their lines disappear.
- `greedy_wrap`: split on single spaces; add words while `len(line) + 1 + len(word) <= width`; a word longer than width gets its own line. Never create a line that starts with whitespace.
- Separators: reuse the old blank lines where the count is unchanged; otherwise emit empty lines.

### Subtask T028 – Refusals and flow-context fallback

- `replace_folded` raises `WriteRefused` (exit 3, message naming the config path passed in by the caller) when any line it would write starts with a space or tab (more-indented), e.g. a new value whose paragraph starts with a space, or contains a tab-led line.
- If the **old** folded value contains more-indented lines, refuse (`WriteRefused`) unless the new value leaves those paragraphs byte-for-byte unchanged — conservative choice (TROUPE-002); document it.
- `render_new_multiline(value, context, content_indent) -> tuple[str, list[str]]`: in `block` context → literal header + body lines; in `flow` context → `scalars.render_string(value, "double")` (double-quoted flow scalar with `\n` escapes).
- A multi-line string replacing a plain/quoted scalar **inside a flow collection** cannot be a block scalar: write it double-quoted. Record this choice in the module docstring (contract silent; YAML forbids block scalars in flow context).

### Subtask T029 – Unit tests (`tests/unit/test_blocks.py`)

Whole-text before/after assertions using `apply_edits`:
- `notes: short  # c` → `"line one\nline two\n"` gives `notes: |    # c` (comment column kept) + `  line one` / `  line two`.
- no trailing newline → `|-`; two trailing newlines → `|+` with one blank line.
- Existing `|` block: replace content; keeps `|`; switch to `|-` when value lacks final newline; `|+` kept when value has one newline.
- Existing block with trailing blank line after it followed by a key: blank line preserved.
- Nested key (indent 4) content indent 6; sequence item `- |` content indent.
- Folded: three paragraphs, change the middle one → first and last bytes identical; middle wrapped at its old width; single long word on its own line; added fourth paragraph wrapped at the overall longest old line; removed paragraph.
- Folded refusal: new paragraph starting with a space → `WriteRefused`.
- First line starting with space → indentation indicator.
- CRLF file: inserted lines use `\r\n`.
- Flow context new multi-line → double-quoted with `\n` escapes.

## Risks & Mitigations

- Off-by-one in folded `\n` ↔ blank-line mapping: test with values parsed back through `yamlcore` (compose the resulting text and compare the scalar value) — add a helper in the test that re-loads and asserts the value equals `new_value`.
- Header detection with comments (`key: >-  # note`) — test.

## Review Guidance

- Every resulting file text is re-parsed in tests and yields exactly the new value.
- Unchanged paragraphs/lines are byte-identical.

## Activity Log

- 2026-10-02T06:01:37Z – system – Prompt created.
