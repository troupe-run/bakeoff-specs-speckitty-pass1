---
schema_version: 1
artifact_type: spec-kitty.analysis-report
command: /spec-kitty.analyze
mission_slug: troupe-config-lineage-01M436R0
mission_id: 01M436R0741RAC0Z3626FRD5C1
generated_at: '2026-10-04T10:36:24.284635+00:00'
analyzer_agent: unknown
input_artifacts:
  spec.md:
    path: kitty-specs/troupe-config-lineage-01M436R0/spec.md
    sha256: f7f971fe7b99216676d08158cc0bbc121f484a06efa8073d3bc8225163a38512
  plan.md:
    path: kitty-specs/troupe-config-lineage-01M436R0/plan.md
    sha256: bb78af7ec70c15c28bdeef488d3a8c22a45721945802cdb0dbe0a7afd00ccbde
  tasks.md:
    path: kitty-specs/troupe-config-lineage-01M436R0/tasks.md
    sha256: 5f636ee9877c7de99daf73ca75620662e1865b91c9e7c3d492463a4f3369475d
  charter:
    path: .kittify/charter/charter.yaml
    sha256: a48e59b0f9fb45472e8fd41c29f431bdb475a6b0598bd083c88c6017f4b0ab03
verdict: ready
issue_counts:
  high: 0
  medium: 1
  low: 3
  critical: 0
  info: 0
findings:
- id: U1
  severity: medium
  category: underspecification
  summary: WP03 T015 and WP05 T019 ask tests to remove LNAME/USERNAME (and LOGNAME/USER) from the child env, but conftest.run_cli only adds env entries and no WP adds a way to unset them.
- id: I1
  severity: low
  category: inconsistency
  summary: plan.md lists a docstring update for commands/watch.py, but no WP owns watch.py and WP03 says watch.py is not touched.
- id: I2
  severity: low
  category: inconsistency
  summary: WP03 changes the run() signature of commands/history.py, which WP04 owns; the prompt records this as an out-of-map edit, but the ownership exception is not mentioned in tasks.md.
- id: C1
  severity: low
  category: charter
  summary: WP01 T005 monkeypatches getpass.getuser to reach the null-login branch; TROUPE-005 prefers real collaborators. The prompt justifies it (a missing login cannot be produced on a real machine), which is acceptable but should be visible to reviewers.
---

## Specification Analysis Report

Mission `troupe-config-lineage-01M436R0`. Artifacts: spec.md, plan.md, research.md, data-model.md, contracts/, quickstart.md, tasks.md, tasks/WP01–WP05.

| ID | Category | Severity | Location(s) | Summary | Recommendation |
|----|----------|----------|-------------|---------|----------------|
| U1 | Underspecification | MEDIUM | tasks/WP03-record-lineage.md:208; tasks/WP05-lineage-acceptance.md:97; tests/conftest.py `run_cli`/`_child_env` | The tests must strip login variables from the child env, but `run_cli(env=...)` can only add or override entries. Setting `LOGNAME=bob` alone works, because `getpass` checks `LOGNAME` first. The WP05 "password-database fallback" variant cannot be written without a way to unset variables. | In WP03 T015 (which owns `conftest.py`), add an `unset: Iterable[str] = ()` parameter to `run_cli` and `_child_env` (and `WatchProcess`). Alternatively, WP05 can override all four variables to `""`: `getpass` skips empty values and falls through to `pwd`. |
| I1 | Inconsistency | LOW | plan.md:95 vs tasks/WP03-record-lineage.md:156 | The plan's source tree mentions a `watch.py` docstring update; no WP owns `watch.py`. Behaviour is unaffected because each `watch` reconcile already goes through `reconcile.reconcile`. | Treat the docstring note as optional. Implementers may add one sentence as a recorded out-of-map edit, or leave it. |
| I2 | Inconsistency | LOW | tasks/WP03-record-lineage.md (T012); tasks/WP04 owned_files | WP03 changes the `run` signature in `commands/history.py`, which WP04 owns. WP03 → WP04 is sequential, so there is no collision risk. | Reviewers of WP03 check that the edit is signature-only (already in reviewer guidance). |
| C1 | Charter | LOW | tasks/WP01-lineage-module.md (T005) | One stand-in, a monkeypatched `getpass.getuser`, is used for the unknowable-login branch. TROUPE-005 names real files, CLI output and eventsourcing, so this is not a violation, but it is a deviation from "no stand-ins". | Keep it, with the documented justification in the test docstring. The real-CLI login tests in WP03/WP05 cover the normal path. |

**Coverage Summary Table:**

| Requirement Key | Has Task? | Task IDs | Notes |
|-----------------|-----------|----------|-------|
| FR-001 lineage-on-every-history-line | Yes | T016, T018, T019–T022 | key order pinned in one place |
| FR-002 actor-from-troupe-actor | Yes | T002, T005, T012, T015, T019 | |
| FR-003 invalid-actor-exits-2 | Yes | T002, T005, T012, T015, T019, T021 | incl. check order before locate |
| FR-004 default-actor-login-name | Yes | T002, T005, T015, T019 | see U1 |
| FR-005 unknown-actor-import-file | Yes | T004, T011, T014, T020 | |
| FR-006 via-per-producer | Yes | T004, T011, T013, T020 | |
| FR-007 at-timestamp | Yes | T003, T014, T018, T020 | shared per change |
| FR-008 set-reason | Yes | T013, T015, T018, T019 | |
| FR-009 one-change-per-producer | Yes | T003, T004, T010, T014, T020 | |
| FR-010 reconcile-import-separate | Yes | T011, T015, T020 | |
| FR-011 each-watch-reconcile-change | Yes | T011, T021 | |
| FR-012 lineage-persisted | Yes | T009, T010, T014, T018, T022 | |
| FR-013 pre-lineage-honest | Yes | T006–T009, T014, T022 | real step-3 fixture |
| FR-014 noop-failed-set-no-reason | Yes | T013, T015, T019 | |
| NFR-001 atomic-change | Yes | T010, T014 | one save() per call |
| NFR-002 user-files-untouched | Yes | T015, T019 | snapshot checks |
| NFR-003 stable-output | Yes | T018, T022 | |
| NFR-004 existing-history-preserved | Yes | T008, T014, T022 | raw row comparison |
| NFR-005 behaviour-coverage | Yes | T023 | requirement→test table |
| C-001 contract-unchanged | Yes | T023 | contracts/ marks out-of-contract |
| C-002 fixed-platform | Yes | all | no new deps |
| C-003 earlier-behaviour-kept | Yes | T017 | existing tests adapted, not weakened |
| C-004 errors-name-variable | Yes | T002, T015 | |
| C-005 no-stored-rewrite | Yes | T009, T014, T022 | |

**Charter Alignment Issues:** none blocking. TROUPE-001 to TROUPE-009 are each addressed in the plan's Charter Check. C1 is noted for reviewer visibility.

**Unmapped Tasks:** none. T006–T008 (fixture) map to FR-013/NFR-004; T023 maps to NFR-005/C-001.

**Metrics:**

- Total Requirements: 24 (14 FR, 5 NFR, 5 C)
- Total Tasks: 23 (5 WPs)
- Coverage %: 100%
- Ambiguity Count: 0
- Duplication Count: 0
- Critical Issues Count: 0

## Next Actions

- No critical or high issues: implementation may proceed.
- U1: fold the fix into WP03 T015 during implementation (add `unset` support to `run_cli`/`_child_env`/`WatchProcess`, or override the four login variables to `""`). That keeps WP05's fallback test writable without an out-of-map edit.
- I1, I2, C1: no action needed beyond reviewer awareness.
