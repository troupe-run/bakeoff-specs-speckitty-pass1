"""The one place that knows the YAML library (ruamel.yaml) and the YAML 1.2 core schema.

No other module imports ``ruamel``: ``compose`` walks ruamel's *parser events* and builds the
small typed ``Raw*`` dataclasses below itself, and ``resolve_plain`` resolves plain scalars
ourselves, because ruamel's own resolver is not the YAML 1.2 core schema (research R-13).

ruamel's composer is not used: it returns the anchored node object for an alias and so loses
where the alias is written (research R-1). From the events, ``compose`` records every anchor as
a ``RawAnchor`` (the span of its ``&name`` token) on the node it is attached to, and every alias
as a ``RawAlias`` (the span of its ``*name`` token) whose ``target`` is the raw node most
recently anchored under that name.

Anchors, aliases and tags are decided in one place, ``compose``'s ``allow_anchors`` switch
("file mode" when true). By default (VALUE mode) every anchor, alias and tag is refused with
``anchors and tags are not supported at line N``, exactly as before the switch existed
(``values.parse_value`` relies on this). In file mode anchors and aliases are composed; an
undefined alias and a recursive alias (one inside the node its anchor is attached to) are refused
(spec C2, FR-002). The one tag accepted in file mode is ``!literal`` on a scalar, recorded as a
``RawTag`` (spec S-10, research R-4); ``!literal`` on a mapping or sequence is refused with
``!literal applies only to scalars``, and every other tag with ``tags are not supported``.
Refusals, like before, are raised only once the whole document parsed, so a parse error anywhere
wins, and the first refusal in document order is reported.

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
- Anchored and ``!literal``-tagged nodes (research R-2, R-4): ``start`` is the *content* start,
  never the ``&`` or ``!``, so such a node has exactly the span it would have without its
  properties: the first key or dash of a block collection, the ``{``/``[`` of a flow collection,
  the first character of a scalar (its quote, or its ``|``/``>`` indicator). Blanks, line breaks
  and comment lines between the properties and the content are skipped. Ends are unchanged. An
  empty value after its properties (``a: &x`` or ``a: !literal`` then a line break, or
  ``[&x , b]``) is a zero-width plain ``""`` scalar at the end of the last property token.
- ``RawAnchor``: exactly the ``&name`` token. ``RawAlias``: exactly the ``*name`` token.
- ``RawTag``: the ``!literal`` token plus the blanks, line breaks and comments after it, up to
  the next property (``!literal &a x``: up to ``&a``) or the content, so deleting the span leaves
  the rest of the node intact. For an empty value it ends at the next property (``a: !literal
  &x``: up to ``&x``, blanks included); with no property after it, it is exactly the
  ``!literal`` token (a following comment is not part of it).
  Only the shorthand written ``!literal`` is accepted: a verbatim ``!<!literal>`` or a ``%TAG``
  handle that resolves to ``!literal`` is refused like any other tag, and a ``%TAG`` directive
  that maps ``!`` elsewhere makes ``!literal`` resolve to another tag, so it is refused too.
"""

import math
import re
from collections.abc import Iterator
from dataclasses import dataclass, replace
from typing import Any, Final

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

LITERAL_TAG: Final = "!literal"
"""The one tag accepted, on scalars in file mode only (spec S-10, research R-4)."""

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
class RawTag:
    """The ``!literal`` tag written on a scalar: ``start``/``end`` span the tag token plus the
    blanks, line breaks and comments after it, up to the next property or the scalar's content
    (research R-4). For an empty value with no property after it, exactly the token."""

    start: int
    end: int


@dataclass(frozen=True)
class RawScalar:
    """A composed scalar: ``text`` is the unescaped/folded content, not yet resolved.

    ``tag`` is set when the scalar is written ``!literal`` (file mode only).
    """

    text: str
    style: ScalarStyle
    start: int
    end: int
    anchor: RawAnchor | None = None
    tag: RawTag | None = None


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
        allow_anchors: File mode: compose anchors and aliases (``RawAnchor``/``RawAlias``)
            and ``!literal`` on scalars (``RawScalar.tag``) instead of refusing them. A tagged
            scalar's ``start`` is its content start; ``tag`` spans the ``!literal`` token and
            the separation after it (see the module docstring).

    Raises:
        LoadError: If the text is not a single valid YAML document; or, unless
            ``allow_anchors``, it uses any anchor, alias or tag; or, with ``allow_anchors``, an
            undefined or recursive alias, ``!literal`` on a mapping or sequence, or any other
            tag. The message starts ``cannot parse {source}: `` and names the line.
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

    In file mode ``!literal`` on a scalar is accepted and its span recorded (``_properties``);
    ``!literal`` on a mapping or sequence and every other tag are refused. In VALUE mode every
    tag is refused with the old message.
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
        # End index of the last event taken: no property of the next node starts before it.
        self._taken_end = 0

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
        self._taken_end = event.end_mark.index
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
        floor = self._taken_end
        event = self._next()
        if isinstance(event, AliasEvent):
            return self._alias(event)
        if not isinstance(event, _ContentEvent):
            raise self._unexpected(event)
        name: str | None = event.anchor
        literal = self._accepts_tag(event)
        if name is not None:
            self._refuse(event, None)
            self._anchored[name] = None
        node = self._content(event)
        if name is None and not literal:
            return node
        start: int = event.start_mark.index
        properties = _properties(self._text, start, floor, name, literal, node.end)
        if properties is None:  # tagged, but not written as the shorthand ``!literal``
            self._refuse(event, "tags are not supported")
            properties = _properties(self._text, start, floor, name, False, node.end)
            assert properties is not None  # untagged properties are always found
        anchor, tag, content_start = properties
        node = replace(node, start=content_start, end=max(node.end, content_start), anchor=anchor)
        if tag is not None and isinstance(node, RawScalar):
            node = replace(node, tag=tag)
        if name is not None and self._anchored[name] is None:
            self._anchored[name] = node  # else redefined inside: the inner one is more recent
        return node

    def _accepts_tag(self, event: _ContentEvent) -> bool:
        """Whether ``event`` carries the accepted tag (``!literal`` on a scalar, file mode).

        Any other tag is refused here: in VALUE mode every tag reads as it always did.
        """
        tag: str | None = event.tag
        if tag is None:
            return False
        if not self._allow_anchors or tag != LITERAL_TAG:
            self._refuse(event, "tags are not supported")
            return False
        if not isinstance(event, ScalarEvent):
            self._refuse(event, f"{LITERAL_TAG} applies only to scalars")
            return False
        return True

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
    if not text.startswith(token, start):  # defensive: ruamel's event starts at the anchor
        start = text.find(token, start)
    return RawAnchor(name=name, start=start, end=start + len(token))


def _properties(
    text: str, start: int, floor: int, anchor_name: str | None, tagged: bool, end: int
) -> tuple[RawAnchor | None, RawTag | None, int] | None:
    """A node's anchor and ``!literal`` tag, in either written order, and its content start.

    ``start`` is where ruamel's event starts: at the anchor when there is one (even when the
    tag is written first), else at the tag. A tag written before the anchor lies between
    ``floor`` (the end of the previous event) and the anchor. ``end`` is the node's end: when it
    is not past the last property token the value is empty, and its content start is that
    token's end (research R-2, R-4). ``None`` when ``tagged`` but no ``!literal`` shorthand is
    written there (a verbatim or ``%TAG`` form that resolves to ``!literal``).
    """
    anchor = None if anchor_name is None else _anchor_token(text, anchor_name, start)
    last_end = start if anchor is None else anchor.end
    tag_start: int | None = None
    if tagged:
        if anchor is None:
            tag_start = start if _is_literal_token(text, start) else None
        elif _is_literal_token(text, after := _content_start(text, anchor.end)):
            tag_start = after  # ``&a !literal x``
        else:
            tag_start = _literal_before(text, floor, anchor.start)  # ``!literal &a x``
        if tag_start is None:
            return None
        last_end = max(last_end, tag_start + len(LITERAL_TAG))
    content_start = last_end if end <= last_end else _content_start(text, last_end)
    tag = None
    if tag_start is not None:
        # Up to the next property or the content; just the token for an empty value.
        tag_end = min(_content_start(text, tag_start + len(LITERAL_TAG)), content_start)
        tag = RawTag(start=tag_start, end=tag_end)
    return anchor, tag, content_start


def _is_literal_token(text: str, index: int) -> bool:
    """Whether a ``!literal`` token, followed by a blank, a line break or EOF, is at ``index``."""
    after = index + len(LITERAL_TAG)
    if not text.startswith(LITERAL_TAG, index):
        return False
    return after == len(text) or text[after] in " \t\r\n"


def _literal_before(text: str, floor: int, anchor_start: int) -> int | None:
    """The ``!literal`` token written before the anchor at ``anchor_start``, at or after ``floor``.

    Only blanks, line breaks and comments separate it from the anchor. The leftmost such token is
    the tag: a later one can only be inside a comment between the tag and the anchor, and an
    earlier one is cut off from the anchor by the tag itself.
    """
    index = text.find(LITERAL_TAG, floor, anchor_start)
    while index >= 0:
        if (
            _is_literal_token(text, index)
            and _content_start(text, index + len(LITERAL_TAG)) == anchor_start
        ):
            return index
        index = text.find(LITERAL_TAG, index + 1, anchor_start)
    return None


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
