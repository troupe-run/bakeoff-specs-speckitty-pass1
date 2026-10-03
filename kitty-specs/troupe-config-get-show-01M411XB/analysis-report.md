---
schema_version: 1
artifact_type: spec-kitty.analysis-report
command: /spec-kitty.analyze
mission_slug: troupe-config-get-show-01M411XB
mission_id: 01M411XBPYCFHFT2CTA5MR35YA
generated_at: '2026-10-03T15:02:16.982035+00:00'
analyzer_agent: unknown
input_artifacts:
  spec.md:
    path: kitty-specs/troupe-config-get-show-01M411XB/spec.md
    sha256: 4dd2da5ddf7eed6d0d7e93373cb925822ed0f22fc517a3f00c746d2b3b05422b
  plan.md:
    path: kitty-specs/troupe-config-get-show-01M411XB/plan.md
    sha256: 6789646ede2364cfd9552c750b7da24ccce60808ed9c0f98ce89917a32b51b77
  tasks.md:
    path: kitty-specs/troupe-config-get-show-01M411XB/tasks.md
    sha256: 169580b0d196dd5314924b1c4aaad3dd73bed5a8db7cde076c94f64e60d3fa00
  charter:
    path: .kittify/charter/charter.yaml
    sha256: a48e59b0f9fb45472e8fd41c29f431bdb475a6b0598bd083c88c6017f4b0ab03
verdict: ready
issue_counts:
  high: 0
  low: 6
  critical: 0
  medium: 1
  info: 0
findings:
- id: I1
  severity: low
  category: inconsistency
  summary: FR-015 help wording for show ('print PATH, or everything, as YAML') differs from WP03 T012 ('print PATH, or the whole configuration, as YAML').
- id: I2
  severity: low
  category: inconsistency
  summary: Spec uses the canonical term 'Section' for mapping/list while contract and WP prompts say 'mapping or list'; meaning is identical.
- id: O1
  severity: medium
  category: ownership
  summary: WP03 edits src/troupe/cli.py, owned by WP02 (pre-authorised out-of-map edit limited to the show subparser); reviewers must check the scope.
- id: U1
  severity: low
  category: underspecification
  summary: File names containing line breaks in --sources labels are left unhandled (research D-6); acceptable, but untested.
- id: C1
  severity: low
  category: coverage
  summary: Step-1 mission's contracts/cli.md still describes show as scalar-only; it is a historical artifact superseded by C-001, so no change is planned.
- id: R1
  severity: low
  category: inconsistency
  summary: 'Re-analysis after WP01 review: research D-10 and FR-008 now require plain strings to read back under YAML 1.2 and 1.1; WP01 rework tracks it, and WP03 parse-back tests inherit it.'
- id: R2
  severity: low
  category: inconsistency
  summary: "D-10 extended to floats: show's YAML writes exponent floats with a '.' (1.0e+20); show on a scalar without --sources must keep get's repr() output (FR-004), so WP03 must not route that case through the renderer."
---

## Specification Analysis Report

| ID | Category | Severity | Location(s) | Summary | Recommendation |
|----|----------|----------|-------------|---------|----------------|
| I1 | Inconsistency | LOW | spec.md FR-015; tasks/WP03 T012 | `show` help wording differs slightly between the spec and the WP prompt | The implementer may use either wording. FR-015 tests check that `get`, `show` and `--sources` are listed, not exact help text |
| I2 | Terminology | LOW | spec.md Domain Language; contracts/cli.md | "Section" vs "mapping or list" | Synonyms with the same meaning; no action needed |
| O1 | Ownership | MEDIUM | tasks/WP03 "Pre-authorised out-of-map edit"; lanes.json lane-b | WP03 changes `cli.py` (owned by WP02) | Safe because WP03 depends on WP02 (sequential). The reviewer must confirm the diff touches only the `show` subparser |
| U1 | Underspecification | LOW | research.md D-6 | Newlines in file names are not handled in source labels | Accept as recorded; the contract is silent |
| R1 | Inconsistency | LOW | research.md D-10; spec.md FR-008 | Added after the WP01 review: plain strings must read back under YAML 1.2 and 1.1 | Covered by WP01 rework (review-feedback-1); WP03 uses the renderer unchanged |
| R2 | Inconsistency | LOW | research.md D-10; spec.md FR-008, FR-004 | Exponent floats in YAML get a `.`; plain scalar output stays repr() | WP03: scalar without `--sources` uses `format_scalar`, never `render` |
| C1 | Coverage | LOW | kitty-specs/troupe-config-load-show-set-01M3XGPG/contracts/cli.md | Old contract describes `show` as scalar-only | Historical artifact superseded by C-001; leave unchanged |

**Coverage Summary Table:**

| Requirement Key | Has Task? | Task IDs | Notes |
|-----------------|-----------|----------|-------|
| FR-001 get-scalar | Yes | T006, T007, T009 | |
| FR-002 get-refuses-sections | Yes | T007, T009 | |
| FR-003 missing-path-exit-5 | Yes | T009, T013 | |
| FR-004 show-scalar-like-get | Yes | T011, T013 | |
| FR-005 show-section-yaml | Yes | T003, T005, T011, T013 | |
| FR-006 show-whole-config | Yes | T011, T013 | |
| FR-007 literal-blocks | Yes | T002, T005 | |
| FR-008 yaml-layout | Yes | T002, T003, T005 | |
| FR-009 sources-comments | Yes | T001, T004, T014 | |
| FR-010 source-file-label | Yes | T001, T004, T014 | |
| FR-011 block-header-comment | Yes | T004, T014 | |
| FR-012 scalar-path-sources | Yes | T011, T014 | |
| FR-013 reconcile-first | Yes | T009, T010, T013 | |
| FR-014 read-only | Yes | T009, T013 | |
| FR-015 help-text | Yes | T008, T012, T013 | |
| NFR-001 round-trip | Yes | T005, T013, T014 | |
| NFR-002 error-discipline | Yes | T009, T013 | |
| NFR-003 quality-gates | Yes | every WP's Definition of Done, T015 | |
| NFR-004 scalar-compat | Yes | T009, T010, T013 | |
| C-001..C-004 | Yes | T009, T010, T015 | C-002 (delivery to main) is handled at merge, outside WPs |

**Charter Alignment Issues:** None. TROUPE-001 (read-only, tested), -003 (errors name the path), -005 (exact-byte and parse-back tests), -006 (gates in each DoD), -007 (reuse of writeback quoting; named constants), -008/-009 (decisions recorded in the DM and research D-1..D-9; spec amended together with the plan).

**Unmapped Tasks:** None. T015 maps to NFR-003 and C-004.

**Metrics:**

- Total Requirements: 23 (15 FR, 4 NFR, 4 C)
- Total Tasks: 15
- Coverage %: 100%
- Ambiguity Count: 0
- Duplication Count: 0
- Critical Issues Count: 0

## Next Actions

- No CRITICAL or HIGH findings: implementation may proceed.
- O1: reviewers of WP03 check that the `cli.py` diff is limited to the `show` subparser.
