---
work_package_id: WP01
title: Project skeleton, CLI and error model
dependencies: []
requirement_refs:
- C-001
- C-003
- C-006
- FR-001
- FR-002
- FR-006
- NFR-004
- NFR-005
planning_base_branch: feat/troupe-config-load-show-set
merge_target_branch: feat/troupe-config-load-show-set
branch_strategy: Planning artifacts for this mission were generated on feat/troupe-config-load-show-set. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/troupe-config-load-show-set unless the human explicitly redirects the landing branch.
base_branch: kitty/mission-troupe-config-load-show-set-01M3XGPG
base_commit: 460f34eff5796f7eacb5cc131cffdb715237b9a7
created_at: '2026-10-02T06:18:33.847983+00:00'
subtasks:
- T001
- T002
- T003
- T004
- T005
phase: Phase 1 - Foundation
agent: claude
history:
- at: '2026-10-02T06:01:37Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/troupe/cli.py
create_intent:
- pyproject.toml
- uv.lock
- .python-version
- src/troupe/__init__.py
- src/troupe/__main__.py
- src/troupe/cli.py
- src/troupe/errors.py
- src/troupe/theatre.py
- src/troupe/commands/__init__.py
- tests/conftest.py
- tests/integration/test_cli_basics.py
execution_mode: code_change
model: ''
owned_files:
- pyproject.toml
- uv.lock
- .python-version
- src/troupe/__init__.py
- src/troupe/__main__.py
- src/troupe/cli.py
- src/troupe/errors.py
- src/troupe/theatre.py
- src/troupe/commands/__init__.py
- tests/conftest.py
- tests/integration/test_cli_basics.py
role: implementer
tags: []
task_type: implement
tracker_refs: []
---

# Work Package Prompt: WP01 – Project skeleton, CLI and error model

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter (`agent_profile`, `role`, `agent`), and behave according to its guidance before parsing the rest of this prompt.

If no profile is specified, run `spec-kitty agent profile list` and select the best match for this work package's `task_type` and `authoritative_surface`.

---

## ⚠️ IMPORTANT: Review Feedback

- **Has review feedback?**: Check the `review_ref` field in the event log (via `spec-kitty agent tasks status`) or the Activity Log below.
- **You must address all feedback** before your work is complete.

## Review Feedback

*[Populated if this WP is returned from review.]*

---

## Objectives & Success Criteria

Create the `troupe` Python project so that `uv run troupe config <subcommand> …` runs from the
repository root, with the exit-code and stdout/stderr discipline every later WP relies on.

Done when:
- `uv sync` installs the project; `uv run troupe config --help` works.
- Malformed invocations exit **2**; a theatre with no root file, or with both `troupe.yml` and
  `troupe.yaml`, exits **4** with a message naming the file(s).
- On any non-zero exit, **stdout is empty** and stderr is `troupe: <message>`.
- Subcommand implementations are loaded lazily from `troupe.commands.<module>` so WP03/WP04/WP08 add
  commands **without editing `cli.py`**.
- `uv run pytest`, `uv run mypy --strict`, `uv run ruff check`, `uv run ruff format --check` all pass.

## Context & Constraints

- Spec: `kitty-specs/troupe-config-load-show-set-01M3XGPG/spec.md` (FR-001, FR-002, FR-006, NFR-004, NFR-005, C-001, C-003).
- Plan: `kitty-specs/troupe-config-load-show-set-01M3XGPG/plan.md` (source layout, Charter Check).
- CLI contract: `kitty-specs/troupe-config-load-show-set-01M3XGPG/contracts/cli.md`.
- Charter: `.kittify/charter/charter.md` — TROUPE-003 (errors name the path/file), TROUPE-005 (real tests), TROUPE-006 (show gate output), TROUPE-007 (one decision, one place: exit codes live only in `errors.py`).
- The repository currently has **no Python code**. You are creating it.

## Branch Strategy

- **Strategy**: Planning artifacts were generated on `feat/troupe-config-load-show-set`; completed changes merge back into `feat/troupe-config-load-show-set`, which is then merged into `main` locally at delivery.
- **Planning base branch**: `feat/troupe-config-load-show-set`
- **Merge target branch**: `feat/troupe-config-load-show-set`
- Execution worktrees are allocated per computed lane from `lanes.json`; use `spec-kitty agent action implement WP01 --agent <name>` to get yours.

## Subtasks & Detailed Guidance

### Subtask T001 – uv project: pyproject, dependencies, console script, tool config, lock

- **Purpose**: one reproducible environment; `uv run troupe` resolves to our console script.
- **Steps**:
  1. Create `pyproject.toml` (src layout) — suggested content:
     ```toml
     [project]
     name = "troupe"
     version = "0.1.0"
     description = "troupe configuration subsystem"
     requires-python = ">=3.12"
     dependencies = ["eventsourcing>=9.5,<10", "ruamel.yaml>=0.19,<0.20"]

     [project.scripts]
     troupe = "troupe.cli:main"

     [build-system]
     requires = ["hatchling"]
     build-backend = "hatchling.build"

     [tool.hatch.build.targets.wheel]
     packages = ["src/troupe"]

     [dependency-groups]
     dev = ["pytest>=8", "mypy>=1.11", "ruff>=0.6"]

     [tool.mypy]
     strict = true
     files = ["src", "tests"]
     mypy_path = "src"

     [tool.ruff]
     line-length = 100
     target-version = "py312"
     src = ["src", "tests"]

     [tool.ruff.lint]
     select = ["E", "F", "W", "I", "UP", "B", "SIM", "RUF"]

     [tool.pytest.ini_options]
     testpaths = ["tests"]
     ```
  2. `.python-version` with `3.12`.
  3. Run `uv sync` to create `uv.lock`; commit it (hash-pinned, research R-08).
  4. `uv run mypy --strict` must run with **no arguments** (it reads `files`). If ruamel lacks types in
     some area, do **not** add a blanket ignore here — WP02 confines ruamel to `yamlcore.py`.
- **Files**: `pyproject.toml`, `uv.lock`, `.python-version`.
- **Notes**: Do not add any dependency beyond those listed. `uv run troupe` must work **from the repository root** with `--theatre` pointing elsewhere.

### Subtask T002 – Error hierarchy with exit codes (`src/troupe/errors.py`)

- **Purpose**: the single named place for exit codes (TROUPE-007).
- **Steps**:
  ```python
  class TroupeError(Exception):
      exit_code: ClassVar[int] = 1
      def __init__(self, message: str) -> None:
          super().__init__(message)
          self.message = message

  class UsageError(TroupeError):     exit_code = 2   # bad invocation or unparsable VALUE
  class WriteRefused(TroupeError):   exit_code = 3   # write refused, no file changed
  class LoadError(TroupeError):      exit_code = 4   # configuration cannot be loaded
  class PathError(TroupeError):      exit_code = 5   # path not found / wrong kind of node
  ```
- Messages must name the offending config path (e.g. `model.temperature`) or file (absolute or theatre-relative path). Constructors take the full message; callers format it. Document this rule in the module docstring.

### Subtask T003 – Theatre and root-file discovery (`src/troupe/theatre.py`)

- **Purpose**: FR-002 — find `<dir>/.troupe/troupe.yml` or `.troupe/troupe.yaml`.
- **Steps**:
  ```python
  @dataclass(frozen=True)
  class Theatre:
      directory: Path      # the --theatre dir (resolved, absolute)
      state_dir: Path      # directory / ".troupe"
      config_file: Path    # the single root file

  def locate(directory: Path) -> Theatre: ...
  ```
  - Neither file exists (including `.troupe/` missing) → `LoadError("no configuration file: <dir>/.troupe/troupe.yml (or troupe.yaml)")`.
  - Both exist → `LoadError("both <…>/troupe.yml and <…>/troupe.yaml exist; remove one")` (name both).
  - `--theatre` pointing at a non-existent directory → `LoadError` naming it (exit 4: config cannot be loaded).
  - Never create anything (the State rule: no files outside the write-back rules; history files are created later by WP03 only after a successful load).

### Subtask T004 – CLI parser, dispatch, stdout/stderr discipline (`src/troupe/cli.py`, `__main__.py`)

- **Purpose**: FR-001, FR-006.
- **Steps**:
  1. `argparse` parser `prog="troupe"` with a required subcommand group `config`, and under it required subcommands:
     - `show PATH`
     - `set PATH VALUE`
     - `history [PATH]`
     Each subcommand parser gets `--theatre DIR` (default: `Path.cwd()`), so options may appear before or after positionals (`troupe config set a.b 1 --theatre /x`). Also accept `--theatre` on the `config` parser for `troupe config --theatre X show a` (use `default=argparse.SUPPRESS` on one of them and merge, so the subcommand default does not clobber).
  2. A VALUE that looks like a negative number (`-5`, `-0.5`) must be accepted as a positional. argparse does this by default when no option looks like a negative number — add a test.
  3. argparse already exits 2 with usage on stderr — keep that behaviour, but make sure **nothing** goes to stdout on error (override `ArgumentParser.error` to raise `UsageError` so the CLI path is uniform). `--help` may print to stdout and exit 0.
  4. Dispatch:
     ```python
     COMMAND_MODULES: Final = {"show": "show", "set": "set_value", "history": "history"}

     class Command(Protocol):
         def run(self, theatre: Theatre, args: argparse.Namespace) -> str: ...

     def main(argv: Sequence[str] | None = None) -> int:
         try:
             args = parser.parse_args(argv)
             theatre = locate(Path(args.theatre))           # exit 4 before importing the command
             module = importlib.import_module(f"troupe.commands.{COMMAND_MODULES[args.command]}")
             output = cast(Command, module).run(theatre, args)
         except TroupeError as err:
             sys.stderr.write(f"troupe: {err.message}\n")
             return err.exit_code
         sys.stdout.write(output)
         return 0
     ```
     Output is produced **only** after the command succeeds (buffered string) — this is how "stdout empty on failure" is guaranteed.
  5. `src/troupe/__main__.py`: `raise SystemExit(main())`. `src/troupe/commands/__init__.py`: docstring describing the `run(theatre, args) -> str` protocol.
- **Notes**: Unexpected exceptions are bugs; let them propagate (traceback, exit 1) rather than masking them as a contract exit code.

### Subtask T005 – Test harness and CLI basics tests

- **Purpose**: shared fixtures used by every later WP; prove the CLI discipline.
- **Steps** (`tests/conftest.py`):
  - `make_theatre(tmp_path) -> Callable[[dict[str, str | bytes]], Path]`: writes files relative to `<theatre>/.troupe/` (bytes written verbatim; `str` encoded UTF-8 **without newline translation** — use `write_bytes(s.encode())`), returns the theatre dir.
  - `run_cli(*args: str, cwd: Path | None = None) -> CliResult(code: int, out: str, err: str)`: runs `[sys.executable, "-m", "troupe", *args]` via `subprocess.run(capture_output=True, text=False)` and decodes UTF-8 **without** newline translation.
  - `snapshot(theatre: Path) -> dict[str, bytes]`: every file under the theatre **except** `.troupe/history.sqlite*`, keyed by relative path — used to assert byte-exact results.
  - `all_files(theatre) -> set[str]`: every file including history files (for the State rule).
- **Tests** (`tests/integration/test_cli_basics.py`), names state what they prove:
  - `test_no_subcommand_is_usage_error_with_empty_stdout` (exit 2).
  - `test_unknown_subcommand_is_usage_error`, `test_set_without_value_is_usage_error`.
  - `test_missing_config_file_exits_4_and_names_file`.
  - `test_both_yml_and_yaml_exit_4_and_name_both_files`.
  - `test_theatre_defaults_to_current_directory` — run with `cwd=` an empty dir, no `--theatre`; assert exit 4 and stderr names that directory's `.troupe/troupe.yml`.
  - `test_missing_root_creates_no_files` — directory listing unchanged after exit 4.
  - `test_uv_run_troupe_from_repo_root` — one smoke test running `uv run troupe config show x --theatre <empty dir>` with `cwd=` the repository root, asserting exit 4 (proves the console script). Mark it so it is skipped only if `uv` is not on PATH.

## Test Strategy

`uv run pytest tests/integration/test_cli_basics.py` plus the full gate set. Tests run the real
CLI as a subprocess — no mocking of argparse or the filesystem.

## Risks & Mitigations

- **argparse writes to stdout** for `--help` only — acceptable. For errors it writes to stderr; ensure no other prints.
- **Lazy import**: if a command module is missing (later WP), `ImportError` surfaces — that is fine before WP03/04/08 land; never catch it as a contract error.
- **Negative-number VALUEs**: test explicitly.

## Review Guidance

- Exit codes appear only in `errors.py`.
- `cli.py` contains no command logic and no YAML handling.
- stdout written in exactly one place, after success.
- All four gates run and output shown in the activity log/hand-off.

## Activity Log

- 2026-10-02T06:01:37Z – system – Prompt created.
