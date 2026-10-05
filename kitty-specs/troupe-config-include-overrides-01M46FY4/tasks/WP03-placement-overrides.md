---
work_package_id: WP03
title: 'Placement: overrides, --in-include, refusals'
dependencies:
- WP01
requirement_refs:
- FR-005
- FR-007
- FR-008
- FR-009
- FR-010
- FR-012
planning_base_branch: feat/troupe-config-include-overrides
merge_target_branch: feat/troupe-config-include-overrides
branch_strategy: Planning artifacts for this mission were generated on feat/troupe-config-include-overrides. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/troupe-config-include-overrides unless the human explicitly redirects the landing branch.
subtasks:
- T013
- T014
- T015
- T016
- T017
phase: Phase 2 - Placement
history:
- at: '2026-10-05T17:30:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/troupe/writeback/placement.py
create_intent:
- tests/unit/test_placement_overrides.py
execution_mode: code_change
owned_files:
- src/troupe/writeback/placement.py
- tests/unit/test_placement_overrides.py
role: implementer
agent: claude
model: ''
tags: []
task_type: implement
tracker_refs: []
---

# Work Package Prompt: WP03 – Placement: overrides, `--in-include`, refusals

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter (`agent_profile`, `role`, `agent`), and behave according to its guidance before parsing the rest of this prompt.

If no profile is specified, run `spec-kitty agent profile list` and select the best match for this work package's `task_type` and `authoritative_surface`.

---

## ⚠️ IMPORTANT: Review Feedback

- **Has review feedback?**: Check the `review_ref` field in the event log (via `spec-kitty agent tasks status`) or the Activity Log below.
- **You must address all feedback** before your work is complete.

---

## Objective

`src/troupe/writeback/placement.py` is the **one place** that decides where a `set` writes (its docstring already says rule FR-011 "is expected to change at step 5"). Replace step-1 rule 2 with the contract's *Overrides* rule and add `--in-include` (*In-include*), returning only **concrete** collections:

```python
def place(root: Node, segments: list[str], dotted: str, *, in_include: bool = False) -> Placement: ...

@dataclass(frozen=True)
class ConvertInclude:
    """Convert the scalar-form ``include`` (in ``parent`` at ``slot``) to mapping form and add ``keys``."""
    include: YamlInclude
    parent: MappingNode | SequenceNode | None   # None: the include is the whole document
    slot: str | int | None
    keys: list[str]

Placement = ReplaceScalar | ReplaceText | ReplaceCollection | AddKeys | AppendItem | ConvertInclude
```

`apply.py` wiring and the CLI flag are WP04; this WP must leave `apply_set` working by keeping `place`'s default (`in_include=False`) callable as today. Until WP04 dispatches `ConvertInclude`, `apply._edits` raises on it — that is fine because no existing test reaches it; do **not** edit `apply.py` here.

## Context

- Spec: Intent Summary, D-6, D-8, D-10; FR-005, FR-007–FR-010, FR-012; US2, US3, US4 scenarios.
- Research **R-3, R-4** — the algorithm below is R-3 restated; follow it exactly.
- Data model invariants (concrete parents; nearest include reference).
- PO decision DM 01M46FYYFFXXZE893KWDP2WJCW: nested includes → the file holding the **nearest** include reference.
- WP01 types: `MergedMapping(base, override, ref)` (sides *as found*), `YamlInclude.holder`, `TextInclude.holder`.

## Branch Strategy

- Planning/base branch: `feat/troupe-config-include-overrides`; final merge target: `feat/troupe-config-include-overrides` (merged into `main` after acceptance).
- Execution worktrees are allocated per computed lane from `lanes.json`; run `spec-kitty agent action implement WP03 --agent <name>` (depends on WP01).

## Subtasks

### T013 — Concrete parents and refusals

1. `concrete_parent(root: Node, node: Node) -> tuple[MappingNode | SequenceNode, str | int] | None`: depth-first search over **concrete** containers by identity (`is`): for `MappingNode` (not merged) entries and `SequenceNode` items compare `entry.value is node`; descend into values; for `YamlInclude` descend into `root`; for `MergedMapping` descend into `base` and `override` (as found) and **not** its `entries`. Return `None` if `node` is the document root. Linear in tree size; fine.
2. `_existing` (PATH fully exists):
   - `YamlInclude` (either form) → `WriteRefused` (step-1 FR-013 message unchanged).
   - `MergedMapping` with `ref` → `WriteRefused(f"{dotted}: value comes from include {ref.target.path} with overrides; refusing to replace it (change a path inside it instead); no file changed")`.
   - `MergedMapping` without `ref` → `WriteRefused(f"{dotted}: this mapping is defined both by {base file} and by overrides in {override file}; replacing it as a whole is refused; no file changed")` (spec D-10).
   - `TextInclude` → `ReplaceText` (holder or not).
   - Scalars and one-sided collections: the parent **must** come from `concrete_parent(root, node)` (not `unwrap(nodes[-2])`, which may be a merged view whose origin is the wrong file). Context `"flow"` iff that concrete parent is flow.
3. D-6: at the very start of `place`, any segment equal to `$ref` → `WriteRefused(f"{dotted}: '$ref' is not a setting; it names an include (no file changed)")`.

### T014 — Nearest include reference and list rule

For a new key with deepest existing ancestor `D = unwrap(found.nodes[-1])` (a concrete `MappingNode`, depth `k = len(found.nodes) - 1`):

- `F = D.origin.file`.
- Candidate include references at depth `j` (0…k): peel `found.nodes[j]` — a `YamlInclude` chain (yield each link), and for a `MergedMapping` its `ref`, plus its `base` and `override` *as found* peeled the same way (recursively for nested merged sides). Keep those whose `target is F` (same `SourceFile` object — the loader shares one per path).
- R = the candidate with the largest `j` (nearest). If several at the same depth, the innermost of a chain.
- **List rule**: if any `unwrap(found.nodes[i])` for `j_R <= i < k` is a `SequenceNode` → no override; `AddKeys(D, keys)`.
- No R (F is the root file) → `AddKeys(D, keys)`.

Put this in `_include_ref(found, D) -> tuple[YamlInclude, int] | None` with a docstring quoting the contract sentence and the DM.

### T015 — Override targets

Given R at depth `j`, `route = segments[j:k]`, `keys` = the missing segments:

1. If R is the `ref` of a `MergedMapping` M at depth `j` (check this **first**; `ref.holder` is also set): descend `M.override` (the holder) along `route`: while the next route key exists in the current override mapping and its value is a plain `MappingNode` (or `_on_side` applies, see 3), go down. Then `AddKeys(<deepest override mapping>, <rest of route> + keys)`.
2. Else if `R.holder` is set (mapping form without siblings): `AddKeys(R.holder, route + keys)` — new keys go after the `$ref` entry.
3. Else (scalar form): `parent, slot = concrete_parent(root, R)` (or `None, None` at document root) → `ConvertInclude(R, parent, slot, route + keys)`.

When D itself is a `MergedMapping` (D-8): `_on_side(D.override, keys)`:
- plain `MappingNode` → `AddKeys(node, keys)`;
- `MergedMapping` → `_on_side(node.override, keys)`;
- `YamlInclude` with `holder` → `AddKeys(holder, keys)`;
- scalar-form `YamlInclude` (the override value was itself an include, e.g. `model: file:other.yaml` in the override) → `ConvertInclude(node, *concrete_parent(root, node), keys)`.

Missing digit-only segments and list-append rules are unchanged from step 1 (keep the existing checks before any of this).

### T016 — `--in-include`

`place(..., in_include=True)` changes only the new-key branch:
- D concrete → `AddKeys(D, keys)` (step-1 rule; for nested includes this is the innermost file).
- D merged → `_on_base(D.base, keys)`: plain mapping → `AddKeys`; `MergedMapping` → recurse into `.base`; `YamlInclude` (either form) → recurse into `unwrap(node)` handling a merged root the same way (spec D-8: innermost included file that defines it).
Existing values, list appends and refusals ignore `in_include` (D-9 / cancelled DM 01M46G22P50PEX048YGJ9TV5N8).

### T017 — Tests and docstring

`tests/unit/test_placement_overrides.py` — load real fixture theatres with `troupe.loader.load`, call `place`, assert placement type, the target node's file (`.origin.file.path` name) and `keys`. Names state what they prove:
- `test_new_key_under_scalar_form_include_converts_it` (ConvertInclude, parent = root mapping, slot `coder`, keys `["temperature"]`)
- `test_new_key_under_ref_only_include_adds_to_holder`
- `test_new_key_under_merged_include_adds_to_holder_after_existing_overrides`
- `test_new_nested_key_extends_existing_override_mapping` (US2-4 variant with override `limits:` present / absent)
- `test_nested_include_override_goes_to_nearest_including_file` (US2-5: target file `agents/coder.yaml`, `ConvertInclude` of `model`)
- `test_new_key_in_root_file_mapping_is_step1`
- `test_new_key_inside_list_item_of_included_file_stays_in_that_file`
- `test_new_key_under_list_item_include_converts_the_item` (D-4)
- `test_new_key_under_merged_mapping_with_include_override_converts_that_include`
- `test_in_include_new_key_goes_to_innermost_included_file` (scalar form, mapping form, nested)
- `test_in_include_without_include_equals_step1`
- `test_existing_overridden_scalar_replaced_in_override_file` / `..._not_overridden_in_included_file` (concrete parent file asserted)
- `test_append_to_included_list_targets_included_file`
- `test_ref_segment_is_refused` (D-6), `test_replacing_whole_include_is_refused_in_both_forms`, `test_replacing_partly_overridden_mapping_is_refused` (D-10) — assert `WriteRefused.exit_code == 3` and the message names PATH.

Rewrite the module docstring: contract rules (*Overrides*, *In-include*), the algorithm summary, and the agent choices it implements (D-6, D-8, D-10) with the DM id for nesting. Remove the "expected to change at step 5" note.

## Definition of Done

- `place` returns only concrete collections; a unit test asserts `not isinstance(<target>, MergedMapping)` for every placement in the suite (helper).
- Existing step-1..4 tests still pass, **except** the two that WP04 updates (new keys under scalar-form includes now return `ConvertInclude`, which `apply` cannot yet dispatch). If they fail in this WP, mark them `pytest.mark.xfail(reason="WP04: Overrides replaces rule 2", strict=True)` **in a one-line, out-of-map edit with rationale** — or leave them failing only if the lane policy requires a green suite; prefer `xfail(strict=True)` so WP04 must remove it.
- Four gates pass; output pasted.

## Risks

- Using `unwrap(nodes[-2])` as a parent anywhere — wrong file under merges. Search for it.
- Identity vs equality: compare `SourceFile` and nodes with `is`.

## Reviewer guidance

- Walk through the US2-5 nested example by hand against the code.
- Check that `in_include` cannot change existing-value behaviour.
- Check every refusal message names PATH (and the file where relevant).

## Activity Log

- 2026-10-05T17:30:00Z – system – Prompt generated via /spec-kitty.tasks
