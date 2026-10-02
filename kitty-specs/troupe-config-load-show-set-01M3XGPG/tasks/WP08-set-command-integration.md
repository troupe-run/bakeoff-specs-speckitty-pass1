---
work_package_id: WP08
title: set PATH VALUE integration
dependencies:
- WP02
- WP03
- WP04
- WP05
- WP06
- WP07
requirement_refs:
- C-005
- FR-010
- FR-011
- FR-012
- FR-013
- FR-014
- FR-023
- NFR-001
- NFR-002
planning_base_branch: feat/troupe-config-load-show-set
merge_target_branch: feat/troupe-config-load-show-set
branch_strategy: Planning artifacts for this mission were generated on feat/troupe-config-load-show-set. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/troupe-config-load-show-set unless the human explicitly redirects the landing branch.
subtasks:
- T036
- T037
- T038
- T039
- T040
- T041
- T042
phase: Phase 4 - set end to end
history:
- at: '2026-10-02T06:01:37Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: "python-pedro"
authoritative_surface: src/troupe/writeback/apply.py
create_intent:
- src/troupe/writeback/placement.py
- src/troupe/writeback/apply.py
- src/troupe/commands/set_value.py
- tests/integration/test_set_existing.py
- tests/integration/test_set_new_entries.py
- tests/integration/test_set_blocks.py
- tests/integration/test_set_history.py
execution_mode: code_change
model: ''
owned_files:
- src/troupe/writeback/placement.py
- src/troupe/writeback/apply.py
- src/troupe/commands/set_value.py
- tests/integration/test_set_existing.py
- tests/integration/test_set_new_entries.py
- tests/integration/test_set_blocks.py
- tests/integration/test_set_history.py
role: "implementer"
agent: "claude"
tags: []
task_type: implement
tracker_refs: []
---

# Work Package Prompt: WP08 – set PATH VALUE integration

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

Complete **User Story 2** (and the `set` half of US3): `troupe config set PATH VALUE` decides where
the change goes, composes the WP05–WP07 renderers into `TextEdit`s, verifies the result in memory,
writes atomically, and records per-leaf history events.

Done when:
- Every US2 acceptance scenario and every `set` edge case in spec.md passes as a **CLI test with whole-file byte assertions on every file of the theatre**.
- Refusals (exit 3) and path errors (exit 5) change no file and append no event.
- A no-op `set` writes nothing and appends nothing.
- `uv run pytest`, `uv run mypy --strict`, `uv run ruff check`, `uv run ruff format --check` all pass; quickstart.md runs as documented.

## Context & Constraints

- Spec FR-010…FR-020, FR-023, NFR-001, NFR-002; contracts/cli.md; research R-01, R-04, R-07, R-12, R-16, R-17; plan "Engineering Alignment" (`set` order: load → resolve → build texts → verify → atomic write → diff → events).
- Files on disk are the source of truth (DM-01M3XGPT4E0D67ZJY8PT7Z9NAT): `old` values are whatever the files contain now.
- Building blocks: `loader.load(…, overrides=…)`, `paths.walk`, `values.parse_value`, `leaves.flatten/diff/same`, `session.open_session`, `writeback.TextEdit/apply_edits`, `fileio`, `scalars`, `comments`, `blocks`, `collections`.
- FR-011 ("deepest existing ancestor mapping") is marked *Changed at step 5* — keep that decision isolated in `placement.py` (TROUPE-007).

## Branch Strategy

- **Planning base branch**: `feat/troupe-config-load-show-set` · **Merge target**: `feat/troupe-config-load-show-set` (then merged into `main` locally at delivery).
- `spec-kitty agent action implement WP08 --agent <name>` (this WP depends on all others; its lane starts after they merge).

## Subtasks & Detailed Guidance

### Subtask T036 – Placement (`src/troupe/writeback/placement.py`)

```python
@dataclass(frozen=True) class ReplaceScalar:       parent: MappingNode | SequenceNode; slot: str | int; node: ScalarNode; context: Context
@dataclass(frozen=True) class ReplaceText:         node: TextInclude
@dataclass(frozen=True) class ReplaceCollection:   parent: MappingNode | SequenceNode | None; slot: str | int | None; node: MappingNode | SequenceNode
@dataclass(frozen=True) class AddKeys:             mapping: MappingNode; keys: list[str]        # keys[0] new in mapping; rest = intermediate mappings
@dataclass(frozen=True) class AppendItem:          sequence: SequenceNode
Placement = ReplaceScalar | ReplaceText | ReplaceCollection | AddKeys | AppendItem

def place(root: Node, segments: list[str], dotted: str) -> Placement
```
Rules (contract "Where the change is written"):
1. PATH exists and is a `ScalarNode` → `ReplaceScalar` (file = node's origin file). `context` = `"flow"` if the parent collection is flow, else `"block"`.
2. PATH exists and is a `TextInclude` → `ReplaceText`.
3. PATH exists and is a `YamlInclude` (its whole value comes from an include) → `WriteRefused(f"{dotted}: value comes from include {target}; refusing to replace it")` (exit 3). A path *inside* the included file is fine.
4. PATH exists and is a mapping/list → `ReplaceCollection`. Replacing the **root** (empty PATH is a usage error anyway) is impossible.
5. PATH missing: walk to the deepest existing node `d` with `remaining` segments:
   - `d` is a mapping (after unwrapping a `YamlInclude`) → `AddKeys(d, remaining)`; the file is `d`'s origin file (the included file when reached through a YAML include).
   - `d` is a sequence and `remaining == [str(len(d.items))]` → `AppendItem(d)`; a larger index, or further segments after the index → `PathError` (exit 5).
   - `d` is a scalar/text include/null-valued key with segments remaining → `PathError(f"{dotted}: {prefix} is not a mapping")` (exit 5). (`key:` with an empty value is a null scalar, not a mapping — conservative choice; document.)

### Subtask T037 – `apply_set`: replacing existing values (`src/troupe/writeback/apply.py`)

```python
def apply_set(root: Node, segments: list[str], dotted: str, value: Value, raw_value: str) -> dict[SourceFile, str]
```
- `ReplaceScalar`:
  - `value` is a non-multi-line `str` or a non-string scalar → `scalars.render_scalar(value, preferred=<current style>, context)` replacing exactly the node span; the line is rebuilt with `comments.replace_in_line` (comment column rule). Current style `literal`/`folded` → see block case.
  - Multi-line `str` replacing a plain/quoted scalar → block context: literal block (WP06) — header replaces the scalar span (comment column rule on that line) and body lines are inserted after the line; flow context: double-quoted.
  - Existing `literal`/`folded` node → `blocks.parse_block` + `replace_literal` / `replace_folded` (folded refusals propagate as exit 3).
  - Collection value replacing a scalar → `collections.replace_value_edits`.
- `ReplaceText` (R-16, revised): if `fileio.uses_crlf(target.text)`: non-string `value` → `WriteRefused` (exit 3), string → `new = fileio.to_crlf(value)`. Otherwise (LF or no line breaks): `new = value` if it is a `str`, else `new = raw_value` — the VALUE argument exactly as typed, for **any** non-string (scalar, mapping or list; never refuse). The whole target text becomes `new`. `apply_set` therefore also takes `raw_value: str`.
- `ReplaceCollection` → `collections.replace_value_edits` (collection→collection or collection→scalar).
- Parent indentation and step: `collections.detect_indent(file.text)` once per file.

### Subtask T038 – `apply_set`: new keys, appends; verification

- `AddKeys` → block mapping: `collections.new_key_edits`; flow mapping: `collections.flow_append_edits` (with nested flow mappings for intermediate keys).
- `AppendItem` → block: `collections.new_item_edits`; flow: `flow_append_edits`.
- Group `TextEdit`s per `SourceFile`, `apply_edits` → new texts.
- **Verify before write (R-17)**: `new_root = loader.load(config_file, overrides={f.path: t for f, t in new_texts.items()})`; check `same_value(lookup(new_root, segments), value)` (deep, type-aware; for a text include compare its new text with the content actually written — `value` or `raw_value` per R-16) and that `flatten(new_root)` equals `flatten(old_root)` for every path not equal to/under `dotted`. On mismatch → `WriteRefused(f"{dotted}: cannot write this change byte-surgically; no file changed")`. Never write when verification fails.
- **No-op**: if the current value at PATH already equals `value` (deep, type-aware), return `{}` before rendering. For a text include, compare the current text with the content that would be written (R-16).

### Subtask T039 – `set PATH VALUE` (`src/troupe/commands/set_value.py`)

```python
def run(theatre: Theatre, args: argparse.Namespace) -> str:
    segments = parse_path(args.path)
    value = parse_value(args.value)                      # exit 2 on bad VALUE (before loading? — after parse_path, before session)
    with open_session(theatre) as s:                     # loads + imports if first command
        new_texts = apply_set(s.tree, segments, args.path, value, args.value)
        if not new_texts:
            return ""
        new_root = load(theatre.config_file, overrides=…)   # or reuse the verified tree from apply_set
        changes = diff(flatten(s.tree), flatten(new_root))
        write_files(new_texts)                           # atomic per file
        s.history.record(changes)                        # only after a successful write
    return ""
```
- Parse VALUE before opening the session so usage errors don't import (exit 2 occurs before loading, R-04).
- If `write_files` raises, no events are recorded (exception propagates).
- `apply_set` may return the verified tree to avoid loading twice — your choice; keep it simple.

### Subtask T040 – Integration tests: existing values (`tests/integration/test_set_existing.py`, `test_set_history.py`)

Use `make_theatre`, `run_cli`, `snapshot`; assert `snapshot(after) == expected_snapshot` (full bytes of every file). Cases:
- plain float change with comment: `  temperature: 0.2  # creativity` → `0.75` → `  temperature: 0.75 # creativity`; then `0.12345` → one space before comment; shrink back to `0.2` → comment returns to its column.
- `name: "Ada"` → `Grace` keeps double quotes; `'Ada'` → `it's` → `'it''s'`; plain `abc` → `a: b` → `'a: b'`; plain → string `true` (VALUE `'"true"'`) → `'true'`; int → string; string → int (plain).
- double-quoted escaping: VALUE with tab → `"a\tb"`; `é` literal.
- value in YAML include: only the included file changes; include target nested in subdir.
- text include LF: content becomes VALUE exactly; CRLF target: `"a\nb\n"` → `a\r\nb\r\n`; CRLF + `5` → exit 3, nothing changed; CRLF + `{a: 1}` → exit 3; LF + `5` → content `5`; LF + `0.20` → content `0.20`; LF + `{a: 1}` → content `{a: 1}`; LF + `[a, b]` → content `[a, b]`; `show` then prints that text and history records it as a string (R-16).
- refusals: `set agents.coder x` when `agents.coder` is `file:agents/coder.yaml` → exit 3, stdout empty, stderr names path, all bytes unchanged, no history events beyond import.
- path errors: `tools.5` on a 2-item list → exit 5; path through scalar → exit 5; missing root file → exit 4; bad VALUE (`a: 1`) → exit 2.
- CRLF YAML file: changed scalar keeps CRLF elsewhere.
- No-op: `set model.temperature 0.2` when already 0.2 → files unchanged (mtime may change? — must not: assert bytes and that no write happened by checking `st_mtime_ns` unchanged), no event.
- History (`test_set_history.py`): first `set` on a fresh theatre → import events then `set` event; `old` from file after a hand edit; list shrink `tools [c]` from `[a, b]` → `set tools.0 a→c`, `remove tools.1`; new key → `set` with `old: null`; seq continues; filter by PATH.

### Subtask T041 – Integration tests: new entries and blocks (`test_set_new_entries.py`, `test_set_blocks.py`)

- New key at end of nested mapping, below trailing comments, above less-indented comment; intermediate mappings; 4-space file; new key into included file's mapping; sibling key/value quoting copied.
- Block list append; flush-style list append; list of mappings.
- Flow list append on the last entry's line with comment column kept; flow mapping new key; empty `[]`.
- Scalar → block mapping keeps key line through comment; block list → scalar; flow list replaced by list in block parent → block.
- Literal: plain → multi-line (`|`), no trailing newline (`|-`); existing `|` replaced, chomping change; new key with multi-line value → literal; new key in flow parent → double-quoted.
- Folded: change one paragraph of three → other paragraphs byte-identical, changed one re-wrapped at old width; long word alone; added paragraph; more-indented → exit 3 unchanged.
- After every successful case, `show PATH` returns the new value (round trip via CLI).

### Subtask T042 – Full gates and quickstart

- Run and paste output of: `uv run pytest`, `uv run mypy --strict`, `uv run ruff check`, `uv run ruff format --check`.
- Execute `kitty-specs/troupe-config-load-show-set-01M3XGPG/quickstart.md` steps in a temp dir; confirm outputs match its comments (fix the quickstart if the documented output is wrong, recording why).
- Confirm `grep -r ruamel src/` hits only `yamlcore.py`.

## Risks & Mitigations

- Renderer bugs could corrupt files → R-17 verification turns them into exit 3; add a test that monkeypatches nothing but uses an unusual-but-legal layout and asserts either success-with-exact-bytes or exit 3 with unchanged files.
- Event/write ordering: events only after the write succeeded.
- Shared `SourceFile` included twice: edits grouped per object.

## Review Guidance

- Each "Where the change is written" and "How it is written" sentence maps to a named integration test.
- Every integration test compares the complete bytes of every theatre file.
- No write path bypasses verification.

## Activity Log

- 2026-10-02T06:01:37Z – system – Prompt created.
