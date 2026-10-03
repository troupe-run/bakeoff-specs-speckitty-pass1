# Tasks: troupe configuration: get for values, show for anything

**Mission**: `troupe-config-get-show-01M411XB` · **Spec**: [spec.md](spec.md) · **Plan**: [plan.md](plan.md) · **Contract**: [contracts/cli.md](contracts/cli.md)
**Planning/merge branch**: `feat/troupe-config-get-show` (delivered to `main` by local merge after acceptance)

Every WP ships tests for every behaviour it adds or changes (charter TROUPE-005). Each WP must pass `uv run pytest`, `uv run mypy --strict`, `uv run ruff check` and `uv run ruff format --check` before it goes to review (TROUPE-006).

## Subtask Index

| ID | Description | WP | Parallel |
|----|-------------|----|----------|
| T001 | `Line` model, `to_text`, `source_label` (`src/troupe/yamlout.py`) | WP01 | [P] |
| T002 | Scalar and key rendering: quoting, non-strings, literal blocks, double-quote fallback | WP01 | |
| T003 | Collection layout: mappings, sequences, compact items, empties, root, include transparency | WP01 | |
| T004 | Source tagging rules (research D-7) | WP01 | |
| T005 | Unit tests incl. parse-back equality (`tests/unit/test_yamlout.py`) | WP01 | |
| T006 | `values.scalar_of(node)` + unit tests | WP02 | [P] |
| T007 | `commands/get.py` with the `config show` refusal message | WP02 | |
| T008 | CLI: register `get` (`cli.py`), help text | WP02 | |
| T009 | `tests/integration/test_get.py` (port of step-1 scalar `show` tests + refusal hint) | WP02 | |
| T010 | Switch value-reading test helpers to `get`; update `test_cli_basics.py` | WP02 | |
| T011 | Rewrite `commands/show.py` (scalar → `get` output; else renderer) | WP03 | |
| T012 | CLI: `show [PATH] [--sources]` parser + help | WP03 | |
| T013 | Rewrite `tests/integration/test_show.py` (sections, whole config, scalar == get, errors) | WP03 | |
| T014 | `tests/integration/test_show_sources.py` (`--sources` acceptance) | WP03 | |
| T015 | Quickstart walk-through, gates, spec/contract/code agreement | WP03 | |

## Phase 1 — Foundations (parallel)

### WP01 — YAML renderer with source tagging

- **Prompt**: [tasks/WP01-yaml-renderer.md](tasks/WP01-yaml-renderer.md)
- **Goal**: A pure module that turns any loaded `Node` into block-style YAML lines. Each line that holds a scalar knows its source file.
- **Priority**: P1 (core of US2/US3)
- **Independent test**: Unit tests build trees by loading real temporary files with `troupe.loader.load`. They assert exact text, then parse the output back with ruamel (safe) and compare it with the resolved data.
- **Subtasks**:
  - T001 `Line`, `to_text`, `source_label` (WP01)
  - T002 scalar and key rendering (WP01)
  - T003 collection layout (WP01)
  - T004 source tagging (WP01)
  - T005 unit tests (WP01)
- **Implementation sketch**: A recursive `_emit(node, indent, lead)` returns `Line`s. Quoting comes from `writeback.scalars`, literal blocks from `writeback.blocks`.
- **Parallel**: independent of WP02.
- **Dependencies**: none.
- **Risks**: literal-block indentation in list items; key quoting; float specials.
- **Estimated prompt size**: ~330 lines.

### WP02 — `get` command

- **Prompt**: [tasks/WP02-get-command.md](tasks/WP02-get-command.md)
- **Goal**: `troupe config get PATH` behaves exactly like step-1 `show PATH`. On a mapping or list it exits 5, and stderr mentions `config show`.
- **Priority**: P1 (US1)
- **Independent test**: CLI tests with exact bytes on real theatres.
- **Subtasks**:
  - T006 `scalar_of` (WP02)
  - T007 `commands/get.py` (WP02)
  - T008 CLI registration (WP02)
  - T009 `test_get.py` (WP02)
  - T010 helper switch + `test_cli_basics.py` (WP02)
- **Implementation sketch**: Move the current `show.py` logic into `get.py`. Extract `scalar_of` into `values.py`. Register `get` in the parser and in `COMMAND_MODULES`.
- **Parallel**: independent of WP01.
- **Dependencies**: none.
- **Risks**: `show` must keep working unchanged until WP03; do not edit `commands/show.py` or `tests/integration/test_show.py`.
- **Estimated prompt size**: ~280 lines.

## Phase 2 — `show` (User Stories 2 & 3)

### WP03 — `show [PATH] [--sources]`

- **Prompt**: [tasks/WP03-show-command.md](tasks/WP03-show-command.md)
- **Goal**: `show` prints a scalar exactly as `get` does. A section, or the whole configuration, prints as YAML through the WP01 renderer, with source comments when `--sources` is given.
- **Priority**: P1/P2
- **Independent test**: CLI tests with exact bytes and parse-back equality; spec US2/US3 acceptance scenarios one by one.
- **Subtasks**:
  - T011 `show.py` (WP03)
  - T012 parser (WP03)
  - T013 `test_show.py` (WP03)
  - T014 `test_show_sources.py` (WP03)
  - T015 gates and agreement (WP03)
- **Dependencies**: WP01, WP02.
- **Risks**: the `cli.py` edit is outside this WP's owned files (it belongs to WP02). It is pre-authorised and limited to the `show` subparser lines.
- **Estimated prompt size**: ~300 lines.

## Dependency graph

```
WP01 ──┐
       ├──> WP03
WP02 ──┘
```

MVP: WP02 alone already delivers `get`. WP01 and WP03 deliver the new `show`.
