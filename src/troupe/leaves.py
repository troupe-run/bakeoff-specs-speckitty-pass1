"""Leaves of the merged configuration and the leaf-level difference between two configurations.

A leaf is a scalar or a text include, addressed by its dotted path in the merged tree (research
R-07): a YAML include is transparent, so its leaves sit at merged paths; a text include is one
leaf whose value is the target file's exact text; list items are addressed ``list.0``,
``list.1``. Empty mappings and lists contribute no leaves. Leaves are what history records.
"""

import math
from dataclasses import dataclass
from typing import Literal

from troupe.tree import MappingNode, Node, ScalarNode, SequenceNode, TextInclude, YamlInclude

JsonScalar = str | int | float | bool | None


@dataclass(frozen=True)
class Change:
    """One leaf change: ``set`` (changed or created; ``old`` is None when created) or ``remove``.

    Attributes:
        op: ``"set"`` or ``"remove"``.
        path: Dotted path in the merged configuration.
        old: Value before (``None`` if the leaf did not exist).
        new: Value after (``None`` for ``remove``).
    """

    op: Literal["set", "remove"]
    path: str
    old: JsonScalar
    new: JsonScalar


def _join(prefix: str, segment: str) -> str:
    return f"{prefix}.{segment}" if prefix else segment


def flatten(node: Node, prefix: str = "") -> dict[str, JsonScalar]:
    """Return every leaf under ``node`` keyed by dotted path, in document order.

    Args:
        node: A SourceTree node (usually the root).
        prefix: The dotted path of ``node`` itself (``""`` for the root).
    """
    leaves: dict[str, JsonScalar] = {}
    _collect(node, prefix, leaves)
    return leaves


def _collect(node: Node, prefix: str, leaves: dict[str, JsonScalar]) -> None:
    if isinstance(node, ScalarNode):
        leaves[prefix] = node.value
    elif isinstance(node, TextInclude):
        leaves[prefix] = node.target.text
    elif isinstance(node, YamlInclude):
        _collect(node.root, prefix, leaves)
    elif isinstance(node, MappingNode):
        for entry in node.entries:
            _collect(entry.value, _join(prefix, entry.key), leaves)
    elif isinstance(node, SequenceNode):
        for index, item in enumerate(node.items):
            _collect(item, _join(prefix, str(index)), leaves)


def same(a: JsonScalar, b: JsonScalar) -> bool:
    """Type-aware equality: ``1``, ``1.0``, ``"1"`` and ``True`` all differ; NaN equals NaN."""
    if type(a) is not type(b):
        return False
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    return a == b


def diff(before: dict[str, JsonScalar], after: dict[str, JsonScalar]) -> list[Change]:
    """Return the leaf changes that turn ``before`` into ``after``.

    Presence matters, not value: a leaf absent before is a ``set`` even when its new value is
    ``None``, and a leaf absent after is a ``remove`` even when its old value was ``None``.

    Returns:
        ``set`` changes in ``after`` order, then ``remove`` changes in ``before`` order; ``[]``
        when nothing differs.
    """
    changes = [
        Change(op="set", path=path, old=before.get(path), new=value)
        for path, value in after.items()
        if path not in before or not same(before[path], value)
    ]
    changes.extend(
        Change(op="remove", path=path, old=value, new=None)
        for path, value in before.items()
        if path not in after
    )
    return changes
