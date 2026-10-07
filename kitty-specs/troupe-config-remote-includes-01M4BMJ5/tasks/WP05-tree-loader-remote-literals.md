---
work_package_id: WP05
title: 'Tree and loader: remote includes and literals'
dependencies:
- WP01
- WP02
- WP04
requirement_refs:
- FR-001
- FR-002
- FR-003
- FR-006
- FR-007
- FR-008
planning_base_branch: feat/troupe-config-remote-includes
merge_target_branch: feat/troupe-config-remote-includes
branch_strategy: Planning artifacts for this mission were generated on feat/troupe-config-remote-includes. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/troupe-config-remote-includes unless the human explicitly redirects the landing branch.
subtasks:
- T019
- T020
- T021
- T022
- T023
phase: Phase 2 - Loading
history:
- at: '2026-10-07T18:00:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/troupe/loader.py
create_intent:
- tests/unit/test_loader_remote.py
- tests/unit/test_loader_literals.py
execution_mode: code_change
model: ''
owned_files:
- src/troupe/tree.py
- src/troupe/loader.py
- src/troupe/reconcile.py
- src/troupe/yamlout.py
- src/troupe/writeback/fileio.py
- tests/unit/test_loader_remote.py
- tests/unit/test_loader_literals.py
- tests/unit/test_yamlout.py
- tests/unit/test_reconcile.py
- tests/unit/test_fileio.py
role: implementer
tags: []
task_type: implement
tracker_refs:
- bakeoff-specs-speckitty-1j5
---

# Work Package Prompt: WP05 – Tree and loader: remote includes and literals

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter (`agent_profile`, `role`, `agent`), and behave according to its guidance before parsing the rest of this prompt.

If no profile is specified, run `spec-kitty agent profile list` and select the best match for this work package's `task_type` and `authoritative_surface`.

---

## ⚠️ IMPORTANT: Review Feedback

- **Has review feedback?**: Check the `review_ref` field in the event log (via `spec-kitty agent tasks status`) or the Activity Log below.
- **You must address all feedback** before your work is complete.

---

## Objective

Make the loader read remote includes and literal strings.

1. **Tree** (R-1, R-5):
   - `SourceFile.path` keeps its name but becomes `Location` (`Path | Url`); add the property `SourceFile.remote`.
   - `ScalarNode` gains `literal: Origin | None = None`, the span of the `!literal` tag.
   - Type fallout in `fileio`, `yamlout` and `reconcile` is handled here, because those modules are about where a source lives.
2. **Loader** (R-3, S-1, S-2, S-3):
   - every include string goes through `troupe.includes`;
   - remote targets are fetched through `remote.fetch`, at most once per URL, with a caller-supplied `fetched` cache that every reload in the same command reuses (R-10);
   - URL cycles exit 4;
   - fetch failures name the URL, the including location and the path.
3. **Literals** (S-7, S-10):
   - a `!literal`-tagged scalar, and an include-looking string whose schema marks it `format: uri`, are plain string `ScalarNode`s;
   - the C3 anchor check and the `$ref` rules follow the same decision.

`configuration.load_configuration` (validation, sessions) is WP06. `set` is WP08/WP09. After this WP, `load(...)` without a schema behaves as before for every existing fixture: the whole existing suite stays green.

## Context

- Spec: S-1, S-2, S-3, S-6 (sources, watched files), S-7, S-10; FR-001, FR-002, FR-003, FR-006, FR-007, FR-008. Contract messages in `contracts/cli.md`.
- Research: **R-1**, **R-3**, **R-5**, **R-10** (`fetched`), **R-11**.
- Inputs from earlier WPs:
  - WP01: `location.Url`/`Location`, `remote.fetch`, `errors.FetchError(url, reason)` with `.url`/`.reason`, test fixture `remote`.
  - WP02: `RawScalar.tag: RawTag | None` (content-start spans), the `!literal` rules in file mode.
  - WP04: `includes.include_kind`, `resolve_target`, `is_yaml_target`, `reads_as_include`; `schema.Step`.
  - WP03: `schema.Schema` (for the type of the `schema=` argument).
- Current loader code (read it whole first): `load`, `_Loader._source`, `_load_yaml` (cycle stack), `_convert`, `_content`, `_mapping`, `_merge_mapping`, `_ref_include` (D-1), `_entries`, `_include`, `_is_include_string`, `_holds_include` (C3).

## Branch Strategy

- Planning/base branch: `feat/troupe-config-remote-includes`. Final merge target: `feat/troupe-config-remote-includes`, which is merged into `main` locally after acceptance.
- Run `spec-kitty agent action implement WP05 --agent <name>`. It depends on WP01, WP02 and WP04.

## Subtasks

### T019 — Tree retype and the read-side modules

1. **`tree.py`**:
   - `SourceFile.path: Location` (import from `troupe.location`). Update its docstring: an absolute resolved `Path` for files on disk, or a `Url` for remote content, which is never written.
   - Add `@property remote -> bool`.
   - `ScalarNode.literal: Origin | None = None`, documented as the `!literal` tag span, which writers keep or drop (R-8; WP07/WP08).
2. Run `uv run mypy --strict` and fix every error **in owned files**:
   - **`writeback/fileio.py`**: `write_files` checks **all** sources **before writing any**. If any `source.path` is not a `Path`, raise `WriteRefused(f"cannot write {source.path}: it is remote content, which troupe never changes; no file changed")`. This is the last safety net (R-7); WP08's refusals mean it should never fire. `atomic_write` keeps taking a `Path`.
   - **`yamlout.py`**: `Line.source: Location | None`. `source_label(path: Location, theatre_dir: Path)` returns `path.text` for a `Url` (S-6: the resolved URL verbatim), otherwise the existing relative path. The callers at about lines 176–178 need no change beyond types.
   - **`reconcile.py`**: `watched_files` skips any `SourceFile` whose `remote` is true, both as `origin.file` and as an include `target`, so the result stays `dict[Path, bytes]`. Docstring: remote content is not watched (S-6); it is re-read on the next reconcile.
3. **Type-only fallout outside owned files.** The `dict[Path, str]` override maps and `config_file = root.origin.file.path` in `writeback/apply.py` (about lines 233, 249, 497–498 and 742) are owned by WP08. Make the **minimal annotation-only** edit there so mypy passes: `dict[Location, str]`, `_ref_path -> Location | None`, and for `config_file` an `assert isinstance(config_file, Path)` with the comment "the root file is always local". Record it in the Activity Log as an out-of-map, type-only edit forced by R-1. Change no behaviour there.

### T020 — Loader: include resolution, remote targets, the fetch cache, cycles

1. Signature:

   ```python
   def load(
       config_file: Path,
       overrides: Mapping[Location, str] | None = None,
       *,
       schema: Schema | None = None,
       fetched: dict[Url, str] | None = None,
   ) -> Node:
   ```

   `fetched` is **filled** by this load: each remote text fetched is stored under its `Url`. Callers in one command pass the same dict to every reload so nothing is fetched twice (R-10). A missing `fetched` means a fresh dict for this call. `overrides` keyed by a `Url` replaces that remote text in memory, symmetrical with paths. Document both.
2. `_Loader._files: dict[Location, SourceFile]` and `_stack: list[Location]`. `_source(location)`:
   - `Path` → as today (resolve, override, `read_source`);
   - `Url` → the override if present, else `fetched[url]` if present, else `remote.fetch(url)` stored in `fetched`. One `SourceFile` per location per load (identity matters to `placement._include_ref`).
3. `_include(text, origin, steps)`, which replaces `target_text`:
   - `target = includes.resolve_target(text, origin.file.path)`. A `LoadError` from it, a non-http(s) URL join (A-3), propagates with its message.
   - `Path` target: the existing missing-target and directory checks and messages, unchanged.
   - `Url` target: call `_source` inside `try`. On `FetchError as err`, raise `LoadError(f"cannot fetch {err.url} (included from {origin.file.path}, at {dotted}): {err.reason}")`, which is the contract message. Construct it as a `FetchError` subclass instance or plain `LoadError`; either way it exits 4.
   - `includes.is_yaml_target(target)` → `YamlInclude` with `_load_yaml`; otherwise `TextInclude`.
4. Cycles: `_load_yaml` compares `Location`s. The message joins `str(location)` with ` -> `, unchanged in shape.
5. Replace `INCLUDE_PREFIX` uses with `includes.include_kind`. Delete the module's own `INCLUDE_PREFIX`/`YAML_SUFFIXES` if nothing else imports them (grep `tests/` too, and update imports in tests only if they are in owned files; otherwise keep re-exported aliases).
6. Update the module docstring's "Include rule" paragraph: it now points to `troupe.includes` and summarises S-1, S-2 and the fetch cache.

### T021 — Loader: literals, path-aware C3, `$ref` rules

1. **Steps instead of segments.** The loader currently threads `segments: list[str]`. Thread `steps: list[Step]` instead, with `("key", k)` from `_entries` and `("index", i)` from sequences. Derive the dotted text for messages with a helper (`dotted(_segments(steps))`); keep `dotted()` public for its existing callers. Merge-key sources and included roots keep the steps of their mount point, as segments do today. Anchored nodes are converted once, at the steps where they are **written**, which is exactly S-7's "for an aliased string, the path of the anchored node".
2. `_content` for a `RawScalar`:
   - `raw.tag is not None` → `ScalarNode(origin, value=raw.text, style=raw.style, literal=Origin(file, raw.tag.start, raw.tag.end))`. The value is always a `str`, never resolved, so `!literal 5` is `'5'` and an empty tagged value is `''` (S-10).
   - Otherwise resolve the value as today. If it is a `str` and `includes.reads_as_include(value, tagged=False, uri=self._uri(steps))` → `self._include(value, origin, steps)`. Otherwise a `ScalarNode`.
   - `_uri(steps)` is `self._schema is not None and self._schema.uri_at(steps)`.
3. **C3, path-aware.** `_holds_include(raw, steps)` and `_is_include_string(raw, steps)` use the same decision: a tagged scalar is never an include, and a `uri` path is never an include. Pass steps while descending a raw node: keys of mappings, indexes of sequences. A `$ref` key in a mapping still counts as an include reference. So `u: &u https://x` with `u` marked `format: uri` is an anchored literal, which is allowed. Without the schema mark it is an anchored remote include reference → exit 4, with the existing message.
4. **`$ref` (S-3)** in `_ref_include`:
   - a tagged raw scalar → `LoadError(f"cannot load {file.path}: {dotted(..$ref)} must be an include string, not !literal (line {n})")`;
   - otherwise the value must have `include_kind` set (`file:`, `https://` or `http://`), regardless of the schema: a `$ref` is always an include.
   - D-1 message: change the parenthetical to `('file:...', 'https://...' or 'http://...')`. The existing test asserts only the `got …` suffix.
5. **Other tags** are refused by `yamlcore` (WP02). Nothing to do here.

### T022 — Unit tests `tests/unit/test_loader_remote.py`

Use the `remote` fixture and `loader.load` directly, with `monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")`:
- `test_remote_yaml_include_embeds_its_content` (scalar form)
- `test_remote_text_include_is_its_body_exactly`, plus `..._with_query_is_text_or_yaml_by_url_path`: `/t.yaml?v=1` is YAML; `/t.md?x.yaml` is text
- `test_ref_form_with_remote_include_and_overrides_merges` (S-3)
- `test_file_include_inside_remote_content_resolves_against_the_url` (S-1): assert the request log contains `/a/prompts/sys.md`
- `test_nested_remote_include_from_remote_content`
- `test_url_cycle_is_refused_naming_the_urls` (a.yaml includes b.yaml, which includes a.yaml)
- `test_same_url_included_twice_is_fetched_once_per_load` (request log count)
- `test_fetched_cache_is_reused_across_loads` (two `load` calls with one dict → one request)
- `test_failed_fetch_names_url_including_file_and_path` (404; the message equals the contract shape)
- `test_file_include_in_remote_content_that_escapes_to_another_scheme_is_refused` (A-3)
- `test_remote_source_files_are_remote_and_local_ones_are_not`
- `test_anchor_on_a_remote_include_reference_is_refused` (C3 still applies)
- `test_remote_content_may_use_anchors_and_aliases_internally`

### T023 — Unit tests `tests/unit/test_loader_literals.py` and read-side cases

- `!literal` on `file:`, `https://` and `http://` strings → a `ScalarNode` with a `str` value; nothing is fetched (request log empty); `literal` covers exactly `!literal `.
- `!literal 5` → `'5'`; `!literal` with an empty value → `''`; `!literal` on a block scalar → its text.
- A schema `format: uri` via `properties`, `additionalProperties` and `items` → a literal, nothing fetched. The same string without the mark → an include. Build the `Schema` with WP03's `load_schema` from a real file.
- A digit-named mapping key under `properties` is looked up as a key, not as an index.
- An anchored literal is allowed; an alias to it is literal at every alias (S-7 edge case).
- `$ref: !literal file:x` → exit-4 message; a D-1 refusal names the new parenthetical.
- `yamlout.source_label` returns a URL verbatim, and `show --sources`-style rendering of a remote scalar ends `# from <url>` (in `tests/unit/test_yamlout.py`).
- `reconcile.watched_files` excludes remote files (in `tests/unit/test_reconcile.py`).
- `fileio.write_files` with one remote and one local source refuses before writing either (in `tests/unit/test_fileio.py`); the local file is unchanged.

## Definition of Done

- The existing suite passes unchanged; the new tests pass; all four gates pass, with output pasted.
- The only out-of-map edit is the annotation-only change in `writeback/apply.py`, recorded.
- `loader.py` contains no prefix tests of its own; every include decision goes through `includes`.

## Risks

- **The `segments` → `steps` refactor** touches every loader method. Mitigation: do it first as a pure refactor and run the suite, then add behaviour.
- **SourceFile identity** across reloads: `_files` is per load, while `fetched` (texts) is shared. Mitigation: the placement tests in the existing suite cover identity.
- **The proxy environment** in unit tests. Mitigation: `monkeypatch.setenv`.

## Reviewer guidance

- One include rule (`includes`), one network call site (`remote.fetch` via `_source`), one cache (`fetched`).
- Every literal decision uses `reads_as_include`.
- The `fileio` safety net checks before writing anything.

## Activity Log

- 2026-10-07T18:00:00Z – system – Prompt generated via /spec-kitty.tasks
