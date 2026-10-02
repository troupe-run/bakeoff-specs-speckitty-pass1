---
work_package_id: WP02
title: Loading, includes and paths
dependencies:
- WP01
requirement_refs:
- C-004
- FR-003
- FR-007
- FR-008
planning_base_branch: feat/troupe-config-load-show-set
merge_target_branch: feat/troupe-config-load-show-set
branch_strategy: Planning artifacts for this mission were generated on feat/troupe-config-load-show-set. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/troupe-config-load-show-set unless the human explicitly redirects the landing branch.
subtasks:
- T006
- T007
- T008
- T009
- T010
phase: Phase 2 - Reading the configuration
history:
- at: '2026-10-02T06:01:37Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: "python-pedro"
authoritative_surface: src/troupe/loader.py
create_intent:
- src/troupe/tree.py
- src/troupe/yamlcore.py
- src/troupe/loader.py
- src/troupe/paths.py
- tests/integration/test_loading.py
- tests/unit/test_yamlcore.py
- tests/unit/test_paths.py
execution_mode: code_change
model: ''
owned_files:
- src/troupe/tree.py
- src/troupe/yamlcore.py
- src/troupe/loader.py
- src/troupe/paths.py
- tests/integration/test_loading.py
- tests/unit/test_yamlcore.py
- tests/unit/test_paths.py
role: "implementer"
agent: "claude"
tags: []
task_type: implement
tracker_refs: []
---

# Work Package Prompt: WP02 – Loading, includes and paths

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

Build the in-memory **SourceTree**: the merged configuration (root file + recursive includes) in
which **every node knows the file and exact character span its bytes came from**. Later WPs read
values from it (`show`, history) and splice edits into files using its spans (`set`).

Done when:
- `load(theatre.config_file)` returns a tree for valid theatres; invalid YAML, undecodable files, a
  missing include target, or an include cycle raise `LoadError` (exit 4) naming the file.
- Plain scalars resolve per **YAML 1.2 core schema exactly** (research R-13) — e.g. `yes`, `2001-12-14`, `1_000` are strings; `0.2` float; `0x1F` int; `~` null.
- `paths.walk/lookup` addresses nodes through YAML includes; errors raise `PathError` naming the path.
- Every origin's `start/end` slice of `file.text` reproduces the node's source text (tested).
- Gates pass.

## Context & Constraints

- Spec FR-003, FR-007, FR-008; research R-01, R-05, R-13, R-14; data-model.md "Source tree".
- Files on disk are the source of truth: the loader reads fresh every command, no caching across runs.
- **`yamlcore.py` is the only module allowed to import `ruamel`** (typing boundary + one place for the YAML-library decision, TROUPE-007). Everything else uses `tree.py` types.
- Out of contract: anchors/aliases/merge keys, multi-document files, keys containing `.`, digit-only mapping keys, tags. Don't build support; don't crash with tracebacks either — anything ruamel rejects becomes `LoadError`.

## Branch Strategy

- **Planning base branch**: `feat/troupe-config-load-show-set` · **Merge target**: `feat/troupe-config-load-show-set` (then merged into `main` locally at delivery).
- Worktree comes from the computed lane in `lanes.json`: `spec-kitty agent action implement WP02 --agent <name>`.

## Subtasks & Detailed Guidance

### Subtask T006 – SourceTree node types (`src/troupe/tree.py`)

```python
Scalar = str | int | float | bool | None
ScalarStyle = Literal["plain", "single", "double", "literal", "folded"]

@dataclass(eq=False)                 # identity semantics: one object per file on disk
class SourceFile:
    path: Path                       # absolute, resolved
    text: str                        # decoded UTF-8, original newlines, BOM kept as U+FEFF (R-14)

@dataclass(frozen=True)
class Origin:
    file: SourceFile
    start: int                       # code-point index into file.text (inclusive)
    end: int                         # exclusive

@dataclass
class ScalarNode:   origin: Origin; value: Scalar; style: ScalarStyle
@dataclass
class MappingEntry: key: str; key_origin: Origin; key_style: ScalarStyle; value: "Node"
@dataclass
class MappingNode:  origin: Origin; flow: bool; entries: list[MappingEntry]
@dataclass
class SequenceNode: origin: Origin; flow: bool; items: list["Node"]
@dataclass
class YamlInclude:  origin: Origin; target: SourceFile; root: "Node"   # origin = the `file:` string
@dataclass
class TextInclude:  origin: Origin; target: SourceFile                 # value = target.text

Node = ScalarNode | MappingNode | SequenceNode | YamlInclude | TextInclude
```
- Add `MappingNode.get(key) -> MappingEntry | None`.
- Keep this module dependency-free (stdlib only).

### Subtask T007 – `yamlcore` adapter and file reading (`yamlcore.py`, `loader.py`)

- **`yamlcore.py`** (only ruamel importer):
  - `compose(text: str, source: str) -> RawNode | None` using `YAML(typ="safe", pure=True)`; convert ruamel nodes into small typed dataclasses (`RawScalar(text, style, start, end)`, `RawMapping(pairs, flow, start, end)`, `RawSequence(items, flow, start, end)`) so ruamel types never leak. ruamel's `ScalarNode.value` is the already-unescaped text; `style` is `None` (plain), `"'"`, `'"'`, `"|"`, `">"`; collections have `flow_style` True/False; marks have `.index`.
  - Map any `ruamel.yaml.YAMLError` (and `ComposerError` for multi-docs, anchors) to `LoadError(f"cannot parse {source}: {problem} at line {n}")`.
  - `resolve_plain(text: str) -> Scalar` implementing the **YAML 1.2 core schema** regexes from research R-13 (null / bool / int incl. `0o`, `0x` / float incl. `.inf`, `.nan`); everything else `str`. Quoted and block scalars are always `str` (do not call `resolve_plain` for them).
  - Verified behaviour (ruamel 0.19.1) to rely on: marks are code-point indices into the input string; a leading BOM counts as index 0; CRLF counts as two characters.
- **Mark caveats** to verify with tests (store spans exactly as ruamel gives them, but know them):
  - Plain scalar `end` excludes trailing spaces and comments.
  - Quoted scalar spans include the quotes.
  - Block scalar (`|`, `>`) span starts at the indicator and ends **after** the content including trailing line breaks consumed by the scalar — WP06 re-parses the header from the text itself; record the raw span.
  - Block collection `end` may sit at the start of the next line or after trailing blank lines — WP07 computes collection ends from text itself, so do not "fix" spans here; just document.
- **`loader.py`**:
  - `read_source(path: Path) -> SourceFile`: `path.read_bytes().decode("utf-8")` (strict). `UnicodeDecodeError` → `LoadError` naming the file. **Never** use text-mode reading (it would translate CRLF).
  - Public entry point: `load(config_file: Path, overrides: Mapping[Path, str] | None = None) -> Node`. When a resolved path is in `overrides`, use that text instead of reading the disk. WP08 uses this to re-load the edited texts **in memory** and verify an edit before writing anything (research R-17). Test it.
  - Empty document (`compose` returns None) → an empty block `MappingNode` with origin `(0, 0)` (so new keys can be added later).
  - Convert raw nodes to `tree` nodes; mapping keys: `key = raw_key.text` (string as written, unescaped).

### Subtask T008 – Include resolution

- A **string** value (any style) beginning with `file:` is an include. Target = `(containing_file.parent / value[5:])`.
- `.yml`/`.yaml` suffix (case-sensitive per contract) → `YamlInclude`: read + compose the target, recurse, `root` = converted target root (empty file → empty mapping).
- Any other suffix → `TextInclude`; content = `read_source(target).text` (exact text, no newline translation).
- Missing target → `LoadError(f"include target not found: {target} (included from {containing_file}, at {dotted path})")`.
- Cycle → keep a stack of `Path.resolve()`d files currently being expanded; revisiting one → `LoadError` naming the cycle (`a.yaml -> b.yaml -> a.yaml`).
- Cache `SourceFile` objects by resolved path within one load, so the same file included twice shares one `SourceFile` (edits stay consistent).
- A text include of a directory or unreadable file → `LoadError`.

### Subtask T009 – Paths (`src/troupe/paths.py`)

```python
def parse_path(text: str) -> list[str]            # "a.b.0" → ["a","b","0"]; empty segment → UsageError naming the path
def is_index(segment: str) -> bool                # digits only

@dataclass
class Walk:
    nodes: list[Node]          # nodes[0] = root, nodes[i] = node reached after i segments (YamlInclude unwrapped)
    remaining: list[str]       # segments not yet consumed (empty when PATH fully exists)

def walk(root: Node, segments: list[str]) -> Walk
def lookup(root: Node, segments: list[str], dotted: str) -> Node   # PathError if remaining
```
- Rules: on `MappingNode` look up the key (as string, even if digits); on `SequenceNode` the segment must be an index — non-digits → `PathError("… is a list; expected an index")`; index ≥ len stops the walk (placement decides append vs exit 5). On a `ScalarNode`/`TextInclude` with segments left → `PathError(f"{dotted}: {prefix} is a scalar")`.
- `YamlInclude` is transparent: walking into it continues at its `root`. Record both the include and its root in a way WP08 can detect "the whole value at PATH comes from an include" — simplest: `Walk.nodes` holds the **un-unwrapped** node per step and callers use a helper `unwrap(node)`; document your choice in the docstring.

### Subtask T010 – Tests

- `tests/unit/test_yamlcore.py`: table-driven `resolve_plain` cases: `null`, `Null`, `~`, empty → None; `true/True/TRUE` → True; `yes`/`Yes`/`on` → str; `0`, `-12`, `+1`, `0o17`(15), `0x1F`(31) → int; `017` → 17 (core int); `1_000` → str; `0.2`, `.5`, `1.`, `1e3`, `-.inf`, `.nan` → float; `2001-12-14` → str. Spans: quoted spans include quotes; BOM file index offsets; CRLF file.
- `tests/integration/test_loading.py` (via the loader API on real temp files):
  - nested mappings/lists load with correct values and styles; for every scalar, `file.text[start:end]` equals its source text.
  - YAML include embeds (value lives in the included `SourceFile`); nested include relative to the **including** file's directory.
  - Text include returns exact text incl. CRLF and no trailing-newline change.
  - Missing target → `LoadError` mentioning the target path; 2-file and self cycle → `LoadError`.
  - Invalid YAML → `LoadError` naming the file.
- `tests/unit/test_paths.py`: parse, walk through include, index on list, non-digit on list, path through scalar, out-of-range index leaves `remaining`.
- Exit-code wiring via CLI is covered in WP04 (`show`) and WP03 (`history`).

## Risks & Mitigations

- **ruamel resolution drift** — never use ruamel's constructed values for plain scalars; use `resolve_plain`.
- **Spans for block scalars/collections are fuzzy at the end** — document; consumers re-derive ends from text.
- **Symlinked includes** — cycle detection on resolved paths handles them.

## Review Guidance

- `grep -r ruamel src/` must only hit `yamlcore.py`.
- Every origin slice test exists and passes.
- Error messages name files/paths.

## Activity Log

- 2026-10-02T06:01:37Z – system – Prompt created.
