---
work_package_id: WP03
title: 'Placement: reached through an alias'
dependencies:
- WP02
requirement_refs:
- FR-003
- FR-004
- FR-006
- FR-007
planning_base_branch: fix/troupe-config-anchor-aliases
merge_target_branch: fix/troupe-config-anchor-aliases
branch_strategy: Planning artifacts for this mission were generated on fix/troupe-config-anchor-aliases. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into fix/troupe-config-anchor-aliases unless the human explicitly redirects the landing branch.
subtasks:
- T011
- T012
- T013
- T014
- T015
phase: Phase 3 - Write rules
history:
- at: '2026-10-06T15:00:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/troupe/writeback/placement.py
create_intent:
- tests/unit/test_placement_aliases.py
execution_mode: code_change
owned_files:
- src/troupe/writeback/placement.py
- tests/unit/test_placement_aliases.py
role: implementer
agent: claude
model: ''
tags: []
task_type: implement
tracker_refs:
- bakeoff-specs-speckitty-qht
---

# Work Package Prompt: WP03 – Placement: reached through an alias

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter (`agent_profile`, `role`, `agent`), and behave according to its guidance before parsing the rest of this prompt.

If no profile is specified, run `spec-kitty agent profile list` and select the best match for this work package's `task_type` and `authoritative_surface`.

---

## ⚠️ IMPORTANT: Review Feedback

- **Has review feedback?**: Check the `review_ref` field in the event log (via `spec-kitty agent tasks status`) or the Activity Log below.
- **You must address all feedback** before your work is complete.

---

## Objective

`src/troupe/writeback/placement.py` is the one place that decides where a `set` goes (TROUPE-007). It now also decides the bug's rule, **"reached through an alias"**:

- a written alias on the route without `expand_alias` → `WriteRefused` (exit 3), the message naming PATH and the alias and mentioning `--expand-alias`;
- a written alias with `expand_alias` → a new placement `ExpandAlias(alias, parent, slot)`;
- reached through a merge key `<<` → `WriteRefused` always; with `expand_alias` the message says merge keys are never written;
- the anchored node reached directly → the ordinary step 1–5 placements (FR-003). So does a new key under a mapping holding `<<`, which is added to the written mapping (FR-007).

## Context

- Spec: US2, US3, FR-003, FR-004, FR-006 (merge part), FR-007, A-0, C4, C6; contract text in `contracts/cli.md` including message formats.
- Research: **R-6** (read fully), R-4 (merge-key view: writers only ever see `written`).
- Data model: `ExpandAlias`, "Write refusals".
- Current code: `place`, `_existing`, `concrete_parent`, `_children`, `_include_ref`, `_peel`, `_on_side`, `_on_base`, `_convert`, and the module docstring. `paths.walk` returns nodes **as found**, so `found.nodes[i]` is an `AliasNode` where the route passes an alias (WP02).
- WP02 types: `AliasNode(origin, name, target, anchored, merge, written)`, `MergeKeyMapping(written)`.

## Branch Strategy

- Planning/base branch: `fix/troupe-config-anchor-aliases`; final merge target: `fix/troupe-config-anchor-aliases`, merged into `main` locally after acceptance.
- Execution worktrees are allocated per computed lane from `lanes.json`; run `spec-kitty agent action implement WP03 --agent <name>` (depends on WP02).

## Subtasks

### T011 — Route scan and refusal messages

1. Signature: `place(root, segments, dotted, *, in_include=False, expand_alias=False)`.
2. After `found = walk(root, segments)`, and **before** any other decision except the D-6 `$ref` refusal (keep that first), scan `found.nodes[1:]` for the first `AliasNode`. The index gives the prefix: `prefix = ".".join(segments[:i])`. This covers:
   - PATH itself is an alias (`model: *m`, C4);
   - an alias above PATH (`coder.settings: *d`, US3-1);
   - the deepest existing ancestor of a new key is, or is below, an alias (C6, US3-3);
   - merge-derived values (`coder.model` via `<<`, US3-4).
3. Write a helper `_through_alias(root, alias, prefix, dotted, expand_alias) -> ExpandAlias` that raises in the refusal cases. Use the exact formats in `contracts/cli.md`:
   - written alias, no flag: `{dotted}: {prefix} is the alias *{name} in {file} line {n}, shared with its anchor &{name}; refusing to change it for every user (use --expand-alias to give this path its own copy); no file changed`. The line is computed from `alias.origin`.
   - merge-derived, no flag: `{dotted}: {prefix} comes through the merge key '<<' (from *{name}); refusing to change a shared value (use --expand-alias to give it its own copy); no file changed`. For an inline `<<` mapping, `(from an inline mapping)`.
   - merge-derived, with flag: `{dotted}: {prefix} comes through the merge key '<<' (from *{name}); merge keys are never written, so it cannot be expanded; no file changed`.
4. **Ordering with the no-op rule.** A `set` whose VALUE equals the current value is a no-op in step 1 (exit 0, nothing written), decided in `apply.py`. Through an alias, the spec says exit 3. Decide here: the alias refusal wins, so `set coder.settings.model opus` exits 3 even though the value is equal, because the user asked to change a shared path. With `--expand-alias` and an equal value, return `ExpandAlias`; WP05's apply checks the no-op first (research R-8 "No-op") and writes nothing. Document this ordering in the docstring.

### T012 — Write-side scan

New keys are sometimes written on a side that is not on `found.nodes`: the override or base side of a step-5 `MergedMapping` (`_on_side`, `_on_base`), or along `route` in a holder mapping. If that side is or passes an `AliasNode`, the write would land in the anchored node, so the same decision applies. Typical file: `coder: {$ref: file:x.yaml, settings: *d}` with `x.yaml` holding `settings: {model: gpt}`, then `set coder.settings.temperature 1`.
1. In `_on_side`: when the node met (or `entry.value` during descent) is an `AliasNode`, call `_through_alias` with the prefix of PATH the alias corresponds to. Pass the dotted prefix down as an argument. The result must be returned (an `ExpandAlias`) or raised.
2. In `_on_base`: same, for the base side under `--in-include`.
3. `_include_ref` / `_peel`: `_peel` should not descend into aliases (aliases are not include chains). An include can never be inside an anchored node (C3), so no include reference is reachable only through an alias; assert that in a comment and a test.

### T013 — `ExpandAlias` placement and its parent

1. Add `@dataclass(frozen=True) class ExpandAlias: alias: AliasNode; parent: Collection; slot: str | int`. The alias is always a **written** alias: for merge-derived nodes the code above has already raised. Add it to the `Placement` union and document it (data-model table).
2. `parent, slot = concrete_parent(root, alias)`. The written alias is a value in a concrete mapping or sequence, including the `written` mapping of a `MergeKeyMapping` and items of a `<<` sequence; those are merge-only and refused before reaching here, but `concrete_parent` must find them consistently. If `None`, raise `PathError`/assert as `_existing` does.
3. Flow-parent, comment and line-position refusals (C9) are **not** decided here; they belong to the text writer (WP04). Placement only decides *that* the alias is expanded.

### T014 — Concrete containers skip aliases; merge-key views resolve to `written`

1. `_children`:
   - `AliasNode` → yields nothing (never a container);
   - `MergeKeyMapping` → `yield from _children(node.written)` (concrete entries, including the `<<` entry; its value may be an `AliasNode`, a mapping or a sequence);
   - `MergedMapping` stays as is.

   Check the ordering of the `isinstance` checks, because `MergeKeyMapping` and `MergedMapping` are both `MappingNode` subclasses.
2. `_existing`: for a `MergeKeyMapping` found at PATH (replacing a whole mapping that holds `<<`), refuse with exit 3: `{dotted}: this mapping uses the merge key '<<'; replacing it as a whole would rewrite the merge key, which troupe never writes; no file changed`. This is the "merge keys are never written" rule (A-0, FR-007); add it to the module docstring.
3. New key whose deepest existing ancestor `D` is a `MergeKeyMapping`: `AddKeys(D.written, keys)`, so the key goes after the last written entry and the `<<` line is untouched (US3-5). If `D.written` holds an `AliasNode`-valued `<<` only, insertion still works because the `<<` entry is a written entry.
4. `ReplaceScalar` and `ReplaceCollection` for a written key inside a `MergeKeyMapping`: `concrete_parent` finds it in `written` (step 1), so nothing else changes.
5. A write at the anchored node itself (`defaults.model`, US2) finds the anchor's location through `concrete_parent`, because aliases are not descended. Add a test that the parent is the mapping under `defaults`, not reached via `coder`.

### T015 — Unit tests (`tests/unit/test_placement_aliases.py`) and docstring

Load real fixture files from `tmp_path` and call `place` directly:
- `test_set_at_anchor_places_in_the_anchored_mapping` (US2-1).
- `test_set_of_anchored_scalar_places_a_scalar_replacement` (US2-2).
- `test_new_key_under_anchored_mapping_is_added_there` (C6).
- `test_path_through_alias_is_refused_mentioning_expand_alias` (US3-1). Assert exit-3 type (`WriteRefused`), that the message starts with PATH, and that it contains `*d`, `--expand-alias` and the file path.
- `test_scalar_alias_at_path_is_refused` (C4).
- `test_new_key_below_alias_is_refused` (C6).
- `test_alias_refusal_wins_over_unchanged_value`.
- `test_merged_value_is_refused_with_and_without_expand_alias` (A-0; check both messages).
- `test_new_key_beside_merge_key_is_added_to_the_written_mapping` (US3-5).
- `test_replacing_a_mapping_with_a_merge_key_is_refused`.
- `test_expand_alias_returns_the_outermost_written_alias_with_its_parent_and_slot` (nested: `d` contains `limits: *l`; returns `*d` first).
- `test_alias_on_the_override_side_of_an_include_is_detected` (T012 fixture).
- `test_list_item_alias_is_expanded_with_its_sequence_parent` (`agents: [*d]` block list).

Update the module docstring: the rule, the refusal ordering (T011 step 4), the merge-key refusals and `ExpandAlias`.

**Run** the new tests, `tests/unit/test_placement_overrides.py` (must pass unchanged), then everything.

## Definition of Done

- All rules above implemented in `placement.py` only; every placement still carries concrete collections.
- New tests pass; the full suite passes; four gates pass with output pasted.
- `apply.py` is WP05's file. Until WP05 lands, `apply_set` may not handle `ExpandAlias`, which is fine because nothing passes `expand_alias=True` yet. Do **not** edit apply. If your tests need it, keep them at the placement level.

## Risks

- **Detecting too late.** The scan must happen before `_existing`, `AppendItem` and the new-key logic, or an alias at PATH could be treated as an ordinary node.
- **Over-refusing.** A route through a `MergedMapping` whose aliased side does not hold the next key is not through an alias. Base the decision only on nodes actually on the route plus the side actually written (T012).

## Reviewer guidance

- One decision function, used by the route scan and the write-side scan.
- Messages match `contracts/cli.md` exactly; tests assert the key parts.
- `_children` never descends into `AliasNode`.

## Activity Log

- 2026-10-06T15:00:00Z – system – Prompt generated via /spec-kitty.tasks
