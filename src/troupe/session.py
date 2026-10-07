"""One command's view of a theatre: the loaded tree and the open history (research R-04, R-07).

This is the only place that decides when a command imports or reconciles. Every command that
loads the configuration does so through ``open_session``, all under the theatre lock:

- a never-imported theatre is imported (one ``import`` event per leaf, in document order). The
  import is its own change, attributed to the unknown actor via ``import`` (FR-005, FR-010);
- otherwise, when the command asks for it, the history is reconciled with the files
  (``troupe.reconcile``), so hand edits made while nothing ran are recorded before the command
  does its own work (FR-004);
- ``history`` never asks (FR-005): it reports only what has been recorded.

Loading goes through ``configuration.load_configuration`` (research R-10), so every command that
opens a session (``get``, ``show``, ``set``, ``history``, ``watch``) reads the schema, fetches
remote includes and validates the configuration, and fails with exit 4 when any of that fails
(spec S-2, S-8, FR-009).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from troupe import reconcile as reconciliation
from troupe.configuration import load_configuration
from troupe.history import HistoryStore
from troupe.leaves import flatten
from troupe.lineage import import_lineage
from troupe.location import Url
from troupe.lock import theatre_lock
from troupe.schema import Schema
from troupe.theatre import Theatre, locate
from troupe.tree import Node


@dataclass
class Session:
    """What a command works with.

    Attributes:
        theatre: The theatre, located again under the lock.
        tree: The configuration as the files on disk were at the start of the session; after a
            reconcile it is also the recorded configuration.
        history: The theatre's history, open for the duration of the session.
        schema: The theatre's schema as read by this session's load, or ``None`` when there is
            no ``troupe.schema.json``; ``tree`` matches it. ``set`` uses it for literal and
            validity decisions on its in-memory reloads (spec S-9, S-11 to S-13).
        fetched: The remote texts this session's load fetched, by URL. ``set`` passes it to its
            reloads, so one command fetches each URL once and sees one snapshot (research R-10).
    """

    theatre: Theatre
    tree: Node
    history: HistoryStore
    schema: Schema | None
    fetched: dict[Url, str]


@contextmanager
def open_session(theatre: Theatre, *, reconcile: bool) -> Iterator[Session]:
    """Lock the theatre, load the configuration, then import or (if asked) reconcile.

    The whole ``with`` block runs under the theatre lock, so no other session (another command
    or ``watch``) can interleave. The root file is located again under the lock, because it may
    have been renamed since the CLI located it. The configuration is loaded (schema read, remote
    includes fetched, configuration validated) before the history is opened, so a load, fetch or
    validation failure leaves no history file behind and records nothing. An import or
    reconcile is saved before the block runs, so it is kept if the command then fails (D-7);
    each is its own change, never attributed to the CLI actor (FR-005, FR-010).
    Right after an import the files equal the recorded configuration, so there is nothing to
    reconcile.

    Args:
        theatre: The theatre located by the CLI.
        reconcile: Whether to reconcile an already-imported theatre (``history`` passes False).

    Raises:
        LoadError: If the theatre cannot be locked, located or loaded, a remote include cannot be
            fetched, or the schema is invalid or not matched; nothing is recorded.
    """
    with theatre_lock(theatre.state_dir):
        current = locate(theatre.directory)
        loaded = load_configuration(current)
        tree = loaded.tree
        store = HistoryStore(current.state_dir)
        try:
            if not store.is_imported():
                store.import_leaves(flatten(tree), import_lineage())
            elif reconcile:
                reconciliation.reconcile(store, tree)
            yield Session(current, tree, store, loaded.schema, loaded.fetched)
        finally:
            store.close()
