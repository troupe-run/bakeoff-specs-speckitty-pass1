---
work_package_id: WP02
title: Pre-lineage fixture
dependencies: []
requirement_refs:
- FR-013
- NFR-004
planning_base_branch: feat/troupe-config-lineage
merge_target_branch: feat/troupe-config-lineage
branch_strategy: Planning artifacts for this mission were generated on feat/troupe-config-lineage. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/troupe-config-lineage unless the human explicitly redirects the landing branch.
subtasks:
- T006
- T007
- T008
phase: Phase 1 - Foundations
history:
- at: '2026-10-04T10:28:42Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: tests/fixtures/pre_lineage/
create_intent:
- tests/fixtures/pre_lineage/make_fixture.py
- tests/fixtures/pre_lineage/troupe.yml
- tests/fixtures/pre_lineage/history.sqlite
- tests/fixtures/pre_lineage/expected_history.jsonl
- tests/fixtures/pre_lineage/README.md
- tests/unit/test_pre_lineage_fixture.py
execution_mode: code_change
model: ''
owned_files:
- tests/fixtures/pre_lineage/**
- tests/unit/test_pre_lineage_fixture.py
role: implementer
tags: []
task_type: implement
tracker_refs: []
---

# Work Package Prompt: WP02 – Pre-lineage fixture

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter (`agent_profile`, `role`, `agent`), and behave according to its guidance before parsing the rest of this prompt.

If no profile is specified, run `spec-kitty agent profile list` and select the best match for this work package's `task_type` and `authoritative_surface`.

---

## ⚠️ IMPORTANT: Review Feedback

- **Has review feedback?**: Check the `review_ref` field in the event log (via `spec-kitty agent tasks status`) or the Activity Log below.
- **You must address all feedback** before your work is complete.

---

## Objective

Produce a **real** history database written by the step-3 code (commit `a589041`, the last commit on `main` before this mission), plus the configuration file it belongs to and an independent oracle of what `troupe config history` must print for it once lineage exists (research D-9, spec FR-013, DM 01M436RBNQT22F9AM54QER2FT9).

WP03 uses the fixture to test the read-time upcast. WP05 uses it for the end-to-end US4 tests. Tests always **copy** the fixture into a temporary theatre; nothing may open it in place.

## Context

- `kitty-specs/troupe-config-lineage-01M436R0/research.md`: D-2 (upcast mapping), D-4 (`at` format), D-9
- `kitty-specs/troupe-config-lineage-01M436R0/contracts/cli.md`: "Events recorded before step 4"
- `src/troupe/history.py` **at `a589041`**: event classes `LeafImported`, `LeafSet`, `LeafRemoved`; aggregate id `uuid5(NAMESPACE_URL, "troupe:config-history")`
- eventsourcing SQLite layout: table `stored_events` with columns `originator_id`, `originator_version`, `topic`, `state`. `state` is JSON bytes from `JSONTranscoder`, and datetimes are encoded as `{"_type_": "datetime_iso", "_data_": "<isoformat>"}`. Verify this against the actual database; don't assume it.

## Branch Strategy

- Planning/base branch: `feat/troupe-config-lineage`; final merge target: `feat/troupe-config-lineage`.
- Execution worktrees are allocated per computed lane from `lanes.json`; implement with `spec-kitty agent action implement WP02 --agent <name>`.

## Subtasks

### T006 — `tests/fixtures/pre_lineage/make_fixture.py`

A standalone script, run by a developer and never by pytest: `uv run python tests/fixtures/pre_lineage/make_fixture.py`. Steps:

1. Create a temporary directory. Run `git worktree add --detach <tmp>/old a589041` from the repo root, and always remove the worktree in a `finally` (`git worktree remove --force`).
2. Create a scratch theatre `<tmp>/theatre/.troupe/troupe.yml` with:
   ```yaml
   model:
     name: gpt
     temperature: 0.2
   tools:
     - search
     - fetch
   retries: 3
   ```
3. Run the **old** CLI with the current interpreter and `PYTHONPATH=<tmp>/old/src`. The dependencies are unchanged, so the current venv works. Use `[sys.executable, "-m", "troupe", "config", ..., "--theatre", theatre]` with `TROUPE_THEATRE` and `TROUPE_ACTOR` removed from the environment. Run these commands, checking that each exits 0:
   1. `history` → imports six leaves (seq 1–6).
   2. `set model.temperature 0.5` → one CLI `set` event (seq 7).
   3. Hand-edit the file: delete the `retries: 3` line and change `name: gpt` to `name: claude`.
   4. `get model.name` → reconcile: `set model.name` then `remove retries` (seq 8–9).
   
   Sleep about 10 ms between steps so the stored timestamps differ.
4. Make sure the database is self-contained. Open it with `sqlite3`, run `PRAGMA wal_checkpoint(TRUNCATE)`, and close it. Assert that no `history.sqlite-wal` with non-zero size remains, then copy only `history.sqlite`.
5. Copy `troupe.yml`, in its final hand-edited state, and `history.sqlite` into `tests/fixtures/pre_lineage/`.
6. Write `expected_history.jsonl` by reading `stored_events` **directly with `sqlite3` and `json`**, not with troupe code (an independent oracle):
   - Select rows ordered by `originator_version`, skipping version 1 (the `Created` event).
   - For each row:
     - `seq = originator_version - 1`;
     - `op` from the topic suffix (`LeafImported` → `import`, `LeafSet` → `set`, `LeafRemoved` → `remove`);
     - `path`, `old` and `new` from the state (`old` is null for import, `new` is null for remove);
     - `actor = {"kind": "unknown", "id": null}`;
     - `via` = `"import"` for import, `null` otherwise;
     - `at` = the state's timestamp parsed with `datetime.fromisoformat`, converted to UTC and formatted `%Y-%m-%dT%H:%M:%S.%fZ`;
     - `reason = null`;
     - `change = f"pre-lineage-{seq}"`.
   - Write each line with `json.dumps(obj, ensure_ascii=False)`, keys in the order `seq, op, path, old, new, actor, via, at, reason, change`.
7. Print a short summary.

Keep the script typed and lint-clean: it lives under `tests/`, so `mypy --strict` and `ruff` check it. Add `if __name__ == "__main__": main()`.

Make sure pytest won't collect it. The file name `make_fixture.py` doesn't match `test_*.py`, so it won't be collected; confirm this.

### T007 — Generate and commit the fixture files

- Run the script and commit `troupe.yml`, `history.sqlite`, `expected_history.jsonl`.
- Inspect `expected_history.jsonl` by eye: 9 lines; seq 1–6 import, 7 set temperature 0.2→0.5, 8 set name gpt→claude, 9 remove retries 3→null.
- Git treats `.sqlite` as binary automatically; don't add `.gitattributes` rules.

### T008 — `README.md` and `tests/unit/test_pre_lineage_fixture.py`

`README.md` (short) must say:
- what the fixture is (a history written by commit `a589041`) and how it was produced, including the exact command;
- that tests must copy it, not open it in place;
- what each file is.

Test file, reading only with `sqlite3`/`json`, no troupe imports:
- `test_fixture_rows_are_version_1_events_with_the_step_3_topics`: every leaf row's state has no `class_version` key, and topics are exactly `troupe.history:ConfigHistory.LeafImported|LeafSet|LeafRemoved` (plus the `Created` row).
- `test_expected_history_matches_the_fixture_rows`: recompute the oracle from the rows (same rules as the script, implemented in the test) and compare with `expected_history.jsonl`. This keeps the two files consistent if someone regenerates only one.
- `test_fixture_database_has_no_wal_dependency`: no `history.sqlite-wal`/`-shm` in the fixture directory.

## Definition of Done

- The fixture directory contains the script, the three generated files and the README; the sanity tests pass.
- `uv run pytest`, `uv run mypy --strict`, `uv run ruff check`, `uv run ruff format --check` all pass; paste their output in the review handoff.
- The temporary git worktree is gone (`git worktree list` shows no leftover).

## Risks

- WAL mode: copying without a checkpoint can produce an empty-looking database.
- Do not compute the oracle `at` with troupe's `format_at`. The oracle must be independent of the code it checks.

## Reviewer guidance

- Re-run the script in a scratch clone if in doubt. The rows will differ (new timestamps), but the shape must match.
- Check that the oracle follows contracts/cli.md "Events recorded before step 4" exactly.

## Activity Log

- 2026-10-04T10:28:42Z – system – Prompt generated via /spec-kitty.tasks
