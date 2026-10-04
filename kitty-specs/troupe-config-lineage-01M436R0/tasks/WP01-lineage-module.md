---
work_package_id: WP01
title: Lineage module
dependencies: []
requirement_refs:
- FR-002
- FR-003
- FR-004
- FR-005
- FR-007
- FR-009
planning_base_branch: feat/troupe-config-lineage
merge_target_branch: feat/troupe-config-lineage
branch_strategy: Planning artifacts for this mission were generated on feat/troupe-config-lineage. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/troupe-config-lineage unless the human explicitly redirects the landing branch.
base_branch: kitty/mission-troupe-config-lineage-01M436R0
base_commit: 1547307bf69dca1031a8c539fcb45d3a2899bb15
created_at: '2026-10-04T10:38:34.834232+00:00'
subtasks:
- T001
- T002
- T003
- T004
- T005
phase: Phase 1 - Foundations
history:
- at: '2026-10-04T10:28:42Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/troupe/lineage.py
create_intent:
- src/troupe/lineage.py
- tests/unit/test_lineage.py
execution_mode: code_change
model: ''
owned_files:
- src/troupe/lineage.py
- tests/unit/test_lineage.py
role: implementer
tags: []
task_type: implement
tracker_refs: []
---

# Work Package Prompt: WP01 – Lineage module

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter (`agent_profile`, `role`, `agent`), and behave according to its guidance before parsing the rest of this prompt.

If no profile is specified, run `spec-kitty agent profile list` and select the best match for this work package's `task_type` and `authoritative_surface`.

---

## ⚠️ IMPORTANT: Review Feedback

- **Has review feedback?**: Check the `review_ref` field in the event log (via `spec-kitty agent tasks status`) or the Activity Log below.
- **You must address all feedback** before your work is complete.

---

## Objective

Create `src/troupe/lineage.py`. This is the **one named place** (TROUPE-007) for every lineage decision:

- the `TROUPE_ACTOR` grammar and its error;
- the login-name fallback;
- the `at` format;
- the change-id formats, both new and pre-lineage;
- the lineage of each producer (import, file reconcile, CLI command);
- the mapping between a `Lineage` and the flat fields stored on events.

Nothing outside this module may build an `Actor`, format an `at`, or mint a change id. WP03 wires the module into the store and the commands. This WP changes no command behaviour.

## Context

Read first:
- `kitty-specs/troupe-config-lineage-01M436R0/spec.md`: Intent Summary (rules and the three DMs), FR-002 to FR-005, FR-007, FR-009, Edge Cases
- `kitty-specs/troupe-config-lineage-01M436R0/research.md`: **D-3, D-4, D-5, D-6** (these are the rules; follow them exactly)
- `kitty-specs/troupe-config-lineage-01M436R0/data-model.md`: Actor, Lineage tables
- `kitty-specs/troupe-config-lineage-01M436R0/contracts/cli.md`: `TROUPE_ACTOR` table and the exact error message
- `src/troupe/errors.py`: `UsageError` (exit 2); messages are complete and user-facing
- `.kittify/charter/charter.md`: TROUPE-003, -005, -006, -007

Style: match the existing modules: a module docstring that says what the module decides and cites FR/D ids, `Final` constants, frozen dataclasses with `Attributes:` docstrings, `Raises:` sections. The code must pass `mypy --strict`.

## Branch Strategy

- Planning/base branch: `feat/troupe-config-lineage`; final merge target: `feat/troupe-config-lineage` (then merged into `main` by the human-directed delivery step).
- Execution worktrees are allocated per computed lane from `lanes.json`; implement with `spec-kitty agent action implement WP01 --agent <name>`.

## Subtasks

### T001 — Types and constants

**Steps** (in `src/troupe/lineage.py`):

```python
ACTOR_ENV_VAR: Final = "TROUPE_ACTOR"
PRE_LINEAGE_CHANGE_PREFIX: Final = "pre-lineage-"

type ActorKind = Literal["human", "agent", "unknown"]
type Via = Literal["import", "cli", "file"]

@dataclass(frozen=True)
class Actor:
    kind: ActorKind
    id: str | None

UNKNOWN_ACTOR: Final = Actor("unknown", None)

@dataclass(frozen=True)
class Lineage:
    actor: Actor
    via: Via | None      # None only for pre-lineage set/remove events (DM 01M436RBNQT22F9AM54QER2FT9)
    at: str              # RFC 3339 UTC, ends in Z
    reason: str | None
    change: str
```

- Document each attribute (see data-model.md).
- `Via | None`: say in the docstring that `None` appears only for events read from a pre-lineage history, never for a new event.

### T002 — `resolve_actor(environ)` and `login_name()`

**Signature**: `def resolve_actor(environ: Mapping[str, str]) -> Actor`. Take a mapping, not `os.environ` directly, so the function is testable without monkeypatching. The CLI passes `os.environ`.

**Rules** (D-5, contract):
1. `ACTOR_ENV_VAR not in environ` → `Actor("human", login_name())`.
2. Otherwise `value = environ[ACTOR_ENV_VAR]` and `kind, sep, ident = value.partition(":")`.
3. Valid only if `sep == ":"`, `kind in ("human", "agent")` (exact, lowercase), and `ident != ""`. Return `Actor(kind, ident)`; `ident` is kept verbatim, so it may contain `:` and spaces (`human:alice:x` → id `alice:x`).
4. Anything else raises `UsageError(f"{ACTOR_ENV_VAR}: invalid value {value!r}: expected 'human:<id>' or 'agent:<id>'")`.
   - Cases that must be rejected: `""`, `"alice"`, `"human:"`, `"agent:"`, `"Human:alice"`, `"robot:x"`, `":x"`.
   - `{value!r}` gives the single-quoted form shown in the contract (`'robot:x'`). For a value that contains a `'` Python switches to double quotes, which is fine.

**`login_name() -> str | None`** (D-6):
```python
try:
    name = getpass.getuser()
except (OSError, KeyError):   # 3.13+: OSError; 3.12: KeyError from pwd
    return None
return name or None
```
Docstring: the login name is `LOGNAME`, `USER`, `LNAME`, `USERNAME`, then the password database, which is the standard library's notion; `None` means it cannot be determined (DM 01M436TX68S2MGE4DN9AM02KTJ).

**Narrowing for mypy**: map `kind` to `ActorKind` with an explicit `if kind == "human": ... elif kind == "agent": ...`, or a small dict typed `dict[str, ActorKind]`, rather than a `cast`.

### T003 — Clock and change ids

```python
def format_at(moment: datetime) -> str:
    """RFC 3339 UTC with microseconds and a Z suffix (D-4)."""
    if moment.tzinfo is None:
        raise ValueError("format_at needs an aware datetime")
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

def now_at() -> str:
    return format_at(datetime.now(UTC))

def new_change_id() -> str:
    return str(uuid.uuid4())

def pre_lineage_change_id(seq: int) -> str:
    return f"{PRE_LINEAGE_CHANGE_PREFIX}{seq}"
```

- `format_at` is also used by WP03's upcast on the stored eventsourcing `timestamp`, which may be in a non-UTC zone if `TZINFO_TOPIC` is set. That is why it converts rather than assumes UTC.
- Fixed width: `%f` always gives 6 digits, so values sort lexically.

### T004 — Producer constructors and stored-field mapping

```python
def import_lineage() -> Lineage:      # actor UNKNOWN, via "import", reason None, fresh at + change
def file_lineage() -> Lineage:        # actor UNKNOWN, via "file",   reason None, fresh at + change
def cli_lineage(actor: Actor, reason: str | None) -> Lineage:  # via "cli"
```
- Each call reads the clock once and mints one change id. One producer calls its constructor exactly once, which is how "every event of one change shares at/change" holds (data-model invariant 1).
- `cli_lineage` keeps `reason` verbatim (`""` stays `""`).

Mapping to and from the flat event fields. WP03 stores these fields; keeping the mapping here keeps one place for it:

```python
class LineageFields(TypedDict):
    actor_kind: str
    actor_id: str | None
    via: str | None
    at: str
    reason: str | None
    change: str

def lineage_fields(lineage: Lineage) -> LineageFields: ...
def lineage_from_fields(actor_kind: str, actor_id: str | None, via: str | None,
                        at: str, reason: str | None, change: str) -> Lineage: ...
def pre_lineage_fields(seq: int, via: Via | None, recorded: datetime) -> LineageFields:
    """Lineage for an event recorded before step 4 (DM 01M436RBNQT22F9AM54QER2FT9)."""
```
- `lineage_from_fields` validates `actor_kind` ∈ the three kinds and `via` ∈ the three values or `None`. On anything else it raises `ValueError` naming the bad value; that would only happen with a corrupt store.
- `pre_lineage_fields` returns `actor_kind="unknown"`, `actor_id=None`, `via` as given (`"import"` for imports, `None` otherwise), `at=format_at(recorded)`, `reason=None`, and `change=pre_lineage_change_id(seq)`.

### T005 — `tests/unit/test_lineage.py`

Test names state what they prove, and bodies check exactly that (TROUPE-005). Required tests (parametrize where natural):

- `test_unset_actor_is_human_with_login_name`: pass `{}` and monkeypatch `getpass.getuser` to return `"bob"` → `Actor("human", "bob")`.
- `test_unset_actor_with_unknown_login_is_human_with_null_id`: `getpass.getuser` raises `OSError`; also `KeyError`; also returns `""` → `Actor("human", None)`.
- `test_human_and_agent_values_give_that_kind_and_id`: `human:alice`, `agent:planner`, `human:alice:x` (id `alice:x`), `agent:with space`.
- `test_invalid_actor_values_raise_usage_error_naming_the_variable`: `""`, `alice`, `human:`, `agent:`, `Human:alice`, `robot:x`, `:x`. Assert `UsageError`, `exit_code == 2`, and the exact message `TROUPE_ACTOR: invalid value 'robot:x': expected 'human:<id>' or 'agent:<id>'` for one case, plus that `"TROUPE_ACTOR"` appears in every message.
- `test_format_at_converts_to_utc_with_microseconds_and_z`: aware datetime at `+02:00` → expected `...Z` string; regex `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$`.
- `test_format_at_rejects_naive_datetime`.
- `test_new_change_ids_are_distinct_uuid_strings`: 1000 ids → 1000 distinct; each parses with `uuid.UUID(...)`.
- `test_pre_lineage_change_id_cannot_collide_with_a_uuid`: `pre_lineage_change_id(3) == "pre-lineage-3"` and `uuid.UUID` raises `ValueError` on it.
- `test_import_and_file_lineage_have_unknown_actor_and_no_reason`: via values, `UNKNOWN_ACTOR`, `reason is None`.
- `test_each_constructor_call_mints_a_new_change`: two `file_lineage()` calls → different `change`.
- `test_cli_lineage_keeps_reason_verbatim`: `""`, `"a\nb"`, `"ünï 'q'"`.
- `test_lineage_round_trips_through_stored_fields`: `lineage_from_fields(**lineage_fields(x)) == x` for each constructor.
- `test_lineage_from_fields_rejects_unknown_kind_or_via`.
- `test_pre_lineage_fields_follow_the_recorded_decision`: via `None` and `"import"`; a `+05:30` datetime → UTC `at`; change `pre-lineage-<seq>`.

Monkeypatch `troupe.lineage.getpass.getuser`, or `getpass.getuser`, depending on the import style. That is the one allowed stand-in, because a missing login cannot be produced on a real machine. Say so in the test docstring.

## Definition of Done

- `src/troupe/lineage.py` exists with the API above, fully typed and documented, citing FR/D/DM ids.
- `tests/unit/test_lineage.py` covers every rule above.
- `uv run pytest`, `uv run mypy --strict`, `uv run ruff check`, `uv run ruff format --check` all pass; paste their output in the review handoff.
- No other file changed.

## Risks

- Exception type from `getpass.getuser()` differs by Python version; catch both.
- Do not read `os.environ` inside `resolve_actor`; take the mapping.

## Reviewer guidance

- Check the rejected-values list against contracts/cli.md exactly, including the exact message.
- Check that no other module would need to know the `at` format or the change-id formats.
- Check that test names match what their bodies assert.

## Activity Log

- 2026-10-04T10:28:42Z – system – Prompt generated via /spec-kitty.tasks
