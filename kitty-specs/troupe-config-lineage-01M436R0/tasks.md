# Tasks: troupe configuration: lineage for every change

**Mission**: `troupe-config-lineage-01M436R0` · **Spec**: [spec.md](spec.md) · **Plan**: [plan.md](plan.md) · **Research**: [research.md](research.md) · **Data model**: [data-model.md](data-model.md) · **Contract**: [contracts/cli.md](contracts/cli.md), [contracts/history-event.schema.json](contracts/history-event.schema.json)
**Planning/merge branch**: `feat/troupe-config-lineage` (delivered to `main` by local merge after acceptance)

Every WP ships tests for every behaviour it adds or changes (charter TROUPE-005). Each WP must pass `uv run pytest`, `uv run mypy --strict`, `uv run ruff check` and `uv run ruff format --check` before it goes to review (TROUPE-006). No WP may leave the test suite red, which is why the history **output** change (WP04) is separate from the **recording** change (WP03).

## Subtask Index

| ID | Description | WP | Parallel |
|----|-------------|----|----------|
| T001 | `Actor`, `Lineage`, constants and types (`src/troupe/lineage.py`) | WP01 | [P] |
| T002 | `resolve_actor(environ)` and `login_name()` (D-5, D-6) | WP01 | |
| T003 | `format_at`, `new_change_id`, `pre_lineage_change_id` (D-3, D-4) | WP01 | |
| T004 | Producer constructors and stored-field mapping (`import_lineage`, `file_lineage`, `cli_lineage`, `lineage_fields`, `lineage_from_fields`) | WP01 | |
| T005 | `tests/unit/test_lineage.py` | WP01 | |
| T006 | `tests/fixtures/pre_lineage/make_fixture.py` (runs the step-3 code at `a589041`) | WP02 | [P] |
| T007 | Generate and commit `troupe.yml`, `history.sqlite`, `expected_history.jsonl` | WP02 | |
| T008 | Fixture `README.md` + a sanity test that the fixture is a real v1 store | WP02 | |
| T009 | Event classes v2 fields + `upcast_v1_v2` (`src/troupe/history.py`) | WP03 | |
| T010 | Store API takes `Lineage`; `HistoryRecord.lineage` | WP03 | |
| T011 | Import lineage in `session.py`; file lineage in `reconcile.py` | WP03 | |
| T012 | `cli.py`: resolve actor before `locate`; `Command.run(theatre, args, actor)`; command signatures | WP03 | |
| T013 | `set --reason TEXT`; `set_value.py` records with `cli_lineage` | WP03 | |
| T014 | Unit tests: store lineage, atomic per call, upcast of the fixture, reconcile lineage | WP03 | |
| T015 | `conftest.py` hermetic env + `tests/integration/test_lineage_recording.py` (actor errors, check order, recorded lineage via the store) | WP03 | |
| T016 | `commands/history.py` renders lineage keys in contract order | WP04 | |
| T017 | Adapt existing integration tests that compare whole history lines | WP04 | |
| T018 | Lineage output tests in `tests/integration/test_history.py` (key order, schema, PATH filter, restart-stable) | WP04 | |
| T019 | `test_lineage_cli.py`: US1 actor + reason scenarios via `history` | WP05 | [P] |
| T020 | `test_lineage_changes.py`: US2/US3 import/file/cli grouping, distinct ids | WP05 | [P] |
| T021 | `test_lineage_changes.py`: `watch` reconciles each get their own change | WP05 | |
| T022 | `test_lineage_pre_lineage.py`: US4 old history read + appended, rows untouched | WP05 | [P] |
| T023 | Quickstart walk-through, spec/contract/code agreement, full gates | WP05 | |

## Phase 1 — Foundations (parallel)

### WP01 — Lineage module

- **Prompt**: [tasks/WP01-lineage-module.md](tasks/WP01-lineage-module.md)
- **Goal**: One module, `src/troupe/lineage.py`, that owns every lineage decision: the actor grammar, the login fallback, the clock format, change ids, per-producer lineage, and the mapping to and from the flat stored fields.
- **Priority**: P1 (foundation for every story)
- **Independent test**: unit tests on `resolve_actor` with every valid and invalid form, `format_at` with aware datetimes in other zones, uniqueness and format of change ids, and the constructors.
- **Subtasks**:
  - T001 types and constants (WP01)
  - T002 actor resolution and login name (WP01)
  - T003 clock and change ids (WP01)
  - T004 constructors and stored-field mapping (WP01)
  - T005 unit tests (WP01)
- **Implementation sketch**: frozen dataclasses, module-level `Final` constants, pure functions. Only `login_name`, `new_change_id` and the constructors touch the outside world (getpass, uuid, clock).
- **Parallel**: independent of WP02.
- **Dependencies**: none.
- **Risks**: `getpass.getuser()` raising different exceptions on 3.12 (`KeyError`) and 3.13+ (`OSError`).
- **Estimated prompt size**: ~280 lines.

### WP02 — Pre-lineage fixture

- **Prompt**: [tasks/WP02-pre-lineage-fixture.md](tasks/WP02-pre-lineage-fixture.md)
- **Goal**: A real history database recorded by the step-3 code, through an import, a CLI `set` and a reconciled hand edit. It comes with a regeneration script and an independent oracle of what `history` must print for it after this step.
- **Priority**: P2 (US4; guards topic stability for every later WP)
- **Independent test**: a sanity test reads the fixture's SQLite rows directly and checks that they are version-1 events (no `class_version`) with the expected topics.
- **Subtasks**:
  - T006 generator script (WP02)
  - T007 generated files (WP02)
  - T008 README + sanity test (WP02)
- **Parallel**: independent of WP01.
- **Dependencies**: none.
- **Risks**: SQLite WAL content not checkpointed into the main file; timestamps in the oracle must be derived from the stored rows, not from troupe code.
- **Estimated prompt size**: ~200 lines.

## Phase 2 — Recording

### WP03 — Record lineage in the store and every producer

- **Prompt**: [tasks/WP03-record-lineage.md](tasks/WP03-record-lineage.md)
- **Goal**: Every event saved from now on carries lineage, built once per producer. Old events are upcast when read. `TROUPE_ACTOR` is validated by every command before the theatre is located, and `set --reason` is stored. The `history` output is **not** changed yet.
- **Priority**: P1 (US1–US4 core)
- **Independent test**: unit tests on `HistoryStore` (lineage persisted across reopen, shared within one call, distinct across calls, upcast of the WP02 fixture without changing its rows) and on `reconcile`. CLI tests for actor errors and for lineage recorded by `set`, `get` and the import, read back through `HistoryStore.records()`.
- **Subtasks**:
  - T009 event v2 + upcast (WP03)
  - T010 store API + `HistoryRecord.lineage` (WP03)
  - T011 session/reconcile lineages (WP03)
  - T012 CLI actor + command signatures (WP03)
  - T013 `set --reason` + cli lineage (WP03)
  - T014 unit tests (WP03)
  - T015 conftest + integration recording tests (WP03)
- **Implementation sketch**: add fields to the three event classes under `class_version = 2` with `upcast_v1_v2`; `import_leaves(leaves, lineage)` / `record(changes, lineage)`; the session and reconcile create their own lineage; `cli.main` resolves the actor after parsing, before `locate`.
- **Parallel**: none (core).
- **Dependencies**: WP01, WP02.
- **Risks**: renaming an event class breaks old histories (keep topics); the `@event` method signatures must list every event field; existing unit tests calling `import_leaves`/`record` must be updated; a stray `TROUPE_ACTOR` in the developer's shell must not leak into tests.
- **Estimated prompt size**: ~450 lines.

## Phase 3 — Output

### WP04 — Lineage in `troupe config history` output

- **Prompt**: [tasks/WP04-history-output.md](tasks/WP04-history-output.md)
- **Goal**: Each `history` line has the keys `seq, op, path, old, new, actor, via, at, reason, change`, in that order. Existing tests are updated to the new line shape.
- **Priority**: P1 (FR-001; makes lineage readable)
- **Independent test**: `tests/integration/test_history.py` checks key order and per-key schema for every line, that the PATH filter keeps lineage, and that two runs are byte-identical.
- **Subtasks**:
  - T016 renderer (WP04)
  - T017 adapt existing tests (WP04)
  - T018 output tests (WP04)
- **Dependencies**: WP03.
- **Risks**: a mechanical test update must not weaken any assertion about the five original keys.
- **Estimated prompt size**: ~220 lines.

## Phase 4 — Acceptance

### WP05 — End-to-end lineage acceptance

- **Prompt**: [tasks/WP05-lineage-acceptance.md](tasks/WP05-lineage-acceptance.md)
- **Goal**: Every acceptance scenario and edge case in the spec is proven through the real CLI and `history`. The quickstart works, the gates are green, and spec, contract and code agree.
- **Priority**: P1
- **Independent test**: the new integration test files themselves.
- **Subtasks**:
  - T019 US1 tests (WP05)
  - T020 US2/US3 grouping tests (WP05)
  - T021 watch tests (WP05)
  - T022 US4 pre-lineage tests (WP05)
  - T023 quickstart + gates + agreement (WP05)
- **Dependencies**: WP04.
- **Risks**: timing flakiness in `watch` tests (reuse `WatchProcess` and `recorded_within`); the login-name expectation must be computed the same way the code computes it.
- **Estimated prompt size**: ~300 lines.

## Dependency graph

```
WP01 ─┐
      ├─> WP03 ─> WP04 ─> WP05
WP02 ─┘
```

MVP: WP01 + WP02 + WP03 + WP04 (lineage recorded and readable). WP05 completes the acceptance proof.
