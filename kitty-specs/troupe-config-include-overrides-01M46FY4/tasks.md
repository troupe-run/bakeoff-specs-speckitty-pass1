# Tasks: troupe configuration: keep shared includes shared

**Mission**: `troupe-config-include-overrides-01M46FY4` · **Spec**: [spec.md](spec.md) · **Plan**: [plan.md](plan.md) · **Research**: [research.md](research.md) · **Data model**: [data-model.md](data-model.md) · **Contract**: [contracts/cli.md](contracts/cli.md) · **Quickstart**: [quickstart.md](quickstart.md)
**Planning/merge branch**: `feat/troupe-config-include-overrides` (delivered to `main` by local merge after acceptance)

Every WP ships tests for every behaviour it adds or changes (charter TROUPE-005), against real files, the real CLI and the real event store. Each WP must pass `uv run pytest`, `uv run mypy --strict`, `uv run ruff check` and `uv run ruff format --check` before review (TROUPE-006). No WP may leave the suite red. Spec D-n ids are the out-of-contract choices in spec.md; R-n ids are research decisions.

## Subtask Index

| ID | Description | WP | Parallel |
|----|-------------|----|----------|
| T001 | `tree.py`: `holder` on `YamlInclude`/`TextInclude`; `MergedMapping(MappingNode)` | WP01 | |
| T002 | `merge.py`: `REF_KEY`, `deep_merge(base, override, ref)` (pure) | WP01 | |
| T003 | `loader.py`: `$ref` recognition, D-1 / non-YAML-sibling / D-7 load errors, merged mappings | WP01 | |
| T004 | `reconcile.watched_files` covers both sides and `ref` targets of merged mappings | WP01 | |
| T005 | `tests/unit/test_merge.py` | WP01 | |
| T006 | `tests/integration/test_loading_ref.py` (US1 loads + exit 4 cases) | WP01 | |
| T007 | `tests/integration/test_reads_overrides.py` (get/show/--sources/history/reconcile/watch over `$ref`) | WP01 | |
| T008 | `convert_include_edits`: block-mapping parent (key line kept, comment gap, value on next line) | WP02 | [P] |
| T009 | `convert_include_edits`: flow parent and flow list item | WP02 | [P] |
| T010 | `convert_include_edits`: block list item and document-root include | WP02 | |
| T011 | D-11 refusal, newline/indent handling, quoted include bytes verbatim | WP02 | |
| T012 | Unit tests in `tests/unit/test_collections.py` | WP02 | |
| T013 | `concrete_parent(root, node)`; `_existing` uses concrete parents; refusals for whole includes, D-6, D-10 | WP03 | |
| T014 | Nearest include reference + list rule (`_include_ref`) | WP03 | |
| T015 | Override targets: `_on_side`, holder, merged-ref descent, `ConvertInclude` placement | WP03 | |
| T016 | `--in-include` (`in_include` parameter of `place`) | WP03 | |
| T017 | `tests/unit/test_placement_overrides.py` + module docstring | WP03 | |
| T018 | `apply.py`: `in_include`, `ConvertInclude` dispatch, no-`MergedMapping` guard | WP04 | |
| T019 | `apply._same_outside`: conversion allowance and `ref` target comparison | WP04 | |
| T020 | `cli.py` `set --in-include`; `commands/set_value.py` passes it | WP04 | |
| T021 | Update the two step-1 tests in `test_set_new_entries.py` (Overrides replaces rule 2) + `--in-include` twins | WP04 | |
| T022 | `tests/integration/test_set_overrides.py` (US2 core, US3) | WP04 | |
| T023 | `tests/integration/test_set_in_include.py` (US4) | WP04 | |
| T024 | Acceptance: nested, flow, list-item and 4-space conversions (US2 2/5/6/7) | WP05 | [P] |
| T025 | Acceptance: refusals D-6, D-10, D-11 and whole include, no file/no event changed | WP05 | [P] |
| T026 | Acceptance: history/lineage of override sets, reconcile of hand-written overrides, `watch` | WP05 | |
| T027 | Quickstart walk-through, spec/contract/code agreement, full gates | WP05 | |

## Phase 1 — Foundations (parallel)

### WP01 — Mapping-form includes: load and read

- **Prompt**: [tasks/WP01-mapping-form-load.md](tasks/WP01-mapping-form-load.md)
- **Goal**: The loader understands `$ref` and builds `MergedMapping` views; every reader (`get`, `show`, `--sources`, history leaves, reconcile, `watch`) sees merged values.
- **Priority**: P1 (US1; foundation for every write)
- **Independent test**: fixture theatres with mapping-form includes; `get`/`show`/`show --sources` output and exit codes; reconcile records hand edits in `$ref` targets.
- **Subtasks**:
  - T001 tree nodes (WP01)
  - T002 merge module (WP01)
  - T003 loader rules and errors (WP01)
  - T004 watched files (WP01)
  - T005 merge unit tests (WP01)
  - T006 loading integration tests (WP01)
  - T007 reads integration tests (WP01)
- **Implementation sketch**: pure `deep_merge` in a new module; loader detects `$ref` in `_convert` for raw mappings and delegates; readers need no change because `MergedMapping` is a `MappingNode`.
- **Parallel**: independent of WP02.
- **Dependencies**: none.
- **Risks**: `ruamel` raw key text for `$ref` in quoted forms (`"$ref"`); include chains; cycles through `$ref`.
- **Estimated prompt size**: ~330 lines.

### WP02 — Include conversion edits

- **Prompt**: [tasks/WP02-include-conversion-edits.md](tasks/WP02-include-conversion-edits.md)
- **Goal**: `writeback/collections.convert_include_edits` renders the byte-surgical edit that turns a scalar-form include into mapping form with override keys, in block, flow, list-item and document-root positions.
- **Priority**: P1 (FR-006)
- **Independent test**: unit tests applying the edits to texts and comparing exact output strings.
- **Subtasks**:
  - T008 block-mapping parent (WP02)
  - T009 flow parent (WP02)
  - T010 block list item and document root (WP02)
  - T011 refusals and formatting rules (WP02)
  - T012 unit tests (WP02)
- **Implementation sketch**: reuse `_Renderer`, `_nest`, `render_flow_value`, `detect_newline`, `comments.replace_in_line`; take spans (`Origin`) and a concrete parent, never a tree walk.
- **Parallel**: fully parallel with WP01 (touches only `collections.py` and its unit tests).
- **Dependencies**: none.
- **Risks**: comment column vs comment gap (contract example keeps the gap for block mappings); CRLF files.
- **Estimated prompt size**: ~300 lines.

## Phase 2 — Placement

### WP03 — Placement: overrides, `--in-include`, refusals

- **Prompt**: [tasks/WP03-placement-overrides.md](tasks/WP03-placement-overrides.md)
- **Goal**: `writeback/placement.place` decides every step-5 write target (FR-005, FR-007–FR-010, FR-012, D-6, D-8, D-10), returning only concrete collections.
- **Priority**: P1
- **Independent test**: unit tests on loaded fixture trees asserting the returned placement type, target mapping file and keys.
- **Subtasks**:
  - T013 concrete parents and refusals (WP03)
  - T014 nearest include reference + list rule (WP03)
  - T015 override targets (WP03)
  - T016 `--in-include` (WP03)
  - T017 unit tests + docstring (WP03)
- **Implementation sketch**: R-3/R-4 algorithm exactly; a new `ConvertInclude(include, parent, slot, keys)` placement.
- **Dependencies**: WP01 (tree types).
- **Risks**: merged parents silently used for writes (guarded by identity search and the WP04 guard).
- **Estimated prompt size**: ~380 lines.

## Phase 3 — Wiring and stories

### WP04 — `set` wiring, verification and story tests

- **Prompt**: [tasks/WP04-set-wiring-and-stories.md](tasks/WP04-set-wiring-and-stories.md)
- **Goal**: `set` (with or without `--in-include`) writes overrides end-to-end, verified in memory; story tests for US2, US3, US4.
- **Priority**: P1
- **Independent test**: CLI runs with byte snapshots of the whole theatre.
- **Subtasks**:
  - T018 apply dispatch (WP04)
  - T019 verifier allowance (WP04)
  - T020 CLI flag (WP04)
  - T021 step-1 tests updated (WP04)
  - T022 US2/US3 tests (WP04)
  - T023 US4 tests (WP04)
- **Dependencies**: WP02, WP03.
- **Risks**: verifier false refusals (exit 3) for legitimate conversions.
- **Estimated prompt size**: ~360 lines.

### WP05 — Acceptance: edges, history and delivery

- **Prompt**: [tasks/WP05-overrides-acceptance.md](tasks/WP05-overrides-acceptance.md)
- **Goal**: Prove the edge scenarios and agent choices end-to-end, history/lineage/watch interplay, and agreement of spec, contract, quickstart and code.
- **Priority**: P2
- **Independent test**: `tests/integration/test_overrides_acceptance.py`; quickstart run.
- **Subtasks**:
  - T024 conversion acceptance (WP05)
  - T025 refusal acceptance (WP05)
  - T026 history/reconcile/watch (WP05)
  - T027 quickstart + agreement + gates (WP05)
- **Dependencies**: WP04.
- **Risks**: finding a behaviour gap late — fix in the owning module with a one-line rationale, or file a beads issue and report it.
- **Estimated prompt size**: ~240 lines.

## Dependency graph

```
WP01 ──► WP03 ──┐
WP02 ───────────┴──► WP04 ──► WP05
```

MVP: WP01 (reads mapping-form includes) is independently useful; CR-A is complete at WP04.
