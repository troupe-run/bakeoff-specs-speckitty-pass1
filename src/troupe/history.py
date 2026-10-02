"""The configuration's change history: an event-sourced aggregate persisted in SQLite (FR-021).

One ``ConfigHistory`` aggregate per theatre, with a fixed id (the database is per theatre), is
stored by the real ``eventsourcing`` library in ``<theatre>/.troupe/history.sqlite`` (SQLite may
add ``history.sqlite-wal``/``-shm`` beside it). Each leaf change is one domain event; the
creation event is version 1, so a change event's ``seq`` is its version minus 1 (research R-02,
R-15). Every operation saves its events in one ``save()`` call, which SQLite applies atomically.

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
from typing import Final, Literal

from eventsourcing.application import AggregateNotFoundError, Application
from eventsourcing.domain import Aggregate, event
from eventsourcing.utils import Environment, EnvType

from troupe.leaves import Change, JsonScalar

HISTORY_DB_NAME: Final = "history.sqlite"
HISTORY_ID: Final = uuid.uuid5(uuid.NAMESPACE_URL, "troupe:config-history")


class ConfigHistory(Aggregate):
    """The history of one theatre's configuration; its events are the history."""

    class LeafImported(Aggregate.Event):
        path: str
        new: JsonScalar

    class LeafSet(Aggregate.Event):
        path: str
        old: JsonScalar
        new: JsonScalar

    class LeafRemoved(Aggregate.Event):
        path: str
        old: JsonScalar

    @staticmethod
    def create_id() -> uuid.UUID:
        return HISTORY_ID

    @event("Created")
    def __init__(self) -> None:
        pass

    @event(LeafImported)
    def leaf_imported(self, path: str, new: JsonScalar) -> None:
        pass

    @event(LeafSet)
    def leaf_set(self, path: str, old: JsonScalar, new: JsonScalar) -> None:
        pass

    @event(LeafRemoved)
    def leaf_removed(self, path: str, old: JsonScalar) -> None:
        pass


@dataclass(frozen=True)
class HistoryRecord:
    """One listed history event (contracts/history-event.schema.json).

    Attributes:
        seq: 1-based position in the history.
        op: ``import``, ``set`` or ``remove``.
        path: Dotted path in the merged configuration.
        old: ``None`` for ``import``.
        new: ``None`` for ``remove``.
    """

    seq: int
    op: Literal["import", "set", "remove"]
    path: str
    old: JsonScalar
    new: JsonScalar


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

    def import_leaves(self, leaves: dict[str, JsonScalar]) -> None:
        """Create the history with one ``import`` event per leaf, in the given order.

        An empty ``leaves`` still creates the history, so the theatre counts as imported.
        """
        history = ConfigHistory()
        for path, value in leaves.items():
            history.leaf_imported(path, value)
        self._app.save(history)

    def record(self, changes: list[Change]) -> None:
        """Append one event per change, atomically; does nothing for ``[]``.

        Raises:
            AggregateNotFoundError: If the theatre has not been imported.
        """
        if not changes:
            return
        history: ConfigHistory = self._app.repository.get(HISTORY_ID)
        for change in changes:
            if change.op == "set":
                history.leaf_set(change.path, change.old, change.new)
            else:
                history.leaf_removed(change.path, change.old)
        self._app.save(history)

    def records(self) -> list[HistoryRecord]:
        """Return every change event, oldest first (``[]`` before import)."""
        records: list[HistoryRecord] = []
        for domain_event in self._app.events.get(HISTORY_ID):
            seq = domain_event.originator_version - 1
            if isinstance(domain_event, ConfigHistory.LeafImported):
                records.append(
                    HistoryRecord(seq, "import", domain_event.path, None, domain_event.new)
                )
            elif isinstance(domain_event, ConfigHistory.LeafSet):
                records.append(
                    HistoryRecord(seq, "set", domain_event.path, domain_event.old, domain_event.new)
                )
            elif isinstance(domain_event, ConfigHistory.LeafRemoved):
                records.append(
                    HistoryRecord(seq, "remove", domain_event.path, domain_event.old, None)
                )
        return records

    def close(self) -> None:
        """Close the database connections."""
        self._app.close()
