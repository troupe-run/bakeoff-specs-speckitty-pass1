"""``troupe config show [PATH] [--sources]``: print PATH, or everything, as YAML.

Spec FR-004 to FR-006, FR-009 to FR-014; contracts/cli.md "get and show".

- A scalar at PATH without ``--sources`` prints exactly what ``get PATH`` prints
  (``values.format_scalar``, FR-004). It never goes through the YAML renderer, whose float
  spellings (``1.0e+20``, ``.inf``) differ from ``get``'s on purpose (research D-3, D-10).
- A mapping or list at PATH, or the whole configuration when PATH is omitted, prints as
  block-style YAML through ``troupe.yamlout`` (FR-005, FR-006).
- With ``--sources`` the same YAML gets ``# from <file>`` on every line holding a scalar, the file
  relative to the resolved theatre directory (FR-009 to FR-011). A scalar PATH with ``--sources``
  prints that scalar as YAML with its comment (FR-012, decision DM 01M411YHFR2PMJEJWMHX4KN9C4).

``show`` reconciles first (FR-013), so it prints what the files say now. It never writes a
configuration or include file (FR-014); only the history store may change.
"""

import argparse

from troupe import yamlout
from troupe.lineage import Actor
from troupe.paths import lookup, parse_path
from troupe.session import open_session
from troupe.theatre import Theatre
from troupe.values import format_scalar, scalar_of


def run(theatre: Theatre, args: argparse.Namespace, actor: Actor) -> str:
    """Return the printed node at ``args.path`` (the whole configuration when it is ``None``).

    ``actor`` is unused: a read-only command records no events of its own.

    Raises:
        UsageError: If PATH has an empty segment (checked before anything is loaded).
        LoadError: If the configuration cannot be loaded.
        PathError: If PATH does not exist.
    """
    path: str | None = args.path
    sources: bool = args.sources
    segments = None if path is None else parse_path(path)
    with open_session(theatre, reconcile=True) as session:
        node = session.tree if segments is None else lookup(session.tree, segments, str(path))
        sources_root = session.theatre.directory if sources else None
    scalar = scalar_of(node)
    if scalar is not None and not sources:
        return format_scalar(scalar.value)
    return yamlout.to_text(yamlout.render(node), sources_root)
