# Mission Review Report: troupe-config-include-overrides-01M46FY4

**Reviewer**: claude (orchestrator; post-merge review, independent of the per-WP reviews)
**Date**: 2026-10-05
**Mission**: `troupe-config-include-overrides-01M46FY4` — troupe configuration: keep shared includes shared (step 5, CR-A Overrides + CR-B In-include)
**Baseline commit**: `7fe7040` (`main` before this mission)
**HEAD at review**: `ded0223` (`main`, merge of `feat/troupe-config-include-overrides`)
**WPs reviewed**: WP01..WP05 (all `done`; WP04 had one rejection cycle, fixed and approved on cycle 2; no arbiter overrides, no self-approvals)

---

## Gate Results

### Gate 1 — Contract tests
- Command: `uv run pytest tests/contract/ -v`
- Result: NOT APPLICABLE. This repository has no `tests/contract/` suite. The gate belongs to the spec-kitty repository itself. The mission's CLI contract (`contracts/cli.md`) is exercised by the integration tests listed below.

### Gate 2 — Architectural tests
- Command: `uv run pytest tests/architectural/ -v`
- Result: NOT APPLICABLE. There is no `tests/architectural/` suite in this repository.

### Gate 3 — Cross-repo E2E
- Result: NOT APPLICABLE. This is a single repository with no cross-repo behaviour and no e2e scenario repository.

### Gate 4 — Issue Matrix
- File: none. `spec.md` references no GitHub issues, so no `issue-matrix.json` was scaffolded.
- Result: NOT APPLICABLE.

### Project quality gates (charter TROUPE-006), run on the merged tree before delivery
- `uv run pytest -q`: 1848 passed
- `uv run mypy --strict`: Success, no issues in 75 source files
- `uv run ruff check`: All checks passed
- `uv run ruff format --check`: 79 files already formatted
- The merged code is identical to the reviewed lane-e code: `git diff a8888cd ded0223 -- src tests pyproject.toml uv.lock` is empty.

---

## FR Coverage Matrix

| FR ID | Description (brief) | WP Owner | Test File(s) | Test Adequacy | Finding |
|-------|---------------------|----------|--------------|---------------|---------|
| FR-001 | Mapping-form include (`$ref` alone = scalar form) | WP01 | tests/integration/test_loading_ref.py | ADEQUATE | — |
| FR-002 | Deep merge (mappings merge; scalars/lists replace; key order) | WP01 | tests/unit/test_merge.py; tests/integration/test_reads_overrides.py | ADEQUATE | — |
| FR-003 | Load errors exit 4 (D-1, D-7, non-YAML siblings, missing/cycle) | WP01 | tests/integration/test_loading_ref.py; test_overrides_acceptance.py | ADEQUATE | — |
| FR-004 | Reads see merged values; `--sources` names the including file | WP01 | tests/integration/test_reads_overrides.py | ADEQUATE | — |
| FR-005 | New key under an include → override in the nearest including file | WP03/WP04 | test_set_overrides.py; test_set_new_entries.py; test_overrides_acceptance.py | ADEQUATE | RISK-2 (by design) |
| FR-006 | Scalar-form conversion (block/flow/list item/comment/CRLF/indent) | WP02/WP04 | tests/unit/test_collections.py; test_set_overrides.py; test_overrides_acceptance.py | ADEQUATE | — |
| FR-007 | Existing override mappings extended | WP03/WP04 | test_set_overrides.py | ADEQUATE | — |
| FR-008 | Existing values change where they live | WP03/WP04 | test_set_overrides.py; test_overrides_acceptance.py | ADEQUATE | — |
| FR-009 | List appends / keys in list items stay in the list's file | WP03/WP04 | test_set_overrides.py | ADEQUATE | — |
| FR-010 | `set --in-include` = step-1 rule, innermost file | WP03/WP04/WP05 | test_set_in_include.py; test_overrides_acceptance.py | ADEQUATE | — |
| FR-011 | `--in-include` only on `set` | WP04 | test_set_in_include.py | ADEQUATE | — |
| FR-012 | Refusals exit 3 (whole include, `$ref` segment, D-10, D-11) | WP03/WP04/WP05 | test_set_overrides.py; test_overrides_acceptance.py; tests/unit/test_placement_overrides.py | ADEQUATE | — |
| FR-013 | History shape unchanged (one `set` per created leaf; reconcile on merged leaves) | WP04/WP05 | test_overrides_acceptance.py; test_reads_overrides.py | ADEQUATE | — |

Every adequacy rating rests on the same evidence: the tests drive the real CLI as a subprocess against real files. They assert exact bytes of every file in the theatre (`snapshot`) and the real event store (`history_events`). Refusal tests use one helper, `_assert_refused` (`tests/integration/test_overrides_acceptance.py:88`). It checks the exit code, empty stdout, one stderr line naming the path or file, an unchanged snapshot and an unchanged event list. Deleting the implementation would fail them. NFR-001..NFR-003 are carried by these same byte and event assertions; NFR-004 is met by the gates above.

---

## Drift Findings

None.

- **Locked decisions:** both are honoured in the code, and both have dedicated tests.
  - DM 01M46FYYFFXXZE893KWDP2WJCW (nested includes → nearest including file) is implemented by `placement._include_ref`.
  - DM 01M46G0570NBW27MB152E1ZQ8K (malformed `$ref` → exit 4) is implemented by `loader._ref_include`.
- **Agent choices:** D-1..D-11 each have tests (WP05 FR/D table).
- **The step-1 rule that changed:** the only expectation changes to step-1 tests are the two that the contract changes (Overrides replaces rule 2), and each has an `--in-include` twin that keeps the step-1 output.
- **Owned files:** every WP-owned file appears in the diff. Out-of-map edits were declared in commit messages:
  - WP03: xfail markers, later removed by WP04;
  - WP04: the `REF_KEY` import and the `_refuse_properties` backstop in `collections.py`;
  - WP05: the `_orders` recursion and docstrings in `apply.py`.

---

## Risk Findings

### RISK-1: Pre-write verifier does not check which side or file a value lands in

**Type**: BOUNDARY-CONDITION
**Severity**: LOW
**Location**: `src/troupe/writeback/apply.py`, `_same_outside` / `_orders`
**Trigger condition**: a renderer bug that writes a new key into the wrong file of an include chain, or moves a value between an included file and its override while keeping the merged result.

**Analysis**: The verifier compares merged views by `ref` target, merged entries and the allowed key orders. Crafted outputs confirm two gaps, both found by the WP04 and WP05 reviews:
- With chained includes, the new key written at the end of an intermediate file would still pass.
- Off the route to PATH, a value moving between the include and its override with an identical merged result would pass.

Placement chooses the file correctly, and no CLI input reaches either case: all story tests snapshot every file and show the key in the intended file. So this is defence in depth, not a user-visible defect. It is tracked as bead `bakeoff-specs-speckitty-c22` (P3).

### RISK-2: The nearest-include rule can write into an intermediate shared file

**Type**: BOUNDARY-CONDITION (by design)
**Severity**: LOW (informational)
**Location**: `src/troupe/writeback/placement.py`, `_include_ref` / `_on_side`
**Trigger condition**: the included file itself contains a mapping-form include. Example: `troupe.yml` has `coder: file:c.yaml`; `c.yaml` has `tools: {$ref: file:d.yaml, mid: 1}`; then `set coder.tools.t 1`.

**Analysis**: The key is written into `c.yaml` as an override next to `mid`. `c.yaml` is the file holding the include reference nearest the key's ancestor, as the contract defines the including file, and the product owner confirmed this for nested includes (DM 01M46FYYFFXXZE893KWDP2WJCW). This review reproduced it through the CLI. It matches the spec, but in this layout `set` modifies `c.yaml`, which is itself included by another file. A product owner who wants "never modify any included file" would need a contract change. Recorded so the behaviour is not a surprise; no action required under the current contract.

---

## Silent Failure Candidates

| Location | Condition | Silent result | Spec impact |
|----------|-----------|---------------|-------------|
| `placement.concrete_parent` | node is a document root | returns `None` | None: documented; callers treat `None` as "include is the whole document" (`ConvertInclude.parent=None`) and convert at column 0 (tested) |
| `placement._include_ref` | no include targets the ancestor's file, or a list lies between | returns `None` | None: documented; means "step-1 rule" (tested) |
| 5 new `assert`s (`merge.deep_merge`, `placement._on_side`, `_on_base`, `apply._concrete`) | an internal invariant is broken | `AssertionError` traceback (exit 1), not exit 3/5 | None reachable: the loader validates first (D-7). Noted by the WP03 review as a robustness point. |

There is no `except …: return ""/None/[]` or `pass` anywhere in the mission's source diff.

---

## Security Notes

| Finding | Location | Risk class | Recommendation |
|---------|----------|------------|----------------|
| No new subprocess, shell, network or `open()` calls in the mission diff | `git diff 7fe7040..HEAD -- src` | — | — |
| `$ref` targets resolve exactly like step-1 `file:` includes, relative to the containing file and not confined to the theatre. `set` (now also through `--in-include` and conversions) writes only to files the configuration already includes. | `loader._ref_include` → `_include` | PATH-TRAVERSAL (pre-existing, unchanged) | No change in this mission; the include model has been unconfined since step 1. If confinement is ever wanted, it is a contract change for every include form. |
| Writes stay atomic (temp file + rename), and a conversion plus its override is one write of one file | `writeback.fileio.write_files` (unchanged) | — | — |

---

## Final Verdict

**PASS WITH NOTES**

### Verdict rationale

- All 13 functional requirements are covered by tests that drive the real CLI against real files and the real event store, and they would fail if the implementation were removed.
- No locked decision, product-owner decision or agent choice (D-1..D-11) is violated, and the only step-1 expectations that changed are the two the contract changes.
- All four project gates pass on the merged tree (1848 tests).
- No security finding was introduced.
- The two risk findings are LOW. One is verifier defence in depth, already tracked as bead c22. The other is a documented consequence of the product owner's nested-include decision.

### Open items (non-blocking)

- Bead `bakeoff-specs-speckitty-c22` (P3): make the verifier confirm which file the added key was written to, and compare the include and override sides off the route.
- RISK-2: if "never modify any file that is itself included" is the intent, it needs a contract change (product owner decision).
- The coordination worktree `.worktrees/troupe-config-include-overrides-01M46FY4-coord` remains because `spec-kitty merge` could not delete the branch it has checked out. Removing it is optional cleanup.

## Retrospective Reminder

The retrospective was captured during merge (commit `619b046`) at `kitty-specs/troupe-config-include-overrides-01M46FY4/retrospective.yaml`. It is not at the `.kittify/missions/<mission_id>/` path the skill names; this spec-kitty install keeps it in the mission directory. Next, surface its findings:

- `spec-kitty retrospect summary`: cross-mission aggregation (read-only)
- `spec-kitty agent retrospect synthesize --mission troupe-config-include-overrides-01M46FY4`: inspect proposals (dry-run by default; add `--apply` to mutate)
