"""The configuration's change history: an event-sourced aggregate persisted in SQLite (FR-021).

One ``ConfigHistory`` aggregate per theatre, with a fixed id (the database is per theatre), is
stored by the real ``eventsourcing`` library in ``<theatre>/.troupe/history.sqlite`` (SQLite may
add ``history.sqlite-wal``/``-shm`` beside it). Each leaf change is one domain event; the
creation event is version 1, so a change event's ``seq`` is its version minus 1 (research R-02,
R-15). Every operation saves its events in one ``save()`` call, which SQLite applies atomically.

The aggregate's state is the recorded configuration: a path -> value map of the leaves the
history has recorded (FR-001 of mission troupe-config-sync-files). The event methods' bodies
build it, and ``eventsourcing`` runs them again on every replay, so it is rebuilt from the
events whenever the aggregate is loaded and existing histories need no migration.

Every leaf event carries its lineage (actor, via, at, reason, change) as stored fields, so the
lineage persists with the event (FR-012, research D-1). One ``import_leaves`` or ``record`` call
is one producer: all its events share one ``Lineage`` and are saved in one ``save()`` (NFR-001).
The leaf event classes are at ``class_version`` 2. Events recorded before lineage existed are
version 1 on disk; eventsourcing upcasts them when they are read, through ``upcast_v1_v2``,
which gives them the pre-lineage lineage of spec DM 01M436RBNQT22F9AM54QER2FT9 (research D-2).
Stored rows are never rewritten (C-005): a version-1 row stays version 1 on disk. All lineage
decisions are made by ``troupe.lineage``; this module only stores and reads its fields.

Values are JSON scalars. Non-finite floats (``.inf``, ``.nan``) round-trip through the store and
are printed by ``json.dumps`` as ``Infinity``/``NaN``, which is not strict JSON; this edge is
accepted.

The persistence settings are fixed here and nothing is read from the process environment, so a
user's environment variables (``PERSISTENCE_MODULE``, ``<APP>_SQLITE_DBNAME``, ``CIPHER_TOPIC``,
...) cannot redirect the store or change its on-disk format.
"""

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

from eventsourcing.application import AggregateNotFoundError, Application
from eventsourcing.domain import Aggregate, event
from eventsourcing.utils import Environment, EnvType

from troupe.leaves import Change, JsonScalar
from troupe.lineage import (
    Lineage,
    Via,
    lineage_fields,
    lineage_from_fields,
    pre_lineage_fields,
)

HISTORY_DB_NAME: Final = "history.sqlite"
HISTORY_ID: Final = uuid.uuid5(uuid.NAMESPACE_URL, "troupe:config-history")


def _upcast_pre_lineage(state: dict[str, Any], via: Via | None) -> None:
    """Give a step-1..3 event its lineage when it is read (DM 01M436RBNQT22F9AM54QER2FT9, D-2).

    eventsourcing's ``Mapper.to_domain_event`` calls this on the decoded state of a stored
    version-1 row, after setting ``originator_version``. Verified by experiment against
    eventsourcing 9.5 (tests/unit/test_history_store.py): ``state["timestamp"]`` is already an
    aware ``datetime`` here, and a version-2 event is stored with ``"class_version": 2`` in its
    state, so it is never upcast again. Only the event object in memory changes; the stored row
    does not (C-005).
    """
    seq = state["originator_version"] - 1
    state.update(pre_lineage_fields(seq, via, state["timestamp"]))


class ConfigHistory(Aggregate):
    """The history of one theatre's configuration; its events are the history.

    The ``Created`` event and the aggregate stay at version 1 (there are no snapshots). The leaf
    event classes must keep their names and nesting: stored rows find them by topic
    (``troupe.history:ConfigHistory.LeafSet`` and so on).
    """

    class LeafImported(Aggregate.Event):
        class_version = 2

        path: str
        new: JsonScalar
        actor_kind: str
        actor_id: str | None
        via: str | None
        at: str
        reason: str | None
        change: str

        @staticmethod
        def upcast_v1_v2(state: dict[str, Any]) -> None:
            _upcast_pre_lineage(state, via="import")

    class LeafSet(Aggregate.Event):
        class_version = 2

        path: str
        old: JsonScalar
        new: JsonScalar
        actor_kind: str
        actor_id: str | None
        via: str | None
        at: str
        reason: str | None
        change: str

        @staticmethod
        def upcast_v1_v2(state: dict[str, Any]) -> None:
            # A pre-lineage set cannot be told apart from a file reconcile: via is unknown.
            _upcast_pre_lineage(state, via=None)

    class LeafRemoved(Aggregate.Event):
        class_version = 2

        path: str
        old: JsonScalar
        actor_kind: str
        actor_id: str | None
        via: str | None
        at: str
        reason: str | None
        change: str

        @staticmethod
        def upcast_v1_v2(state: dict[str, Any]) -> None:
            _upcast_pre_lineage(state, via=None)

    @staticmethod
    def create_id() -> uuid.UUID:
        return HISTORY_ID

    @event("Created")
    def __init__(self) -> None:
        self.leaves: dict[str, JsonScalar] = {}

    # The event methods take every event field; their bodies ignore the lineage, so replaying
    # ``leaves`` does not depend on it.

    @event(LeafImported)
    def leaf_imported(
        self,
        path: str,
        new: JsonScalar,
        actor_kind: str,
        actor_id: str | None,
        via: str | None,
        at: str,
        reason: str | None,
        change: str,
    ) -> None:
        self.leaves[path] = new

    @event(LeafSet)
    def leaf_set(
        self,
        path: str,
        old: JsonScalar,
        new: JsonScalar,
        actor_kind: str,
        actor_id: str | None,
        via: str | None,
        at: str,
        reason: str | None,
        change: str,
    ) -> None:
        # An existing path keeps its position; a new one is appended.
        self.leaves[path] = new

    @event(LeafRemoved)
    def leaf_removed(
        self,
        path: str,
        old: JsonScalar,
        actor_kind: str,
        actor_id: str | None,
        via: str | None,
        at: str,
        reason: str | None,
        change: str,
    ) -> None:
        # Tolerate a path that was never recorded: step-1 ``set`` diffed against the files, not
        # the history, so a key added by hand and then removed by ``set`` was recorded as removed
        # without ever being recorded as present. Replaying such a history must not fail.
        self.leaves.pop(path, None)


@dataclass(frozen=True)
class HistoryRecord:
    """One listed history event (contracts/history-event.schema.json).

    Attributes:
        seq: 1-based position in the history.
        op: ``import``, ``set`` or ``remove``.
        path: Dotted path in the merged configuration.
        old: ``None`` for ``import``.
        new: ``None`` for ``remove``.
        lineage: Who, through which channel, when, why and in which change (FR-001).
    """

    seq: int
    op: Literal["import", "set", "remove"]
    path: str
    old: JsonScalar
    new: JsonScalar
    lineage: Lineage


type _LeafEvent = ConfigHistory.LeafImported | ConfigHistory.LeafSet | ConfigHistory.LeafRemoved


def _lineage(e: _LeafEvent) -> Lineage:
    return lineage_from_fields(e.actor_kind, e.actor_id, e.via, e.at, e.reason, e.change)


class _HistoryApplication(Application[uuid.UUID]):
    """Application whose environment is exactly the one passed in (no ``os.environ``)."""

    def construct_env(self, name: str, env: EnvType | None = None) -> Environment:
        return Environment(name, dict(env or {}))


class HistoryStore:
    """The persisted history of one theatre.

    Keep the instance referenced for as long as it is used and ``close`` it at the end:
    ``eventsourcing`` closes the connection pool of an application that is garbage-collected.
    Creating a store creates the database file; create it only after the configuration loaded.
    """

    def __init__(self, state_dir: Path) -> None:
        """Open (creating if needed) ``state_dir / HISTORY_DB_NAME``."""
        self._app = _HistoryApplication(
            env={
                "PERSISTENCE_MODULE": "eventsourcing.sqlite",
                "SQLITE_DBNAME": str(state_dir / HISTORY_DB_NAME),
            }
        )

    def is_imported(self) -> bool:
        """Return whether the theatre has been imported (the aggregate exists)."""
        try:
            self._app.repository.get(HISTORY_ID)
        except AggregateNotFoundError:
            return False
        return True

    def import_leaves(self, leaves: dict[str, JsonScalar], lineage: Lineage) -> None:
        """Create the history with one ``import`` event per leaf, in the given order.

        An empty ``leaves`` still creates the history, so the theatre counts as imported. Every
        event saved by one call shares ``lineage`` and is saved in one ``save()``; call once
        per producer.
        """
        fields = lineage_fields(lineage)
        history = ConfigHistory()
        for path, value in leaves.items():
            history.leaf_imported(path, value, **fields)
        self._app.save(history)

    def record(self, changes: list[Change], lineage: Lineage) -> None:
        """Append one event per change, atomically; does nothing for ``[]``.

        Every event saved by one call shares ``lineage`` and is saved in one ``save()``; call
        once per producer.

        Raises:
            AggregateNotFoundError: If the theatre has not been imported.
        """
        if not changes:
            return
        fields = lineage_fields(lineage)
        history: ConfigHistory = self._app.repository.get(HISTORY_ID)
        for change in changes:
            if change.op == "set":
                history.leaf_set(change.path, change.old, change.new, **fields)
            else:
                history.leaf_removed(change.path, change.old, **fields)
        self._app.save(history)

    def recorded_leaves(self) -> dict[str, JsonScalar]:
        """Return a copy of the recorded configuration, in recorded order.

        Raises:
            AggregateNotFoundError: If the theatre has not been imported; callers import first.
        """
        history: ConfigHistory = self._app.repository.get(HISTORY_ID)
        return dict(history.leaves)

    def records(self) -> list[HistoryRecord]:
        """Return every change event with its lineage, oldest first (``[]`` before import)."""
        records: list[HistoryRecord] = []
        for domain_event in self._app.events.get(HISTORY_ID):
            seq = domain_event.originator_version - 1
            if isinstance(domain_event, ConfigHistory.LeafImported):
                records.append(
                    HistoryRecord(
                        seq,
                        "import",
                        domain_event.path,
                        None,
                        domain_event.new,
                        _lineage(domain_event),
                    )
                )
            elif isinstance(domain_event, ConfigHistory.LeafSet):
                records.append(
                    HistoryRecord(
                        seq,
                        "set",
                        domain_event.path,
                        domain_event.old,
                        domain_event.new,
                        _lineage(domain_event),
                    )
                )
            elif isinstance(domain_event, ConfigHistory.LeafRemoved):
                records.append(
                    HistoryRecord(
                        seq,
                        "remove",
                        domain_event.path,
                        domain_event.old,
                        None,
                        _lineage(domain_event),
                    )
                )
        return records

    def close(self) -> None:
        """Close the database connections."""
        self._app.close()
