---
work_package_id: WP01
title: 'Mapping-form includes: load and read'
dependencies: []
requirement_refs:
- FR-001
- FR-002
- FR-003
- FR-004
planning_base_branch: feat/troupe-config-include-overrides
merge_target_branch: feat/troupe-config-include-overrides
branch_strategy: Planning artifacts for this mission were generated on feat/troupe-config-include-overrides. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/troupe-config-include-overrides unless the human explicitly redirects the landing branch.
subtasks:
- T001
- T002
- T003
- T004
- T005
- T006
- T007
phase: Phase 1 - Foundations
history:
- at: '2026-10-05T17:30:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/troupe/merge.py
create_intent:
- src/troupe/merge.py
- tests/unit/test_merge.py
- tests/integration/test_loading_ref.py
- tests/integration/test_reads_overrides.py
execution_mode: code_change
owned_files:
- src/troupe/tree.py
- src/troupe/merge.py
- src/troupe/loader.py
- src/troupe/reconcile.py
- src/troupe/paths.py
- tests/unit/test_merge.py
- tests/integration/test_loading_ref.py
- tests/integration/test_reads_overrides.py
role: implementer
agent: claude
model: ''
tags: []
task_type: implement
tracker_refs: []
---

# Work Package Prompt: WP01 – Mapping-form includes: load and read

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter (`agent_profile`, `role`, `agent`), and behave according to its guidance before parsing the rest of this prompt.

If no profile is specified, run `spec-kitty agent profile list` and select the best match for this work package's `task_type` and `authoritative_surface`.

---

## ⚠️ IMPORTANT: Review Feedback

- **Has review feedback?**: Check the `review_ref` field in the event log (via `spec-kitty agent tasks status`) or the Activity Log below.
- **You must address all feedback** before your work is complete.

---

## Objective

Teach the loader the **mapping form** of an include (contract section *Overrides*, first bullet):

```yaml
coder:
  $ref: file:agents/coder.yaml
  temperature: 0.3        # override, deep-merged over the included content
```

and build a **merged view** that every existing reader understands without change. This WP changes no write behaviour (`set` placement is WP03/WP04). After this WP, `get`, `show`, `show --sources`, `history` leaves, reconcile and `watch` all work on configurations that use `$ref`.

## Context

Read first:
- `kitty-specs/troupe-config-include-overrides-01M46FY4/spec.md`: Intent Summary, D-1, D-7, US1, FR-001–FR-004, Edge Cases.
- `kitty-specs/troupe-config-include-overrides-01M46FY4/research.md`: **R-1, R-2** (the rules; follow them exactly).
- `kitty-specs/troupe-config-include-overrides-01M46FY4/data-model.md`: tree nodes and invariants.
- Existing code: `src/troupe/tree.py`, `src/troupe/loader.py` (`_Loader._convert`, `_include`), `src/troupe/paths.py` (`unwrap`, `walk`), `src/troupe/leaves.py` (`flatten`), `src/troupe/yamlout.py` (sources), `src/troupe/reconcile.py` (`watched_files`).

Key fact: `MergedMapping` **subclasses** `MappingNode`. Every reader that does `isinstance(x, MappingNode)` and iterates `entries` therefore reads the merged view. Each `ScalarNode` in the view keeps its own `Origin`, so `show --sources` names the including file for override scalars without any change to `yamlout.py`.

## Branch Strategy

- Planning/base branch: `feat/troupe-config-include-overrides`; final merge target: `feat/troupe-config-include-overrides` (merged into `main` after acceptance).
- Execution worktrees are allocated per computed lane from `lanes.json`; run `spec-kitty agent action implement WP01 --agent <name>`.

## Subtasks

### T001 — Tree nodes (`src/troupe/tree.py`)

1. Add `holder: "MappingNode | None" = None` as the **last** field of `YamlInclude` and of `TextInclude` (a default keeps every existing constructor call valid). Document: "the mapping that holds this include as `$ref` (mapping form); `None` for the scalar form".
2. Add:

```python
@dataclass(kw_only=True)
class MergedMapping(MappingNode):
    """A mapping-form include with overrides, or a mapping both sides of a merge define.

    ``entries`` is the merged view (see ``troupe.merge``). ``base`` and ``override`` are the two
    sides *as found* (a plain mapping, a ``YamlInclude`` or another ``MergedMapping``). ``ref`` is
    the ``$ref`` include at the top of a mapping-form include, else ``None``; ``override`` is then
    the holder mapping as written (its ``$ref`` entry is not in ``entries``).
    Never write through a merged view: writers resolve a concrete side (``writeback.placement``).
    """

    base: "Node"
    override: "Node"
    ref: "YamlInclude | None"
```

`kw_only=True` lets the subclass add required fields after the parent's; construct it with keywords only. No `type: ignore` anywhere.

3. `Node` union: `MergedMapping` is a `MappingNode`, so the union needs no change; say so in a comment.

### T002 — Merge rule (`src/troupe/merge.py`, new, pure)

The **one place** the merge rule lives (TROUPE-007).

```python
REF_KEY: Final = "$ref"

def deep_merge(base: Node, override: Node, *, ref: YamlInclude | None, origin: Origin, flow: bool) -> MergedMapping:
    """Merge ``override`` over ``base`` (both as found; both unwrap to mappings)."""
```

Rules (spec FR-002, R-2):
- `b = unwrap(base)`, `o = unwrap(override)`; both must be `MappingNode` (assert; the loader checks first).
- Entries: for each entry of `b` in order: if `o` has the key (excluding `$ref` when `o` is the holder): if `unwrap(b_value)` and `unwrap(o_value)` are both mappings → a `MappingEntry` with the **override entry's** key, key origin and key style and value `deep_merge(b_value, o_value, ref=None, origin=<o_value origin>, flow=<flow of unwrap(b_value)>)`; else the override entry as is. If `o` lacks the key → the base entry as is. Then every override entry whose key is not in `b`, in override order (skip `$ref`).
- Reuse `MappingEntry` objects; never copy nodes (identity is used by WP03).
- `MergedMapping.origin` = override side's origin (the holder span at the top); `flow` = `unwrap(base).flow` (the view's shape; R-1).
- Docstring: rules + "scalars and lists in the override replace" (contract) + key order (spec Assumptions).

### T003 — Loader (`src/troupe/loader.py`)

In `_convert`, when `raw` is a `RawMapping` that has a key whose text is `$ref` (any quoting style of the *key*; the key text as unescaped is `$ref`):

1. Let `raw_ref` be that key's value. If it is not a `RawScalar`, or its resolved value is not a `str` starting with `file:` → `LoadError(f"cannot load {file.path}: {dotted([*segments, '$ref'])} must be an include string ('file:...'), got {shown}")` (spec D-1; `shown` = the source text of the value, truncated sensibly). Note: a `$ref` key whose value is `file:` but plain-resolves to something else cannot happen (strings only) — but `$ref: 5` resolves to int → error.
2. Resolve the include with the existing `_include(...)` (same relative-path, missing-target, directory and cycle rules; segments as for the mapping itself). Set `holder` on the returned include node. Build the holder `MappingNode` from the raw mapping's entries with `_entries` **so the holder includes its `$ref` entry** (value = the include node). Note `_entries` would call `_convert` on the `$ref` value and recurse into `_include` again — avoid double loading: convert the `$ref` value once and reuse the node (refactor `_entries` to accept a pre-converted value, or build the holder entries explicitly).
3. **No sibling keys** → return the include node (with `holder` set). It behaves exactly like the scalar form (FR-001).
4. **Siblings** and a `TextInclude` → `LoadError(f"cannot load {file.path}: {dotted(segments)}: overrides need a YAML include, but {target} is not a .yml/.yaml file")` (contract: exit 4).
5. **Siblings** and a `YamlInclude` whose `unwrap(root)` is not a `MappingNode` → `LoadError(... f"{dotted(segments)}: cannot override keys of {target}: its content is a list/scalar, not a mapping")` (spec D-7). An **empty** target already loads as an empty `MappingNode` (step 1) and is accepted.
6. Otherwise return `deep_merge(include_node, holder, ref=include_node, origin=holder.origin, flow=unwrap(include_node.root).flow)`.
7. Update the module docstring's include rule: add the mapping form, the three new load errors, and "a `$ref` key is never data" (D-1).

Duplicate keys are already a load error; a mapping with two `$ref` keys is caught by that.

### T004 — Watched files (`src/troupe/reconcile.py`)

`watched_files` must still return *every file the load read*. In `_collect`, handle `MergedMapping` **before** the `MappingNode` branch: collect `node.origin.file`, then recurse into `node.base` and `node.override` (as found; this reaches the `ref` target and every include under either side, including base entries hidden by an override). Do **not** also iterate `entries` (they are a subset of both sides). Update the docstring.

`paths.py`: docstring only — note that `walk` reads merged views (a `MergedMapping` is a `MappingNode`) and that `unwrap` never needs to unwrap a `MergedMapping`.

### T005 — `tests/unit/test_merge.py`

Build trees with the real loader from files written via `make_theatre` (no hand-built nodes where a file can express it). Tests (names state what they prove):
- `test_override_scalar_replaces_included_scalar`
- `test_nested_mappings_merge_recursively_with_both_sides_kept`
- `test_override_list_replaces_included_list_entirely`
- `test_override_mapping_replaces_included_scalar_and_vice_versa`
- `test_merged_keys_are_included_order_then_override_only_keys`
- `test_ref_key_never_appears_in_merged_entries`
- `test_merged_entries_reuse_the_nodes_of_each_side` (identity: `merged.get("model").value is <node from included file tree>`)
- `test_override_scalar_origin_is_including_file_and_base_scalar_origin_is_included_file`

### T006 — `tests/integration/test_loading_ref.py` (real CLI)

Spec US1 scenarios 5 and 6, FR-003:
- `test_ref_alone_reads_like_scalar_form_yaml_include` (`get`/`show` output identical for `{$ref: file:x.yaml}` and `file:x.yaml`, in block and flow form)
- `test_ref_alone_of_text_file_is_its_text`
- `test_ref_with_siblings_on_text_target_exits_4_naming_file`
- `test_ref_value_not_an_include_string_exits_4_naming_file_and_path` (parametrize: `5`, `agents/coder.yaml`, `[a]`, `{x: 1}`, `null`, `"file"`)
- `test_overrides_on_list_or_scalar_content_exit_4_naming_target`
- `test_overrides_on_empty_target_are_accepted_as_empty_mapping` (D-7 correction)
- `test_missing_ref_target_exits_4` and `test_cycle_through_ref_exits_4`
- `test_quoted_ref_key_is_recognised` (`"$ref": file:x.yaml`)
Every exit-4 test asserts: exit 4, empty stdout, one stderr line starting `troupe: ` that contains the file path; and that no file in the theatre changed (`snapshot`).

### T007 — `tests/integration/test_reads_overrides.py` (real CLI)

Fixture from spec US1: `troupe.yml` = `coder:\n  $ref: file:agents/coder.yaml\n  temperature: 0.3\n  tools:\n    web: true\n`; `agents/coder.yaml` = `model: gpt\ntemperature: 0.7\ntools:\n  shell: true\nstop: [a, b]\n`.
- `test_get_returns_override_where_present_else_included_value` (US1-1)
- `test_show_prints_merged_mapping_without_ref` (US1-2, exact stdout)
- `test_show_of_overridden_list_prints_only_override_items` (US1-3)
- `test_show_sources_names_including_file_for_overrides` (US1-4, exact stdout)
- `test_first_command_imports_merged_leaves` (`history` lines' paths/values: `coder.temperature` 0.3 etc., no `$ref` path)
- `test_hand_edit_of_included_value_hidden_by_override_records_nothing` (edit `temperature` in coder.yaml; `get` reconciles; no new event)
- `test_hand_edit_of_override_records_one_set_event`
- `test_watch_follows_ref_target` (start `watch` with `WatchProcess`, edit `agents/coder.yaml` `model`, assert one `set` event within the window; reuse the helpers in `tests/conftest.py`)

## Definition of Done

- New/changed modules fully typed and documented, citing FR/D/R ids; no `type: ignore`.
- All existing tests pass unchanged (no existing test uses `$ref`).
- `uv run pytest`, `uv run mypy --strict`, `uv run ruff check`, `uv run ruff format --check` pass; paste output in the review handoff.

## Risks

- Double conversion of the `$ref` value (would load the target twice and confuse cycle detection) — convert once.
- A merged view's `origin` is the holder's: nothing in this WP may write through it.
- `flatten` relies on `MappingNode` iteration — verify with T007 that no `$ref` path is ever imported.

## Reviewer guidance

- Check D-1/D-7/non-YAML errors name the file and path (TROUPE-003), and that empty targets still work.
- Check `deep_merge` is the only place merge rules live and reuses nodes (identity test).
- Check `watched_files` includes base entries hidden by overrides and the `ref` target.

## Activity Log

- 2026-10-05T17:30:00Z – system – Prompt generated via /spec-kitty.tasks
