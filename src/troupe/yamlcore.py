"""The one place that knows the YAML library (ruamel.yaml) and the YAML 1.2 core schema.

No other module imports ``ruamel``: ``compose`` walks ruamel's *parser events* and builds the
small typed ``Raw*`` dataclasses below itself, and ``resolve_plain`` resolves plain scalars
ourselves, because ruamel's own resolver is not the YAML 1.2 core schema (research R-13).

ruamel's composer is not used: it returns the anchored node object for an alias and so loses
where the alias is written (research R-1). From the events, ``compose`` records every anchor as
a ``RawAnchor`` (the span of its ``&name`` token) on the node it is attached to, and every alias
as a ``RawAlias`` (the span of its ``*name`` token) whose ``target`` is the raw node most
recently anchored under that name.

Anchors and aliases are decided in one place, ``compose``'s ``allow_anchors`` switch. By default
they are refused with ``anchors and tags are not supported at line N``, exactly as before the
switch existed (``values.parse_value`` and the indentation probe rely on this). With
``allow_anchors=True`` they are composed; an undefined alias, a recursive alias (one inside the
node its anchor is attached to) and any tag are refused (spec C2, FR-002). Refusals, like
before, are raised only once the whole document parsed, so a parse error anywhere wins, and the
first refusal in document order is reported.

Span behaviour (ruamel 0.19, verified by ``tests/unit/test_yamlcore.py``). ``start``/``end`` are
code-point indices into the composed string; a leading BOM is index 0 and CRLF counts as two.
Spans are recorded exactly as ruamel's events report them (the same spans its composer gave);
consumers that need precise ends of block nodes must derive them from the text:

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
- Anchored nodes (research R-2): ``start`` is the *content* start, never the ``&``, so an
  anchored node has exactly the span it would have without its anchor: the first key or dash of
  a block collection, the ``{``/``[`` of a flow collection, the first character of a scalar (its
  quote, or its ``|``/``>`` indicator). Blanks, line breaks and comment lines between the anchor
  and the content are skipped. Ends are unchanged. An anchored empty value (``a: &x`` then a line
  break, or ``[&x , b]``) is a zero-width plain ``""`` scalar at the anchor's end.
- ``RawAnchor``: exactly the ``&name`` token. ``RawAlias``: exactly the ``*name`` token.
"""

import math
import re
from collections.abc import Iterator
from dataclasses import dataclass, replace
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.composer import ComposerError
from ruamel.yaml.error import MarkedYAMLError, YAMLError
from ruamel.yaml.events import (
    AliasEvent,
    DocumentEndEvent,
    DocumentStartEvent,
    Event,
    MappingEndEvent,
    MappingStartEvent,
    ScalarEvent,
    SequenceEndEvent,
    SequenceStartEvent,
    StreamEndEvent,
    StreamStartEvent,
)

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
class RawAnchor:
    """An anchor written on a node: ``start``/``end`` span exactly its ``&name`` token."""

    name: str
    start: int
    end: int


@dataclass(frozen=True)
class RawScalar:
    """A composed scalar: ``text`` is the unescaped/folded content, not yet resolved."""

    text: str
    style: ScalarStyle
    start: int
    end: int
    anchor: RawAnchor | None = None


@dataclass(frozen=True)
class RawMapping:
    """A composed mapping; ``pairs`` are (key, value) in document order."""

    pairs: list[tuple["RawNode", "RawNode"]]
    flow: bool
    start: int
    end: int
    anchor: RawAnchor | None = None


@dataclass(frozen=True)
class RawSequence:
    """A composed sequence."""

    items: list["RawNode"]
    flow: bool
    start: int
    end: int
    anchor: RawAnchor | None = None


@dataclass(frozen=True)
class RawAlias:
    """An alias: ``start``/``end`` span exactly its ``*name`` token.

    ``target`` is the raw node most recently anchored as ``name`` before the alias (the same
    object as in the tree, carrying that ``RawAnchor``).
    """

    name: str
    start: int
    end: int
    target: "RawNode"


RawNode = RawScalar | RawMapping | RawSequence | RawAlias


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


def compose(text: str, source: str, *, allow_anchors: bool = False) -> RawNode | None:
    """Compose ``text`` (one YAML document) into raw nodes; ``None`` for an empty document.

    Args:
        text: The document text (as decoded from the file, BOM included).
        source: The file name used in error messages.
        allow_anchors: Compose anchors and aliases (``RawAnchor``/``RawAlias``) instead of
            refusing them.

    Raises:
        LoadError: If the text is not a single valid YAML document, or uses tags, or (unless
            ``allow_anchors``) anchors or aliases, or an undefined or recursive alias. The
            message starts ``cannot parse {source}: `` and names the line.
    """
    events = YAML(typ="safe", pure=True).parse(text)
    try:
        return _Composer(text, source, events, allow_anchors).single_document()
    except MarkedYAMLError as err:
        raise LoadError(f"cannot parse {source}: {_describe(err)}") from err
    except YAMLError as err:
        first_line = str(err).splitlines()[0] if str(err) else type(err).__name__
        raise LoadError(f"cannot parse {source}: {first_line}") from err
    finally:
        events.close()


def _describe(err: MarkedYAMLError) -> str:
    problem = err.problem or err.context or "invalid YAML"
    mark = err.problem_mark or err.context_mark
    return f"{problem} at line {mark.line + 1}" if mark is not None else str(problem)


_ContentEvent = ScalarEvent | MappingStartEvent | SequenceStartEvent


class _Composer:
    """Recursive descent over ruamel's parser events (research R-1), one event of lookahead.

    Refusals of anchors, aliases and tags are collected (the first one in document order wins)
    and raised only after the document parsed, as before this composer existed: ruamel's
    composer built the whole node graph before any refusal was checked.
    """

    def __init__(
        self, text: str, source: str, events: Iterator[Event], allow_anchors: bool
    ) -> None:
        self._text = text
        self._source = source
        self._events = events
        self._peeked: Event | None = None
        self._allow_anchors = allow_anchors
        # name -> the node most recently anchored so; ``None`` while that node is still open.
        self._anchored: dict[str, RawNode | None] = {}
        self._refusal: str | None = None

    def single_document(self) -> RawNode | None:
        self._take(StreamStartEvent)
        if isinstance(self._peek(), StreamEndEvent):
            return None
        self._take(DocumentStartEvent)
        node = self._node()
        self._take(DocumentEndEvent)
        if not isinstance(self._peek(), StreamEndEvent):
            # ruamel's composer's own error, so the message is unchanged (``_describe``).
            raise ComposerError(
                "expected a single document in the stream",
                None,
                "but found another document",
                self._next().start_mark,
            )
        if self._refusal is not None:
            raise LoadError(f"cannot parse {self._source}: {self._refusal}")
        return node

    def _peek(self) -> Event:
        if self._peeked is None:
            self._peeked = next(self._events)
        return self._peeked

    def _next(self) -> Event:
        event = self._peek()
        self._peeked = None
        return event

    def _take[E: Event](self, kind: type[E]) -> E:
        event = self._next()
        if not isinstance(event, kind):
            raise self._unexpected(event)
        return event

    def _unexpected(self, event: Event) -> LoadError:
        # Not reachable from ruamel's parser, which enforces the event grammar itself.
        line = self._line(event.start_mark.index)
        return LoadError(
            f"cannot parse {self._source}: unexpected {type(event).__name__} at line {line}"
        )

    def _node(self) -> RawNode:
        event = self._next()
        if isinstance(event, AliasEvent):
            return self._alias(event)
        if not isinstance(event, _ContentEvent):
            raise self._unexpected(event)
        name: str | None = event.anchor
        if event.tag is not None:
            self._refuse(event, "tags are not supported")
        elif name is not None:
            self._refuse(event, None)
        if name is not None:
            self._anchored[name] = None
        node = self._content(event)
        if name is None:
            return node
        anchor = _anchor_token(self._text, name, event.start_mark.index)
        node = replace(_from_content_start(self._text, node, anchor), anchor=anchor)
        if self._anchored[name] is None:  # else redefined inside: the inner one is more recent
            self._anchored[name] = node
        return node

    def _content(self, event: _ContentEvent) -> RawScalar | RawMapping | RawSequence:
        start: int = event.start_mark.index
        if isinstance(event, ScalarEvent):
            value: Any = event.value
            end: int = event.end_mark.index
            return RawScalar(text=str(value), style=_STYLES[event.style], start=start, end=end)
        if isinstance(event, MappingStartEvent):
            pairs: list[tuple[RawNode, RawNode]] = []
            while not isinstance(self._peek(), MappingEndEvent):
                key = self._node()
                pairs.append((key, self._node()))
            end = self._next().end_mark.index
            return RawMapping(pairs=pairs, flow=bool(event.flow_style), start=start, end=end)
        items: list[RawNode] = []
        while not isinstance(self._peek(), SequenceEndEvent):
            items.append(self._node())
        end = self._next().end_mark.index
        return RawSequence(items=items, flow=bool(event.flow_style), start=start, end=end)

    def _alias(self, event: AliasEvent) -> RawNode:
        name: str = event.anchor
        start: int = event.start_mark.index
        end: int = event.end_mark.index
        placeholder = RawScalar(text="", style="plain", start=start, end=end)
        if name not in self._anchored:
            if not self._allow_anchors:  # ruamel's composer's own error, message unchanged
                raise ComposerError(None, None, f"found undefined alias {name!r}", event.start_mark)
            self._refuse(event, f"undefined alias *{name}")
            return placeholder
        target = self._anchored[name]
        if target is None:
            self._refuse(event, f"recursive alias *{name}")
            return placeholder
        self._refuse(event, None)
        return RawAlias(name=name, start=start, end=end, target=target)

    def _refuse(self, event: Event, problem: str | None) -> None:
        """Record a refusal at ``event``; ``None`` means "an anchor or alias", refused by default.

        Without ``allow_anchors`` every refusal reads exactly as it always did.
        """
        if self._allow_anchors:
            if problem is None:
                return
        else:
            problem = "anchors and tags are not supported"
        if self._refusal is None:
            self._refusal = f"{problem} at line {self._line(event.start_mark.index)}"

    def _line(self, index: int) -> int:
        return self._text.count("\n", 0, index) + 1


def _anchor_token(text: str, name: str, start: int) -> RawAnchor:
    """The ``&name`` token at ``start`` (where ruamel's event for an anchored node starts)."""
    token = "&" + name
    if not text.startswith(token, start):  # with a tag first; refused anyway (C2)
        start = text.find(token, start)
    return RawAnchor(name=name, start=start, end=start + len(token))


def _from_content_start(
    text: str, node: RawScalar | RawMapping | RawSequence, anchor: RawAnchor
) -> RawScalar | RawMapping | RawSequence:
    """``node`` with ``start`` moved from its anchor to its content (research R-2)."""
    if isinstance(node, RawScalar) and node.end <= anchor.end:  # anchored empty value
        return replace(node, start=anchor.end, end=anchor.end)
    return replace(node, start=_content_start(text, anchor.end))


def _content_start(text: str, index: int) -> int:
    """First index at or after ``index`` that is not a blank, a line break or in a comment.

    A ``#`` starts a comment when it follows whitespace or starts a line, as in
    ``writeback.comments.find_comment_start``.
    """
    while index < len(text):
        char = text[index]
        if char in " \t\r\n":
            index += 1
        elif char == "#" and (index == 0 or text[index - 1] in " \t\r\n"):
            line_break = text.find("\n", index)
            index = len(text) if line_break < 0 else line_break
        else:
            break
    return index
