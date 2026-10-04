---
work_package_id: WP04
title: Lineage in troupe config history output
dependencies:
- WP03
requirement_refs:
- C-003
- FR-001
- NFR-003
planning_base_branch: feat/troupe-config-lineage
merge_target_branch: feat/troupe-config-lineage
branch_strategy: Planning artifacts for this mission were generated on feat/troupe-config-lineage. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/troupe-config-lineage unless the human explicitly redirects the landing branch.
subtasks:
- T016
- T017
- T018
phase: Phase 3 - Output
history:
- at: '2026-10-04T10:28:42Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/troupe/commands/history.py
create_intent: []
execution_mode: code_change
model: ''
owned_files:
- src/troupe/commands/history.py
- tests/integration/test_history.py
- tests/integration/test_set_history.py
- tests/integration/test_reconcile_first.py
- tests/integration/test_set_blocks.py
- tests/integration/test_set_new_entries.py
- tests/integration/test_set_existing.py
- tests/integration/test_get.py
- tests/integration/test_show.py
- tests/integration/test_watch.py
- tests/integration/test_watch_includes.py
- tests/integration/test_watch_set.py
role: implementer
tags: []
task_type: implement
tracker_refs: []
---

# Work Package Prompt: WP04 – Lineage in `troupe config history` output

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter (`agent_profile`, `role`, `agent`), and behave according to its guidance before parsing the rest of this prompt.

If no profile is specified, run `spec-kitty agent profile list` and select the best match for this work package's `task_type` and `authoritative_surface`.

---

## ⚠️ IMPORTANT: Review Feedback

- **Has review feedback?**: Check the `review_ref` field in the event log (via `spec-kitty agent tasks status`) or the Activity Log below.
- **You must address all feedback** before your work is complete.

---

## Objective

Make lineage readable. Each line of `troupe config history [PATH]` becomes:

```
{"seq": …, "op": …, "path": …, "old": …, "new": …, "actor": {"kind": …, "id": …}, "via": …, "at": …, "reason": …, "change": …}
```

The keys come in exactly that order (FR-001, research D-8, contracts/cli.md). The existing integration tests that compare whole lines or whole objects are adapted without weakening what they assert about the five original keys.

## Context

- `kitty-specs/troupe-config-lineage-01M436R0/spec.md`: FR-001, NFR-003, C-003
- `kitty-specs/troupe-config-lineage-01M436R0/contracts/cli.md`: "line format", example line
- `kitty-specs/troupe-config-lineage-01M436R0/contracts/history-event.schema.json`
- `src/troupe/commands/history.py` (current `_line`), and `HistoryRecord.lineage` from WP03
- `tests/conftest.py` (WP03): `CORE_KEYS`, `core(events)`, `history_events`, `stored_records`

## Branch Strategy

- Planning/base branch: `feat/troupe-config-lineage`; final merge target: `feat/troupe-config-lineage`.
- Execution worktrees are allocated per computed lane from `lanes.json`; implement with `spec-kitty agent action implement WP04 --agent <name>` (depends on WP03).

## Subtasks

### T016 — Render lineage keys (`src/troupe/commands/history.py`)

```python
def _line(record: HistoryRecord) -> str:
    lineage = record.lineage
    fields = {
        "seq": record.seq, "op": record.op, "path": record.path,
        "old": record.old, "new": record.new,
        "actor": {"kind": lineage.actor.kind, "id": lineage.actor.id},
        "via": lineage.via, "at": lineage.at,
        "reason": lineage.reason, "change": lineage.change,
    }
    return json.dumps(fields, ensure_ascii=False) + "\n"
```

- This dict literal is the one place where the key order is decided. Update the module docstring: the key order, and that `via` may be `null` only for pre-lineage `set`/`remove` events (DM 01M436RBNQT22F9AM54QER2FT9).
- The PATH filter and the "never reconciles" rule are unchanged.

### T017 — Adapt existing integration tests

Run `uv run pytest tests/integration` after T016 and fix every failure that comes from the new line shape. Known places:
- `test_history.py`: `KEYS`, `_valid_record`, and `FIXTURE_IMPORT` comparisons.
- `test_set_history.py`: the dict list at the top and the raw-text comparison around line 88–92.
- Local `_history`/`_event` helpers in `test_reconcile_first.py`, `test_set_blocks.py`, `test_set_new_entries.py`, `test_set_existing.py`, `test_get.py`, `test_show.py`, `test_watch*.py`.

Rules:
- Where a test checks *which* events were recorded, compare `core(events)` with the same expected five-key dicts as before. The expected values must not change.
- Where a test compared **raw text** (exact bytes), keep a bytes-level check. Assert that each line's text *starts with* the old five-key prefix minus the closing brace, e.g. `'{"seq": 7, "op": "set", "path": "model.temperature", "old": 0.2, "new": 0.5, "actor": '`. The exact rendering of the original keys therefore stays pinned.
- Do not delete any test, and do not loosen any value assertion on the original keys.
- If a file outside `owned_files` needs a change, make it, and record a one-line rationale in the handoff.

### T018 — Lineage output tests (`tests/integration/test_history.py`)

Extend `_valid_record` so it checks the full contract schema on **every** line any test reads: key order equals the ten keys, `actor` is an object with exactly `kind`/`id`, `kind` is in the three kinds, an `unknown` kind has a `null` id, `via` is in the three values or `null`, `at` matches `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$`, `reason` is a string or `null`, and `change` is a non-empty string. Implement the checks by hand; do **not** add a jsonschema dependency.

New tests:
- `test_history_lines_have_lineage_keys_in_contract_order`.
- `test_import_lines_show_unknown_actor_via_import_and_one_change`.
- `test_history_path_filter_keeps_full_lineage`: filtered lines equal the corresponding lines of the unfiltered output.
- `test_history_output_is_identical_across_runs`: two `history` runs in separate processes give byte-identical stdout (NFR-003, FR-012).
- `test_history_prints_reason_with_json_escaping`: `set --reason 'say "hi"\nnow ü'` → the parsed `reason` equals the input, and the raw line contains `\"` and `\n` escapes and a literal `ü` (`ensure_ascii=False`).

## Definition of Done

- `history` prints the ten keys in order on every line; all tests are adapted and the new ones pass.
- `uv run pytest`, `uv run mypy --strict`, `uv run ruff check`, `uv run ruff format --check` all pass; paste their output in the review handoff.

## Risks

- Mechanical test edits can silently weaken assertions. Reviewers diff the expected values and they must be unchanged.

## Reviewer guidance

- Verify the key order against contracts/cli.md.
- Spot-check three adapted tests: is the five-key expectation still the same literal data?

## Activity Log

- 2026-10-04T10:28:42Z – system – Prompt generated via /spec-kitty.tasks
