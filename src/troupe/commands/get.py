"""``troupe config get PATH``: print the scalar at PATH (spec FR-001, FR-002, FR-013).

``get`` takes over the step-1 ``show PATH`` behaviour: it reconciles first (hand edits are
recorded before the value is printed, so the printed value is the current file value) and prints
the scalar per ``values.format_scalar``. A text include is a string (the target file's exact
text).

A missing path is a ``PathError`` (exit 5). So is a mapping or a list (including a whole YAML
include); that message names PATH and points to ``troupe config show``.
"""

import argparse
from typing import Final

from troupe.errors import PathError
from troupe.paths import lookup, parse_path, unwrap
from troupe.session import open_session
from troupe.theatre import Theatre
from troupe.tree import MappingNode
from troupe.values import format_scalar, scalar_of

SECTION_REFUSAL: Final = "{path} is a {kind}, not a scalar; use 'troupe config show {path}'"


def run(theatre: Theatre, args: argparse.Namespace) -> str:
    """Return the printed scalar at ``args.path``.

    Raises:
        UsageError: If PATH has an empty segment (checked before anything is loaded).
        LoadError: If the configuration cannot be loaded.
        PathError: If PATH does not exist or names a mapping or list.
    """
    path: str = args.path
    segments = parse_path(path)
    with open_session(theatre, reconcile=True) as session:
        node = lookup(session.tree, segments, path)
    scalar = scalar_of(node)
    if scalar is not None:
        return format_scalar(scalar.value)
    kind = "mapping" if isinstance(unwrap(node), MappingNode) else "list"
    raise PathError(SECTION_REFUSAL.format(path=path, kind=kind))
