"""One command's view of a theatre: the loaded tree and the open history (research R-04, R-07).

This is the only place that decides when a command imports or reconciles. Every command that
loads the configuration does so through ``open_session``, all under the theatre lock:

- a never-imported theatre is imported (one ``import`` event per leaf, in document order). The
  import is its own change, attributed to the unknown actor via ``import`` (FR-005, FR-010);
- otherwise, when the command asks for it, the history is reconciled with the files
  (``troupe.reconcile``), so hand edits made while nothing ran are recorded before the command
  does its own work (FR-004);
- ``history`` never asks (FR-005): it reports only what has been recorded.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from troupe import reconcile as reconciliation
from troupe.history import HistoryStore
from troupe.leaves import flatten
from troupe.lineage import import_lineage
from troupe.loader import load
from troupe.lock import theatre_lock
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
    """

    theatre: Theatre
    tree: Node
    history: HistoryStore


@contextmanager
def open_session(theatre: Theatre, *, reconcile: bool) -> Iterator[Session]:
    """Lock the theatre, load the configuration, then import or (if asked) reconcile.

    The whole ``with`` block runs under the theatre lock, so no other session (another command
    or ``watch``) can interleave. The root file is located again under the lock, because it may
    have been renamed since the CLI located it. The configuration is loaded before the history
    is opened, so a load failure leaves no history file behind and records nothing. An import or
    reconcile is saved before the block runs, so it is kept if the command then fails (D-7);
    each is its own change, never attributed to the CLI actor (FR-005, FR-010).
    Right after an import the files equal the recorded configuration, so there is nothing to
    reconcile.

    Args:
        theatre: The theatre located by the CLI.
        reconcile: Whether to reconcile an already-imported theatre (``history`` passes False).

    Raises:
        LoadError: If the theatre cannot be locked, located or loaded; nothing is recorded.
    """
    with theatre_lock(theatre.state_dir):
        current = locate(theatre.directory)
        tree = load(current.config_file)
        store = HistoryStore(current.state_dir)
        try:
            if not store.is_imported():
                store.import_leaves(flatten(tree), import_lineage())
            elif reconcile:
                reconciliation.reconcile(store, tree)
            yield Session(current, tree, store)
        finally:
            store.close()
