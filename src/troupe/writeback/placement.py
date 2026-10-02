"""Where a ``set`` is written (FR-010..FR-013): the one place that decides it (TROUPE-007).

Contract ("Where the change is written"):

- An existing value is changed in the file that contains it (FR-010). A scalar becomes
  ``ReplaceScalar``, a mapping or list ``ReplaceCollection`` and a text include ``ReplaceText``
  (the target file's content is rewritten; see ``troupe.writeback.apply``).
- A value whose whole value comes from a YAML include is never replaced (FR-013, exit 3); a path
  *inside* the included file is an ordinary path whose node belongs to the included file.
- A new key goes into the file containing the **deepest existing ancestor mapping** of PATH,
  creating the missing intermediate mappings there (FR-011). This rule is expected to change at
  step 5 (C-005), which is why it lives here and nowhere else.
- A final list index equal to the list's length appends; a larger index exits 5 (FR-012).

Choices made where the contract is silent (TROUPE-002, TROUPE-008):

- A key with an empty value (``key:``) holds a null scalar, not a mapping: a path through it is
  a path through a scalar (exit 5), never a request to turn the null into a mapping.
- Missing segments are only ever created as mapping keys. A digit-only missing segment below a
  mapping would need either a mapping with a digit-only key (out of contract, C-004) or a new
  list, which the contract does not describe, so it exits 5.
"""

from dataclasses import dataclass

from troupe.errors import PathError, WriteRefused
from troupe.paths import is_index, unwrap, walk
from troupe.tree import (
    MappingNode,
    Node,
    ScalarNode,
    SequenceNode,
    TextInclude,
    YamlInclude,
)
from troupe.writeback.scalars import Context

Collection = MappingNode | SequenceNode


@dataclass(frozen=True)
class ReplaceScalar:
    """Replace the existing scalar ``node`` at ``slot`` of ``parent``.

    Attributes:
        parent: The collection holding the scalar (in the scalar's file).
        slot: Its key (mapping) or index (sequence).
        node: The scalar.
        context: ``"flow"`` if ``parent`` is a flow collection, else ``"block"``.
    """

    parent: Collection
    slot: str | int
    node: ScalarNode
    context: Context


@dataclass(frozen=True)
class ReplaceText:
    """Rewrite the target file of the text include ``node``."""

    node: TextInclude


@dataclass(frozen=True)
class ReplaceCollection:
    """Replace the existing mapping or list ``node`` at ``slot`` of ``parent``."""

    parent: Collection
    slot: str | int
    node: Collection


@dataclass(frozen=True)
class AddKeys:
    """Add ``keys[0]`` to ``mapping``; ``keys[1:]`` are intermediate mappings, the last the leaf.

    ``mapping`` is the deepest existing ancestor mapping of PATH (FR-011); the new text goes into
    ``mapping.origin.file`` (an included file when the mapping was reached through an include).
    """

    mapping: MappingNode
    keys: list[str]


@dataclass(frozen=True)
class AppendItem:
    """Append a new last item to ``sequence`` (FR-012)."""

    sequence: SequenceNode


Placement = ReplaceScalar | ReplaceText | ReplaceCollection | AddKeys | AppendItem


def place(root: Node, segments: list[str], dotted: str) -> Placement:
    """Decide where ``set dotted VALUE`` is written.

    Args:
        root: The configuration as loaded from disk.
        segments: The parsed, non-empty PATH.
        dotted: PATH as the user wrote it, for messages.

    Raises:
        WriteRefused: If the whole value at PATH comes from a YAML include (exit 3).
        PathError: If PATH runs through a scalar, null or text include, uses a non-index segment
            on a list, uses an index larger than the list's length, or needs a missing segment
            that cannot be created (exit 5).
    """
    found = walk(root, segments)
    if not found.remaining:
        return _existing(found.nodes, segments, dotted)
    deepest = unwrap(found.nodes[-1])
    remaining = found.remaining
    prefix = ".".join(segments[: len(segments) - len(remaining)]) or "(root)"
    if isinstance(deepest, SequenceNode):
        # ``walk`` only stops at a list on an index >= its length.
        index = int(remaining[0])
        if index == len(deepest.items) and len(remaining) == 1:
            return AppendItem(deepest)
        if index > len(deepest.items):
            raise PathError(
                f"{dotted}: index {index} is out of range for {prefix}"
                f" (length {len(deepest.items)}; only index {len(deepest.items)} appends)"
            )
        raise PathError(f"path not found: {dotted} (no {prefix}.{remaining[0]})")
    if not isinstance(deepest, MappingNode):  # pragma: no cover - ``walk`` raises first
        raise PathError(f"{dotted}: {prefix} is not a mapping")
    digit = next((segment for segment in remaining if is_index(segment)), None)
    if digit is not None:
        raise PathError(
            f"path not found: {dotted} (no {prefix}.{remaining[0]}; a missing list index"
            f" '{digit}' cannot be created)"
        )
    return AddKeys(deepest, list(remaining))


def _existing(nodes: list[Node], segments: list[str], dotted: str) -> Placement:
    node = nodes[-1]
    if isinstance(node, YamlInclude):
        raise WriteRefused(
            f"{dotted}: value comes from include {node.target.path}; refusing to replace it"
            " (change a path inside it instead); no file changed"
        )
    if isinstance(node, TextInclude):
        return ReplaceText(node)
    parent = unwrap(nodes[-2])
    if not isinstance(parent, MappingNode | SequenceNode):  # pragma: no cover - walk invariant
        raise PathError(f"{dotted}: parent of the value is not a collection")
    slot: str | int = segments[-1] if isinstance(parent, MappingNode) else int(segments[-1])
    if isinstance(node, ScalarNode):
        return ReplaceScalar(parent, slot, node, "flow" if parent.flow else "block")
    return ReplaceCollection(parent, slot, node)
