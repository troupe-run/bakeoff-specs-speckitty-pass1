---
work_package_id: WP10
title: Acceptance, documentation sync and gates
dependencies:
- WP09
requirement_refs:
- C-001
- C-003
- C-004
- NFR-001
- NFR-002
- NFR-003
- NFR-005
planning_base_branch: feat/troupe-config-remote-includes
merge_target_branch: feat/troupe-config-remote-includes
branch_strategy: Planning artifacts for this mission were generated on feat/troupe-config-remote-includes. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/troupe-config-remote-includes unless the human explicitly redirects the landing branch.
subtasks:
- T045
- T046
- T047
phase: Phase 4 - Acceptance
history:
- at: '2026-10-07T18:00:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: tests/integration/test_remote_acceptance.py
create_intent:
- tests/integration/test_remote_acceptance.py
execution_mode: code_change
model: ''
owned_files:
- tests/integration/test_remote_acceptance.py
role: implementer
tags: []
task_type: implement
tracker_refs:
- bakeoff-specs-speckitty-1j5
---

# Work Package Prompt: WP10 – Acceptance, documentation sync and gates

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter (`agent_profile`, `role`, `agent`), and behave according to its guidance before parsing the rest of this prompt.

If no profile is specified, run `spec-kitty agent profile list` and select the best match for this work package's `task_type` and `authoritative_surface`.

---

## ⚠️ IMPORTANT: Review Feedback

- **Has review feedback?**: Check the `review_ref` field in the event log (via `spec-kitty agent tasks status`) or the Activity Log below.
- **You must address all feedback** before your work is complete.

---

## Objective

Close the mission:

1. **Cross-cutting acceptance tests** for the non-functional requirements and edge cases that no single story owns.
2. **The quickstart walk-through**, actually run.
3. **Spec, contract and code agreement** (TROUPE-009, DIRECTIVE_037).
4. **Full gates with output** (TROUPE-006), and beads for anything left open (TROUPE-008).

## Context

- Spec: NFR-001 to NFR-005, C-001 to C-006, Edge Cases, SC-001 to SC-005.
- `quickstart.md`, `contracts/cli.md`, research R-1 to R-13 and the adversarial findings (A-1, A-6 deferred).
- Beads: feature `bakeoff-specs-speckitty-1j5`. Related existing bead: `bakeoff-specs-speckitty-0uv` (PermissionError during include resolution). Check whether remote loading changed it; do not fix it here.

## Branch Strategy

- Planning/base branch: `feat/troupe-config-remote-includes`. Final merge target: `feat/troupe-config-remote-includes`, which is merged into `main` locally after acceptance.
- Run `spec-kitty agent action implement WP10 --agent <name>`. It depends on WP09.

## Subtasks

### T045 — `tests/integration/test_remote_acceptance.py`

1. **NFR-001**: across a scripted sequence of every refused remote write (US2 scenarios 1–4, `--expand-alias` and `--in-include`), the server log holds only `GET` requests, and the snapshot is unchanged.
2. **NFR-002**: parametrise over one case per exit code (2: bad VALUE tag / `--include` on `get`; 3: remote write, schema violation; 4: failed fetch, invalid schema; 5: bad path). Each changes 0 files and records 0 events: compare `snapshot` and `history_events` before and after.
3. **NFR-003**: one representative successful `set` per new write shape (`!literal` new key, tag kept, tag inserted, tag removed, local override under a remote include, `--include` remote). Assert byte-exact files and that untouched files are byte-identical.
4. **Edge cases** (spec list):
   - the same URL included twice is fetched once;
   - an anchor on a remote include reference → exit 4;
   - remote YAML using anchors, aliases and merge keys reads correctly and is read-only;
   - an aliased string whose anchored node is literal by schema stays literal;
   - a redirect to `ftp://` → exit 4;
   - `watch` reports a failed fetch and keeps running;
   - a `set` on an unrelated path with a failing remote → exit 4.
5. **History and lineage** with remote leaves:
   - `set --reason r` on a local override under a remote include records the CLI lineage;
   - an upstream change is recorded with file lineage on the next command;
   - `history team` lists remote leaves.

### T046 — Quickstart and documentation agreement

1. Run `quickstart.md` step by step in a temporary directory, with the stand-in server on a free port; substitute the port. Paste the transcript into the Activity Log. Every annotated outcome must match. If one does not, the code or the quickstart is wrong: fix whichever disagrees with the spec, via a recorded out-of-map edit or by sending it back.
2. Compare `contracts/cli.md`'s message table with the messages the code actually prints, using the test outputs. Fix any drift in the **contract file** (planning artifact, `kitty-specs/…/contracts/cli.md`) in a separate commit whose message says why, unless the code contradicts the spec, in which case fix the code.
3. Check that every S-n in spec.md has at least one test whose name or docstring cites it. List S-n → test in the Activity Log (NFR-005).
4. Module docstrings of `location`, `remote`, `includes`, `schema`, `configuration`, `loader`, `placement`, `apply`, `yamlcore`, `scalars`, `blocks`, `aliases`, `reconcile`, `watch` and `cli` describe step-7 behaviour. Fix stale ones; docstrings are in the owning files, so record any out-of-map docstring-only edits.

### T047 — Gates and close-out

1. Run and paste the output of `uv run pytest`, `uv run mypy --strict`, `uv run ruff check` and `uv run ruff format --check`. Note any skipped tests and why; the TLS test must not be skipped here, since `openssl` is installed in this environment.
2. File beads for follow-ups found during the mission:
   - adversarial A-1 (no size limit on remote bodies), as a P3 decision for the product owner;
   - A-6 (`http://` in clear text, no warning), P4;
   - anything found in T045 and T046.

   Link them to `bakeoff-specs-speckitty-1j5`.
3. Do **not** close `bakeoff-specs-speckitty-1j5`; acceptance and merge do that.

## Definition of Done

- The acceptance tests pass, the quickstart transcript matches, the docs agree, all four gates pass with output pasted, and the follow-up beads are filed with their IDs listed.

## Reviewer guidance

- NFR tests check snapshots and history, not only exit codes.
- The quickstart transcript is real output.

## Activity Log

- 2026-10-07T18:00:00Z – system – Prompt generated via /spec-kitty.tasks
