# Research & Decisions: troupe configuration: lineage

Each decision below is one the contract leaves open. Choices that are out of contract at the product level are recorded in [spec.md](spec.md) as DMs. The decisions here are about how to implement them, and the product owner confirmed them in the Engineering Alignment on 2026-10-04.

## D-1 — Where lineage is stored

- **Decision**: As fields on each leaf event (`LeafImported`, `LeafSet`, `LeafRemoved`). The fields are `actor_kind: str`, `actor_id: str | None`, `via: str | None`, `at: str`, `reason: str | None` and `change: str`. The classes get `class_version = 2`.
- **Rationale**: every `history` line is one event, so each event carries exactly what its line prints. A whole change is saved in one `save()` (already true), which keeps it atomic (NFR-001). Replay of the aggregate's `leaves` state is unaffected, because the event method bodies ignore the new fields.
- **Alternatives considered**:
  - A separate `ChangeRecorded` event before each group of leaf events. Rejected: it would shift `seq` (a version number) and break the "one event = one line" rule, and readers would have to join the two.
  - A separate table or file. Rejected: a second store would need its own atomicity with the event store.

## D-2 — Old (version-1) events

- **Decision**: Use the eventsourcing upcasting hook. Each event class defines `upcast_v1_v2(state)`, which the mapper calls on decoded version-1 state before building the event object. The state already holds `originator_version` and the decoded `timestamp`, so the mapping is:
  - `actor_kind = "unknown"` and `actor_id = None`;
  - `reason = None`;
  - `via = "import"` for `LeafImported` and `None` for `LeafSet` and `LeafRemoved`;
  - `at = format_at(timestamp)`;
  - `change = f"pre-lineage-{originator_version - 1}"`, which is `pre-lineage-<seq>`.
- **Rationale**: this is the library's own migration mechanism. Rows on disk are never rewritten (C-005, NFR-004), and the mapping lives in one named place, next to the event classes (TROUPE-007). It carries out spec DM 01M436RBNQT22F9AM54QER2FT9.
- **Alternatives considered**:
  - A one-off migration that rewrites rows. Rejected: it violates C-005 and risks the user's audit trail.
  - `getattr(..., default)` at read sites. Rejected: the knowledge would be scattered, and version-1 events would leave the aggregate as half-formed objects.

## D-3 — Change id format

- **Decision**: `str(uuid.uuid4())`, minted once per producer in `lineage.py`. Ids for old events have the form `pre-lineage-<seq>`.
- **Rationale**: ids are unique across processes and restarts without any coordination or stored counter. A UUID can never equal `pre-lineage-…`.
- **Alternatives considered**:
  - A sequence number stored in the history. Rejected: it adds state and cross-process coordination.
  - ULIDs. Rejected: they would need a dependency.

## D-4 — `at` timestamp

- **Decision**: `datetime.now(UTC)` is read once per producer and formatted by a single `format_at(dt)`, which converts with `astimezone(UTC)` and gives `YYYY-MM-DDTHH:MM:SS.ffffffZ`. Old events use the same function on the stored `timestamp`.
- **Rationale**: the result is RFC 3339, ends in `Z`, has a fixed width, sorts lexically, and gives every event of a change the same `at` (FR-007). `astimezone` also handles a `TZINFO_TOPIC` that is not UTC.
- **Alternatives considered**:
  - Whole seconds. Rejected: it loses ordering detail for nothing.
  - The library's per-event `timestamp`. Rejected: it differs from event to event within one change.

## D-5 — `TROUPE_ACTOR` grammar and error

- **Decision**:
  - The value is split at the first `:`.
  - The kind must be exactly `human` or `agent` (lowercase), and the id (the rest, verbatim) must be non-empty.
  - Every other value is rejected: unset-but-empty, no colon, another kind, a different case, or an empty id.
  - The error is `UsageError` (exit 2) with the message `TROUPE_ACTOR: invalid value '<value>': expected 'human:<id>' or 'agent:<id>'`.
  - The check runs after `parse_args` and before `locate`.
- **Rationale**: this is the contract wording taken literally. The message names the variable (TROUPE-003, PO-accepted). The check order follows spec DM 01M436TPQDWVSZQYFD6D5343DC.

## D-6 — Login name

- **Decision**: `getpass.getuser()` (`LOGNAME`, `USER`, `LNAME`, `USERNAME`, then the password database). An `OSError` or `KeyError` from it, or an empty result, gives `id = None` (spec DM 01M436TX68S2MGE4DN9AM02KTJ).
- **Rationale**: it is the standard Python notion of the login name, and it works without a controlling terminal, unlike `os.getlogin()`, which fails under CI, cron and agents.
- **Alternatives considered**:
  - `os.getlogin()`. Rejected: it fails when there is no terminal.
  - `pwd.getpwuid(os.getuid())` alone. Rejected: it ignores the conventional `LOGNAME`/`USER`.

## D-7 — How the actor reaches producers

- **Decision**:
  - `Command.run(theatre, args, actor)` receives the resolved `Actor`; only `set` uses it.
  - `HistoryStore.import_leaves(leaves, lineage)` and `HistoryStore.record(changes, lineage)` take the lineage.
  - `session.open_session` builds `import_lineage()` for an import.
  - `reconcile.reconcile` builds `file_lineage()` for each reconcile, which also covers each `watch` reconcile (FR-011).
  - `set` builds `cli_lineage(actor, reason)` after its write succeeds.
- **Rationale**: each producer creates exactly one lineage at the point where it saves, so the rule "one producer, one change" holds by construction (FR-009, FR-010). Imports and reconciles never see the CLI actor, so they cannot accidentally attribute file events to it (FR-005).
- **Alternatives considered**: storing the actor on `argparse.Namespace`. Rejected: it is untyped under `mypy --strict`.

## D-8 — Output shape

- **Decision**: `HistoryRecord` gains `lineage: Lineage`. `commands/history.py` renders keys in the order `seq, op, path, old, new, actor, via, at, reason, change`, with `actor` as `{"kind": …, "id": …}`.
- **Rationale**: the key order the PO confirmed, kept in one place.

## D-9 — Pre-lineage test fixture

- **Decision**: `tests/fixtures/pre_lineage/` holds `troupe.yml` and the `history.sqlite` recorded by the code at commit `a589041`, through an import, a CLI `set` and a hand edit reconciled by `get`. It also holds `make_fixture.py`, which regenerates the fixture from that commit in a temporary git worktree. Tests copy the fixture into a temporary theatre and never use it in place.
- **Rationale**: it tests the real old on-disk format produced by the real old code (TROUPE-005), not a hand-made imitation.
- **Alternatives considered**: synthesising version-1 rows by writing SQL directly. Rejected: that tests our own idea of the old format, not the format itself.
