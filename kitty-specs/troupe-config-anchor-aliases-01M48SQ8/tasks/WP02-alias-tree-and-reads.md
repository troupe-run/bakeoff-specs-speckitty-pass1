---
work_package_id: WP02
title: Aliases and merge keys in the tree; reads resolve
dependencies:
- WP01
requirement_refs:
- FR-001
- FR-002
planning_base_branch: fix/troupe-config-anchor-aliases
merge_target_branch: fix/troupe-config-anchor-aliases
branch_strategy: Planning artifacts for this mission were generated on fix/troupe-config-anchor-aliases. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into fix/troupe-config-anchor-aliases unless the human explicitly redirects the landing branch.
subtasks:
- T005
- T006
- T007
- T008
- T009
- T010
phase: Phase 2 - Tree and reads
history:
- at: '2026-10-06T15:00:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/troupe/loader.py
create_intent:
- tests/unit/test_loader_aliases.py
- tests/integration/test_aliases_read.py
execution_mode: code_change
owned_files:
- src/troupe/tree.py
- src/troupe/loader.py
- src/troupe/merge.py
- src/troupe/paths.py
- src/troupe/leaves.py
- src/troupe/yamlout.py
- src/troupe/reconcile.py
- tests/unit/test_loader_aliases.py
- tests/integration/test_aliases_read.py
- tests/integration/test_set_overrides.py
role: implementer
agent: claude
model: ''
tags: []
task_type: implement
tracker_refs:
- bakeoff-specs-speckitty-qht
---

# Work Package Prompt: WP02 – Aliases and merge keys in the tree; reads resolve

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter (`agent_profile`, `role`, `agent`), and behave according to its guidance before parsing the rest of this prompt.

If no profile is specified, run `spec-kitty agent profile list` and select the best match for this work package's `task_type` and `authoritative_surface`.

---

## ⚠️ IMPORTANT: Review Feedback

- **Has review feedback?**: Check the `review_ref` field in the event log (via `spec-kitty agent tasks status`) or the Activity Log below.
- **You must address all feedback** before your work is complete.

---

## Objective

Make configurations with anchors, aliases and merge keys loadable. Every read then sees resolved values:
- `get`, `show`, `show --sources`;
- history leaves (`leaves.flatten`);
- reconcile (`reconcile.reconcile`, `watched_files`).

The reporter's file must load and print `opus` for `get coder.settings.model`. Anchor uses the spec forbids must exit 4, naming the file (C2, C3, C13, A-0 bad `<<` values). This is User Story 1.

Writes are **not** in scope (WP03–WP05). After this WP, a `set` through an alias must not be able to write: the existing verifier (`apply._same_outside`) has no `AliasNode` branch and refuses with exit 3. Confirm with one integration test (T010) that `set coder.settings.model sonnet` exits 3 and changes nothing, even before WP03 lands.

## Context

- Spec: US1, FR-001, FR-002, A-0, C1, C2, C3, C13; Domain Language; Key Entities.
- Research: **R-3** (AliasNode and the dispatch-site table), **R-4** (merge keys), **R-5** (load restrictions). Data model: "Tree nodes", "Load errors".
- Current code: `tree.py`, `loader.py` (`_Loader._convert`, `_mapping`, `_entries`, `_include`, cycle stack), `merge.py`, `paths.py` (`unwrap`, `walk`), `leaves.py`, `yamlout.py` (`_content`), `reconcile.py` (`watched_files`, `_collect`), `values.scalar_of` (already uses `unwrap`).
- WP01 delivers `yamlcore.compose(text, source, allow_anchors=True)`, `RawAnchor`, `RawAlias` and content-start spans.

## Branch Strategy

- Planning/base branch: `fix/troupe-config-anchor-aliases`; final merge target: `fix/troupe-config-anchor-aliases`, merged into `main` locally after acceptance.
- Execution worktrees are allocated per computed lane from `lanes.json`; run `spec-kitty agent action implement WP02 --agent <name>` (depends on WP01).

## Subtasks

### T005 — Tree types (`src/troupe/tree.py`)

1. `Anchor` (frozen dataclass): `name: str`, `origin: Origin` (the `&name` token), `path: tuple[str, ...]`, the merged path where the anchored node is loaded (used by the WP05 verifier).
2. Add `anchor: Anchor | None = None` to `ScalarNode`, `MappingNode` and `SequenceNode` as a keyword field with a default. `MergedMapping` is `kw_only`; check its construction still type-checks. `MappingNode` is a non-frozen dataclass whose `eq` compares fields; `anchor` joins the comparison, which is intended.
3. `AliasNode` (dataclass, `eq=False` like `SourceFile`, because identity matters):
   - `origin: Origin`: the `*name` token. For merge-derived nodes, the alias token inside the `<<` value, or the `<<` key's span for an inline `<<` mapping;
   - `name: str | None`: `None` only for an inline `<<` mapping;
   - `target: Node`: the anchored node itself for a written alias; the merged-in entry's value for a merge-derived one;
   - `anchored: Node | None`: the anchored node, `None` for inline `<<`;
   - `merge: bool = False`;
   - `written: "AliasNode | None" = None`: for merge-derived nodes, the written alias inside the `<<` value they come from, if any.

   Docstring: transparent to readers via `paths.unwrap`; never a concrete container; a written alias has `target is anchored`.
4. `MergeKeyMapping(MappingNode)` (`kw_only`, like `MergedMapping`): `written: MappingNode`, the concrete mapping as written, **including** its `<<` entry. `entries` is the view (T007); `origin` and `flow` are `written`'s.
5. Add `AliasNode` to the `Node` union. `MergeKeyMapping` needs no union member (it is a `MappingNode`).
6. Module docstring: describe both new types and the identity rules.

### T006 — Loader: aliases, anchors, C3 (`src/troupe/loader.py`)

1. Call `yamlcore.compose(file.text, str(file.path), allow_anchors=True)` in `_load_yaml`.
2. Keep a per-file registry `self._anchored: dict[int, Node]` keyed by `id(raw)`. Raw nodes live as long as the load, so ids are stable. Clear or scope it per `_load_yaml` call, because anchors are per file and per document.
3. In `_convert`, after building a node from a raw node with `raw.anchor`:
   - set `node.anchor = Anchor(raw.anchor.name, Origin(file, raw.anchor.start, raw.anchor.end), tuple(segments))`;
   - register it.

   For `RawAlias`: look up `id(raw.target)`; it must be present because anchors precede aliases, so assert it. Return `AliasNode(origin=Origin(file, raw.start, raw.end), name=raw.name, target=node, anchored=node)`.
4. **C3 refusals** (exit 4, `LoadError`), checked on raw nodes before conversion:
   - an anchored raw node that is an include string (scalar resolving to a `str` starting `file:`), a mapping with a `$ref` key, or contains either at any depth (walk the raw subtree; aliases inside are already-checked anchored nodes, so skip them): `cannot load {file}: anchor &{name} at line {n} is on an include reference (or a value containing one); anchors may not share includes`;
   - a mapping key with `anchor`, or a `RawAlias` key: `cannot load {file}: mapping key at line {n} under {dotted} has an anchor or is an alias`. Do this in `_entries` before the existing "is not a scalar" check, so the message is specific.
5. Includes inside included files: anchors are per file. The registry must not leak across `_load_yaml` calls, and an alias in file B can never refer to an anchor in A (WP01 already reports it as undefined).
6. Update the module docstring: the anchor rule, C3 and the registry.

### T007 — Merge keys (`src/troupe/merge.py`, `loader._mapping`)

1. `merge.py`: `MERGE_KEY: Final = "<<"` and `merge_keys(written: MappingNode, sources: list[tuple[AliasNode | None, MappingNode, Origin]]) -> MergeKeyMapping`, pure. Each source is `(written alias or None, the source mapping as found (unwrapped), origin for the derived AliasNode)`. Rules (A-0, R-4):
   - the view's entries are `written`'s entries in order, where the `<<` entry is replaced in place by the merged-in entries;
   - a merged-in key is skipped if any written key has that name, or if an earlier source already supplied it;
   - each merged-in entry is a new `MappingEntry` with the source entry's `key`, `key_origin` and `key_style`, and value `AliasNode(origin=<source origin>, name=<alias name or None>, target=<source entry value>, anchored=<the source's anchored node or None>, merge=True, written=<written alias or None>)`;
   - a source that is a `MergeKeyMapping` contributes its view entries. Wrapping an already merge-derived value again is fine.
2. Loader recognition: a pair whose key is a `RawScalar` with `text == "<<"` and `style == "plain"`. A quoted `'<<'` is an ordinary key, so add a test. Its value must be one of:
   - a `RawAlias` whose target converts to a mapping (after `unwrap`);
   - a `RawMapping`;
   - a `RawSequence` whose items are each one of those.

   Anything else → `cannot load {file}: {dotted}.<<: merge value must be a mapping, an alias of one, or a list of those (line {n})`.
3. `<<` beside `$ref` in one mapping → `cannot load {file}: {dotted}: a merge key '<<' cannot be combined with '$ref' (line {n})` (C13).
4. The concrete `written` mapping keeps the `<<` entry. Its value is converted normally: an `AliasNode`, a mapping, or a sequence of those. That way `placement._children` (WP03) can find written aliases inside `<<` values, and reconcile and verification see the written structure.
5. Duplicate-key rule: `<<` appears at most once (existing duplicate check). Merged-in keys never count as duplicates of written keys.

### T008 — Readers (`paths.py`, `leaves.py`, `yamlout.py`, `reconcile.py`)

Follow research R-3's dispatch table:
- `paths.unwrap`: loop while the node is a `YamlInclude` **or an `AliasNode`**; `YamlInclude` → `.root`, `AliasNode` → `.target`. Update the docstrings: `Walk.nodes` still holds nodes *as found*, so an `AliasNode` is visible to placement (WP03).
- `leaves._collect`: an `AliasNode` → `_collect(node.target, prefix, leaves)`. A `MergeKeyMapping` is a `MappingNode`, so its view entries give the resolved leaves (C1, C11).
- `yamlout._content`: `unwrap` already handles it; tighten the assert (not a `YamlInclude` and not an `AliasNode`). `show` output then has no `&`, `*` or `<<`. `_collection_lines` and `_value_lines` iterate entries and items and call `_content` or `unwrap` on children; verify every child path unwraps aliases, and add tests.
- `reconcile._collect` (`watched_files`): an `AliasNode` adds nothing and is not descended. For a `MergeKeyMapping`, walk `written` (concrete) rather than the view, so files are collected once.
- `values.scalar_of` uses `unwrap` already; add no code, only a test (T010).
- `show --sources` attributes a scalar to `node.origin.file`, which for aliased scalars is the anchored node's file (C1). No code change expected; test it.

### T009 — Unit tests (`tests/unit/test_loader_aliases.py`)

Load real files written to `tmp_path` (loader-level, no CLI):
- `test_alias_is_an_alias_node_sharing_the_anchored_node`: `coder.settings` and `reviewer.settings` are `AliasNode`s whose `target is` the node at `defaults`.
- `test_anchored_node_records_anchor_name_span_and_path`.
- `test_merge_key_view_lists_written_keys_and_merged_keys_at_the_merge_position`.
- `test_written_key_wins_over_merged_key`, `test_earlier_merge_source_wins` (`<<: [*a, *b]`).
- `test_merged_values_are_merge_derived_alias_nodes`: `merge=True`, `written` points at the alias inside `<<`.
- `test_merge_view_keeps_the_written_mapping_with_its_merge_entry`.
- `test_quoted_merge_key_is_an_ordinary_key`.
- `test_nested_merge_key_mapping_contributes_its_view`.
- Load errors (each `LoadError`, the message names the file and line): an anchored include string, an anchored `$ref` mapping, an anchored mapping containing an include, an anchored key, an alias key, `<<: 5`, `<<: [*a, 3]`, `<<` beside `$ref`, and a tag (message `tags are not supported`).
- `test_aliases_in_an_included_file_resolve_within_that_file`.

### T010 — Integration (`tests/integration/test_aliases_read.py`) and step-5 test updates

Through the real CLI (`make_theatre`, `run_cli`, `snapshot`), User Story 1:
1. `test_get_through_alias_prints_anchored_value` (US1-1).
2. `test_show_prints_resolved_values_without_anchor_alias_or_merge_syntax` (US1-1). Compare the full stdout.
3. `test_merge_key_reads_written_key_over_merged_key` (US1-2) and `test_earlier_merge_source_wins_on_read` (US1-3).
4. `test_show_sources_attributes_aliased_scalar_to_anchor_file` (US1-4).
5. `test_aliases_inside_included_file_resolve` (US1-5).
6. `test_unsupported_anchor_uses_make_every_command_exit_4`, parametrized over the US1-6 inputs and over `get`, `show`, `set`, `history`: exit 4, empty stdout, stderr names the file.
7. `test_history_import_records_resolved_alias_leaves`: on first use the import contains `coder.settings.model` and `reviewer.settings.model` (C1/C11 groundwork).
8. `test_set_through_alias_is_refused_and_changes_nothing`: exit 3, files and history unchanged. It holds already through the verifier; WP03 then makes the message mention `--expand-alias`, and WP05 tightens this test or adds its own.

Update `tests/integration/test_set_overrides.py::test_include_with_anchor_or_tag_is_not_converted`:
- exit code 4 stays;
- the message is now the C3 anchor-on-include message for `&a` and `tags are not supported` for `!t`;
- assert the right substring per parameter and keep the snapshot assertion.

Rename the section comment to cite spec C2/C3. Leave `test_converter_refuses_an_anchor_or_tag_before_the_include` untouched; it exercises the writer guard directly.

## Definition of Done

- Reporter's file loads; `get` and `show` print resolved values; every load error above exits 4 naming the file.
- All tests above pass; the full suite passes (the step-5 message test updated as described).
- Four gates pass (`uv run pytest`, `uv run mypy --strict`, `uv run ruff check`, `uv run ruff format --check`); output pasted.
- Docstrings of `tree.py`, `loader.py`, `merge.py`, `paths.py` cite A-0, C1, C2, C3 and C13 where implemented.

## Risks

- **Missed dispatch sites.** Run `grep -n "isinstance" src/troupe/*.py src/troupe/commands/*.py` and check each site against R-3's table. Writeback modules are WP03 and WP05; leave them, but list any you think need work in your handoff.
- **Identity.** The anchored node must be converted once and shared; `is` comparisons in placement and verification rely on it.
- **Exponential reads** (billion laughs) are accepted (plan Risks); do not add guards.

## Reviewer guidance

- Check `unwrap` handles `AliasNode`, and that no reader descends into `MergeKeyMapping.written` *and* its view (no double leaves).
- Check `reconcile.watched_files` covers included files reached only through merge views or aliases.
- Load-error messages name file and line.

## Activity Log

- 2026-10-06T15:00:00Z – system – Prompt generated via /spec-kitty.tasks
