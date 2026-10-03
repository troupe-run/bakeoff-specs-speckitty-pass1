---
work_package_id: WP03
title: troupe config watch
dependencies:
- WP02
requirement_refs:
- FR-008
- FR-009
- FR-010
- FR-011
- FR-012
- FR-013
- FR-014
- NFR-001
- NFR-002
- NFR-005
- NFR-007
planning_base_branch: feat/troupe-config-sync-files
merge_target_branch: feat/troupe-config-sync-files
branch_strategy: Planning artifacts for this mission were generated on feat/troupe-config-sync-files. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/troupe-config-sync-files unless the human explicitly redirects the landing branch.
subtasks:
- T011
- T012
- T013
- T014
- T015
- T016
- T017
phase: Phase 3 - Watch (User Story 2)
history:
- at: '2026-10-03T03:00:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/troupe/commands/watch.py
create_intent:
- src/troupe/commands/watch.py
- tests/integration/test_watch.py
execution_mode: code_change
model: ''
owned_files:
- src/troupe/cli.py
- src/troupe/commands/watch.py
- src/troupe/commands/__init__.py
- tests/conftest.py
- tests/integration/test_watch.py
role: implementer
tags: []
task_type: implement
tracker_refs: []
---

# Work Package Prompt: WP03 – `troupe config watch`

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter (`agent_profile`, `role`, `agent`), and behave according to its guidance before parsing the rest of this prompt.

If no profile is specified, run `spec-kitty agent profile list` and select the best match for this work package's `task_type` and `authoritative_surface`.

---

## ⚠️ IMPORTANT: Review Feedback

- **Has review feedback?**: Check the `review_ref` field in the event log (via `spec-kitty agent tasks status`) or the Activity Log below.
- **You must address all feedback** before your work is complete.

---

## Objective

Add `troupe config watch [--theatre DIR]`, which:
- runs in the foreground;
- once it can observe changes, prints exactly one line `watching <dir>` to stdout and flushes it;
- records every change to the root file or any included file within 2 seconds;
- keeps running through edits that make the configuration unloadable, reporting them on stderr;
- exits 0 on SIGINT or SIGTERM.

**Requirements**: FR-008, FR-009, FR-010, FR-011, FR-012, FR-013, FR-014, NFR-001, NFR-002, NFR-005, NFR-007.

## Context

Read first:
- `kitty-specs/troupe-config-sync-files-01M3ZT6R/spec.md`: decisions D-1–D-4 and D-8, User Story 2, FR-008–FR-014, Edge Cases
- `kitty-specs/troupe-config-sync-files-01M3ZT6R/contracts/cli-watch.md`: the behaviour table (authoritative for observable behaviour)
- `kitty-specs/troupe-config-sync-files-01M3ZT6R/research.md`: R-03, R-05, R-06, R-09
- `kitty-specs/troupe-config-sync-files-01M3ZT6R/data-model.md`: Watch session state machine
- `src/troupe/cli.py` (output discipline), `src/troupe/theatre.py` (`ROOT_FILE_NAMES`, `locate`)
- WP02 output: `open_session(theatre, *, reconcile=True)` and `troupe.reconcile.watched_files(tree)`

## Branch Strategy

- Planning/base branch: `feat/troupe-config-sync-files`. Final merge target: `feat/troupe-config-sync-files` (then `main`).
- Execution worktrees are allocated per computed lane from `lanes.json`. Run `spec-kitty agent action implement WP03 --agent <name>`.

---

## Subtask T011 — CLI wiring (`src/troupe/cli.py`)

**Steps**:
1. Add the subparser: `watch = commands.add_parser("watch", help="record hand edits as they happen until SIGINT/SIGTERM")`. It takes no positional arguments. Add it to the `_add_theatre_option` loop. Any extra argument becomes an argparse error, which already becomes `UsageError` (exit 2).
2. Compute the theatre **as given** (D-8, FR-009) next to the existing fallback. Keep a single fallback chain:
   ```python
   theatre_arg = args.theatre if args.theatre is not None else os.environ.get(THEATRE_ENV_VAR)
   given = theatre_arg if theatre_arg else os.getcwd()
   theatre = locate(Path(given))
   ```
   `Path.cwd()` and `os.getcwd()` are the same string. Do not resolve `given`.
3. Dispatch long-running commands separately. The step-1 `Command` protocol returns stdout text, which does not fit a command that announces readiness and then keeps running (research R-09):
   ```python
   if args.command == "watch":
       from troupe.commands.watch import watch   # keep lazy import discipline
       watch(theatre, given, announce=_announce, report=_report)
       return 0
   ```
   - `_announce(line)` does `sys.stdout.write(line + "\n"); sys.stdout.flush()`.
   - `_report(message)` does `sys.stderr.write(f"troupe: {message}\n"); sys.stderr.flush()`.
   - Keep `COMMAND_MODULES` for the step-1 commands. If you prefer a small `LONG_RUNNING` mapping, keep the decision in one place.
4. Update the module docstring. stdout is still written only by `cli.py`; for `watch` that happens through the `announce` callback, exactly once, after readiness. A `TroupeError` raised before readiness (e.g. `LoadError` at startup) still gives the usual one-line stderr, empty stdout and its exit code (FR-010).
5. Update `src/troupe/commands/__init__.py`'s docstring to mention the long-running `watch` protocol.

---

## Subtask T012 — `watch` startup (`src/troupe/commands/watch.py`)

**Public function**:
```python
POLL_INTERVAL: Final = 0.25   # seconds; the only place the reaction-time budget is spent (NFR-001)

def watch(
    theatre: Theatre,
    given: str,
    *,
    announce: Callable[[str], None],
    report: Callable[[str], None],
    stop: threading.Event | None = None,
) -> None:
```
`stop` is injectable for in-process tests. When it is `None`, create one and install the signal handlers (T015).

**Startup**:
1. Install the signal handlers first (T015), so a signal during startup is honoured.
2. Call `baseline = _reconcile_and_snapshot(theatre)`. It opens `open_session(theatre, reconcile=True)`; this imports a never-imported theatre (D-3) or reconciles. Inside the session it builds the baseline (T013) from `session.tree`. A `LoadError` here propagates, so the CLI exits 4 and `watching` is never printed (D-4, FR-010).
3. If `stop` is already set, return without announcing.
4. Call `announce(f"watching {given}")` exactly once (FR-009, D-2, D-8).

**Why the baseline makes the line a promise (NFR-002)**: the baseline holds the bytes that the startup load actually read. Any edit that lands after the load, including before or just after the line is printed, makes the current bytes differ from the baseline, so the first poll after it triggers a reconcile.

---

## Subtask T013 — Poll loop and baseline

**Baseline** (`dict[Path, bytes | None]`), built inside a session:
- `watched_files(session.tree)`: resolved paths mapped to the loaded bytes.
- Both root candidates, keyed by `session.theatre.state_dir / name` for `name in ROOT_FILE_NAMES` (unresolved paths, the same ones `locate` checks):
  - The located one (`session.theatre.config_file`) maps to `watched[config_file.resolve()]`, the same loaded bytes. This also works when `troupe.yml` is a symlink.
  - The other one maps to `None`, which means "absent". `locate` just proved it is absent, so do not re-read it.

**Current state**: for each key of the baseline, `path.read_bytes()`. Map `FileNotFoundError` and other `OSError` to `None`, or to a distinct sentinel such as `b"\0unreadable"` if you want unreadable to differ from absent. Either way the next reconcile reports the `LoadError` naming the file.

**Loop**:
```python
while not stop.wait(POLL_INTERVAL):
    if baseline is not None and _current(baseline) == baseline:
        continue
    try:
        baseline = _reconcile_and_snapshot(theatre)
        last_error = None
    except LoadError as err:
        baseline = None                 # unloadable: retry every tick (T014)
        if err.message != last_error:
            report(err.message)
            last_error = err.message
```
- Byte comparison, not mtime (research R-03). A save that writes a temp file and renames it over the original changes bytes at the same path, so it is detected.
- The watched set is recomputed on every successful reconcile (FR-012). A newly added include is in the next baseline, and a removed one drops out.
- The lock is held only inside `_reconcile_and_snapshot` (through `open_session`), never while sleeping.
- Pass the original `theatre` each time. `open_session` re-locates under the lock, so renaming `troupe.yml` to `troupe.yaml` works: the next tick sees the candidate bytes change.

---

## Subtask T014 — Unloadable configuration while watching (D-1, FR-013)

- On `LoadError` during a tick, write **one** stderr line via `report(err.message)`; the message already names the file (TROUPE-003). Record nothing: `open_session` raised before any save.
- While unloadable (`baseline is None`), attempt a reconcile on **every** tick. That covers a missing include target being created, a cycle being broken, or a duplicate root file being deleted, none of which a stale baseline could see (research R-05).
- Report again only if the message differs from the last one reported. When the configuration loads again, clear `last_error`, so a later breakage is reported again.
- Never exit because of a `LoadError` after readiness.
- Other exceptions are bugs. Let them propagate; do not swallow them.

---

## Subtask T015 — Signals (FR-014, NFR-005, research R-06)

- When `stop` is not injected:
  ```python
  stop = threading.Event()
  previous = {sig: signal.signal(sig, lambda *_: stop.set()) for sig in (signal.SIGINT, signal.SIGTERM)}
  try: ...
  finally:
      for sig, handler in previous.items(): signal.signal(sig, handler)
  ```
- The handler only sets the flag, so a reconcile in progress (one atomic `save()`) completes. The loop checks `stop` between ticks, and `stop.wait(POLL_INTERVAL)` returns at once when it is set.
- `watch` returns normally and the CLI returns 0. Nothing further is written to stdout.
- `signal.signal` works only in the main thread. The CLI calls `watch` in the main thread, and in-process tests inject `stop` instead.

---

## Subtask T016 — Test harness (`tests/conftest.py`)

Add importable helpers in the style of `run_cli`:
```python
class WatchProcess:
    """A real ``python -m troupe config watch`` child; use as a context manager (always killed)."""
    def __init__(self, *args: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> None
        # Popen([sys.executable, "-m", "troupe", "config", "watch", *args], stdout=PIPE, stderr=PIPE)
        # strip TROUPE_THEATRE from the inherited env like run_cli
        # start reader threads that push stdout lines / stderr lines into queues/lists
    def wait_ready(self, timeout: float = 10.0) -> str     # first stdout line (raises on timeout or exit)
    def stderr_lines(self) -> list[str]
    def stop(self, sig: int = signal.SIGINT, timeout: float = 5.0) -> tuple[int, str, str]
        # send signal, wait, return (exit code, remaining stdout, all stderr)
    def __enter__/__exit__   # __exit__ kills the child if still running

def history_events(theatre: Path) -> list[dict[str, object]]   # run_cli history → json.loads per line

def recorded_within(theatre: Path, edited_at: float, seconds: float = 2.0) -> list[dict[str, object]]:
    """Wait until ``edited_at + seconds``, then return ``history``.

    This is the contract check itself (FR-011): a ``history`` started that late must already show
    the edit.
    """
```
- Use `time.monotonic()` for `edited_at`.
- Decode bytes as UTF-8 without newline translation.
- The 10-second startup timeout is generous because subprocess Python startup can be slow on CI. It is not part of the 2-second contract, which starts when the line appears.

---

## Subtask T017 — `tests/integration/test_watch.py`

Each test uses `with WatchProcess("--theatre", str(theatre)) as w:` and stops `w` before its final assertions where needed. Scenario numbers refer to US2:
1. `test_watch_prints_exactly_watching_dir_and_nothing_else` (1, D-2): the line equals `f"watching {theatre}"`. After an edit and a stop, the remaining stdout is `""`.
2. `test_watching_line_echoes_theatre_argument_verbatim` (D-8): pass a **relative** `--theatre` (run with `cwd=theatre.parent`, arg `theatre.name`) and also a path with a trailing slash. The line echoes each exactly.
3. `test_watching_line_uses_env_var_then_cwd_when_no_option` (D-8).
4. `test_root_file_edit_is_recorded_within_two_seconds` (2, NFR-001).
5. `test_edit_immediately_after_watching_line_is_not_missed` (NFR-002): edit in the same instant the line is read, keeping the file size the same (`a: 1` → `a: 2`).
6. `test_yaml_include_and_text_include_edits_are_recorded` (3).
7. `test_comment_only_and_formatting_only_edits_record_nothing` (4): wait 2.5 s, then the history is unchanged.
8. `test_sigint_and_sigterm_exit_zero_within_two_seconds` (5, NFR-005): parametrize over the two signals.
9. `test_watch_imports_a_never_imported_theatre_before_the_line` (6): `.troupe/history.sqlite` exists as soon as the line is read, before any other command runs.
10. `test_watch_on_unloadable_configuration_exits_4_without_the_line` (7): parametrize over no root file, both root files, bad YAML, missing include and an include cycle. Check exit 4, stdout `""`, and that stderr names the file.
11. `test_unloadable_edit_reports_once_keeps_watching_then_recovers` (8, D-1):
    - Write bad YAML: wait until one stderr line names the file, and `history` is unchanged.
    - Write different bad YAML that gives the same message: no new line. Write an error with a different message: one more line.
    - Fix the file with a changed value: the value is recorded within 2 s.
    - Stop: exit 0.
12. `test_missing_include_target_created_later_is_recorded` (US4 scenario 3, owned here because it exercises the unloadable retry): add the include line first, then create the target. Its leaves are recorded within 2 s.
13. `test_rapid_successive_saves_settle_without_duplicates` (9): 5 saves 50 ms apart ending on the value 5. After 2 s, the recorded configuration equals the file, and no two consecutive events record the same `old → new`.
14. `test_atomic_rename_save_is_detected`: write a temp file and `os.replace` it over the root.
15. `test_watch_with_extra_argument_exits_2` (FR-008): `run_cli("config", "watch", "x", "--theatre", ...)` exits 2 with empty stdout.
16. `test_watch_never_changes_configuration_files` (NFR-004): snapshot before and after a session with edits; equal to the hand-edited bytes.

Never assert on a bare sleep except as the contract deadline (`recorded_within`) or the "nothing recorded" wait (2.5 s). Always clean up the child.

---

## Definition of Done

- [ ] `watch` implemented per the contract table. `POLL_INTERVAL` is defined in exactly one place.
- [ ] stdout is written only by `cli.py`: once for `watch`, and never on a non-zero exit.
- [ ] All tests in T017 pass reliably. Run the watch suite 3 times in a row and show the output.
- [ ] Gates run and output shown: `uv run pytest`, `uv run mypy --strict`, `uv run ruff check`, `uv run ruff format --check`.
- [ ] `spec-kitty agent tasks mark-status T011 T012 T013 T014 T015 T016 T017 --status done --mission troupe-config-sync-files-01M3ZT6R`.

## Risks

- **Flakiness**: use deadlines and always clean up the children. The 2-second contract has ample headroom (one tick of 0.25 s plus a reconcile of milliseconds).
- **Signal handler restoration**: restore the previous handlers in `finally`, so in-process callers are not left with altered handlers.
- **Printing the line before the baseline exists** breaks NFR-002. The order is load, then baseline, then announce.

## Reviewer Guidance

- Verify that the baseline is built from the loaded texts, not from a separate read after the session.
- Verify that the unloadable state retries every tick and reports only on a message change.
- Verify the exit code is 0 on both signals and that stdout holds exactly one line.
- Verify `watching <dir>` uses the argument as given, never resolved.

## Activity Log

- 2026-10-03T03:00:00Z – system – Prompt generated via /spec-kitty.tasks
