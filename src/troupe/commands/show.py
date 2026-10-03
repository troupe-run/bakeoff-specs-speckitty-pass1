"""``troupe config show PATH``: print the scalar at PATH (FR-009).

``show`` reconciles first (FR-004): hand edits are recorded before the value is printed, so the
printed value is the current file value.

A text include is a string (the target file's exact text). A mapping, a list (including a whole
YAML include) or a missing path is a ``PathError`` (exit 5).
"""

import argparse

from troupe.errors import PathError
from troupe.paths import lookup, parse_path, unwrap
from troupe.session import open_session
from troupe.theatre import Theatre
from troupe.tree import MappingNode, ScalarNode, TextInclude
from troupe.values import format_scalar


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
        node = unwrap(lookup(session.tree, segments, path))
    if isinstance(node, ScalarNode):
        return format_scalar(node.value)
    if isinstance(node, TextInclude):
        return format_scalar(node.target.text)
    # ``unwrap`` never returns a YamlInclude, so what is left is a mapping or a list.
    kind = "mapping" if isinstance(node, MappingNode) else "list"
    raise PathError(f"{path} is a {kind}, not a scalar")
