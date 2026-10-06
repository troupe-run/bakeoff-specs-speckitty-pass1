---
work_package_id: WP05
title: 'set with aliases: apply loop, verification, CLI'
dependencies:
- WP03
- WP04
requirement_refs:
- FR-003
- FR-004
- FR-005
- FR-008
- FR-009
planning_base_branch: fix/troupe-config-anchor-aliases
merge_target_branch: fix/troupe-config-anchor-aliases
branch_strategy: Planning artifacts for this mission were generated on fix/troupe-config-anchor-aliases. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into fix/troupe-config-anchor-aliases unless the human explicitly redirects the landing branch.
subtasks:
- T020
- T021
- T022
- T023
- T024
- T025
phase: Phase 4 - Wiring
history:
- at: '2026-10-06T15:00:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/troupe/writeback/apply.py
create_intent:
- tests/integration/test_set_aliases.py
- tests/integration/test_set_expand_alias.py
execution_mode: code_change
owned_files:
- src/troupe/writeback/apply.py
- src/troupe/writeback/collections.py
- src/troupe/cli.py
- src/troupe/commands/set_value.py
- tests/unit/test_collections.py
- tests/integration/test_set_aliases.py
- tests/integration/test_set_expand_alias.py
role: implementer
agent: claude
model: ''
tags: []
task_type: implement
tracker_refs:
- bakeoff-specs-speckitty-qht
---

# Work Package Prompt: WP05 – `set` with aliases: apply loop, verification, CLI

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter (`agent_profile`, `role`, `agent`), and behave according to its guidance before parsing the rest of this prompt.

If no profile is specified, run `spec-kitty agent profile list` and select the best match for this work package's `task_type` and `authoritative_surface`.

---

## ⚠️ IMPORTANT: Review Feedback

- **Has review feedback?**: Check the `review_ref` field in the event log (via `spec-kitty agent tasks status`) or the Activity Log below.
- **You must address all feedback** before your work is complete.

---

## Objective

Wire everything so `troupe config set` follows the contract end to end:
- set at the anchor changes it everywhere (US2);
- through an alias, exit 3 with `--expand-alias` in stderr (US3; this is the bug);
- `set --expand-alias PATH VALUE` expands and sets, matching the worked example byte-for-byte (US4).

The verifier must keep its promise: the value reads back and nothing else changed. A refused or failed `set` changes no file and records no event. History records one event per resolved leaf whose value changed (C11).

## Context

- Spec: US2, US3, US4, FR-003, FR-004, FR-005, FR-008, FR-009, C5, C10, C11, NFR-001–NFR-003, C-005.
- Research: **R-8** (apply loop and verification), **R-9** (anchors kept), **R-10** (CLI). Contract: `contracts/cli.md`.
- Current code: `writeback/apply.py` (`apply_set`, `_edits`, `_matches`, `_verify`, `_same_outside`, `_orders`, `_gains_override`); `writeback/collections.py` (`replace_value_edits`, `_anchor`, `_anchor_line_edits`, `detect_indent`); `cli.py` (`--in-include` pattern); `commands/set_value.py`.
- From WP03: `place(..., expand_alias=)` and `ExpandAlias(alias, parent, slot)`. From WP04: `aliases.expand_edits(file, alias, parent, slot, step, path=)`.

## Branch Strategy

- Planning/base branch: `fix/troupe-config-anchor-aliases`; final merge target: `fix/troupe-config-anchor-aliases`, merged into `main` locally after acceptance.
- Execution worktrees are allocated per computed lane from `lanes.json`; run `spec-kitty agent action implement WP05 --agent <name>` (depends on WP03 and WP04).

## Subtasks

### T020 — `apply_set(..., expand_alias=False)`: the expand loop

1. **No-op first** (R-8). Before placing, walk PATH. If it exists, `_matches(unwrap(node), value)` holds and `expand_alias` is set, return `WritePlan({}, None)`: nothing to write, nothing to expand. Without `expand_alias`, placement refuses first (WP03 ordering). Keep the existing no-op check for ordinary placements as is.
2. Loop:
   ```
   texts: dict[SourceFile, str] = {}
   current_root = root
   for _ in range(MAX_EXPANSIONS):  # 64; named constant with a comment
       placement = place(current_root, segments, dotted, in_include=..., expand_alias=...)
       if not isinstance(placement, ExpandAlias): break
       file = placement.alias.origin.file
       text = texts.get(file, file.text)   # careful: SourceFile objects differ per load
       edits = expand_edits(<SourceFile with text>, placement.alias, placement.parent, placement.slot, detect_indent(text), path=dotted)
       new_text = apply_edits(text, edits)
       texts[<original SourceFile for this path>] = new_text
       current_root = load(config_file, overrides={path: text for ...})   # LoadError -> _refuse
   else: raise WriteRefused(f"{dotted}: too many aliases to expand; no file changed")
   ```
   Key the accumulated texts by **path**, because each `load` creates new `SourceFile` objects. Map them back to the original `SourceFile` objects of `root` for `WritePlan.files`. `write_files` uses `file.path`, so either works as long as there is one entry per path.
3. After the loop, render the ordinary placement against `current_root`. Its `SourceFile.text` is the expanded text, because the in-memory load used the overrides. Splice it and record the final text for that path. Assert that only one path changed overall (anchors are per file, C-005).
4. Verify once against the **original** `root` with the final texts: `_verify(root, segments, dotted, files, reads_back, expand_alias=expand_alias)`.
5. Text includes (`ReplaceText`) are unaffected; aliases cannot point to includes (C3).

### T021 — `_same_outside`: alias identity, alias→copy, anchors kept

Implement R-8's three rules. `_same_outside(old, new, here, target, *, expand_alias)`:
1. **Alias unchanged.** If `old` is an `AliasNode`, then outside the route, or on the route without `expand_alias`, or when `old.merge` is set:
   - `new` must be an `AliasNode` with the same `name` and `merge`;
   - `_anchor_path(new) == _anchor_path(old)`, where `_anchor_path(a)` is `a.anchored.anchor.path` if `a.anchored` is not `None` and has an anchor, else `None`.

   **Do not descend**: the anchored node is compared at its own place. This is why setting `defaults.model` does not look like a change at `coder.settings.model`. For merge-derived aliases, also compare `old.written`'s anchor path when present.
2. **Alias becomes copy.** If `old` is a written `AliasNode`, the node is on the route (`here` is a strict prefix of `target`, or `here == target`), `expand_alias` is set and `new` is not an `AliasNode`, then compare `unwrap(old)` with `new` recursively, as if `old` were the anchored content. Ignore `anchor` on this comparison's top level, because the copy has none (C8). The content may differ only at PATH. Inner aliases fall under rule 1. When `here == target`, the reads-back check handles the target (whole replacement through an expanded alias).
3. **Anchors kept.** For scalar, mapping and sequence nodes outside `target`: `(old.anchor.name if old.anchor else None) == (new.anchor.name if new.anchor else None)`, except inside a copy made by rule 2, where the new side has no anchors (C8). Pass a flag `in_copy=True` down the recursion and skip anchor comparison there. At `target` itself, `reads_back` plus an anchor check: if the old node at PATH had an anchor, the new node must have the same anchor name (C5). Add that check in `_verify`, not in `_same_outside`'s early return.
4. `MergeKeyMapping`: compare as a mapping, view entries by key, so merged-in values follow rule 1. Additionally, `isinstance(new, MergeKeyMapping) == isinstance(old, MergeKeyMapping)`, because a merge mapping must stay one.
5. `_matches`: unwrap aliases when comparing (`_matches(unwrap(node), value)` at the top, and recursively for children).
6. Update the module docstring with the three rules and the expand loop.

### T022 — `collections.py`: anchors kept (R-9) and indentation with anchors

1. `detect_indent(text)`: call `yamlcore.compose(text, "<indentation>", allow_anchors=True)`. Today anchored files fall back to the default step, because WP01 keeps the default refusal; that would be wrong for 4-space files with anchors. `_first_step` must ignore `RawAlias` nodes (no step information).
2. `replace_value_edits` / `_anchor` (the key- or dash-line locator): when the replaced node `old` has `anchor` and the anchor token lies on the head line after the `:` or `-`, set `head_end = old.anchor.origin.end`. The new inline value or block follows the anchor: `defaults: &d` + newline + new block lines, or `defaults: &d {}` / `x: &m [a, b]` / `x: &m 5` inline. If the anchor is **not** on the head line, raise `WriteRefused`: `{path}: the anchor &{name} of this value is not on its key's line; replacing the value would move it; no file changed` (R-9).
3. Flow-context replacements (`_replace_in_flow`): the anchor precedes the value's span and is untouched, so verify only, with a unit test.
4. `_replace_compact_item` (list items `- &a {..}`): same rule as 2, with a unit test.
5. Unit tests in `tests/unit/test_collections.py`:
   - `test_kind_change_keeps_anchor_on_key_line` (scalar → mapping, mapping → scalar, block → flow);
   - `test_kind_change_refuses_anchor_on_its_own_line`;
   - `test_detect_indent_reads_files_with_anchors`.

### T023 — CLI flag

- `cli.py`: `set_.add_argument("--expand-alias", action="store_true", help="give an aliased value on PATH its own copy before setting it")`. Update the module docstring's command list and the "exists only on set" sentence (C10).
- `commands/set_value.py`: `expand_alias: bool = args.expand_alias`; pass it to `apply_set`. Docstring: expansion and set are one write and one verification; recording is unchanged (C11).

### T024 — Integration: US2 and US3 (`tests/integration/test_set_aliases.py`)

Real CLI, byte snapshots of every theatre file, history via the conftest helpers:
- `test_set_at_anchor_changes_it_for_every_alias` (US2-1): only line 2 changes; `get` through both aliases prints `sonnet`; history has exactly three `set` events for `defaults.model`, `coder.settings.model` and `reviewer.settings.model`, with one shared lineage (C11).
- `test_set_anchored_scalar_keeps_anchor` (US2-2): `model: &m sonnet`.
- `test_replacing_anchored_collection_keeps_anchor` (US2-3, C5).
- `test_new_key_under_anchor_appears_through_aliases` (US2-4).
- `test_set_through_alias_exits_3_mentions_expand_alias_and_changes_nothing` (US3-1, **the bug**): exit 3, empty stdout, stderr contains `coder.settings.model`, `*d` and `--expand-alias`; snapshot equal; no new events; `get reviewer.settings.model` and `get defaults.model` still print `opus`.
- `test_scalar_alias_path_is_refused` (US3-2), `test_new_key_below_alias_is_refused` (US3-3).
- `test_merged_value_is_refused_with_and_without_expand_alias` (US3-4; both messages).
- `test_new_key_beside_merge_key_is_written_and_merge_line_unchanged` (US3-5).
- `test_anchor_not_on_key_line_blocks_kind_change` (R-9).

### T025 — Integration: US4 (`tests/integration/test_set_expand_alias.py`)

- `test_worked_example_is_reproduced_byte_for_byte` (US4-1): file equals the contract's "after"; `reviewer` and `defaults` still `opus`; history has exactly one `set` event for `coder.settings.model`.
- `test_flow_anchor_is_expanded_in_block_style` (US4-2).
- `test_scalar_alias_is_expanded_in_place` (US4-3).
- `test_list_item_alias_is_expanded_under_its_dash` (US4-4).
- `test_nested_aliases_on_path_are_each_expanded_with_their_comment` (US4-5).
- `test_copy_drops_inner_anchor_and_comments` (US4-6).
- `test_expansion_refusals_change_nothing` (US4-7): flow parent, comment on the line, alias on the next line. Exit 3; files and history unchanged.
- `test_expand_alias_without_alias_on_path_equals_plain_set` (US4-8): compare the resulting bytes and events with a plain `set` on a twin theatre.
- `test_expand_alias_is_rejected_by_other_subcommands` (US4-9): `get`, `show`, `history`, `watch` → exit 2, empty stdout.
- `test_expand_alias_with_reason_records_lineage` (US4-10).
- `test_expand_alias_with_unchanged_value_writes_nothing` (R-8 no-op).

## Definition of Done

- The reporter's command `set coder.settings.model sonnet` exits 3 with `--expand-alias` in stderr and changes nothing. `set --expand-alias …` produces the worked example exactly.
- All tests above pass; the full suite passes unchanged otherwise; four gates pass with output pasted.
- Docstrings of `apply.py`, `collections.py`, `cli.py` and `set_value.py` cite C5, C10, C11 and R-8–R-10.

## Risks

- **Verifier false refusals** (exit 3 where a write is legitimate), for example a change at an anchor seen through aliases. Rule 1 must not descend; US2-1 proves it.
- **Verifier false acceptances.** An expansion that also changed another alias must be refused. Add a unit-level test that calls `_same_outside` with a hand-made bad text: expand two aliases while the path needs one. It must return `False`.
- **SourceFile identity across in-memory loads** (T020 step 2): key by path.

## Reviewer guidance

- Run the reporter's scenario yourself and paste the output.
- Check the history assertions count events exactly, and that every refusal test checks both the files and the history.

## Activity Log

- 2026-10-06T15:00:00Z – system – Prompt generated via /spec-kitty.tasks
