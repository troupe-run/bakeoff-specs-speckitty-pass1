"""Reconcile: bring the recorded configuration in line with the files (FR-002, FR-003).

The rule: record ``diff(recorded leaves, leaves of the files)`` and nothing else. Because a
``set`` records its own events in the same locked session as its write-back, a reconcile that
later sees the write-back finds no difference: write-backs are never recorded twice (FR-015,
research R-01). Reconcile only reads files; it never writes them (NFR-004).

Each reconcile is its own change: it builds one ``file_lineage()`` (unknown actor, via ``file``)
for all the events it records. That covers the reconcile before a command's own work and each
reconcile ``watch`` performs (FR-005, FR-010, FR-011). It never sees the CLI actor.

This module also names the files a load read (``watched_files``), which ``watch`` observes.
"""

from pathlib import Path

from troupe.history import HistoryStore
from troupe.leaves import Change, diff, flatten
from troupe.lineage import file_lineage
from troupe.tree import MappingNode, Node, SequenceNode, SourceFile, TextInclude, YamlInclude


def reconcile(store: HistoryStore, tree: Node) -> list[Change]:
    """Record one event per leaf that differs between the history and ``tree``; return them.

    Ordering (D-6) is ``leaves.diff``'s: ``set`` in file document order, then ``remove`` in
    recorded order. All events are saved in one atomic ``save()`` and share one new file
    lineage, so they form one change; nothing is saved for ``[]``.
    Call only under the theatre lock and only after the theatre has been imported.
    """
    changes = diff(store.recorded_leaves(), flatten(tree))
    store.record(changes, file_lineage())
    return changes


def watched_files(tree: Node) -> dict[Path, bytes]:
    """Return every file the load read, mapped to its bytes as loaded (research R-03).

    That is the origin file of every node plus every include target (YAML and text, any depth).
    ``SourceFile.text`` is strict-UTF-8-decoded without newline translation, so encoding it back
    gives exactly the bytes that were read. Keyed by the resolved path: ``SourceFile`` compares
    by identity.
    """
    files: dict[Path, bytes] = {}
    _collect(tree, files)
    return files


def _add(file: SourceFile, files: dict[Path, bytes]) -> None:
    files.setdefault(file.path, file.text.encode("utf-8"))


def _collect(node: Node, files: dict[Path, bytes]) -> None:
    _add(node.origin.file, files)
    if isinstance(node, MappingNode):
        for entry in node.entries:
            _collect(entry.value, files)
    elif isinstance(node, SequenceNode):
        for item in node.items:
            _collect(item, files)
    elif isinstance(node, YamlInclude):
        _add(node.target, files)
        _collect(node.root, files)
    elif isinstance(node, TextInclude):
        _add(node.target, files)
