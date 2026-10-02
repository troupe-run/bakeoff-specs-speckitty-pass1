---
work_package_id: WP05
title: 'Write-back primitives: files, scalars, comments'
dependencies:
- WP02
requirement_refs:
- FR-015
- FR-020
- NFR-002
planning_base_branch: feat/troupe-config-load-show-set
merge_target_branch: feat/troupe-config-load-show-set
branch_strategy: Planning artifacts for this mission were generated on feat/troupe-config-load-show-set. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/troupe-config-load-show-set unless the human explicitly redirects the landing branch.
subtasks:
- T020
- T021
- T022
- T023
- T024
phase: Phase 3 - Byte-surgical write-back renderers
history:
- at: '2026-10-02T06:01:37Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: ''
authoritative_surface: src/troupe/writeback/
create_intent:
- src/troupe/writeback/__init__.py
- src/troupe/writeback/fileio.py
- src/troupe/writeback/scalars.py
- src/troupe/writeback/comments.py
- tests/unit/test_fileio.py
- tests/unit/test_scalars.py
- tests/unit/test_comments.py
execution_mode: code_change
model: ''
owned_files:
- src/troupe/writeback/__init__.py
- src/troupe/writeback/fileio.py
- src/troupe/writeback/scalars.py
- src/troupe/writeback/comments.py
- tests/unit/test_fileio.py
- tests/unit/test_scalars.py
- tests/unit/test_comments.py
role: ''
tags: []
task_type: implement
tracker_refs: []
---

# Work Package Prompt: WP05 – Write-back primitives: files, scalars, comments

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

Pure, unit-tested building blocks for byte-surgical write-back (decision DM-01M3XGW5Z97R8VC909JF3TVPTT:
**never re-serialise; splice only the replacement text**):

1. `fileio` — newline detection, CRLF conversion, atomic temp-file + rename writes.
2. `scalars` — which quoting style can represent a string; style choice; rendering (incl. minimal double-quote escaping) and canonical text for non-strings.
3. `comments` — rebuild a single changed line so its end-of-line comment keeps its column (or sits one space after a value that reaches it).

No CLI wiring here (WP08 does that). Done when all unit tests pass and gates pass.

## Context & Constraints

- Spec FR-015, FR-020, NFR-002; research R-05, R-10, R-12, R-13, R-14.
- Contract text (authoritative):
  - "A changed scalar keeps its quoting style if that style can represent the new value; otherwise plain if possible, else single-quoted, else double-quoted."
  - "A new key, and a new string value, copy the quoting style of the preceding sibling key or value; with no sibling, plain (or the minimal quoting the text needs)."
  - "A double-quoted scalar escapes only what YAML requires (`\\`, `\"` and control characters, as `\t`, `\n`, …); every other character is written literally."
  - "When a changed value's length changes, the comment on that line is moved back to its previous column; if the new value reaches that column, exactly one space separates value and comment. No other line changes. Columns count Unicode code points."
- Out of contract: TAB before an end-of-line comment.
- Use `troupe.yamlcore` (WP02) for round-trip checks; do not import ruamel here.

## Branch Strategy

- **Planning base branch**: `feat/troupe-config-load-show-set` · **Merge target**: `feat/troupe-config-load-show-set` (then merged into `main` locally at delivery).
- `spec-kitty agent action implement WP05 --agent <name>`.

## Subtasks & Detailed Guidance

### Subtask T020 – `fileio.py` [P]

```python
def detect_newline(text: str) -> str                 # "\r\n" if the first line break is CRLF, else "\n"
def uses_crlf(text: str) -> bool                     # contains "\r\n"
def to_crlf(value: str) -> str                       # every "\n" not preceded by "\r" → "\r\n"
def atomic_write(path: Path, text: str) -> None
def write_files(new_texts: Mapping[SourceFile, str]) -> None   # only files whose text changed
```
- `atomic_write`: `tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")`, write `text.encode("utf-8")` (BOM already part of `text`, R-14), `flush` + `os.fsync`, copy permission bits from the original (`os.chmod(tmp, stat.S_IMODE(path.stat().st_mode))`), then `os.replace(tmp, path)`. On any exception remove the temp file and re-raise. Write via `os.fdopen(fd, "wb")` — never text mode.
- `write_files` computes nothing; callers pass complete new texts **after** all planning succeeded (NFR-002).
- `src/troupe/writeback/__init__.py`: package docstring summarising the splice approach, plus the shared edit value every renderer (WP06/WP07) returns and WP08 applies:
  ```python
  @dataclass(frozen=True)
  class TextEdit:
      start: int      # code-point index into SourceFile.text
      end: int        # exclusive; start == end means pure insertion
      text: str

  def apply_edits(text: str, edits: Sequence[TextEdit]) -> str
  ```
  `apply_edits` sorts by `start`, rejects overlapping edits with `ValueError` (a bug, not a contract error), and splices right-to-left so earlier indices stay valid. Test it.

### Subtask T021 – Quoting representability and choice (`scalars.py`) [P]

```python
Context = Literal["block", "flow"]          # where the scalar sits: block collection vs inside [..]/{..}
QuoteStyle = Literal["plain", "single", "double"]

def can_plain(s: str, context: Context) -> bool
def can_single(s: str) -> bool
def choose_style(s: str, preferred: QuoteStyle | None, context: Context) -> QuoteStyle
```
- `can_plain` — conservative rules **and** a round-trip check:
  - non-empty, single line (no `\n`, `\r`, U+0085/2028/2029), no leading/trailing whitespace, no control characters, no U+FEFF;
  - first character not one of `-?:,[]{}#&*!|>'"%@` + backtick (conservative: even `-x` is refused);
  - does not contain `": "` or `" #"`, does not end with `":"`;
  - in `flow` context also no `,[]{}`;
  - `yamlcore.resolve_plain(s)` returns a `str` equal to `s` (so `true`, `0.2`, `null`, `~`, `0x1F` are **not** plain-representable as strings);
  - round-trip: compose `f"k: {s}\n"` (block) or `f"[{s}]\n"` (flow) with `yamlcore` and assert the parsed scalar is plain with text `s`.
- `can_single`: every character is `\t` or `ch.isprintable()` (excludes line breaks, controls, U+2028 …).
- Double-quoted can represent anything.
- `choose_style(s, preferred, ctx)`: if `preferred` is set and representable → `preferred`; else first of plain → single → double that can represent `s`. Callers pass `preferred` = current style (changed scalar) or the preceding sibling's style (new key/value), or `None`.

### Subtask T022 – Rendering (`scalars.py`)

```python
def render_string(s: str, style: QuoteStyle) -> str
def render_nonstring(v: int | float | bool | None) -> str
def render_scalar(v: Scalar, preferred: QuoteStyle | None, context: Context) -> str  # dispatch
```
- `plain` → `s`. `single` → `"'" + s.replace("'", "''") + "'"`.
- `double` → `'"' + escaped + '"'` where only these are escaped: `\` → `\\`, `"` → `\"`, and control characters: `\0 \a \b \t \n \v \f \r \e` by name, other C0/DEL/C1 as `\xNN`, U+2028 `\L`, U+2029 `\P`, U+0085 `\N`. Every other character (incl. non-ASCII, `'`, `#`) literally.
- Non-strings (R-10) are always plain canonical text: `True`→`true`, `False`→`false`, `None`→`null`, `int`→`str(v)`, float → `repr(v)` except `inf`→`.inf`, `-inf`→`-.inf`, `nan`→`.nan`. Check `repr` output re-resolves to the same float via `resolve_plain` (`1e+20` does).
- Multi-line strings are **not** handled here (block scalars are WP06); `render_scalar` may still produce a double-quoted multi-line string when the caller requests flow context (WP06/WP07 decide when).

### Subtask T023 – End-of-line comments (`comments.py`) [P]

```python
def find_comment_start(line: str, from_col: int) -> int | None
def replace_in_line(line: str, start_col: int, end_col: int, new_text: str) -> str
```
- `line` excludes the line break. `find_comment_start` scans from `from_col`, tracking single/double-quote state (`''` escape in single, `\"` in double); a `#` outside quotes that is preceded by a space (or is at column 0) starts a comment.
- `replace_in_line`:
  1. `before = line[:start_col]`, `after = line[end_col:]`, `c = find_comment_start(line, end_col)`.
  2. If `c is None` or `len(new_text) == end_col - start_col`: return `before + new_text + after` (no other change).
  3. Else `mid = line[end_col:c].rstrip(" ")`, `comment = line[c:]`, `head = before + new_text + mid`; if `len(head) + 1 <= c` → `head + " " * (c - len(head)) + comment`; else `head + " " + comment`.
- Columns are Python `str` indices = Unicode code points (test with `é`, `日本`, emoji).
- Lines not touched by a change are never passed here ("No other line changes").

### Subtask T024 – Unit tests

- `tests/unit/test_fileio.py`: newline detection; `to_crlf` leaves existing `\r\n` alone; `atomic_write` preserves BOM/CRLF bytes exactly and file mode, leaves no temp file on success or on simulated failure (e.g. write into a read-only directory → exception, no residue, original unchanged).
- `tests/unit/test_scalars.py`: tables:
  - plain-representable: `abc`, `hello world`, `a-b`, `x:y`; not: `true`, `0.2`, `null`, `""`, ` lead`, `a: b`, `a #b`, `#x`, `-x`, `[x`, `a,b` (flow only), multi-line.
  - `choose_style`: keeps `double` for `Grace`; keeps `single` for `it's` (rendered `'it''s'`); `plain` → `single` for `a: b`; `plain`→`double` for `tab\there`; `None` → plain for `abc`.
  - escaping: `"a\"b\\c"`, tab → `\t`, `é` literal, `\x01` → `\x01`, U+2028 → `\L`.
  - non-strings: `true`, `null`, `42`, `0.75`, `1e+20`, `.inf`.
- `tests/unit/test_comments.py`:
  - shrink: `"  temperature: 0.75 # c"` replace `0.75`→`0.2` → `"  temperature: 0.2  # c"`.
  - grow within: `"a: 0.2  # c"` → `0.75` → `"a: 0.75 # c"` (column kept).
  - grow past: `"a: 1 # c"` → `12345` → `"a: 12345 # c"`.
  - same length → identical except value.
  - `#` inside quotes not a comment: `'a: "x # y"  # c'`.
  - flow line: `"tools: [a, b]  # c"` replacing `b` with `bbb` → comment column kept.
  - Unicode columns.

## Risks & Mitigations

- Over-permissive `can_plain` silently changes a value's type on the next load → keep rules conservative **and** do the round-trip check.
- Tab before a comment is out of contract — do not special-case.

## Review Guidance

- Each contract sentence above maps to at least one named test.
- No ruamel import outside `yamlcore`.

## Activity Log

- 2026-10-02T06:01:37Z – system – Prompt created.
