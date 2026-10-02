"""Configuration paths (FR-003): ``.``-separated segments; a digit-only segment indexes a list.

Walking is include-aware: a ``YamlInclude`` is transparent and the walk continues at its
``root``. ``Walk.nodes`` deliberately holds the node *as found* at each step (not unwrapped), so
a caller can tell that the whole value at a path comes from a YAML include
(``isinstance(walk.nodes[-1], YamlInclude)``); use ``unwrap`` to get the embedded content.
"""

from dataclasses import dataclass

from troupe.errors import PathError, UsageError
from troupe.tree import MappingNode, Node, SequenceNode, YamlInclude


def parse_path(text: str) -> list[str]:
    """Split ``"a.b.0"`` into ``["a", "b", "0"]``.

    Raises:
        UsageError: If any segment is empty (including the empty path); the message names it.
    """
    segments = text.split(".")
    if "" in segments:
        raise UsageError(f"invalid path '{text}': empty segment")
    return segments


def is_index(segment: str) -> bool:
    """Return whether ``segment`` is digit-only (ASCII ``0-9``), i.e. a list index."""
    return segment.isascii() and segment.isdigit()


def unwrap(node: Node) -> Node:
    """Return the content of ``node``: the (innermost) root of a ``YamlInclude``, else ``node``."""
    while isinstance(node, YamlInclude):
        node = node.root
    return node


@dataclass
class Walk:
    """Result of walking a path as far as it exists.

    Attributes:
        nodes: ``nodes[0]`` is the root; ``nodes[i]`` is the node reached after ``i`` segments,
            as found (a ``YamlInclude`` is not unwrapped; see ``unwrap``).
        remaining: Segments not consumed; empty when the whole path exists. The walk stops at a
            missing mapping key or at a list index ``>= len(list)``.
    """

    nodes: list[Node]
    remaining: list[str]


def walk(root: Node, segments: list[str]) -> Walk:
    """Follow ``segments`` from ``root`` as far as they exist.

    Raises:
        PathError: If a non-index segment meets a list, or any segment meets a scalar or text
            include; the message names the full dotted path and the offending prefix.
    """
    path = ".".join(segments)
    nodes = [root]
    for consumed, segment in enumerate(segments):
        current = unwrap(nodes[-1])
        prefix = ".".join(segments[:consumed]) or "(root)"
        if isinstance(current, MappingNode):
            entry = current.get(segment)
            if entry is None:
                return Walk(nodes, segments[consumed:])
            nodes.append(entry.value)
        elif isinstance(current, SequenceNode):
            if not is_index(segment):
                raise PathError(f"{path}: {prefix} is a list; expected an index, got '{segment}'")
            index = int(segment)
            if index >= len(current.items):
                return Walk(nodes, segments[consumed:])
            nodes.append(current.items[index])
        else:
            raise PathError(f"{path}: {prefix} is a scalar")
    return Walk(nodes, [])


def lookup(root: Node, segments: list[str], dotted: str) -> Node:
    """Return the node at ``segments`` as found (not unwrapped; see ``unwrap``).

    Args:
        root: The tree root.
        segments: Parsed path.
        dotted: The path as the user wrote it, for messages.

    Raises:
        PathError: If the path does not exist (or ``walk`` raises); the message names ``dotted``.
    """
    result = walk(root, segments)
    if result.remaining:
        missing = segments[: len(segments) - len(result.remaining) + 1]
        raise PathError(f"path not found: {dotted} (no {'.'.join(missing)})")
    return result.nodes[-1]
