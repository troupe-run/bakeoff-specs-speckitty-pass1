---
work_package_id: WP04
title: The include rule in one module
dependencies:
- WP01
- WP03
requirement_refs:
- FR-002
- FR-007
- FR-011
- FR-012
planning_base_branch: feat/troupe-config-remote-includes
merge_target_branch: feat/troupe-config-remote-includes
branch_strategy: Planning artifacts for this mission were generated on feat/troupe-config-remote-includes. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/troupe-config-remote-includes unless the human explicitly redirects the landing branch.
subtasks:
- T015
- T016
- T017
- T018
phase: Phase 2 - Loading
history:
- at: '2026-10-07T18:00:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/troupe/includes.py
create_intent:
- src/troupe/includes.py
- tests/unit/test_includes.py
execution_mode: code_change
model: ''
owned_files:
- src/troupe/includes.py
- tests/unit/test_includes.py
role: implementer
tags: []
task_type: implement
tracker_refs:
- bakeoff-specs-speckitty-1j5
---

# Work Package Prompt: WP04 – The include rule in one module

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter (`agent_profile`, `role`, `agent`), and behave according to its guidance before parsing the rest of this prompt.

If no profile is specified, run `spec-kitty agent profile list` and select the best match for this work package's `task_type` and `authoritative_surface`.

---

## ⚠️ IMPORTANT: Review Feedback

- **Has review feedback?**: Check the `review_ref` field in the event log (via `spec-kitty agent tasks status`) or the Activity Log below.
- **You must address all feedback** before your work is complete.

---

## Objective

Today the test "is this string an include?" is written three times in `loader.py`: in `_content`, in `_is_include_string` and in `_ref_include`. Step 7 changes the rule in four ways:
- remote strings are includes;
- `file:` inside remote content resolves against a URL (S-1);
- YAML or text depends on the URL **path** (S-2);
- some include-looking strings are literals (S-7, S-10).

`set` must also decide which VALUE strings it writes as `!literal` (S-11, S-12, S-13). This WP creates **`src/troupe/includes.py`**, the one place for all of these rules (TROUPE-007, research R-3, R-8). WP05 (loader) and WP09 (`set`) use it. This WP changes no existing module.

## Context

- Spec: S-1, S-2, S-3, S-7, S-10, S-11, S-12, S-13; FR-002, FR-007, FR-011, FR-012.
- Research: **R-3**, **R-8**; data model "Decision functions".
- From WP01: `troupe.location.Url`, `Location`. From WP03: `troupe.schema.Schema`, `Step`, `Schema.uri_at`.
- Existing code: `loader.INCLUDE_PREFIX`, `YAML_SUFFIXES`, `loader._include` (local resolution `including.parent / target_text`, with the target not yet resolved); `values.Value` (`Scalar | dict[str, Value] | list[Value]`); `paths.walk`/`unwrap`/`is_index`; `errors.WriteRefused`.

## Branch Strategy

- Planning/base branch: `feat/troupe-config-remote-includes`. Final merge target: `feat/troupe-config-remote-includes`, which is merged into `main` locally after acceptance.
- Run `spec-kitty agent action implement WP04 --agent <name>`. It depends on WP01 and WP03.

## Subtasks

### T015 — Kind, target and YAML-or-text

```python
FILE_PREFIX: Final = "file:"
REMOTE_PREFIXES: Final = ("https://", "http://")
YAML_SUFFIXES: Final = (".yml", ".yaml")

type IncludeKind = Literal["file", "remote"]

def include_kind(text: str) -> IncludeKind | None: ...
def resolve_target(text: str, containing: Location) -> Location: ...
def is_yaml_target(target: Location) -> bool: ...
```

- **`include_kind`**: a case-sensitive prefix test, exactly as `file:` is tested today. `HTTPS://x` is not an include; the contract says "starting `https://` or `http://`". `file:` → `"file"`; `https://`/`http://` → `"remote"`; anything else → `None`.
- **`resolve_target`** (requires `include_kind(text)` to be set; assert it):
  - remote string → `Url(text)`, exactly as written;
  - `file:` + `Path` containing → `containing.parent / rest`. This is not resolved: the loader keeps doing `.exists()`/`.resolve()` exactly as today;
  - `file:` + `Url` containing → `Url(urljoin(containing.text, rest))` (S-1). Examples, all to be tested:
    - `https://h/a/team.yaml` + `prompts/sys.md` → `https://h/a/prompts/sys.md`
    - `../x.yaml` → `https://h/x.yaml`
    - `/root.yaml` → `https://h/root.yaml`
    - `sys.md?v=1` → `https://h/a/sys.md?v=1`
  - Document that the result of `file:` inside remote content is **remote**, and so read-only (S-1, S-4).
  - Edge case: a `file:` reference whose urljoin result has a non-http(s) scheme (`file:file:///etc/passwd` gives `rest = "file:///etc/passwd"`, and urljoin returns `file:///etc/passwd`). Raise `LoadError(f"include {text!r} in {containing} does not resolve to an http(s) URL")`. Research A-3: remote content may never reach local disk. The loader adds context to this error.
- **`is_yaml_target`**:
  - `Path` → `target.suffix in YAML_SUFFIXES`, as today;
  - `Url` → `PurePosixPath(urlsplit(target.text).path).suffix in YAML_SUFFIXES`, so query and fragment are ignored. `https://h/team.yaml?v=2` is YAML; `https://h/team.yaml.txt` is text; `https://h/` is text.

  Case-sensitive, like local includes.

### T016 — `reads_as_include` and `path_steps`

```python
def reads_as_include(text: str, *, tagged: bool, uri: bool) -> bool:
    """Whether a string value is read as an include (spec S-7, S-10): it looks like one, is
    not tagged ``!literal`` and its schema does not mark it ``format: uri``."""

def path_steps(root: Node, segments: Sequence[str]) -> list[Step]: ...
```

- `reads_as_include` is deliberately tiny, but it is **the** rule. WP05's loader calls it for scalar-form strings. `$ref` values do not use it, because they are always includes (S-3); state that in the docstring.
- **`path_steps`**: the key/index kind of each PATH segment, for `Schema.uri_at` (WP03).
  - Walk with `paths.walk(root, list(segments))`. For each consumed segment, the container it was looked up in decides: an `unwrap`-ped `SequenceNode` gives `("index", int(segment))`, a mapping gives `("key", segment)`.
  - For the remaining (new) segments: if the deepest existing node is a sequence, the first remaining segment is an index (append); all others are keys. This mirrors `placement.place`, where a missing list index can only be the append index and new segments under a mapping are keys.
  - Use `walk`'s `nodes`/`remaining` the same way `placement.place` does (read it). Do not reimplement path parsing.
  - If walk raises `PathError`, let it propagate: `set` would fail the same way.

### T017 — `LiteralStr`, `IncludeStr` and `mark_literals`

```python
class LiteralStr(str):
    """A VALUE string that ``set`` writes tagged ``!literal`` (spec S-11, S-13; research R-8).
    Only ``mark_literals`` creates it; renderers write ``!literal `` before it."""

class IncludeStr(str):
    """A VALUE string that ``set --include`` writes untagged so that it is an include (S-12).
    Renderers treat it as a plain string; it exists so the no-op check can tell an include
    from a literal (research R-9)."""

def mark_literals(
    value: Value,
    steps: Sequence[Step],
    schema: Schema | None,
    *,
    include: bool,
    dotted: str,
) -> Value: ...
```

Rules, applied to **every** string in VALUE at its own resulting path (S-11). For a nested string, `steps + [("key", k)]` or `[("index", i)]`:
- `uri = schema is not None and schema.uri_at(path)`.
- Without `include`: a string with `include_kind(s) is not None and not uri` → `LiteralStr(s)`. Every other value is returned unchanged.
- With `include` (S-12):
  - if any include-looking string has `uri` true → `WriteRefused(f"{dotted}: schema {schema.path} marks {sub_dotted} as format uri, so it cannot be an include; no file changed")`. `sub_dotted` is PATH plus the nested keys, rendered like `loader.dotted`;
  - otherwise every include-looking string becomes an `IncludeStr(s)`: written untagged and read as an include.
- Result invariant, which WP08's no-op check and tag edits rely on: after `mark_literals`, a VALUE string is a `LiteralStr` (written tagged, reads as a literal), an `IncludeStr` (written untagged, reads as an include), or a plain `str` (not include-looking, or literal by the schema's `uri` mark).
- Mappings: build a new dict with the same key order. Lists: a new list. Never mutate the input.
- `LiteralStr` keeps `==` and `hash` of `str`, so verification and no-op comparisons with plain strings keep working. WP08 decides include-versus-literal comparisons explicitly.

Docstring: the S-13 example (`set b file:p.md` → `b: !literal file:p.md`), and that a local **text include** write (`_plan_text`) writes file text, never YAML. That WP08 rule converts a `LiteralStr` back to a plain `str`.

### T018 — Unit tests (`tests/unit/test_includes.py`)

Pure unit tests; build a small real tree with `loader.load` on `tmp_path` files for `path_steps`:
- `include_kind`: parametrised over `file:x`, `https://x`, `http://x`, `HTTPS://x` (None), `ftp://x` (None), `files:x` (None), `` (None), ` file:x` (None).
- `resolve_target`: local relative path; the URL cases above; `file:` with a non-http(s) result raises a `LoadError` naming the include.
- `is_yaml_target`: local `.yml`/`.yaml`/`.YAML` (text), URL with query, fragment, trailing slash and `.yaml.txt`.
- `reads_as_include`: the truth table over looks-like, tagged and uri.
- `path_steps`: a mapping → keys; through a list → an index step; append index; new keys under a mapping; a digit-named mapping key → a key step.
- `mark_literals`:
  - a plain URL string → `LiteralStr`, and `isinstance` is checked;
  - a non-include string → unchanged `str` (not `LiteralStr`);
  - `uri` at PATH → unchanged;
  - a nested dict/list with mixed strings → only the include-looking ones are marked, each judged at its own path (S-11 example: `{coder: {docs: https://x.example/y, n: 1}}`);
  - with `include` → include-looking strings become `IncludeStr`, others unchanged, and the input is not mutated;
  - `include` plus a `uri` path → `WriteRefused` (exit 3) with the contract message, naming the nested path;
  - `schema=None` → every include-looking string is marked.

## Definition of Done

- All four gates pass with output pasted.
- `includes.py` imports only `location`, `schema`, `paths`, `tree`, `values` and `errors` from troupe; check that `troupe.loader` does not import anything that imports it back.
- No other module is changed. WP05 and WP09 wire it in.

## Risks

- **Import cycles**: `includes` → `values` → `yamlcore`/`tree`, and later `loader` → `includes`. Mitigation: keep `includes` free of loader imports, and run `python -c "import troupe.loader"` in the tests.
- **urljoin surprises**: covered by explicit cases.

## Reviewer guidance

- One rule per function, with docstrings citing S-n.
- `mark_literals` is pure (no mutation) and refuses `--include` on `uri` paths.

## Activity Log

- 2026-10-07T18:00:00Z – system – Prompt generated via /spec-kitty.tasks
