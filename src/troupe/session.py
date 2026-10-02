"""One command's view of a theatre: the loaded tree and the open history (research R-04).

This is the only place a theatre is imported: every command that loads the configuration does so
through ``open_session``, which imports (one ``import`` event per leaf, in document order) when
the history does not exist yet. Importing is not reconciling: once imported, later hand edits
never produce events.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from troupe.history import HistoryStore
from troupe.leaves import flatten
from troupe.loader import load
from troupe.theatre import Theatre
from troupe.tree import Node


@dataclass
class Session:
    """What a command works with.

    Attributes:
        theatre: The located theatre.
        tree: The configuration as the files on disk were at the start of the command.
        history: The theatre's history, open for the duration of the session.
    """

    theatre: Theatre
    tree: Node
    history: HistoryStore


@contextmanager
def open_session(theatre: Theatre) -> Iterator[Session]:
    """Load the configuration, then open (and if needed import into) the history.

    The configuration is loaded before the history is opened, so a load failure leaves no
    history file behind. A command that fails after the session opened keeps the import.

    Raises:
        LoadError: If the configuration cannot be loaded; nothing is created.
    """
    tree = load(theatre.config_file)
    store = HistoryStore(theatre.state_dir)
    try:
        if not store.is_imported():
            store.import_leaves(flatten(tree))
        yield Session(theatre, tree, store)
    finally:
        store.close()
