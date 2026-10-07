---
work_package_id: WP06
title: 'Load and validate: sessions, watch and the read stories'
dependencies:
- WP03
- WP05
requirement_refs:
- FR-001
- FR-003
- FR-006
- FR-007
- FR-008
- FR-009
planning_base_branch: feat/troupe-config-remote-includes
merge_target_branch: feat/troupe-config-remote-includes
branch_strategy: Planning artifacts for this mission were generated on feat/troupe-config-remote-includes. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/troupe-config-remote-includes unless the human explicitly redirects the landing branch.
subtasks:
- T024
- T025
- T026
- T027
- T028
- T029
phase: Phase 2 - Loading
history:
- at: '2026-10-07T18:00:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/troupe/configuration.py
create_intent:
- src/troupe/configuration.py
- tests/unit/test_configuration.py
- tests/integration/test_remote_read.py
- tests/integration/test_literals.py
- tests/integration/test_schema_validation.py
- tests/integration/test_watch_schema.py
execution_mode: code_change
model: ''
owned_files:
- src/troupe/configuration.py
- src/troupe/session.py
- src/troupe/commands/watch.py
- tests/unit/test_configuration.py
- tests/integration/test_remote_read.py
- tests/integration/test_literals.py
- tests/integration/test_schema_validation.py
- tests/integration/test_watch_schema.py
role: implementer
tags: []
task_type: implement
tracker_refs:
- bakeoff-specs-speckitty-1j5
---

# Work Package Prompt: WP06 – Load and validate: sessions, watch and the read stories

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter (`agent_profile`, `role`, `agent`), and behave according to its guidance before parsing the rest of this prompt.

If no profile is specified, run `spec-kitty agent profile list` and select the best match for this work package's `task_type` and `authoritative_surface`.

---

## ⚠️ IMPORTANT: Review Feedback

- **Has review feedback?**: Check the `review_ref` field in the event log (via `spec-kitty agent tasks status`) or the Activity Log below.
- **You must address all feedback** before your work is complete.

---

## Objective

1. **`src/troupe/configuration.py`** is the single "loaded and valid" entry point (research R-10, TROUPE-007):

   ```python
   @dataclass(frozen=True)
   class Loaded:
       tree: Node
       schema: Schema | None
       fetched: dict[Url, str]   # remote texts this command has fetched (shared by every reload)

   def load_configuration(
       theatre: Theatre,
       overrides: Mapping[Location, str] | None = None,
       fetched: dict[Url, str] | None = None,
   ) -> Loaded: ...

   def violation(tree: Node, schema: Schema) -> Violation | None: ...   # tree → data → validate
   ```

   The order is: `schema = load_schema(theatre.state_dir)`, then `tree = loader.load(theatre.config_file, overrides, schema=schema, fetched=fetched)`, then validation. A violation raises `LoadError(f"configuration does not match schema {schema.path} at {v.path}: {v.message}")` (exit 4, S-8). The schema is read **before** the tree because literal decisions depend on it.
2. **`session.open_session`** loads through `load_configuration`. `Session` gains `schema: Schema | None` and `fetched: dict[Url, str]`, which WP08 and WP09 use for `set`. Every command that opens a session (`get`, `show`, `set`, `history`, `watch`) therefore fetches, validates and exits 4 on failure.
3. **`watch`** loads through the session (unchanged) and adds `<state_dir>/troupe.schema.json` to its baseline, so a schema change triggers a reconcile (S-6, R-11).
4. **End-to-end read stories**: US1 (remote reads), US4 (literals) and US5 (load-time validation) pass through the real CLI.

## Context

- Spec: US1, US4, US5 (scenarios 1, 2, 4, 5), S-2, S-6, S-7, S-8, S-10; FR-001, FR-003, FR-006, FR-007, FR-008, FR-009; edge cases.
- Research: R-6, R-10, R-11, R-13. Contract message table.
- From WP03: `schema.load_schema`, `Schema.validate(data) -> Violation | None`. From WP05: `loader.load(..., schema=, fetched=)`, remote `SourceFile`s, `watched_files` without remote sources. From WP01: fixtures `remote` and `https_remote`, `run_cli` with `NO_PROXY`.
- Existing: `session.open_session` (lock, `locate` again under the lock, `load`, history import or reconcile); `commands/watch._reconcile_and_snapshot` (the baseline includes both root candidates, absent → `None`); `values.scalar_of` (a `TextInclude` reads as its target text); `paths.unwrap`; `MergedMapping.entries`/`MergeKeyMapping.entries` are resolved views.

## Branch Strategy

- Planning/base branch: `feat/troupe-config-remote-includes`. Final merge target: `feat/troupe-config-remote-includes`, which is merged into `main` locally after acceptance.
- Run `spec-kitty agent action implement WP06 --agent <name>`. It depends on WP03 and WP05.

## Subtasks

### T024 — `configuration.py`

1. Implement `Loaded`, `load_configuration` and `violation` as above.
2. **Tree → data** (`_data(node)`), following the readers:
   - `unwrap` first, so aliases, includes and merged views resolve;
   - `ScalarNode` → `value`; `TextInclude` → the target text (as `values.scalar_of`);
   - `MappingNode` (any subclass) → `{entry.key: _data(entry.value) for entry in node.entries}`;
   - `SequenceNode` → a list.

   Python `float('nan')`/`inf` pass through unchanged; jsonschema handles them as numbers. Document that `!literal` strings are plain strings here (S-8).
3. `fetched` defaults to a new dict when not given, and the same dict object is returned in `Loaded.fetched`, so callers keep sharing it.
4. Module docstring: one entry point, its order and why (schema first), the exit codes (4 here; `set` turns violations into exit 3 in WP08 by calling `violation` itself on its in-memory reload).
5. Unit tests in `tests/unit/test_configuration.py`:
   - `_data` on merged, aliased, text-include and literal trees equals what `show` prints;
   - with no schema there is no validation;
   - a violation message names the schema file and path;
   - `fetched` is shared and filled.

### T025 — Sessions and `watch`

1. In `session.open_session`, replace `tree = load(current.config_file)` with `loaded = load_configuration(current)`. Keep the order "load before opening history", so a fetch or validation failure records nothing and leaves no history file (existing docstring promise). Add `schema` and `fetched` to `Session` and document them.
2. In `commands/watch._reconcile_and_snapshot`, after the root candidates, add `baseline[session.theatre.state_dir / SCHEMA_FILE_NAME] = _read(...)` (absent → `None`). Comment: the schema decides what is a literal and what is valid, so editing it is a change to watch (S-6).
3. In `watch`, while unloadable (`baseline is None`), the existing loop retries on every tick. With a failing remote include, every retry fetches again, bounded by the 10 s deadline. This is the existing step-3 behaviour, now stated in spec S-6 (analysis I1). Keep it, and record in the docstring that remote content is only re-read when a reconcile runs. Do not add URL polling (S-6).

### T026 — Integration US1: `tests/integration/test_remote_read.py`

Use `make_theatre` with the `remote` fixture, and `run_cli` via the per-module helpers as in other integration files. Each test asserts the exit code, stdout exactly, and stderr (empty or the single `troupe: …` line):
1. `test_get_reads_a_value_from_a_remote_yaml_include` (US1-1)
2. `test_get_of_a_remote_text_include_prints_the_body_exactly` (US1-2, query string → text)
3. `test_ref_form_overrides_win_and_sources_name_url_and_local_file` (US1-3, `show coder --sources`: `model` → `# from http://127.0.0.1:…/coder.yaml`, `temperature` → `# from .troupe/troupe.yml`)
4. `test_file_include_inside_remote_yaml_is_fetched_from_the_same_server` (US1-4; request log)
5. `test_failed_fetch_exits_4_naming_url_and_local_file`, parametrised over 404, a non-UTF-8 body, a redirect to `ftp://` and a closed port (US1-5). One slow test for the 10 s deadline (`hang`) through the CLI, asserting exit 4 and `timed out after 10 s`.
6. `test_url_cycle_exits_4`
7. `test_upstream_change_is_recorded_as_a_file_lineage_set_event`: import, change the served body, run `get`, and assert one `set` event for the changed leaf with the file lineage (actor unknown, via `file`), using `history_events` (US1-6, S-6).
8. `test_every_command_that_loads_fails_with_exit_4_when_a_fetch_fails`: `get`, `show`, `set`, `history`, plus `watch` startup (`watch` exits 4 and never prints `watching`).
9. `test_each_url_is_fetched_once_per_command` (request log after one `show`)
10. `test_https_include_with_an_untrusted_certificate_exits_4` (`https_remote`; skipped with a reason if `openssl` is missing)

### T027 — Integration US4: `tests/integration/test_literals.py`

1. `test_schema_uri_setting_is_a_literal_and_is_not_fetched` (US4-1; the request log is empty)
2. `test_uri_through_additional_properties_and_items_is_literal` (US4-2)
3. `test_uri_only_through_ref_allof_or_pattern_properties_is_an_include` (US4-3: the server **is** asked; serve the URL so it loads)
4. `test_literal_tagged_strings_show_without_the_tag` (US4-4, exact `show` output, including `'5'` quoted as a string)
5. `test_literal_on_a_mapping_list_or_ref_and_other_tags_exit_4_naming_the_file` (US4-5)
6. `test_anchored_literal_is_literal_through_its_aliases` (edge case)

### T028 — Integration US5 (load part): `tests/integration/test_schema_validation.py`

1. `test_configuration_not_matching_the_schema_exits_4_naming_schema_and_path`: a local value, and also a value from a **remote** include (US5-1).
2. `test_invalid_schema_files_exit_4_naming_the_schema_file`: not JSON, NaN, wrong `$schema`, meta-schema failure, remote `$ref` (US5-2).
3. `test_format_uri_is_not_asserted` (US5-4)
4. `test_without_schema_file_behaviour_is_unchanged` (US5-5; a representative step-1 fixture gives byte-identical output)
5. `test_validation_failure_records_nothing_and_creates_no_history` (session order)

The `set` half of US5 (scenario 3) is WP08's.

### T029 — `tests/integration/test_watch_schema.py`

Use `WatchProcess` from `conftest`, following `tests/integration/test_watch.py`:
1. `test_editing_the_schema_triggers_a_reconcile`: a `!literal`-free string becomes an include, or stops being one, when the schema's `format: uri` mark is added or removed. Assert the recorded `set` event within 2 s.
2. `test_watch_does_not_poll_remote_urls`: after `watching` appears, the request log stays unchanged for 2 s while nothing local changes.
3. `test_invalid_schema_while_watching_is_reported_and_watch_keeps_running`: stderr names the schema file; fixing it resumes recording.

## Definition of Done

- All new tests pass, the whole suite passes, and all four gates pass, with output pasted.
- Nothing outside `configuration.py` calls `load_schema` and then `load` as a pair. Grep and record.

## Risks

- **History command semantics**: `history` opens a session without reconciling but still loads, so it now fetches and validates too. That is intended ("every command that loads the configuration", spec FR-009); test it in T026.8.
- **Slow tests**: only one CLI deadline test lives here.
- **Flaky watch timing**: reuse the existing `recorded_within` helpers and the 2 s budget. Bead `bakeoff-specs-speckitty-93m` already tracks one flaky watch test, so do not add timing-sensitive assertions beyond the existing pattern.

## Reviewer guidance

- One entry point. A load failure leaves no history file.
- `watch` baselines the schema file and makes no URL requests while idle.
- Test names state what they prove, and stdout and stderr are asserted exactly.

## Activity Log

- 2026-10-07T18:00:00Z – system – Prompt generated via /spec-kitty.tasks
