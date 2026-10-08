"""Render a loaded configuration node as block-style YAML lines, each tagged with its source file.

Used by ``troupe config show`` (FR-005, FR-007 to FR-011). The module is pure: it reads only the
in-memory tree and never touches the filesystem. Quoting and literal-block rules are not decided
here; they come from ``troupe.writeback.scalars`` and ``troupe.writeback.blocks``, the same rules
``set`` writes with (TROUPE-007, research R-1).

``show``-only rules added on top (D-10), so that common YAML 1.2 *and* 1.1 readers read the output
back as the same data: a string or key stays plain only if ruamel safe-load reads it back as the
same string under both versions, and a float written with an exponent but no ``.`` gets ``.0``
before the ``e`` (``1e+20`` -> ``1.0e+20``).

Exception to ``troupe.yamlcore``'s "no other module imports ruamel": this module deliberately
imports ruamel's loader for the D-10 read-back probe, which asks how real *readers* load a
string, a question ``yamlcore``'s composer does not answer. The probe is the only ruamel use here.

Layout (research D-1): 2-space indentation; ``key:`` then nested entries 2 deeper; a list under a
key is indented (``key:`` then ``  - item``); list items that are mappings or lists are compact
(``- k: v``, ``- - a``); empty collections are ``{}``/``[]``; no ``---``.

Sources (research D-7): a line holding a scalar (a one-line scalar or a literal-block header) gets
the file of that scalar; lines that only open a collection, ``{}``/``[]`` lines and block body
lines get none. A ``YamlInclude`` and an ``AliasNode`` are transparent at every level
(``paths.unwrap``): an aliased scalar's source is the file holding its anchored node (spec C1).
"""

import os
import warnings
from dataclasses import dataclass
from functools import cache, lru_cache
from pathlib import Path, PurePath
from typing import Final

from ruamel.yaml import YAML

from troupe.location import Location, Url
from troupe.paths import unwrap
from troupe.tree import (
    AliasNode,
    MappingNode,
    Node,
    ScalarNode,
    SequenceNode,
    TextInclude,
    YamlInclude,
)
from troupe.writeback import blocks, scalars

INDENT_STEP: Final = 2
SOURCE_COMMENT_PREFIX: Final = " # from "
_ITEM_INDICATOR: Final = "-"
_EMPTY_MAPPING: Final = "{}"
_EMPTY_SEQUENCE: Final = "[]"
# D-10: plain strings must read back under both YAML versions common readers use.
_READER_VERSIONS: Final = ((1, 2), (1, 1))
_PROBE_SCALAR: Final = "x"
_PROBE_CACHE_SIZE: Final = 4096
# D-10: YAML 1.1 floats need a "." in the mantissa (1e+20 -> 1.0e+20).
_FLOAT_EXPONENT: Final = "e"
_MANTISSA_FRACTION: Final = ".0"


@dataclass(frozen=True)
class Line:
    """One output line.

    Attributes:
        text: The line without its line break.
        source: The file or URL of the scalar this line holds (a one-line scalar or a
            literal-block header), else ``None`` (research D-7, R-11).
    """

    text: str
    source: Location | None = None


def render(node: Node) -> list[Line]:
    """Render ``node`` (as found; a ``YamlInclude`` is unwrapped) as block YAML lines.

    A mapping or list renders its entries or items at column 0; an empty one renders as ``{}`` or
    ``[]``. A scalar renders bare, or as a literal block whose body is at column ``INDENT_STEP``.
    The result is never empty, and reads back as the node's resolved data (FR-005, NFR-001).
    """
    value = _content(node)
    if isinstance(value, MappingNode | SequenceNode):
        return _collection_lines(value, "", 0)
    return _scalar_lines(value, "", INDENT_STEP)


def to_text(lines: list[Line], sources_root: Path | None) -> str:
    """Join ``lines``, each ending with ``"\\n"``; with ``sources_root``, add source comments.

    The comment ``" # from <label>"`` (``SOURCE_COMMENT_PREFIX``) is appended to every line whose
    ``source`` is set, with the label from ``source_label`` relative to ``sources_root``
    (FR-010, FR-011). Without a root no comment is ever added, so both outputs come from one list.
    """
    return "".join(_line_text(line, sources_root) + "\n" for line in lines)


def source_label(path: Location, theatre_dir: Path) -> str:
    """Return ``path`` relative to ``theatre_dir`` with ``/`` separators (research D-6).

    A file outside the theatre directory gives a ``../`` path. Both arguments must already be
    resolved absolute paths; nothing is resolved here (no filesystem access). Remote content is
    labelled with its resolved URL, verbatim (spec S-6).
    """
    if isinstance(path, Url):
        return path.text
    return PurePath(os.path.relpath(path, theatre_dir)).as_posix()


def _content(node: Node) -> MappingNode | SequenceNode | ScalarNode | TextInclude:
    """``paths.unwrap`` narrowed for the type checker: never a ``YamlInclude`` or ``AliasNode``.

    So ``show`` prints resolved values with no anchor, alias or merge-key syntax (spec C1).
    """
    value = unwrap(node)
    assert not isinstance(value, YamlInclude | AliasNode)  # unwrap loops until it is neither
    return value


def _line_text(line: Line, sources_root: Path | None) -> str:
    if sources_root is None or line.source is None:
        return line.text
    return line.text + SOURCE_COMMENT_PREFIX + source_label(line.source, sources_root)


def _collection_lines(node: MappingNode | SequenceNode, lead: str, column: int) -> list[Line]:
    """Render a mapping's entries or a list's items at ``column`` (research D-1).

    Args:
        node: The (unwrapped) collection.
        lead: Text already on the first line: ``" " * column`` or a compact item's ``"... - "``;
            ``len(lead) == column``.
        column: The column of every entry's key or item's dash.
    """
    if isinstance(node, MappingNode):
        heads = [_render_key(entry.key) + ":" for entry in node.entries]
        children = [entry.value for entry in node.entries]
        compact = False
        empty = _EMPTY_MAPPING
    else:
        heads = [_ITEM_INDICATOR] * len(node.items)
        children = node.items
        compact = True
        empty = _EMPTY_SEQUENCE
    if not children:
        return [Line(lead + empty)]
    lines: list[Line] = []
    for index, (head, child) in enumerate(zip(heads, children, strict=True)):
        prefix = lead if index == 0 else " " * column
        lines += _value_lines(child, prefix + head, column, compact=compact)
    return lines


def _value_lines(node: Node, head: str, column: int, *, compact: bool) -> list[Line]:
    """Render the value after ``head`` (``key:`` or ``-``, whose first character is at ``column``).

    Nested content and literal-block bodies go to ``column + INDENT_STEP``. A non-empty collection
    under a key starts on the next line; under ``-`` (``compact``) it starts on the same line.
    """
    value = _content(node)
    nested = column + INDENT_STEP
    if isinstance(value, MappingNode | SequenceNode):
        is_empty = not (value.entries if isinstance(value, MappingNode) else value.items)
        if compact or is_empty:
            return _collection_lines(value, head + " ", nested)
        return [Line(head), *_collection_lines(value, " " * nested, nested)]
    return _scalar_lines(value, head + " ", nested)


def _scalar_lines(node: ScalarNode | TextInclude, lead: str, body_indent: int) -> list[Line]:
    """Render a scalar after ``lead``: one line, or a literal header plus body lines (D-2 to D-5).

    Non-strings use ``_render_nonstring`` (D-3, D-10). Text-include values and strings containing
    a line break are literal blocks when ``can_block`` holds (D-2); strings a block cannot hold
    are double-quoted (D-4); other strings take plain, single or double quoting (D-5, D-10).
    """
    if isinstance(node, TextInclude):
        text, source, as_block = node.target.text, node.target.path, True
    else:
        source = node.origin.file.path
        if not isinstance(node.value, str):
            return [Line(lead + _render_nonstring(node.value), source)]
        text, as_block = node.value, "\n" in node.value
    if as_block and blocks.can_block(text):
        header, body = _literal_block(text, body_indent)
        return [Line(lead + header, source), *(Line(line) for line in body)]
    style: scalars.QuoteStyle = "double" if as_block else _quote_style(text, as_key=False)
    return [Line(lead + scalars.render_string(text, style), source)]


def _render_nonstring(value: int | float | bool | None) -> str:
    """``scalars.render_nonstring``, with a ``.`` in exponent floats for YAML 1.1 readers (D-10).

    YAML 1.1 floats need a ``.`` in the mantissa, so ``1e+20`` is written ``1.0e+20``; ``repr``
    always signs the exponent, as 1.1 also requires. ``.inf``/``-.inf``/``.nan`` and every other
    value are unchanged (D-3).
    """
    text = scalars.render_nonstring(value)
    if not isinstance(value, float) or _FLOAT_EXPONENT not in text or "." in text:
        return text
    mantissa, exponent = text.split(_FLOAT_EXPONENT)
    return f"{mantissa}{_MANTISSA_FRACTION}{_FLOAT_EXPONENT}{exponent}"


def _literal_block(text: str, body_indent: int) -> tuple[str, list[str]]:
    """Return a literal block's header and body lines for ``text`` (research D-2).

    The empty text is written ``|-`` with no body: every chomping reads back ``""`` and strip
    states it most plainly (research D-2, choice recorded there).
    """
    if text == "":
        return blocks.literal_header(text, "strip", INDENT_STEP), []
    return blocks.render_new_multiline(text, "block", body_indent, INDENT_STEP)


def _render_key(key: str) -> str:
    """Render a mapping key with the same quoting rule as values (research D-5, D-10)."""
    return scalars.render_string(key, _quote_style(key, as_key=True))


def _quote_style(s: str, *, as_key: bool) -> scalars.QuoteStyle:
    """Return the quoting style for a one-line string value or key in ``show`` output.

    ``choose_style`` decides first (D-5). Plain is kept only if common YAML readers also read it
    back as the same string (D-10); otherwise single quotes if they can hold ``s``, else double.
    """
    style = scalars.choose_style(s, None, "block")
    if style == "plain" and not _plain_reads_back(s, as_key=as_key):
        style = "single" if scalars.can_single(s) else "double"
    return style


@lru_cache(maxsize=_PROBE_CACHE_SIZE)
def _plain_reads_back(s: str, *, as_key: bool) -> bool:
    """Whether plain ``s`` loads as exactly the string ``s`` under YAML 1.2 and 1.1 (D-10).

    As a value ``k: <s>`` must load as ``{"k": s}``; as a key ``<s>: x`` must load as exactly
    ``{s: "x"}``, which also rules out the merge key ``<<``. Any reader error means "no".
    """
    if as_key:
        document, expected = f"{s}: {_PROBE_SCALAR}\n", {s: _PROBE_SCALAR}
    else:
        document, expected = f"{_PROBE_SCALAR}: {s}\n", {_PROBE_SCALAR: s}
    for version in _READER_VERSIONS:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")  # 1.1 readers warn about some numbers
                loaded = _reader(version).load(document)
        except Exception:  # any reader failure means plain does not read back
            return False
        if loaded != expected:
            return False
    return True


@cache
def _reader(version: tuple[int, int]) -> YAML:
    """The ruamel safe loader for ``version``, created once (the probe runs per string)."""
    reader = YAML(typ="safe", pure=True)
    reader.version = version
    return reader
