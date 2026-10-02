"""The one place that knows the YAML library (ruamel.yaml) and the YAML 1.2 core schema.

No other module imports ``ruamel``: ``compose`` turns ruamel's node graph into the small typed
``Raw*`` dataclasses below, and ``resolve_plain`` resolves plain scalars ourselves, because
ruamel's own resolver is not the YAML 1.2 core schema (research R-13).

Span behaviour (ruamel 0.19, verified by ``tests/unit/test_yamlcore.py``). ``start``/``end`` are
code-point indices into the composed string; a leading BOM is index 0 and CRLF counts as two.
Spans are recorded exactly as ruamel reports them; consumers that need precise ends of block
nodes must derive them from the text:

- Plain scalars: the span covers the scalar text only; trailing spaces and comments are excluded.
  A multi-line plain scalar's span covers all its lines.
- Quoted scalars: the span includes the quotes.
- Block scalars (``|``, ``>``): the span starts at the indicator and ends after the content
  *including* the trailing line breaks the scalar consumes (e.g. blank lines kept by ``|+`` or
  stripped by clip/``-``); comment lines after the content are not included.
- Empty (null) values are zero-width spans whose position is unreliable: ``a:`` followed by a
  newline yields the start of the *next* line, ``- `` yields the column after the dash, and a
  value at end of file yields ``len(text)``.
- Block collections: ``start`` is the first key/dash; ``end`` is the start of the next token
  after the collection, so it usually lies past trailing blank lines *and comment lines* (at the
  start of the next sibling's line, or at end of file).
- Flow collections: the span is exactly ``[...]`` / ``{...}``.
- Anchors and tags would be inside a node's span; they are rejected here (out of contract, C-004).
"""

import math
import re
from dataclasses import dataclass
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import MarkedYAMLError, YAMLError
from ruamel.yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from troupe.errors import LoadError
from troupe.tree import Scalar, ScalarStyle

_STYLES: dict[str | None, ScalarStyle] = {
    None: "plain",
    "'": "single",
    '"': "double",
    "|": "literal",
    ">": "folded",
}

# YAML 1.2 core schema (https://yaml.org/spec/1.2.2/#1023-core-schema), research R-13.
_NULL = re.compile(r"null|Null|NULL|~|")
_TRUE = re.compile(r"true|True|TRUE")
_FALSE = re.compile(r"false|False|FALSE")
_INT_DEC = re.compile(r"[-+]?[0-9]+")
_INT_OCT = re.compile(r"0o[0-7]+")
_INT_HEX = re.compile(r"0x[0-9a-fA-F]+")
_FLOAT = re.compile(r"[-+]?(\.[0-9]+|[0-9]+(\.[0-9]*)?)([eE][-+]?[0-9]+)?")
_INF = re.compile(r"[-+]?\.(inf|Inf|INF)")
_NAN = re.compile(r"\.(nan|NaN|NAN)")


@dataclass(frozen=True)
class RawScalar:
    """A composed scalar: ``text`` is the unescaped/folded content, not yet resolved."""

    text: str
    style: ScalarStyle
    start: int
    end: int


@dataclass(frozen=True)
class RawMapping:
    """A composed mapping; ``pairs`` are (key, value) in document order."""

    pairs: list[tuple["RawNode", "RawNode"]]
    flow: bool
    start: int
    end: int


@dataclass(frozen=True)
class RawSequence:
    """A composed sequence."""

    items: list["RawNode"]
    flow: bool
    start: int
    end: int


RawNode = RawScalar | RawMapping | RawSequence


def resolve_plain(text: str) -> Scalar:
    """Resolve a plain scalar's text per the YAML 1.2 core schema; anything else is a string.

    Only for plain scalars: quoted and block scalars are always strings.
    """
    if _NULL.fullmatch(text):
        return None
    if _TRUE.fullmatch(text):
        return True
    if _FALSE.fullmatch(text):
        return False
    if _INT_DEC.fullmatch(text):
        return int(text, 10)
    if _INT_OCT.fullmatch(text):
        return int(text[2:], 8)
    if _INT_HEX.fullmatch(text):
        return int(text[2:], 16)
    if _FLOAT.fullmatch(text):
        return float(text)
    if _INF.fullmatch(text):
        return -math.inf if text.startswith("-") else math.inf
    if _NAN.fullmatch(text):
        return math.nan
    return text


def compose(text: str, source: str) -> RawNode | None:
    """Compose ``text`` (one YAML document) into raw nodes; ``None`` for an empty document.

    Args:
        text: The document text (as decoded from the file, BOM included).
        source: The file name used in error messages.

    Raises:
        LoadError: If the text is not a single valid YAML document, or uses anchors, aliases or
            tags (out of contract).
    """
    try:
        node: Node | None = YAML(typ="safe", pure=True).compose(text)
    except MarkedYAMLError as err:
        raise LoadError(f"cannot parse {source}: {_describe(err)}") from err
    except YAMLError as err:
        first_line = str(err).splitlines()[0] if str(err) else type(err).__name__
        raise LoadError(f"cannot parse {source}: {first_line}") from err
    return None if node is None else _convert(node, text, source)


def _describe(err: MarkedYAMLError) -> str:
    problem = err.problem or err.context or "invalid YAML"
    mark = err.problem_mark or err.context_mark
    return f"{problem} at line {mark.line + 1}" if mark is not None else str(problem)


def _convert(node: Node, text: str, source: str) -> RawNode:
    start: int = node.start_mark.index
    end: int = node.end_mark.index
    if end > start and text[start] in "&!":  # node content never starts so
        line = text.count("\n", 0, start) + 1
        raise LoadError(f"cannot parse {source}: anchors and tags are not supported at line {line}")
    if isinstance(node, ScalarNode):
        value: Any = node.value
        return RawScalar(text=str(value), style=_STYLES[node.style], start=start, end=end)
    if isinstance(node, MappingNode):
        pairs = [(_convert(k, text, source), _convert(v, text, source)) for k, v in node.value]
        return RawMapping(pairs=pairs, flow=bool(node.flow_style), start=start, end=end)
    if isinstance(node, SequenceNode):
        items = [_convert(item, text, source) for item in node.value]
        return RawSequence(items=items, flow=bool(node.flow_style), start=start, end=end)
    raise LoadError(f"cannot parse {source}: unsupported node {type(node).__name__}")
