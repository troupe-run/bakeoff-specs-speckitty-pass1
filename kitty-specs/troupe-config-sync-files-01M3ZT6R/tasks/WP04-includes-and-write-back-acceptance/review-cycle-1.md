---
affected_files: []
cycle_number: 1
mission_slug: troupe-config-sync-files-01M3ZT6R
reproduction_command:
reviewed_at: '2026-10-03T04:31:52Z'
reviewer_agent: user
wp_id: WP04
---

# WP04 review feedback (cycle 1): changes requested

Gates are green (1274 passed in 221 s; mypy --strict, ruff check and ruff format --check are clean). The US3/US4 tests are good: they assert exact event lists, use multisets or the full set of allowed orderings for races, test nothing outside the contract (C-003), match their names, stop their children inside context managers, and have deadlines on every wait. One blocking issue remains.

## Issue 1 (blocking): no test fails when the theatre lock is removed (FR-016, NFR-003, charter "a test that can fail")

**Evidence (reviewer mutation runs on scratch copies; the worktree was not touched):**

- Mutant A: delete the lock from `session.py` (`with theatre_lock(...)` replaced by `if True:`). Running the **full suite** against this mutant gives **1274 passed**. No test anywhere protects FR-016. `tests/unit/test_lock.py` tests the primitive only, so it cannot see whether sessions actually take the lock.
- Mutant B: make `flock` a no-op in `lock.py`. The unit lock test catches this, but every WP04 race test still passes. As the implementer reported, `watch` (0.25 s poll) always reconciles before the subprocesses have started, so `test_hand_edit_with_concurrent_show_and_watch_is_recorded_once`, `test_hand_edit_just_before_set_is_recorded_once` and `test_history_has_no_gaps_or_duplicate_seq_after_races` never actually race.

**A black-box test that detects the missing lock is feasible and cheap.** The reviewer measured this design: fresh theatre, imported once; then each round makes a hand edit to `troupe.yml` (`model.name: m<r>`) and immediately `Popen`s 3 `config show model.name` subprocesses together, with **no `watch`**; wait for all of them, then assert that every exit code is 0 **and** that exactly one new event exists, `set model.name m<r-1>→m<r>`.

| Build | Rounds (k=3 unless noted) | Failing rounds | Trials that detected it |
|---|---|---|---|
| session lock removed | 3 × 30 | 8, 6, 7 (23 %) | 3/3 |
| flock no-op | 4 × 20 | 4, 4, 3, 4 (19 %) | 4/4 |
| flock no-op, k=6 | 3 × 20 | 4, 1, 5 | 3/3 |
| real lock | 20 + 20 (k=6) + 30 | 0 | no false positives |

The failure modes seen are `IntegrityError: UNIQUE constraint failed: stored_events...` (exit 1) and the edit recorded twice. At about 20 % per round, **30 rounds miss with probability about 0.8^30 ≈ 0.1 %**, at a cost of about 17 s. 20 rounds would cost about 11 s with about 1.5 % misses. 30 is recommended.

**Requested change** (in `tests/integration/test_watch_set.py`, which you own):

1. Add `test_concurrent_commands_record_a_hand_edit_exactly_once` (or similar), with no `watch`, as described above: 30 rounds, 3 `show` processes started together with `Popen` (not a thread pool around `run_cli`, so that start-up overlaps as much as possible). Every process must exit 0 with stdout `m<r>\n` and empty stderr, the round must add exactly one event `("set","model.name",prev,new)`, and `_assert_well_formed` must hold at the end. Give every wait a timeout, and kill and reap children in `finally`.
2. Verify it yourself: temporarily remove the lock in `session.py` (and separately make `flock` a no-op), run the new test about 3 times, check that it fails every time, then restore the code. Report the measured failure counts and runtime in your completion note. Do not commit the mutation.
3. In the docstring or comments of `test_hand_edit_with_concurrent_show_and_watch_is_recorded_once`, state honestly that `watch` usually reconciles first, so this test checks that the commands do not duplicate the edit afterwards. It is not the lock-detecting race; the new test is.

## Non-blocking notes (for the orchestrator, no WP04 action required)

- `quickstart.md` is not portable. `sed -i` is GNU-only (BSD/macOS needs `sed -i ''`). The fixed `/tmp/t` is never cleaned, so a second run starts from a stale history. `kill -INT %1` relies on job control: in a non-interactive script, bash starts background jobs with SIGINT ignored, so `watch` would not stop. Suggestions: use `mktemp -d`, a portable edit (`perl -pi -e` or a `printf` rewrite), and `kill -INT $!`.
- The WP04 prompt (T022.5) labels the "only config files plus `history.sqlite*`, no lock/temp file" check as NFR-003. In spec.md, NFR-003 is "No duplicate events". The file-set check belongs to a different requirement. The FR→test table and the status bookkeeping should map it correctly.
- The one-assertion follow-up in `test_reconcile_first.py` (history exits 4 with empty stdout while the file is broken) is correct and in scope as an orchestrator request. It is a shared-file touch with WP02 and is noted here for coordination.
