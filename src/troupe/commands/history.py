"""``troupe config history [PATH]``: print recorded changes as JSON Lines (FR-024).

One JSON object per line, oldest first, keys in the order ``seq, op, path, old, new``. With
PATH, only events whose path equals PATH or lies under it (``PATH.``-prefixed); a PATH that
matches nothing prints nothing.

``history`` never reconciles (FR-005): it reports what has been recorded. It still imports a
never-imported theatre (D-5).
"""

import argparse
import json

from troupe.history import HistoryRecord
from troupe.paths import parse_path
from troupe.session import open_session
from troupe.theatre import Theatre


def _matches(record: HistoryRecord, path: str) -> bool:
    return record.path == path or record.path.startswith(path + ".")


def _line(record: HistoryRecord) -> str:
    fields = {
        "seq": record.seq,
        "op": record.op,
        "path": record.path,
        "old": record.old,
        "new": record.new,
    }
    return json.dumps(fields, ensure_ascii=False) + "\n"


def run(theatre: Theatre, args: argparse.Namespace) -> str:
    """Return the history (filtered by ``args.path`` if given) as JSON Lines.

    Raises:
        UsageError: If PATH has an empty segment (checked before anything is loaded).
        LoadError: If the configuration cannot be loaded.
    """
    path: str | None = args.path
    if path is not None:
        parse_path(path)
    with open_session(theatre, reconcile=False) as session:
        records = session.history.records()
    if path is not None:
        records = [record for record in records if _matches(record, path)]
    return "".join(_line(record) for record in records)
