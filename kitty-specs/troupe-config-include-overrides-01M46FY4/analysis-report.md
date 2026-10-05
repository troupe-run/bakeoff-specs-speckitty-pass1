---
schema_version: 1
artifact_type: spec-kitty.analysis-report
command: /spec-kitty.analyze
mission_slug: troupe-config-include-overrides-01M46FY4
mission_id: 01M46FY4WYKMK8GW2V0RC8QQQ7
generated_at: '2026-10-05T17:17:03.408370+00:00'
analyzer_agent: unknown
input_artifacts:
  spec.md:
    path: kitty-specs/troupe-config-include-overrides-01M46FY4/spec.md
    sha256: 62138923fa9f7bd2db9921d2dcef3e8e976f8f3bf852ebd5dfbe883b25eac83d
  plan.md:
    path: kitty-specs/troupe-config-include-overrides-01M46FY4/plan.md
    sha256: 292003ed5339740da5807fe37136edbfc55553b8f3bce1e00fdb546d7943d904
  tasks.md:
    path: kitty-specs/troupe-config-include-overrides-01M46FY4/tasks.md
    sha256: c6c2aad31f0b93b1560aed35e0f4ac0132492ea6201001cae6a96d440607f343
  charter:
    path: .kittify/charter/charter.yaml
    sha256: a48e59b0f9fb45472e8fd41c29f431bdb475a6b0598bd083c88c6017f4b0ab03
verdict: ready
issue_counts:
  low: 5
  critical: 0
  medium: 2
  high: 0
  info: 0
findings:
- id: I1
  severity: medium
  category: inconsistency
  summary: data-model says YamlInclude.holder is set only for mapping form without overrides; WP01 T003 sets holder on every $ref include and WP03 T015 relies on the merged ref's holder being set (checked after the merged-ref case).
- id: O1
  severity: medium
  category: ownership
  summary: WP03 DoD asks for xfail(strict=True) on two tests in tests/integration/test_set_new_entries.py, a WP04-owned file, to keep the suite green between WP03 and WP04.
- id: C1
  severity: low
  category: coverage
  summary: NFR-001..NFR-004 are not listed in any WP requirement_refs; they are exercised by the byte-snapshot and no-event assertions in WP04/WP05 tests but not traced explicitly.
- id: U1
  severity: low
  category: underspecification
  summary: 'WP02 converts two shapes the spec does not name: an include value on the line after its key, and a whole-document include; both apply the contract rule but are not listed as agent choices in spec D-n.'
- id: I2
  severity: low
  category: inconsistency
  summary: Spec D-5 says the gap before the comment is kept; WP02 applies the step-1 FR-020 column rule for flow and list-item conversions (value changed in place). Different on purpose but the spec wording reads as universal.
- id: I3
  severity: low
  category: inconsistency
  summary: plan.md Project Structure lists test_show_sources.py and test_watch_includes.py extensions; tasks put those tests in the new tests/integration/test_reads_overrides.py instead.
- id: O2
  severity: low
  category: ownership
  summary: WP05 T027 may correct quickstart.md (planning artifact) outside its owned_files; flagged as an out-of-map edit with rationale.
---

## Specification Analysis Report

| ID | Category | Severity | Location(s) | Summary | Recommendation |
|----|----------|----------|-------------|---------|----------------|
| I1 | Inconsistency | MEDIUM | data-model.md (Tree nodes), tasks/WP01 T003, tasks/WP03 T015 | `holder` meaning differs: data-model "without overrides only"; WP01 sets it on every `$ref` include; WP03 checks the merged-ref case first because `ref.holder` is set. | Implementers follow WP01/WP03 (holder = the mapping holding the `$ref`, always); align data-model wording when WP01 lands. |
| O1 | Ownership | MEDIUM | tasks/WP03 DoD; tasks/WP04 T021 | WP03 must mark two WP04-owned tests `xfail(strict=True)` to keep the suite green; WP04 removes them. | Accept as a declared, one-line out-of-map edit; WP03 reviewer checks only the marker changed. |
| C1 | Coverage | LOW | spec.md NFR-001..004; WP frontmatter | NFRs not traced in `requirement_refs`. | Covered by WP04/WP05 snapshot + event-count assertions; WP05 T027 FR/D→test table should include NFRs. |
| U1 | Underspecification | LOW | tasks/WP02 T008 (case 2), T010 (document root) | Two conversion shapes not named in spec. | Both are the contract rule applied to other layouts; record them in the spec Agent choices at acceptance if kept. |
| I2 | Inconsistency | LOW | spec.md D-5; tasks/WP02 T009/T010 | Gap rule vs column rule for comments. | Clarify D-5 to "block-mapping key line" during WP05 agreement check. |
| I3 | Inconsistency | LOW | plan.md Project Structure; tasks.md WP01 | Test file layout differs. | Tasks are authoritative; no action needed. |
| O2 | Ownership | LOW | tasks/WP05 T027 | quickstart.md correction outside owned files. | Allowed with rationale. |

**Coverage Summary Table:**

| Requirement Key | Has Task? | Task IDs | Notes |
|-----------------|-----------|----------|-------|
| FR-001 mapping-form include | Yes | T001, T003, T006 | |
| FR-002 deep merge | Yes | T002, T005, T007 | |
| FR-003 load errors | Yes | T003, T006, T025 | |
| FR-004 reads see merged values | Yes | T004, T007 | |
| FR-005 new key → override | Yes | T014, T015, T022, T024 | |
| FR-006 scalar-form conversion | Yes | T008–T012, T018, T024 | |
| FR-007 extend existing overrides | Yes | T015, T022 | |
| FR-008 existing values where they live | Yes | T013, T022 | |
| FR-009 lists stay in their file | Yes | T014, T022 | |
| FR-010 `--in-include` | Yes | T016, T023 | |
| FR-011 `--in-include` only on `set` | Yes | T020, T023 | |
| FR-012 refusals | Yes | T013, T011, T022, T025 | |
| FR-013 history unchanged in shape | Yes | T022, T026 | |
| NFR-001 shared files untouched | Yes (implicit) | T022, T024 | snapshot assertions |
| NFR-002 byte-surgical writes | Yes (implicit) | T012, T019, T022, T024 | |
| NFR-003 refusals change nothing | Yes (implicit) | T006, T025 | |
| NFR-004 behaviour coverage + gates | Yes | T027 | |

**Charter Alignment Issues:** none. TROUPE-001 (byte preservation: verifier + snapshots), TROUPE-002 (refusals D-1, D-6, D-10, D-11), TROUPE-003 (messages name path/file in WP01/WP03), TROUPE-005/006 (tests per WP, four gates), TROUPE-007 (merge rule in `merge.py`, placement in `placement.py`), TROUPE-008/009 (D-n recorded in spec; spec amended with plan) are all reflected.

**Unmapped Tasks:** none (T027 is delivery/verification, mapped to NFR-004).

**Metrics:**

- Total Requirements: 13 FR + 4 NFR + 5 C
- Total Tasks: 27
- Coverage: 100% of FRs (13/13) with ≥1 task; NFRs covered implicitly
- Ambiguity Count: 0
- Duplication Count: 0
- Critical Issues Count: 0

## Next Actions

- No CRITICAL/HIGH findings: implementation may proceed.
- I1 and O1 are handled by following the WP prompts as written; tidy data-model wording (I1) and D-5 wording (I2), and record U1 shapes, in the WP05 agreement step.
