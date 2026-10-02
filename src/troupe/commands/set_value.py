"""``troupe config set PATH VALUE``: change one value byte-surgically, record it (FR-010..023).

Order (plan "Engineering Alignment"; research R-04, R-12, R-17):

1. Parse PATH and VALUE: a usage error (exit 2) happens before anything is loaded or imported.
2. Open the session: load the files on disk and import the theatre if this is its first command.
3. ``apply_set``: decide placement, render, verify in memory. Refusals (exit 3) and path errors
   (exit 5) happen here, before any write; a no-op returns no files.
4. Write the changed file(s) atomically.
5. Only after a successful write, append one event per changed leaf (``leaves.diff`` of the tree
   before and the verified tree after). A failed write appends nothing.

Success prints nothing.
"""

import argparse

from troupe.errors import WriteRefused
from troupe.leaves import diff, flatten
from troupe.paths import parse_path
from troupe.session import open_session
from troupe.theatre import Theatre
from troupe.values import parse_value
from troupe.writeback.apply import apply_set
from troupe.writeback.fileio import write_files


def run(theatre: Theatre, args: argparse.Namespace) -> str:
    """Set ``args.path`` to ``args.value``; return the (empty) stdout text.

    Raises:
        UsageError: If PATH has an empty segment or VALUE is not one YAML flow node (exit 2).
        LoadError: If the configuration cannot be loaded (exit 4).
        WriteRefused: If the change cannot be written as contracted, or writing failed (exit 3).
        PathError: If PATH cannot be reached or created (exit 5).
    """
    path: str = args.path
    raw_value: str = args.value
    segments = parse_path(path)
    value = parse_value(raw_value)
    with open_session(theatre) as session:
        plan = apply_set(session.tree, segments, path, value, raw_value)
        if plan.tree is None:
            return ""
        changes = diff(flatten(session.tree), flatten(plan.tree))
        try:
            write_files(plan.files)
        except OSError as err:
            names = ", ".join(str(file.path) for file in plan.files)
            raise WriteRefused(f"{path}: cannot write {names}: {err.strerror or err}") from err
        session.history.record(changes)
    return ""
