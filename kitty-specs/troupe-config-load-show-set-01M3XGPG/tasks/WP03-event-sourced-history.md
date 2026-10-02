---
work_package_id: WP03
title: Event-sourced history and import
dependencies:
- WP02
requirement_refs:
- C-002
- FR-021
- FR-022
- FR-023
- FR-024
- NFR-003
planning_base_branch: feat/troupe-config-load-show-set
merge_target_branch: feat/troupe-config-load-show-set
branch_strategy: Planning artifacts for this mission were generated on feat/troupe-config-load-show-set. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/troupe-config-load-show-set unless the human explicitly redirects the landing branch.
subtasks:
- T011
- T012
- T013
- T014
- T015
phase: Phase 2 - Reading the configuration
history:
- at: '2026-10-02T06:01:37Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: ''
authoritative_surface: src/troupe/history.py
create_intent:
- src/troupe/leaves.py
- src/troupe/history.py
- src/troupe/session.py
- src/troupe/commands/history.py
- tests/unit/test_leaves.py
- tests/unit/test_history_store.py
- tests/integration/test_history.py
execution_mode: code_change
model: ''
owned_files:
- src/troupe/leaves.py
- src/troupe/history.py
- src/troupe/session.py
- src/troupe/commands/history.py
- tests/unit/test_leaves.py
- tests/unit/test_history_store.py
- tests/integration/test_history.py
role: ''
tags: []
task_type: implement
tracker_refs: []
---

# Work Package Prompt: WP03 – Event-sourced history and import

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

Hold the configuration's change history as an event-sourced aggregate using the **real
`eventsourcing` library**, persisted in `<theatre>/.troupe/history.sqlite`; import a theatre on its
first command; implement `troupe config history [PATH]`.

Done when:
- First command against a theatre (that loads) appends one `import` event per leaf, `old` null, in document order; later commands never re-import (importing is not reconciling).
- `history` prints JSON Lines `{"seq","op","path","old","new"}` oldest first, `seq` from 1; with PATH only events whose path equals PATH or starts with `PATH.`.
- Hand edits after import produce **no** events (files are the source of truth; DM-01M3XGPT4E0D67ZJY8PT7Z9NAT).
- Exit 4 (load failure) creates **no** history file.
- `leaves.diff` and `HistoryStore.record` are ready for WP08's `set`.
- Gates pass.

## Context & Constraints

- Spec FR-021, FR-022, FR-023 (event shape), FR-024, NFR-003, C-002; data-model.md "Leaves" and "History"; research R-02, R-04, R-07, R-15; contracts/history-event.schema.json.
- Verified with eventsourcing 9.5.5 (research R-15): versions start at 1 for the creation event; an `Application` instance must stay referenced while used (a dropped temporary closes the pool → `ConnectionPoolClosedError`); SQLite WAL side files `history.sqlite-wal`/`-shm` appear beside the DB.
- State rule (NFR-003): only `<theatre>/.troupe/history.sqlite*` may be created by this WP.

## Branch Strategy

- **Planning base branch**: `feat/troupe-config-load-show-set` · **Merge target**: `feat/troupe-config-load-show-set` (then merged into `main` locally at delivery).
- `spec-kitty agent action implement WP03 --agent <name>` (lane worktree from `lanes.json`).

## Subtasks & Detailed Guidance

### Subtask T011 – Leaves (`src/troupe/leaves.py`) [P]

```python
JsonScalar = str | int | float | bool | None

def flatten(node: Node, prefix: str = "") -> dict[str, JsonScalar]   # insertion order = document order
def same(a: JsonScalar, b: JsonScalar) -> bool                       # type-aware: 1 != 1.0 != "1", True != 1; nan == nan

@dataclass(frozen=True)
class Change:
    op: Literal["set", "remove"]
    path: str
    old: JsonScalar
    new: JsonScalar

def diff(before: dict[str, JsonScalar], after: dict[str, JsonScalar]) -> list[Change]
```
- `flatten`: `ScalarNode` → leaf; `TextInclude` → leaf with `target.text`; `YamlInclude` → flatten its root under the same prefix; mapping entries → `prefix.key`; sequence items → `prefix.i`; empty collections → no leaves. Join with `.`; no leading dot.
- `diff`: for each path of `after` (in order) whose value is absent in `before` or `not same(...)` → `set` (old = before value or None); then for each path of `before` (in order) absent from `after` → `remove` (new None).
- Note: a leaf whose value is `null` in `before` and absent in `after` is still a `remove`; a new leaf with value `null` is still a `set` (presence matters, not value).

### Subtask T012 – Aggregate and store (`src/troupe/history.py`)

```python
HISTORY_DB_NAME: Final = "history.sqlite"
HISTORY_ID: Final = uuid.uuid5(uuid.NAMESPACE_URL, "troupe:config-history")

class ConfigHistory(Aggregate):
    @staticmethod
    def create_id() -> uuid.UUID: return HISTORY_ID
    @event("Created")
    def __init__(self) -> None: ...
    @event("LeafImported")
    def leaf_imported(self, path: str, new: JsonScalar) -> None: ...
    @event("LeafSet")
    def leaf_set(self, path: str, old: JsonScalar, new: JsonScalar) -> None: ...
    @event("LeafRemoved")
    def leaf_removed(self, path: str, old: JsonScalar) -> None: ...

@dataclass(frozen=True)
class HistoryRecord:
    seq: int; op: Literal["import","set","remove"]; path: str; old: JsonScalar; new: JsonScalar

class HistoryStore:
    def __init__(self, state_dir: Path) -> None   # Application(env={"PERSISTENCE_MODULE": "eventsourcing.sqlite", "SQLITE_DBNAME": str(state_dir / HISTORY_DB_NAME)})
    def is_imported(self) -> bool                 # repository.get(HISTORY_ID) / AggregateNotFoundError
    def import_leaves(self, leaves: dict[str, JsonScalar]) -> None   # create aggregate + one event per leaf, single save()
    def record(self, changes: list[Change]) -> None                 # no-op when empty; single save()
    def records(self) -> list[HistoryRecord]                         # events.get(HISTORY_ID), skip Created, seq = originator_version - 1
    def close(self) -> None
```
- Pass the env **explicitly** to the `Application` (`env=` argument) so a user's environment variables cannot redirect persistence; explicit `env` wins over `os.environ` in eventsourcing.
- Import with an empty leaf set still creates the aggregate (theatre counts as imported).
- One `save()` per operation → atomic in SQLite.
- Keep JSON-compatible values only (str/int/float/bool/None). Verify bool survives as bool and `1.0` as float through the store (test).
- Type hints: eventsourcing is typed; `Application[uuid.UUID]` generic works under `mypy --strict`.

### Subtask T013 – Session (`src/troupe/session.py`)

```python
@dataclass
class Session:
    theatre: Theatre
    tree: Node
    history: HistoryStore

@contextmanager
def open_session(theatre: Theatre) -> Iterator[Session]:
    tree = load(theatre.config_file)          # LoadError here → no store created, no files
    store = HistoryStore(theatre.state_dir)
    try:
        if not store.is_imported():
            store.import_leaves(flatten(tree))
        yield Session(theatre, tree, store)
    finally:
        store.close()
```
- This is the only place import happens (research R-04): every command that loads uses `open_session`. A command that later fails with exit 3/5 keeps the import.
- Document in the docstring that `tree` reflects the files on disk at the start of the command.

### Subtask T014 – `history [PATH]` (`src/troupe/commands/history.py`)

- `run(theatre, args) -> str`: open session; take `store.records()`; filter by `args.path` if given (`r.path == p or r.path.startswith(p + ".")`); return `"".join(json.dumps(asdict-ish, ensure_ascii=False) + "\n")` with key order `seq, op, path, old, new`.
- A PATH matching nothing → empty output, exit 0 (the contract defines no error for it).
- Validate PATH syntax via `paths.parse_path` (empty segments → exit 2).

### Subtask T015 – Tests

- `tests/unit/test_leaves.py`: flatten of nested mapping/list/includes (YAML include leaves at merged paths; text include leaf = file text); diff cases: change, create, remove, list shrink (`tools.1` removed), type change `1`→`"1"` is a `set`, identical → `[]`.
- `tests/unit/test_history_store.py` (real SQLite in `tmp_path`): import then reopen a **new** store instance and read back (persistence); `seq` 1..n; record appends after import with continuing seq; `record([])` appends nothing; bool/float/None round-trip types.
- `tests/integration/test_history.py` (CLI subprocess):
  - `test_history_on_fresh_theatre_imports_every_leaf_in_document_order` (exact JSON lines for a fixture with mapping, list, YAML include, text include).
  - `test_second_history_run_does_not_reimport`.
  - `test_hand_edit_after_import_produces_no_event`.
  - `test_history_path_filter_matches_exact_and_dotted_prefix_only` (`model` vs `models`).
  - `test_history_creates_only_history_files_under_dot_troupe` (all_files diff ⊆ `.troupe/history.sqlite*`; config bytes unchanged).
  - `test_load_failure_creates_no_history_file` (missing include → exit 4, no `history.sqlite`).
  - Each line validates against `contracts/history-event.schema.json` required keys and op/old/new rules (check manually; no new dependency).

## Risks & Mitigations

- **Pool closed** — keep the store referenced for the whole command (session context manager).
- **WAL side files** — confined to `.troupe/`; tests assert it.
- **JSON of non-finite floats** — `json.dumps` emits `Infinity`/`NaN`; acceptable edge, document in the module docstring.

## Review Guidance

- Real eventsourcing + SQLite in tests (no in-memory POPO substitutes for persistence tests).
- Import happens only in `session.py`; only when not yet imported.
- No history file on exit 4.

## Activity Log

- 2026-10-02T06:01:37Z – system – Prompt created.
