"""VALUE arguments, scalar printing and scalar detection: the one place each is decided.

``parse_value`` turns a ``set`` VALUE argument into a plain Python value. VALUE is exactly one
YAML 1.2 core-schema *flow* node: plain scalars resolve per ``yamlcore.resolve_plain``, quoted
scalars are strings, ``{...}`` is a ``dict`` and ``[...]`` a ``list``. Block nodes (``a: 1``,
``- a``, ``|``/``>`` scalars) are refused, because they cannot be told apart from a mistyped
argument (FR-004). ``format_scalar`` is how ``get`` (and ``show`` on a scalar) prints a scalar
(FR-005). ``scalar_of`` decides whether a node is a scalar at all, and what its value is
(FR-001/FR-013).
"""

from dataclasses import dataclass

from troupe import yamlcore
from troupe.errors import LoadError, UsageError
from troupe.paths import unwrap
from troupe.tree import Node, Scalar, ScalarNode, TextInclude
from troupe.yamlcore import RawMapping, RawNode, RawScalar

type Value = Scalar | dict[str, Value] | list[Value]

_BLOCK_SCALAR_STYLES = ("literal", "folded")


def parse_value(text: str) -> Value:
    """Parse a VALUE argument as one YAML 1.2 core flow node.

    An empty (or comment-only) VALUE is the empty plain scalar, i.e. ``None``.

    Raises:
        UsageError: If ``text`` is not valid YAML, is not a single flow node, uses anchors,
            aliases or tags, or has a duplicate or non-scalar mapping key; the message quotes
            ``text``.
    """
    try:
        raw = yamlcore.compose(text, source=f"VALUE {text!r}")
    except LoadError as err:
        raise UsageError(err.message) from err
    if raw is None:
        return None
    if _is_block(raw):
        raise UsageError(f"VALUE is not a single YAML flow node: {text!r}")
    return _convert(raw, text)


def _is_block(raw: RawNode) -> bool:
    # Only the root needs checking: YAML forbids block nodes inside flow collections.
    if isinstance(raw, RawScalar):
        return raw.style in _BLOCK_SCALAR_STYLES
    return not raw.flow


def _convert(raw: RawNode, text: str) -> Value:
    if isinstance(raw, RawScalar):
        return yamlcore.resolve_plain(raw.text) if raw.style == "plain" else raw.text
    if isinstance(raw, RawMapping):
        mapping: dict[str, Value] = {}
        for raw_key, raw_value in raw.pairs:
            if not isinstance(raw_key, RawScalar):
                raise UsageError(f"VALUE has a mapping key that is not a scalar: {text!r}")
            if raw_key.text in mapping:
                raise UsageError(f"VALUE has duplicate key {raw_key.text!r}: {text!r}")
            mapping[raw_key.text] = _convert(raw_value, text)
        return mapping
    return [_convert(item, text) for item in raw.items]


def format_scalar(value: Scalar) -> str:
    """Return how ``show`` prints ``value`` (contracts/cli.md "Scalar printing").

    A string prints exactly, plus ``"\\n"`` unless it already ends with one; ``true``/``false``;
    ``null``; integers in decimal; floats as ``repr()``. Every result ends with ``"\\n"``.
    """
    if isinstance(value, str):
        return value if value.endswith("\n") else value + "\n"
    if isinstance(value, bool):  # before int: bool is an int subclass
        printed = "true" if value else "false"
    elif value is None:
        printed = "null"
    elif isinstance(value, int):
        printed = str(value)
    else:
        printed = repr(value)
    return printed + "\n"


@dataclass(frozen=True)
class ScalarValue:
    """A node's scalar value. ``ScalarValue(None)`` is a YAML null, which *is* a scalar."""

    value: Scalar


def scalar_of(node: Node) -> ScalarValue | None:
    """Return the scalar value of ``node``, or ``None`` if it is a mapping or a list.

    ``node`` may be as found (a ``YamlInclude`` is unwrapped here, so an include whose root is a
    scalar counts as that scalar). A text include is the string ``target.text``, exactly.
    """
    content = unwrap(node)
    if isinstance(content, ScalarNode):
        return ScalarValue(content.value)
    if isinstance(content, TextInclude):
        return ScalarValue(content.target.text)
    return None
