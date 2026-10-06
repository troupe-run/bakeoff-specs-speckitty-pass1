# Tasks: troupe configuration: anchors and aliases stay honest

**Mission**: `troupe-config-anchor-aliases-01M48SQ8` · **Spec**: [spec.md](spec.md) · **Plan**: [plan.md](plan.md) · **Research**: [research.md](research.md) · **Data model**: [data-model.md](data-model.md) · **Contract**: [contracts/cli.md](contracts/cli.md) · **Quickstart**: [quickstart.md](quickstart.md)
**Planning/merge branch**: `fix/troupe-config-anchor-aliases` (delivered to `main` by local merge after acceptance)
**Bug**: `bakeoff-specs-speckitty-qht`

Rules for every WP:
- Tests (TROUPE-005): every WP ships tests for every behaviour it adds or changes, against real files, the real CLI and the real event store.
- Gates (TROUPE-006): each WP must pass `uv run pytest`, `uv run mypy --strict`, `uv run ruff check` and `uv run ruff format --check` before review. No WP may leave the suite red.
- IDs: A-0 and C1–C14 are the out-of-contract choices in spec.md; R-n ids are research decisions.

## Subtask Index

| ID | Description | WP | Parallel |
|----|-------------|----|----------|
| T001 | `yamlcore`: event-based composer, `RawAnchor`, `RawAlias`, `allow_anchors` switch | WP01 | |
| T002 | `yamlcore`: content-start spans for anchored nodes (R-2) | WP01 | |
| T003 | `yamlcore`: refusals (tags, undefined/recursive alias, multiple documents), legacy refusal when `allow_anchors=False` | WP01 | |
| T004 | Unit tests: composer spans/refusals (`test_yamlcore.py`), VALUE refusal C14 (`test_values.py`) | WP01 | |
| T005 | `tree.py`: `Anchor`, `anchor` field, `AliasNode`, `MergeKeyMapping` | WP02 | |
| T006 | `loader.py`: alias conversion with shared anchored nodes, anchor paths, C3 refusals | WP02 | |
| T007 | `merge.py` + `loader.py`: merge keys (`<<`) view, precedence, bad values, C13 | WP02 | |
| T008 | Readers: `paths.unwrap`, `leaves`, `yamlout`, `reconcile` through aliases | WP02 | |
| T009 | Unit tests `tests/unit/test_loader_aliases.py` | WP02 | |
| T010 | Integration `tests/integration/test_aliases_read.py` (US1) + step-5 anchor/tag message updates | WP02 | |
| T011 | `placement`: route scan for the first alias; refusal messages | WP03 | |
| T012 | `placement`: write-side scan (`_on_side`, `_on_base`, holder routes) | WP03 | |
| T013 | `placement`: `ExpandAlias` placement and merge-key refusals (A-0) | WP03 | |
| T014 | `placement`: concrete containers skip aliases; merge-key views resolve to `written` | WP03 | |
| T015 | Unit tests `tests/unit/test_placement_aliases.py` + module docstring | WP03 | |
| T016 | `writeback/aliases.py`: C9 refusals | WP04 | [P] |
| T017 | `writeback/aliases.py`: copy rendering (C8) for mappings, sequences, scalars | WP04 | [P] |
| T018 | `writeback/aliases.py`: key-line and dash-line edits with the troupe comment; inner aliases | WP04 | |
| T019 | Unit tests `tests/unit/test_alias_expansion.py` | WP04 | |
| T020 | `apply.py`: `expand_alias` parameter, expand → reload → place loop, no-op first | WP05 | |
| T021 | `apply._same_outside`: alias identity, alias→copy allowance, anchors kept | WP05 | |
| T022 | `collections.py`: anchors kept on kind-changing replacement (R-9, C5); `detect_indent` with anchors | WP05 | |
| T023 | `cli.py` `set --expand-alias`; `commands/set_value.py` passes it | WP05 | |
| T024 | Integration `tests/integration/test_set_aliases.py` (US2, US3) | WP05 | |
| T025 | Integration `tests/integration/test_set_expand_alias.py` (US4) | WP05 | |
| T026 | Acceptance: history, lineage, reconcile and `watch` with aliases (C11) | WP06 | [P] |
| T027 | Acceptance: edge cases (redefined anchors, aliases in includes, `--in-include` combination, merge new key) | WP06 | [P] |
| T028 | Quickstart walk-through, spec/contract/code agreement, docstrings | WP06 | |
| T029 | Full gates, bug evidence, follow-up beads | WP06 | |

## Phase 1 — Parsing

### WP01 — Event-based composer

- **Prompt**: [tasks/WP01-event-composer.md](tasks/WP01-event-composer.md)
- **Goal**: `yamlcore.compose` builds raw nodes from parser events, recording anchors and alias occurrences with their spans. Anchored nodes start at their content. Tags, undefined and recursive aliases, and multiple documents are refused. With `allow_anchors=False`, the default, it still refuses anchors and aliases exactly as today, so nothing downstream changes yet.
- **Priority**: P1 (foundation)
- **Independent test**: unit tests on spans and refusals; the whole existing suite passes unchanged.
- **Subtasks**:
  - T001 event composer (WP01)
  - T002 content-start spans (WP01)
  - T003 refusals and legacy switch (WP01)
  - T004 unit tests (WP01)
- **Dependencies**: none
- **Estimated prompt size**: ~260 lines

## Phase 2 — Tree and reads

### WP02 — Aliases and merge keys in the tree; reads resolve

- **Prompt**: [tasks/WP02-alias-tree-and-reads.md](tasks/WP02-alias-tree-and-reads.md)
- **Goal**: The loader accepts anchors, aliases and merge keys:
  - `AliasNode` wraps each alias occurrence, and the anchored node is shared;
  - `MergeKeyMapping` is the view over a mapping holding `<<`;
  - C3 and C13 are refused at load.

  `get`, `show`, `show --sources`, history leaves and reconcile all see resolved values (US1).
- **Priority**: P1 (US1)
- **Independent test**: reporter's file loads; `get`/`show`/`--sources` print resolved values; every C2/C3/C13/A-0 load error exits 4 naming the file.
- **Subtasks**: T005, T006, T007, T008, T009, T010 (WP02)
- **Dependencies**: WP01
- **Estimated prompt size**: ~380 lines

## Phase 3 — Write rules (parallel)

### WP03 — Placement: "reached through an alias"

- **Prompt**: [tasks/WP03-placement-through-alias.md](tasks/WP03-placement-through-alias.md)
- **Goal**: `placement.place` decides "reached through an alias", and only there:
  - without the flag → exit 3, with `--expand-alias` in the message;
  - with the flag → `ExpandAlias`;
  - through `<<` → always exit 3.

  Writes at the anchor and new keys under a mapping holding `<<` are ordinary placements.
- **Priority**: P1 (US3, the bug)
- **Independent test**: unit tests over loaded fixture trees for every route shape.
- **Subtasks**: T011, T012, T013, T014, T015 (WP03)
- **Dependencies**: WP02
- **Estimated prompt size**: ~320 lines

### WP04 — Expansion text

- **Prompt**: [tasks/WP04-alias-expansion-edits.md](tasks/WP04-alias-expansion-edits.md)
- **Goal**: `writeback/aliases.expand_edits` returns the `TextEdit`s that replace one written alias with a block-style copy and put `  # expanded from *<name> by troupe` on its key or dash line (C7–C9).
- **Priority**: P1 (US4)
- **Independent test**: unit tests apply the edits to fixture texts and compare whole texts; the result re-loads to the same resolved values.
- **Subtasks**: T016, T017, T018, T019 (WP04)
- **Dependencies**: WP02 (can run in parallel with WP03)
- **Estimated prompt size**: ~300 lines

## Phase 4 — Wiring

### WP05 — `set` with aliases: apply loop, verification, CLI

- **Prompt**: [tasks/WP05-set-wiring-and-stories.md](tasks/WP05-set-wiring-and-stories.md)
- **Goal**: `set` works end to end (US2–US4):
  - the expand loop;
  - the verifier rules for aliases and anchors;
  - anchors kept on replacement;
  - the `--expand-alias` flag;
  - integration tests with byte snapshots and history.
- **Priority**: P1
- **Independent test**: the reporter's scenario through the CLI; the worked example byte-for-byte.
- **Subtasks**: T020, T021, T022, T023, T024, T025 (WP05)
- **Dependencies**: WP03, WP04
- **Estimated prompt size**: ~420 lines

## Phase 5 — Acceptance

### WP06 — Acceptance, history and agreement

- **Prompt**: [tasks/WP06-aliases-acceptance.md](tasks/WP06-aliases-acceptance.md)
- **Goal**: Prove C11 (history, lineage, reconcile, `watch`) and the remaining edge cases through the CLI. Walk through the quickstart. Make spec, contract, docstrings and code agree, and run all gates.
- **Priority**: P2
- **Independent test**: acceptance suite plus quickstart output.
- **Subtasks**: T026, T027, T028, T029 (WP06)
- **Dependencies**: WP05
- **Estimated prompt size**: ~230 lines

## Dependency graph

```
WP01 → WP02 → WP03 ┐
              WP04 ┴→ WP05 → WP06
```

MVP: WP01–WP03 plus WP05 without the expansion tests, which already stop the reported bug. The full scope (WP04, WP06) is required for delivery.
