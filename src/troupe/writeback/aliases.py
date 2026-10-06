"""Expansion text: replace one written alias with a block-style copy (spec C7-C9; research R-7).

``expand_edits`` returns the ``TextEdit`` values that turn a written ``*name`` into a copy of its
anchored node, with ``  # expanded from *<name> by troupe`` at the end of the key's line (or the
list item's dash line). It sets no value: the caller (``apply``) applies the edits, reloads and
writes the value into the copy, one alias at a time, outermost first (C7).

Contract and choices:

- C9 refusals (``WriteRefused``, exit 3, "no file changed"): the alias is inside a flow
  collection; it is not written on its key's or dash's line; its line already has an end-of-line
  comment; anything but blanks stands between the key's ``:`` (or the ``-``) and the alias.
- C8 copy: rendered node by node from the anchored node's content, never by copying text ranges,
  so comments are never copied and no ``&name`` is ever written (spans exclude anchors, R-2).
  Keys and one-line plain/single/double scalars keep their written text; other scalars use the
  step-1 rules (multi-line strings become literal blocks, ``blocks.render_new_multiline``).
  Empty collections are ``{}``/``[]``. Flow collections are written in block style.
- C7: aliases inside the copy stay aliases (``*name``).
- A-0/FR-007: merge keys are never written, so a copy that would contain a ``<<`` entry (at any
  depth, not looking inside inner aliases, which stay aliases) is refused (``WriteRefused``).
- Placement (R-7): a mapping copy goes at the key's column + ``step``, a list copy at the key's
  column + the parent mapping's sequence offset (flush if its nearest sibling list is flush, as
  ``collections`` does). Under a dash, the copy goes at the dash's column + 2. Inside the copy,
  nested mappings are indented by ``step``, nested lists by the same offset, and collection
  items use compact form (``- k: v``), as ``collections`` renders new values.
- A collection copy (or a scalar copy written as a literal block) adds lines after the alias's
  line, using the file's newline. If that line is the last one and has no line break, the file
  still ends without one, unless the copy ends with a literal block (whose value needs it); this
  is the convention of ``collections``.
- A scalar copy replaces just the alias token: ``model: opus  # expanded from *m by troupe``.
"""

from dataclasses import dataclass, field
from typing import NoReturn

from troupe.errors import WriteRefused
from troupe.merge import is_merge_entry
from troupe.paths import unwrap
from troupe.tree import (
    AliasNode,
    MappingEntry,
    MappingNode,
    MergedMapping,
    MergeKeyMapping,
    Node,
    ScalarNode,
    SequenceNode,
    SourceFile,
    TextInclude,
    YamlInclude,
)
from troupe.writeback import TextEdit
from troupe.writeback.blocks import (
    Chomp,
    can_block,
    check_block_end,
    choose_chomp,
    render_new_multiline,
)
from troupe.writeback.comments import find_comment_start
from troupe.writeback.fileio import detect_newline
from troupe.writeback.scalars import choose_style, render_scalar, render_string

COMMENT = "  # expanded from *{name} by troupe"
"""The end-of-line comment written on the expanded alias's key or dash line (contract)."""

_BOM = "\ufeff"
_BLANKS = " \t"
_WRITTEN_FORMS = ("plain", "single", "double")


@dataclass(frozen=True)
class _Head:
    """The key or ``-`` owning the alias: its line, its column, the index after ``:``/``-``."""

    line_start: int
    column: int
    head_end: int
    is_item: bool


@dataclass
class _Out:
    """Rendered lines (no line breaks); ``tail`` is set when the last lines are a literal body."""

    lines: list[str] = field(default_factory=list)
    tail: tuple[int, Chomp] | None = None

    def add(self, line: str) -> None:
        self.lines.append(line)
        self.tail = None

    def extend(self, other: "_Out") -> None:
        self.lines.extend(other.lines)
        self.tail = other.tail


def expand_edits(
    file: SourceFile,
    alias: AliasNode,
    parent: MappingNode | SequenceNode,
    slot: str | int,
    step: int,
    *,
    path: str,
) -> list[TextEdit]:
    """Return the edits replacing the written alias ``alias`` with a block-style copy (C7-C9).

    Args:
        file: The file the alias is written in.
        alias: A written alias (``merge`` false) that is the value at ``slot`` of ``parent``.
        parent: The concrete collection holding the alias (a ``MergeKeyMapping``'s ``written``
            is used if the view is given).
        slot: The alias's key (mapping) or index (sequence) in ``parent``.
        step: The file's indentation step (``collections.detect_indent``).
        path: The configuration path being set, for messages.

    Raises:
        WriteRefused: For the C9 cases; the message names ``path``, ``*name``, the file and line.
        ValueError: If ``alias`` is not a written alias held at ``slot`` of ``parent`` (a
            programming error, not a contract error).
    """
    if alias.merge or alias.name is None:
        raise ValueError("only a written alias can be expanded")
    text = file.text
    line_no = text.count("\n", 0, alias.origin.start) + 1
    where = f"{path}: the alias *{alias.name} at {file.path} line {line_no}"

    def refuse(reason: str) -> NoReturn:
        raise WriteRefused(f"{where} {reason}; no file changed")

    if parent.flow:
        refuse("is inside a flow collection; a block-style copy cannot be written there")
    concrete = parent.written if isinstance(parent, MergeKeyMapping) else parent
    head = _head(text, concrete, slot, alias)
    between = text[head.head_end : alias.origin.start]
    if "\n" in between:
        owner = "dash's" if head.is_item else "key's"
        refuse(
            f"is not on its {owner} line; moving it would rewrite a line you did not ask to change"
        )
    if between.strip(_BLANKS):
        refuse("cannot be expanded byte-surgically: something other than blanks precedes it")
    line_end = _content_line_end(text, alias.origin.end)
    line = text[head.line_start : line_end]
    if find_comment_start(line, alias.origin.end - head.line_start) is not None:
        refuse(
            "cannot be expanded: its line already has a comment; troupe's comment would replace it"
        )
    if text[alias.origin.end : line_end].strip(_BLANKS):
        refuse("cannot be expanded byte-surgically: something other than blanks follows it")

    content = unwrap(alias.target)
    if _has_merge_key(content):
        refuse(
            "refers to a value that uses the merge key '<<'; copying it would write a merge key,"
            " which troupe never does"
        )
    seq_offset = (
        _sequence_offset(text, concrete, step) if isinstance(concrete, MappingNode) else step
    )
    copy = _Copy(step, seq_offset)
    out = _Out()
    item_col = head.column + 2
    copy.attach(
        out,
        "",
        unwrap(alias.target),
        head.column,
        is_item=head.is_item,
        map_indent=item_col if head.is_item else None,
        seq_indent=item_col if head.is_item else None,
    )
    comment = COMMENT.format(name=alias.name)
    inline = out.lines[0].lstrip(" ")
    if inline:
        edits = [TextEdit(alias.origin.start, alias.origin.end, inline + comment)]
    else:
        edits = [TextEdit(head.head_end, alias.origin.end, comment)]
    below = _Out(out.lines[1:], out.tail)
    if below.lines:
        edits.append(_insert_below(file, line_end, below, path))
    return edits


def _head(
    text: str, parent: MappingNode | SequenceNode, slot: str | int, alias: AliasNode
) -> _Head:
    """Locate the key's ``:`` or the item's ``-`` owning ``alias`` at ``slot`` of ``parent``."""
    if isinstance(parent, MappingNode):
        entry = parent.get(slot) if isinstance(slot, str) else None
        if entry is None or entry.value is not alias:
            raise ValueError(f"the alias is not the value of key {slot!r}")
        key = entry.key_origin
        colon = key.end + len(text[key.end :]) - len(text[key.end :].lstrip(_BLANKS))
        if text[colon : colon + 1] != ":":
            raise ValueError(f"no ':' after key {slot!r}")
        return _Head(_line_start(text, key.start), _column(text, key.start), colon + 1, False)
    if (
        not isinstance(slot, int)
        or not 0 <= slot < len(parent.items)
        or parent.items[slot] is not alias
    ):
        raise ValueError(f"the alias is not item {slot!r}")
    before = alias.origin.start
    while before > 0 and text[before - 1] in _BLANKS:
        before -= 1
    if before > 0 and text[before - 1] == "-":
        dash = before - 1
        return _Head(_line_start(text, dash), _column(text, dash), dash + 1, True)
    # Not on a dash line: report it from the dash at the item's column (found by line search).
    dash = _dash_before(text, parent, before)
    return _Head(_line_start(text, dash), _column(text, dash), dash + 1, True)


def _dash_before(text: str, seq: SequenceNode, pos: int) -> int:
    """Index of the nearest ``-`` at the sequence's column on a line at or before ``pos``."""
    column = _column(text, seq.origin.start)
    start = _line_start(text, pos)
    while True:
        offset = 1 if start == 0 and text.startswith(_BOM) else 0
        at = start + offset + column
        if text[at : at + 1] == "-" and set(text[start + offset : at]) <= {" ", "-"}:
            return at
        if start == 0:
            raise ValueError("no '-' found for the sequence item")
        start = _line_start(text, start - 1)


@dataclass(frozen=True)
class _Copy:
    """Block-style rendering of existing nodes at a fixed step and sequence offset (C8)."""

    step: int
    seq_offset: int

    def attach(
        self,
        out: _Out,
        head: str,
        node: Node,
        parent_col: int,
        *,
        is_item: bool = False,
        map_indent: int | None = None,
        seq_indent: int | None = None,
    ) -> None:
        """Write ``node`` after ``head`` (``key:``, or ``-`` if ``is_item``, at ``parent_col``)."""
        if isinstance(node, AliasNode):
            if node.merge or node.name is None:
                raise ValueError("a merge-derived alias is never copied")
            out.add(f"{head} *{node.name}")
            return
        node = _concrete(node)
        if isinstance(node, MappingNode) and node.entries:
            out.add(head)
            indent = map_indent if map_indent is not None else parent_col + self.step
            self.mapping(out, node, indent)
        elif isinstance(node, SequenceNode) and node.items:
            default = parent_col + (self.step if is_item else self.seq_offset)
            out.add(head)
            self.sequence(out, node, seq_indent if seq_indent is not None else default)
        elif isinstance(node, MappingNode | SequenceNode):
            out.add(head + (" {}" if isinstance(node, MappingNode) else " []"))
        else:
            self.scalar(out, head, node, parent_col + self.step)

    def scalar(self, out: _Out, head: str, node: ScalarNode, content_indent: int) -> None:
        """Write a scalar after ``head``: its written text if one line, else step-1 rules."""
        source = node.origin.source
        if node.origin.start == node.origin.end:
            out.add(head)  # a null written as nothing stays nothing
        elif node.style in _WRITTEN_FORMS and "\n" not in source:
            out.add(f"{head} {source}")
        elif isinstance(node.value, str) and "\n" in node.value and can_block(node.value):
            header, body = render_new_multiline(node.value, "block", content_indent, self.step)
            out.add(f"{head} {header}")
            out.lines.extend(body)
            out.tail = (content_indent, choose_chomp("clip", node.value))
        else:
            out.add(f"{head} {render_scalar(node.value, None, 'block')}")

    def mapping(self, out: _Out, node: MappingNode, indent: int) -> None:
        for entry in node.entries:
            self.attach(out, " " * indent + _key_text(entry) + ":", entry.value, indent)

    def sequence(self, out: _Out, node: SequenceNode, dash_col: int) -> None:
        for item in node.items:
            self.item(out, item, dash_col)

    def item(self, out: _Out, node: Node, dash_col: int) -> None:
        """Write one item; non-empty collections use compact form (``- k: v``, ``- - a``)."""
        content = node if isinstance(node, AliasNode) else _concrete(node)
        if isinstance(content, MappingNode) and content.entries:
            inner = _Out()
            self.mapping(inner, content, dash_col + 2)
        elif isinstance(content, SequenceNode) and content.items:
            inner = _Out()
            self.sequence(inner, content, dash_col + 2)
        else:
            self.attach(out, " " * dash_col + "-", node, dash_col, is_item=True)
            return
        inner.lines[0] = " " * dash_col + "- " + inner.lines[0][dash_col + 2 :]
        out.extend(inner)


def _has_merge_key(node: Node) -> bool:
    """Whether copying ``node`` would write a ``<<`` entry; inner aliases are not descended."""
    if isinstance(node, MergeKeyMapping):
        return True
    if isinstance(node, MappingNode):
        return any(is_merge_entry(e) or _has_merge_key(e.value) for e in node.entries)
    if isinstance(node, SequenceNode):
        return any(_has_merge_key(item) for item in node.items)
    return False


def _concrete(node: Node) -> ScalarNode | MappingNode | SequenceNode:
    """The node as written: a ``MergeKeyMapping``'s ``written``; includes are impossible (C3)."""
    assert not isinstance(node, YamlInclude | TextInclude | MergedMapping), "C3: no includes"
    assert not isinstance(node, AliasNode)
    return node.written if isinstance(node, MergeKeyMapping) else node


def _key_text(entry: MappingEntry) -> str:
    """The key as written if on one line, else rendered by the step-1 quoting rules."""
    source = entry.key_origin.source
    if source and "\n" not in source:
        return source
    return render_string(entry.key, choose_style(entry.key, None, "block"))


def _insert_below(file: SourceFile, line_end: int, below: _Out, path: str) -> TextEdit:
    """Insert ``below`` after the line ending at ``line_end`` (its content end)."""
    text = file.text
    newline = detect_newline(text)
    pos = _next_line(text, line_end)
    if below.tail is not None:
        check_block_end(text, pos, below.tail[0], below.tail[1], path)
    open_end = pos == len(text) and not text.endswith("\n")
    body = "".join(line + newline for line in below.lines)
    if open_end:
        body = newline + (body if below.tail is not None else body[: -len(newline)])
    return TextEdit(pos, pos, body)


def _sequence_offset(text: str, mapping: MappingNode, step: int) -> int:
    """0 if the nearest sibling block sequence (from the last entry) is flush (``collections``)."""
    for entry in reversed(mapping.entries):
        value = entry.value
        if isinstance(value, SequenceNode) and not value.flow and value.items:
            flush = _column(text, value.origin.start) == _column(text, entry.key_origin.start)
            return 0 if flush else step
    return step


def _line_start(text: str, pos: int) -> int:
    return text.rfind("\n", 0, pos) + 1


def _next_line(text: str, pos: int) -> int:
    """Start of the line after the one containing ``pos`` (``len(text)`` on the last line)."""
    end = text.find("\n", pos)
    return len(text) if end < 0 else end + 1


def _content_line_end(text: str, pos: int) -> int:
    """End of the line containing ``pos``, excluding ``"\\r\\n"``/``"\\n"``."""
    end = text.find("\n", pos)
    if end < 0:
        return len(text)
    return end - 1 if end > _line_start(text, pos) and text[end - 1] == "\r" else end


def _column(text: str, pos: int) -> int:
    """Column of ``pos`` in code points; a leading BOM is not a column."""
    start = _line_start(text, pos)
    return pos - start - (1 if start == 0 and text.startswith(_BOM) else 0)
