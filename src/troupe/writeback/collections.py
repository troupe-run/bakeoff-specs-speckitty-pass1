"""New entries and collection values (FR-011, FR-012, FR-016, FR-019, FR-020; research R-06).

Contract:

- FR-016: a new collection value is written in block style at the file's indentation (default 2),
  or in flow style if its parent is a flow collection; replacing a scalar by a block collection
  keeps the key's line bytes through its end-of-line comment. Product-owner ruling: a flow
  collection under a block parent replaced by a new collection is written in *block* style.
- FR-019: a new block list item or mapping key goes after the collection's last entry and below
  any comment lines following it, before the next less-indented line; a comment line indented
  less than the entries ends the collection. In a flow collection the new entry is appended after
  the last entry, on that entry's line.
- FR-015: a new key, and a new string value, copy the quoting style of the preceding sibling key
  or value; with no sibling, plain or the minimal quoting the text needs.
- FR-020: a changed line keeps its end-of-line comment at its column (``comments.replace_in_line``).
- Include overrides FR-006: ``convert_include_edits`` turns a scalar-form include into mapping
  form (``$ref`` first, include bytes verbatim) with its first override (spec D-2 to D-5, D-11).

Every function is pure: it reads ``SourceFile.text`` and the SourceTree spans and returns
``TextEdit`` values. Block collection ends reported by the parser run past trailing blank and
comment lines (see ``troupe.yamlcore``), so extents are derived here from the text: the last
entry's content ends where its deepest last scalar ends (reliable spans), and the region rule
below is applied line by line from there.

Choices made where the contract is silent (TROUPE-002, TROUPE-008):

- Indentation step (R-06): the first block mapping key or block sequence nested under a mapping
  key deeper than that key gives the step; sequence items give no information (``- k: v`` is
  compact form, not indentation). A new list under a key is flush (``key:`` then ``- a`` at the
  key's column) if the nearest sibling block sequence in the same mapping is flush, else indented
  by the step.
- Mapping items in new sequences use compact form ``- k: v`` (continuation lines at ``-`` + 2);
  nested lists in new items likewise ``- - a``.
- Empty ``{}``/``[]`` are written in flow form (``key: []``) even in block context: block style
  cannot express an empty collection.
- A new multi-line string in block context is a literal block (``blocks.render_new_multiline``)
  whose content is indented one step deeper than its key or ``-``; in flow context it is
  double-quoted.
- Trailing blank lines after a collection stay after the inserted entry (they keep separating
  blocks); blank lines that belong to a ``|+``/``>+`` value stay inside it.
- A file ending without a line break still ends without one after an insertion at its end,
  except when the inserted text ends with a block scalar (its value needs the final break).
- Appending after a ``|``/``>``/``|+``/``>+`` block scalar that ends a file without a final line
  break is refused: the new break would become part of that value, and changing its header to
  strip chomping would rewrite another line (review cycle 1).
- The empty-value ``:`` of a flow mapping is recognised from the parsed spans (a ``:`` after the
  key's span with an empty value), never from text ending in ``:``: ``[C:, D:]`` holds strings
  and ``{a:}`` has the key ``a:`` (review cycle 1).
- FR-019 is applied literally to flush sequences: a column-0 comment after a flush list under a
  root key is "indented at least as much as the entries", so a new item goes below it.
- Appending after an empty flow mapping value keeps a space after its ``:`` (``{a: , b: 1}``),
  because ``{a:, b: 1}`` reads ``a:`` as the key.
- Kind-changing replacement refuses (``WriteRefused``) when removing the old value would also
  remove a comment it cannot keep: a multi-line plain/quoted/flow value containing ``#``, or a
  comment after a value that does not start on the key's line.
- Kind-changing replacement of a block collection by another block collection writes the new
  top-level entries at the old entries' column when that column is valid for the new kind.

Anchors and aliases (step 6; spec C5, research R-9):

- Replacing an anchored value keeps its anchor (C5): when the ``&name`` token is on the key's
  (or dash's) line, the new inline value or block lines follow it (``defaults: &d`` then the
  new block, ``x: &m [a, b]``, ``d: &d 5``). An anchor elsewhere (``defaults:`` with ``&d``
  alone on the next line) would have to move, so the replacement is refused (``WriteRefused``,
  exit 3). Scalars replaced in place and flow values keep it anyway: their spans exclude it.

``!literal`` (spec S-10, S-11; research R-8):

- New string values are rendered only by ``scalars.render_scalar`` and
  ``blocks.render_new_multiline``, which write ``!literal `` before an ``includes.LiteralStr``;
  keys go through ``render_string`` and are never tagged.
- Kind-changing replacement of a tagged scalar by a collection removes the tag token and the
  blanks after it on its line (``!literal`` on a collection is refused on load); an anchor
  written before or after the tag stays (C5), and a line holding nothing but the tag is deleted.
- The indentation step and the open-end check parse with anchors and aliases allowed, so files
  using them are measured like any other; an alias gives no indentation information.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from typing import TypeGuard

from troupe import yamlcore
from troupe.errors import LoadError, WriteRefused
from troupe.merge import REF_KEY
from troupe.tree import (
    MappingEntry,
    MappingNode,
    Node,
    Origin,
    Scalar,
    ScalarNode,
    ScalarStyle,
    SequenceNode,
    SourceFile,
    TextInclude,
    YamlInclude,
)
from troupe.writeback import TextEdit
from troupe.writeback.blocks import (
    DEFAULT_INDENT_STEP,
    Chomp,
    can_block,
    check_block_end,
    choose_chomp,
    parse_block,
    render_new_multiline,
)
from troupe.writeback.comments import find_comment_start, replace_in_line
from troupe.writeback.fileio import detect_newline
from troupe.writeback.scalars import QuoteStyle, choose_style, render_scalar, render_string
from troupe.yamlcore import LITERAL_TAG, RawAlias, RawMapping, RawNode, RawSequence

type Value = Scalar | dict[str, Value] | list[Value]
"""A value to write: same shape as ``troupe.values.Value`` (a parsed VALUE argument)."""

Collection = MappingNode | SequenceNode

BOM = "\ufeff"
_QUOTE_STYLES: tuple[QuoteStyle, ...] = ("plain", "single", "double")
_FLOW_SEPARATOR = ", "
_COPYABLE_SEPARATOR = re.compile(r",[ ]*")


# --- Text helpers -------------------------------------------------------------------------------


def _line_start(text: str, pos: int) -> int:
    return text.rfind("\n", 0, pos) + 1


def _line_end(text: str, pos: int) -> int:
    """Index of the ``"\\n"`` ending the line containing ``pos``, or ``len(text)``."""
    end = text.find("\n", pos)
    return len(text) if end < 0 else end


def _next_line(text: str, pos: int) -> int:
    """Start of the line after the one containing ``pos`` (``len(text)`` on the last line)."""
    end = _line_end(text, pos)
    return end + 1 if end < len(text) else end


def _content_line_end(text: str, pos: int) -> int:
    """End of the line containing ``pos``, excluding ``"\\r\\n"``/``"\\n"``."""
    start = _line_start(text, pos)
    end = _line_end(text, pos)
    return end - 1 if end > start and text[end - 1] == "\r" else end


def _bom_offset(text: str, line_start: int) -> int:
    return 1 if line_start == 0 and text.startswith(BOM) else 0


def _column(text: str, pos: int) -> int:
    """Column of ``pos`` in code points; a leading BOM is not a column."""
    start = _line_start(text, pos)
    return pos - start - _bom_offset(text, start)


def _lines_from(text: str, pos: int) -> Iterator[tuple[int, str]]:
    """Yield ``(start, line)`` for each line from ``pos``; lines exclude their line break."""
    while pos < len(text):
        end = _line_end(text, pos)
        yield pos, text[pos:end].removesuffix("\r")
        pos = end + 1


def _leading_spaces(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _ends_without_break(text: str) -> bool:
    return text not in ("", BOM) and not text.endswith("\n")


def _minimal_edit(text: str, start: int, end: int, new_text: str) -> list[TextEdit]:
    """The smallest edit turning ``text[start:end]`` into ``new_text`` (none if equal)."""
    old = text[start:end]
    if old == new_text:
        return []
    prefix = 0
    limit = min(len(old), len(new_text))
    while prefix < limit and old[prefix] == new_text[prefix]:
        prefix += 1
    suffix = 0
    while suffix < limit - prefix and old[-1 - suffix] == new_text[-1 - suffix]:
        suffix += 1
    return [TextEdit(start + prefix, end - suffix, new_text[prefix : len(new_text) - suffix])]


# --- Indentation (T030) -------------------------------------------------------------------------


def detect_indent(text: str) -> int:
    """Return the file's indentation step (research R-06); ``DEFAULT_INDENT_STEP`` if unknown.

    The step is the column difference between the first block mapping key (in document order)
    whose value is a block mapping or block sequence indented deeper than the key, and the first
    entry of that value. Flush sequences (``key:`` then ``- a`` at the key's column), block
    scalar bodies, flow collections and sequence items give no information.
    """
    try:
        root = yamlcore.compose(text, "<indentation>", allow_anchors=True)
    except LoadError:
        return DEFAULT_INDENT_STEP
    step = None if root is None else _first_step(text, root)
    return step if step is not None else DEFAULT_INDENT_STEP


def _first_step(text: str, node: RawNode) -> int | None:
    """The first step found below ``node``; an alias (``RawAlias``) carries no information."""
    if isinstance(node, RawMapping) and not node.flow:
        for key, value in node.pairs:
            child = _raw_entry_start(value)
            if child is not None:
                step = _column(text, child) - _column(text, key.start)
                if step > 0:
                    return step
            found = _first_step(text, value)
            if found is not None:
                return found
    elif isinstance(node, RawSequence) and not node.flow:
        for item in node.items:
            found = _first_step(text, item)
            if found is not None:
                return found
    return None


def _raw_entry_start(node: RawNode) -> int | None:
    """Index of the first key/dash of a non-empty block collection, else ``None``."""
    if isinstance(node, RawMapping) and not node.flow and node.pairs:
        return node.pairs[0][0].start
    if isinstance(node, RawSequence) and not node.flow and node.items:
        return node.start
    return None


# --- Block collection extent and insertion point (T031) -----------------------------------------


def entry_column(text: str, node: Collection) -> int:
    """Column of a block collection's entries: its first key, or its first ``-``.

    An empty collection (only the root mapping of an empty document) has column 0. For a mapping
    written compactly in a sequence item (``- k: v``) this is the key's column, not the dash's.
    """
    if isinstance(node, MappingNode):
        return _column(text, node.entries[0].key_origin.start) if node.entries else 0
    return _column(text, node.origin.start) if node.items else 0


def insertion_point(text: str, node: Collection) -> int:
    """Index where the lines of a new entry of the block collection ``node`` are inserted.

    From the line after the last entry's content, a line belongs to the collection if it is
    indented more than the entries, or is a comment line indented at least as much as the
    entries; blank lines belong only if a later line does. The first other line ends the
    collection. The result is the start of the line after the last belonging non-blank line, so
    trailing blank lines stay after the new entry. If that line is the last line of a file that
    does not end with a line break, the result is ``len(text)`` and the caller must prefix a
    line break. An empty root document inserts at the end of the text.
    """
    if not _has_entries(node):
        return len(text)
    column = entry_column(text, node)
    pos = _content_after(text, node)
    for start, line in _lines_from(text, pos):
        stripped = line.strip(" \t")
        if not stripped:
            continue
        indent = _leading_spaces(line) - _bom_offset(text, start)
        if indent > column or (stripped.startswith("#") and indent >= column):
            pos = _next_line(text, start)
            continue
        break
    return pos


def _has_entries(node: Collection) -> bool:
    return bool(node.entries) if isinstance(node, MappingNode) else bool(node.items)


def _content_after(text: str, node: Node, owner_end: int = 0, owner_col: int = 0) -> int:
    """Start of the line after the last line holding ``node``'s content.

    ``owner_end`` is the end of the node's key or ``-`` (used for empty values, whose own position
    is unreliable) and ``owner_col`` that key's or dash's column (a block scalar's parent indent).
    """
    if isinstance(node, MappingNode) and not node.flow:
        if not node.entries:
            return _next_line(text, owner_end)
        last = node.entries[-1]
        key = last.key_origin
        return _content_after(text, last.value, key.end, _column(text, key.start))
    if isinstance(node, SequenceNode) and not node.flow:
        dash = _dash_pos(text, node, len(node.items) - 1)
        return _content_after(text, node.items[-1], dash + 1, _column(text, dash))
    if _is_block_scalar(text, node):
        block = parse_block(text, node.origin.start, owner_col)
        return block.content_end if block.lines else _next_line(text, node.origin.start)
    if node.origin.start == node.origin.end:
        return _next_line(text, owner_end)
    return _next_line(text, node.origin.end - 1)


def _is_block_scalar(text: str, node: Node) -> bool:
    if isinstance(node, ScalarNode):
        return node.style in ("literal", "folded")
    if isinstance(node, YamlInclude | TextInclude):
        return text[node.origin.start : node.origin.start + 1] in ("|", ">")
    return False


def _dash_pos(text: str, seq: SequenceNode, index: int) -> int:
    """Index of the ``-`` of item ``index`` of the block sequence ``seq``.

    Walks back line by line from just before the item's start (an empty item's position is the
    character after its dash) to the line with a ``-`` at the sequence's column, preceded only by
    spaces or the dashes of enclosing compact items.
    """
    if index == 0:
        return seq.origin.start
    column = entry_column(text, seq)
    pos = max(seq.items[index].origin.start - 1, 0)
    start = _line_start(text, pos)
    while True:
        at = start + _bom_offset(text, start) + column
        prefix = text[start + _bom_offset(text, start) : at]
        after = text[at + 1 : at + 2]
        if (
            text[at : at + 1] == "-"
            and after in ("", " ", "\t", "\n", "\r")
            and set(prefix) <= {" ", "-"}
        ):
            return at
        if start == 0:
            raise ValueError(f"no '-' found for sequence item {index}")
        start = _line_start(text, start - 1)


# --- Rendering new block entries (T032) ---------------------------------------------------------


@dataclass
class _Lines:
    """Rendered lines (without line breaks) and the trailing block scalar, if the last is one.

    ``tail`` is ``(content_indent, chomp)`` of a block scalar whose body ends the lines; text
    inserted before other lines must then be checked with ``blocks.check_block_end``.
    """

    lines: list[str] = field(default_factory=list)
    tail: tuple[int, Chomp] | None = None

    def add(self, line: str) -> None:
        self.lines.append(line)
        self.tail = None

    def extend(self, other: "_Lines") -> None:
        self.lines.extend(other.lines)
        self.tail = other.tail


@dataclass(frozen=True)
class _Renderer:
    """Block-style rendering at a fixed indentation step and sequence offset under keys."""

    step: int
    seq_offset: int

    def attach(
        self,
        out: _Lines,
        head: str,
        value: Value,
        parent_col: int,
        preferred: QuoteStyle | None,
        *,
        is_item: bool = False,
        map_indent: int | None = None,
        seq_indent: int | None = None,
    ) -> None:
        """Write ``value`` after ``head`` (``key:``, or ``-`` if ``is_item``, at ``parent_col``).

        ``map_indent``/``seq_indent`` override the column of a new mapping/list value.
        """
        if isinstance(value, dict) and value:
            out.add(head)
            self.mapping(
                out, value, map_indent if map_indent is not None else parent_col + self.step
            )
        elif isinstance(value, list) and value:
            default = parent_col + (self.step if is_item else self.seq_offset)
            out.add(head)
            self.sequence(out, value, seq_indent if seq_indent is not None else default)
        elif isinstance(value, dict | list):
            out.add(head + (" {}" if isinstance(value, dict) else " []"))
        elif isinstance(value, str) and "\n" in value and can_block(value):
            content = parent_col + self.step
            header, body = render_new_multiline(value, "block", content, self.step)
            out.add(head + " " + header)
            out.lines.extend(body)
            out.tail = (content, choose_chomp("clip", value))
        else:
            out.add(head + " " + render_scalar(value, preferred, "block"))

    def mapping(self, out: _Lines, value: dict[str, Value], indent: int) -> None:
        for key, item in value.items():
            self.attach(out, " " * indent + _block_key(key, None) + ":", item, indent, None)

    def sequence(self, out: _Lines, value: list[Value], dash_col: int) -> None:
        for item in value:
            self.item(out, item, dash_col, None)

    def item(self, out: _Lines, value: Value, dash_col: int, preferred: QuoteStyle | None) -> None:
        """Write one sequence item; collections use compact form (``- k: v``, ``- - a``)."""
        if isinstance(value, dict | list) and value:
            inner = _Lines()
            if isinstance(value, dict):
                self.mapping(inner, value, dash_col + 2)
            else:
                self.sequence(inner, value, dash_col + 2)
            inner.lines[0] = " " * dash_col + "- " + inner.lines[0][dash_col + 2 :]
            out.extend(inner)
        else:
            self.attach(out, " " * dash_col + "-", value, dash_col, preferred, is_item=True)


def _block_key(key: str, preferred: QuoteStyle | None) -> str:
    return render_string(key, choose_style(key, preferred, "block"))


def _quote_style(style: ScalarStyle) -> QuoteStyle | None:
    return next((s for s in _QUOTE_STYLES if s == style), None)


def _value_style(node: Node | None) -> QuoteStyle | None:
    """The preferred style a new string value copies from ``node`` (a preceding sibling)."""
    return _quote_style(node.style) if isinstance(node, ScalarNode) else None


def render_block_value(
    value: Value, indent: int, step: int, seq_offset: int | None = None
) -> list[str]:
    """Return the block-style lines (without line breaks) of a non-empty collection value.

    Mapping keys or sequence dashes are at column ``indent``; nested mappings are indented by
    ``step`` under their key, nested lists by ``seq_offset`` (default ``step``; 0 is flush).
    Items of sequences that are collections use compact form. A scalar or empty collection
    renders as no lines: callers write those on the key's or dash's line.
    """
    renderer = _Renderer(step, step if seq_offset is None else seq_offset)
    out = _Lines()
    if isinstance(value, dict):
        renderer.mapping(out, value, indent)
    elif isinstance(value, list):
        renderer.sequence(out, value, indent)
    return out.lines


def _sequence_offset(text: str, mapping: MappingNode, step: int) -> int:
    """0 if the nearest sibling block sequence (searching from the last entry) is flush."""
    for entry in reversed(mapping.entries):
        value = entry.value
        if isinstance(value, SequenceNode) and not value.flow and value.items:
            flush = _column(text, value.origin.start) == _column(text, entry.key_origin.start)
            return 0 if flush else step
    return step


def _join(out: _Lines, newline: str, *, lead: bool, final_break: bool) -> str:
    """Join lines with ``newline``; ``final_break`` False drops the last line's break."""
    body = "".join(line + newline for line in out.lines)
    if not final_break and out.tail is None:
        body = body[: -len(newline)]
    return (newline if lead else "") + body


def _check_open_end(file: SourceFile, path: str) -> None:
    """Refuse a line break appended to a file that ends without one if it changes any value.

    The break would become the final line break of a ``|``/``>``/``|+``/``>+`` block scalar
    ending the file (``"x"`` would read ``"x\\n"``); avoiding that would mean rewriting the
    scalar's header, another line, so the write is refused (TROUPE-002).

    Raises:
        WriteRefused: Naming ``path`` and the file.
    """
    text = file.text
    before = yamlcore.compose(text, str(file.path), allow_anchors=True)
    after = yamlcore.compose(text + detect_newline(text), str(file.path), allow_anchors=True)
    if _shape(before) != _shape(after):
        raise WriteRefused(
            f"cannot write {path} in {file.path}: the file ends inside a block scalar without a"
            " final line break, and a new line after it would change that value"
        )


type _Shape = tuple[object, ...] | str | None


def _shape(node: RawNode | None) -> _Shape:
    """A raw node's content without positions, for comparing two parses."""
    if node is None:
        return None
    if isinstance(node, RawMapping):
        return tuple((_shape(key), _shape(value)) for key, value in node.pairs)
    if isinstance(node, RawSequence):
        return tuple(_shape(item) for item in node.items)
    if isinstance(node, RawAlias):
        return ("*", node.name)
    return (node.style, node.text)


def _insert_entry(file: SourceFile, node: Collection, out: _Lines, path: str) -> list[TextEdit]:
    return _insert_lines(file, insertion_point(file.text, node), out, path)


def _insert_lines(file: SourceFile, pos: int, out: _Lines, path: str) -> list[TextEdit]:
    """Insert ``out`` at the line start ``pos`` (``len(text)`` after an unterminated last line)."""
    text = file.text
    at_open_end = pos == len(text) and _ends_without_break(text)
    if at_open_end:
        _check_open_end(file, path)
    if out.tail is not None:
        check_block_end(text, pos, out.tail[0], out.tail[1], path)
    newline = detect_newline(text)
    body = _join(out, newline, lead=at_open_end, final_break=not at_open_end)
    return [TextEdit(pos, pos, body)]


def new_key_edits(
    file: SourceFile,
    mapping: MappingNode,
    keys: list[str],
    value: Value,
    step: int,
    *,
    path: str,
    seq_offset: int | None = None,
) -> list[TextEdit]:
    """Add ``keys[0]`` (and the missing intermediate mappings ``keys[1:-1]``) to ``mapping``.

    ``keys`` are the missing path segments below the deepest existing mapping (FR-011); the last
    one gets ``value``. A block mapping gets the new lines at ``insertion_point``; a flow mapping
    gets a flow entry (``flow_append_edits``) with nested flow mappings for intermediate keys.
    The first key copies the last existing key's quoting style, a string value the last entry's
    value style (FR-015); deeper levels have no sibling.

    Args:
        file: The file containing ``mapping`` (``mapping.origin.file``).
        mapping: The deepest existing ancestor mapping.
        keys: The missing segments, at least one.
        value: The value of the last segment.
        step: The file's indentation step (``detect_indent``).
        path: The configuration path, for refusal messages.
        seq_offset: Indentation of new lists under keys (0 = flush); default from the nearest
            sibling block sequence of ``mapping``, else ``step``.

    Raises:
        WriteRefused: If a new block scalar would absorb the lines after it.
    """
    if not keys:
        raise ValueError("new_key_edits needs at least one key")
    if mapping.flow:
        return flow_append_edits(file, mapping, keys[0], _nest(keys[1:], value))
    text = file.text
    last = mapping.entries[-1] if mapping.entries else None
    key_style = _quote_style(last.key_style) if last is not None else None
    value_style = _value_style(last.value) if last is not None else None
    offset = _sequence_offset(text, mapping, step) if seq_offset is None else seq_offset
    out = _Lines()
    _add_new_keys(
        out,
        _Renderer(step, offset),
        keys,
        value,
        entry_column(text, mapping),
        key_style,
        value_style,
    )
    return _insert_entry(file, mapping, out, path)


def _add_new_keys(
    out: _Lines,
    renderer: _Renderer,
    keys: list[str],
    value: Value,
    indent: int,
    key_style: QuoteStyle | None,
    value_style: QuoteStyle | None,
) -> None:
    """Add the block lines of ``keys[0]`` at ``indent``, intermediate mappings, then ``value``.

    The styles are the preceding sibling's (FR-015) and apply to the first level only.
    """
    for key in keys[:-1]:
        out.add(" " * indent + _block_key(key, key_style) + ":")
        key_style = value_style = None
        indent += renderer.step
    head = " " * indent + _block_key(keys[-1], key_style) + ":"
    renderer.attach(out, head, value, indent, value_style)


def new_item_edits(
    file: SourceFile,
    seq: SequenceNode,
    value: Value,
    step: int,
    *,
    path: str,
    seq_offset: int | None = None,
) -> list[TextEdit]:
    """Append ``value`` to ``seq`` (FR-012), block or flow.

    A string value copies the previous item's quoting style (FR-015). Block: a ``- `` line at
    the sequence's column at ``insertion_point``; collections in compact form.

    Raises:
        WriteRefused: If a new block scalar would absorb the lines after it.
    """
    if seq.flow:
        return flow_append_edits(file, seq, None, value)
    renderer = _Renderer(step, step if seq_offset is None else seq_offset)
    out = _Lines()
    preferred = _value_style(seq.items[-1]) if seq.items else None
    renderer.item(out, value, entry_column(file.text, seq), preferred)
    return _insert_entry(file, seq, out, path)


def _nest(keys: list[str], value: Value) -> Value:
    for key in reversed(keys):
        value = {key: value}
    return value


# --- Flow collections (T033) --------------------------------------------------------------------


def render_flow_value(value: Value, preferred: QuoteStyle | None = None) -> str:
    """Render ``value`` in flow style: ``{k: v, …}``, ``[a, …]`` or a scalar.

    ``preferred`` applies to a string ``value`` only (a sibling's style); multi-line strings are
    double-quoted (block scalars are not allowed in flow context).
    """
    if isinstance(value, dict):
        return "{" + _flow_entries(value) + "}"
    if isinstance(value, list):
        return "[" + _FLOW_SEPARATOR.join(render_flow_value(v) for v in value) + "]"
    if isinstance(value, str) and "\n" in value:
        return render_new_multiline(value, "flow", 0)[0]
    return render_scalar(value, preferred, "flow")


def _flow_entries(value: dict[str, Value]) -> str:
    """The entries of a flow mapping without its braces: ``k: v, …``."""
    return _FLOW_SEPARATOR.join(
        render_string(k, choose_style(k, None, "flow")) + ": " + render_flow_value(v)
        for k, v in value.items()
    )


def flow_append_edits(
    file: SourceFile, node: Collection, key: str | None, value: Value
) -> list[TextEdit]:
    """Append an entry to the flow collection ``node`` right after its last entry (FR-019).

    ``key`` is the new key for a mapping and ``None`` for a sequence. The separator copies the
    one between the last two entries when it is ``,`` plus spaces, else ``", "``; an empty
    collection gets the entry right after its opening bracket. The changed line keeps its
    end-of-line comment's column (FR-020).
    """
    text = file.text
    if isinstance(node, MappingNode):
        if key is None:
            raise ValueError("a new flow mapping entry needs a key")
        entries = node.entries
        last = entries[-1] if entries else None
        key_style = _quote_style(last.key_style) if last is not None else None
        entry = render_string(key, choose_style(key, key_style, "flow")) + ": "
        entry += render_flow_value(value, _value_style(last.value) if last else None)
        starts = [e.key_origin.start for e in entries]
        ends = [_flow_entry_end(text, e)[0] for e in entries]
        bare_colon = last is not None and _flow_entry_end(text, last)[1]
    else:
        if key is not None:
            raise ValueError("a new sequence item has no key")
        items = node.items
        entry = render_flow_value(value, _value_style(items[-1]) if items else None)
        starts = [item.origin.start for item in items]
        ends = [item.origin.end for item in items]
        bare_colon = False
    if not ends:
        return _insert_in_line(text, node.origin.start + 1, entry)
    separator = _FLOW_SEPARATOR
    if len(ends) >= 2:
        between = text[ends[-2] : starts[-1]]
        if _COPYABLE_SEPARATOR.fullmatch(between):
            separator = between
    at = ends[-1]
    if bare_colon:
        # The last entry is "key:" with an empty value ("{a: }"); "a:" directly followed by ","
        # would read as the key "a:", so the ":" keeps a space after it.
        spaces = len(text[at:]) - len(text[at:].lstrip(" "))
        if spaces:
            at += spaces
        else:
            separator = " " + separator
    return _insert_in_line(text, at, separator + entry)


def _flow_entry_end(text: str, entry: MappingEntry) -> tuple[int, bool]:
    """End of a flow mapping entry and whether it ends with a bare ``:`` indicator.

    A non-empty value ends the entry at its span's end (a ``:`` inside the value's or key's span
    is text, not an indicator). For an empty value, the entry ends after the ``:`` indicator that
    follows the key's span (``{a: }``) and the flag is true; with no such indicator (``{a}``, or
    ``{a:}`` whose key is ``a:``) it ends at the key's end and the flag is false.
    """
    value = entry.value.origin
    if value.start != value.end:
        return value.end, False
    pos = entry.key_origin.end
    rest = text[pos:].lstrip(" \t")
    if rest.startswith(":"):
        return len(text) - len(rest) + 1, True
    return pos, False


def _insert_in_line(text: str, at: int, insert: str) -> list[TextEdit]:
    """Insert ``insert`` at ``at``, keeping the end-of-line comment of that line in its column."""
    start = _line_start(text, at)
    end = _content_line_end(text, at)
    column = at - start
    new_line = replace_in_line(text[start:end], column, column, insert)
    return _minimal_edit(text, start, end, new_line)


# --- Kind-changing replacement (T034) -----------------------------------------------------------


@dataclass(frozen=True)
class _Anchor:
    """The key or ``-`` that owns a value in a block collection.

    Attributes:
        line_start: Start of the key's/dash's line.
        column: Column of the key or dash.
        head_end: Index just after the ``:`` or ``-``.
        is_item: Whether the owner is a sequence item's ``-``.
    """

    line_start: int
    column: int
    head_end: int
    is_item: bool


@dataclass(frozen=True)
class _OldValue:
    """What removing the old value touches: a span on the anchor line and/or whole lines."""

    inline: tuple[int, int] | None
    lines: tuple[int, int] | None


def replace_value_edits(
    file: SourceFile,
    parent: Collection,
    index_or_key: str | int,
    old: Node,
    new_value: Value,
    step: int,
    *,
    path: str,
    seq_offset: int | None = None,
) -> list[TextEdit]:
    """Replace ``old`` (the value at ``index_or_key`` of ``parent``) by a value of another kind.

    For scalar to collection, collection to scalar and collection to collection changes; a
    scalar replacing a scalar is ``scalars``/``blocks`` business. Flow parent: the old span is
    replaced by ``render_flow_value(new_value)``. Block parent: the key's (or ``-``'s) line keeps
    its bytes up to and including its end-of-line comment (FR-016, FR-020); the old value is
    removed (its inline text, block scalar body or entry lines; comment lines after the last old
    entry stay); a non-empty new collection is written below in block style, anything else on
    the key's line. A ``!literal`` tag on ``old`` is removed with it, keeping its anchor.

    Args:
        file: The file containing ``parent``.
        parent: The collection holding ``old``.
        index_or_key: The key (mapping) or index (sequence) of ``old``.
        old: The current value node.
        new_value: The new value.
        step: The file's indentation step.
        path: The configuration path, for refusal messages.
        seq_offset: As in ``new_key_edits``.

    Raises:
        WriteRefused: If removing the old value would drop a comment, or a new block scalar
            would absorb the lines after it.
    """
    text = file.text
    if parent.flow:
        return _replace_in_flow(text, parent, index_or_key, old, new_value)
    anchor = _past_node_anchor(file, _anchor(text, parent, index_or_key), old, path)
    if isinstance(parent, MappingNode):
        offset = _sequence_offset(text, parent, step) if seq_offset is None else seq_offset
    else:
        offset = step if seq_offset is None else seq_offset
    renderer = _Renderer(step, offset)
    if (
        anchor.is_item
        and _is_block_collection(old)
        and _line_start(text, old.origin.start) == (anchor.line_start)
    ):
        return _replace_compact_item(file, anchor, old, new_value, renderer, path)
    removed = _old_value(file, anchor, old, path)
    map_indent, seq_indent = _new_indents(text, anchor, old, step, offset)
    out = _Lines()
    renderer.attach(
        out,
        "",
        new_value,
        anchor.column,
        None,
        is_item=anchor.is_item,
        map_indent=map_indent,
        seq_indent=seq_indent,
    )
    inline_text, below = out.lines[0], _Lines(out.lines[1:], out.tail)
    tag = _tag_cut(text, old)
    on_head_line = tag is not None and _line_start(text, tag[0]) == anchor.line_start
    edits = _anchor_line_edits(text, anchor, removed, inline_text, tag if on_head_line else None)
    edits += _below_edits(file, anchor, removed, below, path)
    if tag is not None and not on_head_line and not _covers(removed.lines, tag[0]):
        edits += _remove_tag_on_own_line(text, tag)
    return edits


def _tag_cut(text: str, old: Node) -> tuple[int, int] | None:
    """The ``!literal`` token on ``old`` plus the spaces and tabs right after it, or ``None``.

    Stops before a comment or line break, and never reaches past the tag's span
    (``ScalarNode.literal``), so an anchor after it is kept.
    """
    if not isinstance(old, ScalarNode) or old.literal is None:
        return None
    start = old.literal.start
    end = start + len(LITERAL_TAG)
    while end < old.literal.end and text[end] in " \t":
        end += 1
    return start, end


def _covers(lines: tuple[int, int] | None, pos: int) -> bool:
    return lines is not None and lines[0] <= pos < lines[1]


def _remove_tag_on_own_line(text: str, tag: tuple[int, int]) -> list[TextEdit]:
    """Remove a tag written on a line between the key's line and the value's first line.

    The whole line goes if nothing else is on it; else only the tag, the comment keeping its
    column (FR-020).
    """
    start = _line_start(text, tag[0])
    end = _content_line_end(text, start)
    line = text[start:end]
    cut_start, cut_end = tag[0] - start, tag[1] - start
    if not (line[:cut_start] + line[cut_end:]).strip(" \t"):
        return [TextEdit(start, _next_line(text, start), "")]
    return _minimal_edit(text, start, end, replace_in_line(line, cut_start, cut_end, ""))


def _is_block_collection(node: Node) -> TypeGuard[Collection]:
    return isinstance(node, MappingNode | SequenceNode) and not node.flow


def _anchor(text: str, parent: Collection, index_or_key: str | int) -> _Anchor:
    if isinstance(parent, MappingNode):
        if not isinstance(index_or_key, str):
            raise ValueError("a mapping value is addressed by key")
        entry = parent.get(index_or_key)
        if entry is None:
            raise ValueError(f"no key {index_or_key!r}")
        key = entry.key_origin
        colon = key.end + len(text[key.end :]) - len(text[key.end :].lstrip(" \t"))
        if text[colon : colon + 1] != ":":
            raise ValueError(f"no ':' after key {index_or_key!r}")
        return _Anchor(_line_start(text, key.start), _column(text, key.start), colon + 1, False)
    if not isinstance(index_or_key, int):
        raise ValueError("a sequence item is addressed by index")
    dash = _dash_pos(text, parent, index_or_key)
    return _Anchor(_line_start(text, dash), _column(text, dash), dash + 1, True)


def _past_node_anchor(file: SourceFile, head: _Anchor, old: Node, path: str) -> _Anchor:
    """Move ``head.head_end`` past the ``&name`` of ``old`` so the new value follows it (R-9, C5).

    Raises:
        WriteRefused: If ``old``'s anchor is not on the key's (or dash's) line: the new value
            would have to move it, which is not a byte-surgical change.
    """
    if not isinstance(old, ScalarNode | MappingNode | SequenceNode) or old.anchor is None:
        return head
    node_anchor = old.anchor
    text = file.text
    start = node_anchor.origin.start
    if _line_start(text, start) != head.line_start or start < head.head_end:
        raise WriteRefused(
            f"{path}: the anchor &{node_anchor.name} of this value is not on its key's line;"
            " replacing the value would move it; no file changed"
        )
    return replace(head, head_end=node_anchor.origin.end)


def _new_indents(text: str, anchor: _Anchor, old: Node, step: int, offset: int) -> tuple[int, int]:
    """Columns for a new mapping / list value: the old entries' column when valid for the kind."""
    map_indent = anchor.column + step
    seq_indent = anchor.column + (step if anchor.is_item else offset)
    if _is_block_collection(old):
        old_col = entry_column(text, old)
        if old_col > anchor.column:
            map_indent = old_col
        if old_col > anchor.column or (old_col == anchor.column and not anchor.is_item):
            seq_indent = old_col
    return map_indent, seq_indent


def _old_value(file: SourceFile, anchor: _Anchor, old: Node, path: str) -> _OldValue:
    """Locate what must be removed of ``old``; refuse if that would drop a comment."""
    text = file.text
    anchor_end = _content_line_end(text, anchor.line_start)
    if _is_block_collection(old):
        first = (
            old.entries[0].key_origin.start if isinstance(old, MappingNode) else old.origin.start
        )
        return _OldValue(None, (_line_start(text, first), _content_after(text, old)))
    if _is_block_scalar(text, old):
        block = parse_block(text, old.origin.start, anchor.column)
        lines = (block.content_start, block.content_end) if block.lines else None
        return _OldValue((block.header_start, block.header_end), lines)
    start, end = old.origin.start, old.origin.end
    if start == end:
        return _OldValue(None, None)
    last_line_end = _content_line_end(text, end - 1)
    tail = text[end:last_line_end]
    multi_line = "\n" in text[start:end]
    if start <= anchor_end and not multi_line:
        return _OldValue((start, end), None)
    if ("#" in text[start:end] and multi_line) or tail.strip(" \t"):
        raise WriteRefused(
            f"cannot replace {path} in {file.path}: removing its old value would drop a comment"
        )
    if start <= anchor_end:
        return _OldValue(
            (start, anchor_end), (_next_line(text, anchor_end), _next_line(text, end - 1))
        )
    return _OldValue(None, (_line_start(text, start), _next_line(text, end - 1)))


def _anchor_line_edits(
    text: str,
    anchor: _Anchor,
    removed: _OldValue,
    inline_text: str,
    tag: tuple[int, int] | None = None,
) -> list[TextEdit]:
    """Rewrite the anchor line: remove the old inline value, write ``inline_text`` after the head.

    ``inline_text`` is ``""`` when the new value goes on the lines below; then the line keeps
    its bytes up to and including its comment, losing only the old value and the spaces before.
    ``tag`` (``_tag_cut``, on this line) is removed too: after the head it is cut with the old
    value; before it (``!literal &a``) only the tag goes and the anchor's bytes stay.
    """
    start = anchor.line_start
    end = _content_line_end(text, start)
    line = text[start:end]
    head = anchor.head_end - start
    has_comment = find_comment_start(line, head) is not None
    if removed.inline is not None:
        cut_end = removed.inline[1] - start
        if not has_comment and not inline_text:
            cut_end = len(line)
    elif inline_text or tag is not None:
        cut_end = head if has_comment else len(line)
    else:
        return []
    cut_start, kept = head, ""
    if tag is not None:
        tag_start, tag_end = tag[0] - start, tag[1] - start
        if tag_start < head:
            cut_start, kept = tag_start, line[tag_end:head]
        else:
            cut_end = max(cut_end, tag_end)
    new_line = replace_in_line(line, cut_start, cut_end, kept + inline_text)
    return _minimal_edit(text, start, end, new_line)


def _below_edits(
    file: SourceFile, anchor: _Anchor, removed: _OldValue, below: _Lines, path: str
) -> list[TextEdit]:
    """Replace the old value's lines (or insert after the anchor line) with ``below``."""
    text = file.text
    if removed.lines is not None:
        start, end = removed.lines
    else:
        start = end = _next_line(text, anchor.line_start)
    if not below.lines and start == end:
        return []
    if below.tail is not None:
        check_block_end(text, end, below.tail[0], below.tail[1], path)
    newline = detect_newline(text)
    lead = start == len(text) and _ends_without_break(text) and bool(below.lines)
    if lead:
        _check_open_end(file, path)
    open_end = end == len(text) and _ends_without_break(text)
    body = _join(below, newline, lead=lead, final_break=not open_end) if below.lines else ""
    if open_end and not below.lines and start > 0:
        # Deleting the last lines of a file without a final break: drop the preceding break.
        start -= 2 if text[start - 2 : start] == "\r\n" else 1
    return [TextEdit(start, end, body)]


def _replace_compact_item(
    file: SourceFile,
    anchor: _Anchor,
    old: Node,
    new_value: Value,
    renderer: _Renderer,
    path: str,
) -> list[TextEdit]:
    """Replace an item whose old block collection starts on the ``-`` line (``- k: v``)."""
    text = file.text
    out = _Lines()
    renderer.item(out, new_value, anchor.column, None)
    out.lines[0] = out.lines[0][anchor.column + 2 :]
    start = old.origin.start
    end = _content_after(text, old)
    if out.tail is not None:
        check_block_end(text, end, out.tail[0], out.tail[1], path)
    open_end = end == len(text) and _ends_without_break(text)
    body = _join(out, detect_newline(text), lead=False, final_break=not open_end)
    return [TextEdit(start, end, body)]


def _replace_in_flow(
    text: str, parent: Collection, index_or_key: str | int, old: Node, new_value: Value
) -> list[TextEdit]:
    rendered = render_flow_value(new_value)
    start, end = old.origin.start, old.origin.end
    tag = _tag_cut(text, old)
    if tag is not None:  # drop the tag; keep what stands between it and the value (an anchor)
        return _rewrite_span(text, tag[0], end, text[tag[1] : start] + rendered)
    if start != end:
        return _rewrite_span(text, start, end, rendered)
    if not isinstance(parent, MappingNode) or not isinstance(index_or_key, str):
        raise ValueError("an empty flow value must be a mapping value")
    entry = parent.get(index_or_key)
    if entry is None:
        raise ValueError(f"no key {index_or_key!r}")
    after, bare_colon = _flow_entry_end(text, entry)
    prefix = " " if bare_colon else ": "
    return _insert_in_line(text, after, prefix + rendered)


def _rewrite_span(text: str, start: int, end: int, new_text: str) -> list[TextEdit]:
    """Replace ``text[start:end]`` keeping the comment column of the line where ``end`` lies."""
    first = _line_start(text, start)
    last = _line_start(text, end)
    line_end = _content_line_end(text, end)
    last_line = text[last:line_end]
    new_line = replace_in_line(last_line, 0, end - last, text[first:start] + new_text)
    return _minimal_edit(text, first, line_end, new_line)


# --- Include conversion to mapping form (mission include-overrides, FR-006, research R-7) ------


def convert_include_edits(
    file: SourceFile,
    parent: Collection | None,
    slot: str | int | None,
    include: Origin,
    keys: list[str],
    value: Value,
    step: int,
    *,
    path: str,
) -> list[TextEdit]:
    """Turn the scalar-form include at ``include`` into mapping form with one new override.

    This is only the text half of FR-006: the caller has already decided that the include must
    be converted, and passes spans and the concrete collection holding the include. ``$ref`` is
    written plain and first (D-2) and the include string's bytes ``text[start:end]``, quotes and
    escapes included, move to it verbatim (D-5). The override lines are rendered by the step-1
    new-key renderer (FR-015 to FR-017) with no sibling to copy styles from: ``$ref`` is not a
    configuration value. New lines go immediately after the include's line, use the file's line
    ending, and are indented with the caller's ``step`` (``detect_indent``).

    - Block mapping parent, value on the key's line (``coder: file:x.yaml  # c``): the separator
      and the include string are deleted, the rest of the line is kept byte for byte, so the gap
      before the comment stays and the comment follows the key (D-5, contract example
      ``coder:  # c``). The ``$ref`` line and the overrides go below at key column + ``step``.
      This keeps the *gap*, unlike FR-020 which keeps the *column* of a value changed in place:
      here the value leaves the line, so there is no value whose column the comment could keep.
    - Block mapping parent with the value on a following line, block sequence item (D-4) and
      document root (``parent`` is ``None``): ``$ref: `` is inserted before the include string,
      a pure insertion that keeps the bytes between the string and any comment (D-5); the
      overrides go below at the include string's column (for an item, its content column).
    - Flow parent, mapping or sequence (D-3): the include string becomes
      ``{$ref: <bytes>, k: v}``, nested flow mappings for intermediate keys; the line keeps its
      end-of-line comment's column (FR-020).

    Args:
        file: The file holding the include (``include.file``).
        parent: The collection holding the include, or ``None`` for a whole-document include.
        slot: The include's key in a block mapping ``parent``; unused otherwise.
        include: The span of the include string.
        keys: The override path below the include, at least one segment; ``keys[:-1]`` become
            intermediate mappings and the last gets ``value``.
        value: The override's value.
        step: The file's indentation step.
        path: The configuration path, for refusal messages.

    Raises:
        WriteRefused: If the include string spans several lines (D-11), an anchor or tag
            precedes it (bead crs: converting would drop or move it), or a new block scalar
            would absorb the lines after it; raised before any edit is produced.
    """
    if not keys:
        raise ValueError("convert_include_edits needs at least one override key")
    text = file.text
    start, end = include.start, include.end
    include_text = text[start:end]
    if "\n" in include_text or include_text[:1] in ("|", ">"):
        line = text.count("\n", 0, start) + 1
        raise WriteRefused(
            f"{path}: the include at {file.path} line {line} spans several lines; cannot convert"
            " it to mapping form without rewriting it; no file changed"
        )
    _refuse_properties(file, parent, slot, start, path)
    ref = f"{REF_KEY}: {include_text}"
    if parent is not None and parent.flow:
        entries = _flow_entries({keys[0]: _nest(keys[1:], value)})
        return _rewrite_span(text, start, end, "{" + ref + _FLOW_SEPARATOR + entries + "}")
    renderer = _Renderer(step, step)
    out = _Lines()
    if isinstance(parent, MappingNode):
        if slot is None:
            raise ValueError("an include in a mapping is addressed by its key")
        anchor = _anchor(text, parent, slot)
        if anchor.line_start == _line_start(text, start):
            indent = anchor.column + step
            out.add(" " * indent + ref)
            _add_new_keys(out, renderer, keys, value, indent, None, None)
            below = _insert_lines(file, _next_line(text, start), out, path)
            return [TextEdit(anchor.head_end, end, ""), *below]
    _add_new_keys(out, renderer, keys, value, _column(text, start), None, None)
    below = _insert_lines(file, _next_line(text, start), out, path)
    return [TextEdit(start, start, REF_KEY + ": "), *below]


def _refuse_properties(
    file: SourceFile, parent: Collection | None, slot: str | int | None, start: int, path: str
) -> None:
    """Refuse a conversion when anything but blanks and comments precedes the include string.

    Between the include's owner (the key's ``:``, the item's ``-``, the previous flow item or
    the start of the document) and the include string only whitespace, comments, flow ``,``/``[``
    and, for a whole document, directives and ``---`` may appear. Anything else is an anchor or
    a tag (``coder: &a file:x.yaml``, ``- !t file:x.yaml``) that conversion would delete or move
    onto the new mapping, so it is refused (TROUPE-001, TROUPE-002). The loader rejects anchors
    and tags already; this keeps the writer safe on its own.
    """
    text = file.text
    if isinstance(parent, MappingNode):
        if not isinstance(slot, str):
            raise ValueError("an include in a mapping is addressed by its key")
        lower = _anchor(text, parent, slot).head_end
    elif isinstance(parent, SequenceNode):
        if not isinstance(slot, int):
            raise ValueError("an include in a sequence is addressed by its index")
        if not parent.flow:
            lower = _anchor(text, parent, slot).head_end
        elif slot:
            lower = parent.items[slot - 1].origin.end
        else:
            lower = parent.origin.start + 1
    else:
        lower = 0
    for raw in text[lower:start].split("\n"):
        line = raw.rstrip("\r")
        cut = find_comment_start(line, 0)
        content = (line if cut is None else line[:cut]).strip(" \t" + BOM)
        if isinstance(parent, SequenceNode) and parent.flow:
            content = content.strip(" \t,[")
        elif parent is None:
            if content.startswith("%"):
                continue
            if content.startswith("---"):
                content = content[3:].strip(" \t")
        if content:
            line_no = text.count("\n", 0, start) + 1
            raise WriteRefused(
                f"{path}: the include at {file.path} line {line_no} has an anchor or tag;"
                " cannot convert it to mapping form without dropping it; no file changed"
            )
