---
schema_version: 1
artifact_type: spec-kitty.analysis-report
command: /spec-kitty.analyze
mission_slug: troupe-config-remote-includes-01M4BMJ5
mission_id: 01M4BMJ55Q91FZYFPD9AG3AEWN
generated_at: '2026-10-07T17:24:18.963867+00:00'
analyzer_agent: unknown
input_artifacts:
  spec.md:
    path: kitty-specs/troupe-config-remote-includes-01M4BMJ5/spec.md
    sha256: ed2cb7d39926caadc6b489cd27e9fcf4bc21f9f27ca6765797559a4bc4a65b48
  plan.md:
    path: kitty-specs/troupe-config-remote-includes-01M4BMJ5/plan.md
    sha256: a1166e900cacb01115ceff8805b43249687bf870abd33322cff9e56e4eae1d04
  tasks.md:
    path: kitty-specs/troupe-config-remote-includes-01M4BMJ5/tasks.md
    sha256: 4e82da804207cf29bb0e81f0724869c027176dce39286f586884745e395e50f9
  charter:
    path: .kittify/charter/charter.yaml
    sha256: a48e59b0f9fb45472e8fd41c29f431bdb475a6b0598bd083c88c6017f4b0ab03
verdict: ready
issue_counts:
  medium: 2
  high: 0
  critical: 0
  low: 5
  info: 0
findings:
- id: U1
  severity: medium
  category: underspecification
  summary: '!literal on a mapping key is neither allowed nor refused by spec or tasks; WP02 composes it and the loader would silently accept a tagged key with a shifted key span.'
- id: I1
  severity: medium
  category: inconsistency
  summary: S-6 says watch does not poll URLs, but while the configuration is unloadable watch retries every 0.25 s tick (step-3 rule), refetching a failing remote include each tick.
- id: U2
  severity: low
  category: underspecification
  summary: Spec S-11 keeps an existing !literal for a string value but does not say what set --include does to a tagged value; research R-8 decides (tag removed).
- id: I2
  severity: low
  category: inconsistency
  summary: plan.md Project Structure test-file list differs from tasks.md (test_configuration, test_set_schema, test_set_include_remote, test_remote_acceptance, test_loader_remote/literals added; test_set_existing ownership).
- id: I3
  severity: low
  category: inconsistency
  summary: data-model.md names Schema's field 'location', WP03 names it 'path'.
- id: I4
  severity: low
  category: inconsistency
  summary: Spec S-2 says one URL is fetched at most once per load; plan R-10 and WP05/WP08 strengthen this to once per command (shared fetched cache).
- id: C1
  severity: low
  category: coverage
  summary: 'Planned cross-ownership edits: WP05 annotation-only edit in apply.py (WP08) and WP09 bug fixes outside its test-only files; documented but not enforced by ownership.'
---

## Specification Analysis Report

Mission `troupe-config-remote-includes-01M4BMJ5`. Inputs checked: spec.md, plan.md, research.md, data-model.md, contracts/cli.md, tasks.md and WP01–WP10, and the charter (TROUPE-001…009).

| ID | Category | Severity | Location(s) | Summary | Recommendation |
|----|----------|----------|-------------|---------|----------------|
| U1 | Underspecification | MEDIUM | spec.md S-10; WP02 T007; WP05 T021 | `!literal` on a mapping key (`!literal a: 1`) is not addressed. WP02 composes any tagged scalar, keys included. The loader's `_entries` ignores the tag, and the key's span would start after it. | Refuse `!literal` on mapping keys with exit 4, naming the file and line (keys are never includes; TROUPE-002). Add it to WP05 T021 and a test, and record it as a clarification of S-10. |
| I1 | Inconsistency | MEDIUM | spec.md S-6 and edge cases; WP06 T025 | "watch does not poll URLs" holds while loadable. While unloadable, the step-3 retry-every-tick loop refetches a failing URL about every 0.25 s plus the fetch time. | Either state in S-6 that a broken configuration is retried as in step 3 (and so refetched), or retry only on local change after a `FetchError`. Recommend the former (no new behaviour), with WP06 documenting it. |
| U2 | Underspecification | LOW | spec.md S-11, S-12; research R-8 | The effect of `--include` on an existing `!literal` value is decided only in research (the tag is removed). | Mention in spec S-12: with `--include` a replaced value's `!literal` tag is removed so the string reads as an include. |
| I2 | Inconsistency | LOW | plan.md Project Structure vs tasks.md | The test file names in the plan predate the work-package split. | Refresh the plan's tree, or note that tasks.md is authoritative for file names. |
| I3 | Inconsistency | LOW | data-model.md `Schema`; WP03 T011 | Field `location` vs `path`. | Use `path`, as WP03 does. |
| I4 | Inconsistency | LOW | spec.md S-2; research R-10 | Fetch-once scope: per load (spec) vs per command (plan). The plan is stricter and compatible. | Optionally align the S-2 wording; no behaviour conflict. |
| C1 | Coverage | LOW | WP05, WP08, WP09 | Two planned edits cross file ownership. | Keep the Activity Log records; reviewers check that they stay type-only or minimal. |

**Coverage Summary Table:**

| Requirement Key | Has Task? | Task IDs | Notes |
|-----------------|-----------|----------|-------|
| FR-001 remote-includes-load | Yes | T019–T022, T026 | WP05, WP06 |
| FR-002 includes-inside-remote-content | Yes | T015, T020, T022, T026 | WP04, WP05, WP06 |
| FR-003 failed-fetch | Yes | T002, T005, T020, T026 | WP01, WP05, WP06 |
| FR-004 remote-content-read-only | Yes | T034, T035, T039, T040 | WP08 |
| FR-005 local-overrides-under-remote | Yes | T034, T040 | WP08 |
| FR-006 remote-leaves-reads-history-watch | Yes | T019, T025, T026, T029 | WP05, WP06 |
| FR-007 schema-marks-literals | Yes | T012, T016, T021, T027 | WP03–WP06 |
| FR-008 literal-tag | Yes | T006–T008, T021, T027 | WP02, WP05, WP06 |
| FR-009 configuration-validates | Yes | T011, T013, T024, T028 | WP03, WP06 |
| FR-010 set-keeps-valid | Yes | T036, T041 | WP08 |
| FR-011 include-looking-written-literal | Yes | T017, T030–T033, T037, T038, T042 | WP04, WP07, WP08, WP09 |
| FR-012 include-flag | Yes | T017, T037, T041, T042, T043 | WP04, WP08, WP09 |
| NFR-001 remote-never-written | Yes | T035, T040, T045 | WP08, WP10 |
| NFR-002 refusals-change-nothing | Yes | T045 | WP10, plus every refusal test's snapshot |
| NFR-003 byte-surgical-writes | Yes | T045, T042 | WP09, WP10 |
| NFR-004 bounded-waiting | Yes | T002, T005, T026 | WP01, WP06 |
| NFR-005 behaviour-coverage | Yes | T046, T047 | WP10 |
| C-001…C-006 | Yes | WP01 (C-006), WP08 (C-005), WP10 (C-001, C-003, C-004); C-002 met by the stack | |

**Charter Alignment Issues:** none.
- TROUPE-001/002 are covered by byte-snapshot and refusal tests.
- TROUPE-003 by the message contract.
- TROUPE-004: the dependency was added on the product owner's "safest assumption" direction (DM 01M4BMXJ…).
- TROUPE-005/006: every WP requires tests and all four gates.
- TROUPE-007: one module per decision.
- TROUPE-008: S-1…S-12 confirmed as agent choices; no invented size limit (A-1).
- TROUPE-009: spec, contract and docs are synced in WP10.

**Unmapped Tasks:** none. T044 (S-13 sweep) and T046/T047 (docs, gates) trace to C-003, NFR-005 and TROUPE-006.

**Metrics:**

- Total requirements: 23 (12 FR, 5 NFR, 6 C)
- Total tasks: 47
- Coverage: 100% (requirements with at least one task)
- Ambiguity count: 0
- Duplication count: 0
- Critical issues: 0

### Next Actions

- No CRITICAL or HIGH findings: implementation may proceed.
- Recommended before or within WP05/WP06: resolve U1 (refuse tagged keys) and I1 (document the watch retry behaviour). Both are small spec clarifications plus a test each.
- LOW items can be folded into WP10's documentation sync.
