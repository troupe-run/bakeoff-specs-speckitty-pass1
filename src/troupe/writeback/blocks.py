"""Multi-line strings: literal and folded block scalars (FR-017, FR-018, research R-11).

Contract (FR-017): a multi-line string (a ``str`` containing ``"\\n"``) replacing a plain or quoted
scalar, or as a new key's value, is written as a literal block (``|``, or ``|-`` without a trailing
newline); under a flow parent it is a double-quoted flow scalar. An existing block scalar keeps its
indicator and chomping unless the value's trailing newlines require a different chomping.

Contract (FR-018): in a folded (``>``) value, paragraphs whose text is unchanged keep their bytes; a
changed paragraph is re-wrapped greedily by word at the width of its longest old content line (an
over-long word takes a line of its own); a paragraph with no counterpart in the old value wraps at
the value's longest old content line; a change that would introduce a more-indented line exits 3.

Every function here is pure: it reads the original file text and returns ``TextEdit`` values.
Indices are code points into ``SourceFile.text``. ruamel's end mark of a block scalar is not used;
header and content extents are re-derived from the text (see ``troupe.yamlcore``).

Choices made where the contract is silent (TROUPE-002, TROUPE-008):

- A value without ``"\\n"`` replacing an existing block scalar stays a block scalar with the same
  indicator and ``strip`` chomping: the contract says a block scalar keeps its style.
- A multi-line value replacing a plain or quoted scalar *inside a flow collection* is written
  double-quoted: YAML does not allow block scalars in flow context.
- A first content line led by a space (or a leading line of only spaces) gets an explicit
  indentation indicator equal to the content indent minus the parent's column (the file's indent
  step for new blocks); otherwise YAML would detect the wrong indentation.
- Refused (``WriteRefused``, exit 3) because the result would not read back as the value, and no
  other byte may change to prevent it: ``keep`` chomping followed by blank lines (they would join
  the value), and lines after the block indented at least as deep as its content (an indented
  comment line would become content).
- Folded values are split into units exactly as YAML folds them: a *text paragraph* is a run of
  lines that do not start with white space (joined by single spaces); every *more-indented* line
  (starting with a space or tab after the content indent) is a unit of its own, and line breaks
  next to it are kept. Old and new units are aligned with ``difflib`` so that inserting or
  removing a paragraph leaves the other paragraphs' bytes unchanged; units inside a changed region
  are paired by position to find the old width. A new unit whose text equals an old unit not
  already kept elsewhere copies that old unit's lines, so reordered paragraphs keep their bytes.
- More-indented lines in folded values (product-owner ruling, review cycle 1): any change to a
  folded value whose old content contains a more-indented line (including a line of only spaces
  deeper than the content indent) is refused (exit 3), because writing it back would put a
  more-indented line into a folded value. A change whose new value would contain one is refused
  too. Writing the identical value is a no-op and returns no edits.
- Body lines always end with a line break, even at the end of a file that had none, because a
  ``clip`` block at end of file without a final break would lose the value's final newline.

Callers must check ``can_block`` first and write a double-quoted scalar when it is false (control
characters other than tab, carriage return, U+FEFF and the Unicode line separators cannot be held
by a block scalar). Every edit is verified by the caller re-composing the new text (NFR-002).
"""

import difflib
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

from troupe.errors import WriteRefused
from troupe.includes import LiteralStr
from troupe.writeback import TextEdit
from troupe.writeback.comments import find_comment_start, replace_in_line
from troupe.writeback.scalars import LITERAL_PREFIX, Context, can_single, render_string

Chomp = Literal["strip", "clip", "keep"]
Indicator = Literal["|", ">"]

DEFAULT_INDENT_STEP = 2
_CHOMP_CHARS: dict[Chomp, str] = {"strip": "-", "clip": "", "keep": "+"}
_CHOMP_BY_CHAR: dict[str, Chomp] = {"-": "strip", "+": "keep"}
_WHITE = " \t"
_CHOMP_PREFERENCE: tuple[Chomp, ...] = ("clip", "strip", "keep")


@dataclass(frozen=True)
class BlockScalar:
    """An existing block scalar, located in its file's text.

    Attributes:
        indicator: ``"|"`` (literal) or ``">"`` (folded).
        chomp: Chomping from the header (``-`` strip, none clip, ``+`` keep).
        indent_indicator: The header's indentation digit, or ``None``.
        header_start: Index of the indicator character.
        header_end: Index just after the header token (indicator, chomp and digit).
        content_start: Start of the line after the header line.
        content_end: End of the last content line including its line break; equal to
            ``content_start`` when there are no content lines. For ``clip``/``strip`` trailing
            empty lines are not content; for ``keep`` they are.
        content_indent: Column of the content.
        parent_indent: Column of the parent (the key, or the ``-`` of a sequence item).
        lines: Raw content lines, indentation included, without line breaks (nor ``"\\r"``).
        line_starts: Index in the text where each of ``lines`` starts.
    """

    indicator: Indicator
    chomp: Chomp
    indent_indicator: int | None
    header_start: int
    header_end: int
    content_start: int
    content_end: int
    content_indent: int
    parent_indent: int
    lines: list[str]
    line_starts: list[int]


@dataclass(frozen=True)
class Paragraph:
    """One folding unit of a folded value.

    Attributes:
        text: The unit's text in the value (a text paragraph's lines joined by single spaces).
        spaced: Whether this is a more-indented line (always a unit of its own).
        line_range: Indices into ``BlockScalar.lines``.
        width: Longest content line of the unit, excluding the content indentation.
    """

    text: str
    spaced: bool
    line_range: range
    width: int


@dataclass(frozen=True)
class _Unit:
    """One folding unit of a new value; ``old`` is its aligned old unit index, if any."""

    text: str
    spaced: bool
    old: int | None
    unchanged: bool


# --- Literal rendering and chomping (T025) ------------------------------------------------------


def can_block(value: str) -> bool:
    """Return whether a block scalar can hold ``value`` (tab and printable characters only)."""
    return all(can_single(line) for line in value.split("\n"))


def required_chomps(value: str) -> set[Chomp]:
    """Return the chompings that read back ``value``'s trailing newlines exactly."""
    if value == "":
        return {"strip", "clip", "keep"}
    trailing = _trailing_newlines(value)
    if trailing == len(value) or trailing >= 2:
        return {"keep"}  # clip of a block without content lines is "", not "\n"
    return {"clip", "keep"} if trailing == 1 else {"strip"}


def choose_chomp(current: Chomp, value: str) -> Chomp:
    """Keep ``current`` if it reads back ``value``; else the required one (clip before keep)."""
    return current if current in required_chomps(value) else _preferred_chomp(value)


def literal_lines(value: str, content_indent: int) -> list[str]:
    """Return a literal block's body lines (without line breaks) for ``value``.

    Non-empty lines are indented by ``content_indent``; empty lines stay empty. The body reads
    back as ``value`` under the chomping ``required_chomps`` gives for it.
    """
    body = _body(value)
    lines = [" " * content_indent + line if line else "" for line in _split_body(body)]
    return lines + [""] * _trailing_empty_lines(value)


def literal_header(value: str, chomp: Chomp, indent_step: int = DEFAULT_INDENT_STEP) -> str:
    """Return a new literal block header: ``|``, the indentation digit if needed, the chomp.

    Raises:
        ValueError: If an indentation indicator is needed and ``indent_step`` is not 1-9.
    """
    digit = _indicator_digit(indent_step) if _needs_indicator(_split_body(_body(value))) else ""
    return "|" + digit + _CHOMP_CHARS[chomp]


def render_new_multiline(
    value: str,
    context: Context,
    content_indent: int,
    indent_step: int = DEFAULT_INDENT_STEP,
) -> tuple[str, list[str]]:
    """Render a multi-line value for a new key or item.

    Returns:
        ``(header, body_lines)``: in block context the literal header to write after ``key: ``
        (or ``- ``) and the body lines (without line breaks) to write below it, each followed by
        the file's newline; in flow context a double-quoted scalar and no body lines. The caller
        checks ``can_block`` first for block context. For an ``includes.LiteralStr`` the header
        (``!literal |-``) or the double-quoted scalar starts with ``scalars.LITERAL_PREFIX``
        (spec S-11, S-13); the body lines are the same.
    """
    prefix = LITERAL_PREFIX if isinstance(value, LiteralStr) else ""
    if context == "flow":
        return prefix + render_string(value, "double"), []
    chomp = _preferred_chomp(value)
    header = literal_header(value, chomp, indent_step)
    return prefix + header, literal_lines(value, content_indent)


def check_block_end(text: str, pos: int, content_indent: int, chomp: Chomp, path: str) -> None:
    """Refuse if the lines from ``pos`` on would become part of a block scalar ending there.

    Blank lines would join a ``keep`` value; a blank line longer than the content indent, or the
    first non-blank line indented to the content indent or deeper, would become content.

    Raises:
        WriteRefused: Naming ``path``.
    """
    for _start, line in _lines_from(text, pos):
        if line.strip(" ") == "":
            if len(line) > content_indent or chomp == "keep":
                raise WriteRefused(
                    f"cannot write {path} as a block scalar: the blank lines after it would "
                    "become part of its value"
                )
            continue
        if _leading_spaces(line) >= content_indent:
            raise WriteRefused(
                f"cannot write {path} as a block scalar: the indented line after it would "
                "become part of its value"
            )
        return


def replace_with_multiline(
    text: str,
    start: int,
    end: int,
    value: str,
    *,
    context: Context,
    parent_indent: int,
    path: str,
    indent_step: int = DEFAULT_INDENT_STEP,
    newline: str = "\n",
) -> list[TextEdit]:
    """Replace the plain or quoted scalar ``text[start:end]`` by the multi-line ``value``.

    Block context: a literal block whose content is indented ``parent_indent + indent_step``;
    the end-of-line comment after the scalar keeps its column (FR-020). Flow context: a
    double-quoted scalar. The caller checks ``can_block`` first for block context.

    A replacement path: ``LiteralStr`` never reaches here, and no tag is written; tags of
    replaced values are the caller's separate edit (WP08).

    Args:
        text: The file text.
        start: Start of the scalar's span (a real plain/quoted scalar, not an empty value).
        end: End of the scalar's span.
        value: The new value.
        context: ``"flow"`` if the scalar is inside ``[...]``/``{...}``.
        parent_indent: Column of the key, or of the ``-`` of a sequence item.
        path: The configuration path, for refusal messages.
        indent_step: The file's indentation step.
        newline: The file's newline (``fileio.detect_newline``).

    Raises:
        WriteRefused: If the result would not read back as ``value`` (see ``check_block_end``),
            or something other than a comment follows the scalar on its line.
    """
    if context == "flow":
        return _optional(_rewrite_line_span(text, start, end, render_string(value, "double")))
    _require_block(value)
    line_end = _line_end(text, end)
    tail = text[end:line_end].rstrip("\r")
    tail_col = len(tail) - len(tail.lstrip(" "))
    if tail.strip(" ") and find_comment_start(tail, tail_col) != tail_col:
        raise WriteRefused(f"cannot write {path} as a block scalar: text follows it on its line")
    chomp = _preferred_chomp(value)
    content_indent = parent_indent + indent_step
    header = literal_header(value, chomp, indent_step)
    after = line_end + 1 if line_end < len(text) else line_end
    check_block_end(text, after, content_indent, chomp, path)
    body = _join(literal_lines(value, content_indent), newline)
    edits = _optional(_rewrite_line_span(text, start, end, header))
    edits.append(TextEdit(after, after, body if line_end < len(text) else newline + body))
    return edits


# --- Existing block scalars (T026) --------------------------------------------------------------


def parse_block(
    text: str, header_start: int, parent_indent: int, indent_step: int = DEFAULT_INDENT_STEP
) -> BlockScalar:
    """Parse the block scalar whose header starts at ``header_start`` (its span's start).

    The content runs from the next line while lines are blank or indented at least to the
    content indent: the header digit plus ``parent_indent``, else the first non-blank line's
    indent (``parent_indent + indent_step`` when the block has no content lines).

    Raises:
        ValueError: If ``text[header_start]`` is not ``|`` or ``>``.
    """
    indicator = text[header_start : header_start + 1]
    if indicator not in ("|", ">"):
        raise ValueError(f"no block scalar header at index {header_start}")
    chomp: Chomp = "clip"
    digit: int | None = None
    pos = header_start + 1
    for _ in range(2):
        ch = text[pos : pos + 1]
        if ch in _CHOMP_BY_CHAR and chomp == "clip" and ch:
            chomp = _CHOMP_BY_CHAR[ch]
        elif ch in "123456789" and digit is None and ch:
            digit = int(ch)
        else:
            break
        pos += 1
    line_end = _line_end(text, header_start)
    content_start = line_end + 1 if line_end < len(text) else line_end
    rows = list(_lines_from(text, content_start))
    if digit is not None:
        content_indent = parent_indent + digit
    else:
        first = next((line for _s, line in rows if line.strip(" ")), None)
        detected = _leading_spaces(first) if first is not None else 0
        content_indent = detected if detected > parent_indent else parent_indent + indent_step
    lines: list[str] = []
    starts: list[int] = []
    for row_start, line in rows:
        blank = line.strip(" ") == "" and len(line) <= content_indent
        if not blank and _leading_spaces(line) < content_indent:
            break
        lines.append(line)
        starts.append(row_start)
    if chomp != "keep":
        while lines and lines[-1].strip(" ") == "" and len(lines[-1]) <= content_indent:
            lines.pop()
            starts.pop()
    content_end = content_start
    if starts:
        content_end = _line_end(text, starts[-1])
        content_end += 1 if content_end < len(text) else 0
    return BlockScalar(
        indicator=">" if indicator == ">" else "|",
        chomp=chomp,
        indent_indicator=digit,
        header_start=header_start,
        header_end=pos,
        content_start=content_start,
        content_end=content_end,
        content_indent=content_indent,
        parent_indent=parent_indent,
        lines=lines,
        line_starts=starts,
    )


def replace_block(
    block: BlockScalar, text: str, new_value: str, newline: str, path: str
) -> list[TextEdit]:
    """Replace an existing block scalar's value, literal or folded (FR-017, FR-018).

    A replacement path: ``LiteralStr`` never reaches here, and the header's tag (if any) is not
    touched; tags of replaced values are the caller's separate edit (WP08).
    """
    if block.indicator == ">":
        return replace_folded(block, text, new_value, newline, path)
    return replace_literal(block, text, new_value, newline, path)


def replace_literal(
    block: BlockScalar, text: str, new_value: str, newline: str, path: str
) -> list[TextEdit]:
    """Replace a block scalar's content by ``new_value`` written as literal lines.

    The header keeps its indicator, digit and chomping unless the chomping must change; only
    then does the header line change (its comment keeps its column).

    Raises:
        ValueError: If ``can_block(new_value)`` is false (the caller must check first).
        WriteRefused: If the result would not read back as ``new_value``.
    """
    _require_block(new_value)
    lines = literal_lines(new_value, block.content_indent)
    return _rewrite_block(block, text, new_value, [(line, None) for line in lines], newline, path)


# --- Folded paragraphs (T027, T028) -------------------------------------------------------------


def greedy_wrap(paragraph: str, width: int) -> list[str]:
    """Wrap ``paragraph`` greedily by word so lines are at most ``width`` long where possible.

    Lines break only at a single space between two non-white characters, so no line starts or
    ends with white space that the paragraph does not; a word longer than ``width`` takes a
    line of its own.
    """
    lines: list[str] = []
    current = ""
    for word in _words(paragraph):
        if current and len(current) + 1 + len(word) <= width:
            current += " " + word
        else:
            if current:
                lines.append(current)
            current = word
    lines.append(current)
    return lines


def folded_paragraphs(lines: list[str], content_indent: int) -> list[Paragraph]:
    """Split a folded block's raw content lines into folding units (see the module notes)."""
    paragraphs: list[Paragraph] = []
    run: list[int] = []

    def close_run() -> None:
        if run:
            texts = [lines[i][content_indent:] for i in run]
            width = max(len(t) for t in texts)
            paragraphs.append(Paragraph(" ".join(texts), False, range(run[0], run[-1] + 1), width))
            run.clear()

    for index, line in enumerate(lines):
        content = line[content_indent:]
        if _is_blank(line, content_indent):
            close_run()
        elif content[0] in _WHITE:
            close_run()
            paragraphs.append(Paragraph(content, True, range(index, index + 1), len(content)))
        else:
            run.append(index)
    close_run()
    return paragraphs


def replace_folded(
    block: BlockScalar, text: str, new_value: str, newline: str, path: str
) -> list[TextEdit]:
    """Replace a folded block's value, keeping the bytes of unchanged paragraphs (FR-018).

    Raises:
        ValueError: If ``can_block(new_value)`` is false (the caller must check first).
        WriteRefused: If a more-indented line would be written that is not an unchanged old one,
            or the result would not read back as ``new_value``.
    """
    _require_block(new_value)
    ci = block.content_indent
    old = folded_paragraphs(block.lines, ci)
    if any(p.spaced for p in old):
        if new_value == _folded_value(block, old):
            return []
        raise WriteRefused(
            f"cannot write {path}: its folded value contains a more-indented line, and writing "
            "it back would put a more-indented line into a folded value"
        )
    leading, units, separators = _split_folded(new_value, old)
    overall = max((p.width for p in old), default=0)
    out: list[tuple[str, str | None]] = []

    old_leading = old[0].line_range.start if old else len(block.lines)
    out += _empty_lines(block, text, range(0, old_leading), leading)
    for index, unit in enumerate(units):
        if index > 0:
            previous = units[index - 1]
            reuse = range(0, 0)
            if previous.old is not None and unit.old is not None and unit.old == previous.old + 1:
                reuse = range(old[previous.old].line_range.stop, old[unit.old].line_range.start)
            out += _empty_lines(block, text, reuse, separators[index - 1])
        if unit.unchanged and unit.old is not None:
            out += [(block.lines[i], _verbatim(block, text, i)) for i in old[unit.old].line_range]
        elif unit.spaced:
            raise WriteRefused(
                f"cannot write {path}: the change would put a more-indented line "
                f"({unit.text!r}) into a folded value"
            )
        else:
            width = old[unit.old].width if unit.old is not None else overall
            out += [(" " * ci + line, None) for line in greedy_wrap(unit.text, width)]
    old_trailing = range(old[-1].line_range.stop if old else old_leading, len(block.lines))
    out += _empty_lines(block, text, old_trailing, _trailing_empty_lines(new_value))
    return _rewrite_block(block, text, new_value, out, newline, path)


# --- Internals ----------------------------------------------------------------------------------


def _split_folded(new_value: str, old: list[Paragraph]) -> tuple[int, list[_Unit], list[int]]:
    """Return the new value's leading empty lines, units and empty lines between units."""
    parts = re.split(r"(\n+)", _body(new_value))
    leading = 0
    if parts[0] == "" and len(parts) > 1:
        leading = len(parts[1])
        parts = parts[2:]
    elif parts == [""]:
        parts = []
    texts = parts[0::2]
    breaks = [len(sep) for sep in parts[1::2]]
    spaced = [t[0] in _WHITE for t in texts]
    separators = [k if not (spaced[i] or spaced[i + 1]) else k - 1 for i, k in enumerate(breaks)]
    old_keys = [(p.spaced, p.text) for p in old]
    new_keys = list(zip(spaced, texts, strict=True))
    matcher = difflib.SequenceMatcher(None, old_keys, new_keys, autojunk=False)
    pairing: dict[int, tuple[int, bool]] = {}
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("equal", "replace"):
            for offset in range(min(i2 - i1, j2 - j1)):
                pairing[j1 + offset] = (i1 + offset, tag == "equal")
    kept = {i for i, unchanged in pairing.values() if unchanged}
    for j, key in enumerate(new_keys):
        if pairing.get(j, (None, False))[1]:
            continue
        moved = next((i for i, k in enumerate(old_keys) if k == key and i not in kept), None)
        if moved is not None:  # same text, other position (reordered): keep its bytes
            pairing[j] = (moved, True)
            kept.add(moved)
    units = [
        _Unit(text, sp, *pairing.get(j, (None, False))) for j, (sp, text) in enumerate(new_keys)
    ]
    return leading, units, separators


def _folded_value(block: BlockScalar, old: list[Paragraph]) -> str:
    """The value YAML reads from a folded block's content (used to recognise a no-op)."""
    if not old:
        return "\n" * len(block.lines) if block.chomp == "keep" else ""
    value = "\n" * old[0].line_range.start
    for index, unit in enumerate(old):
        if index > 0:
            previous = old[index - 1]
            empties = unit.line_range.start - previous.line_range.stop
            joined_text = not (previous.spaced or unit.spaced)
            value += "\n" * (empties if joined_text else empties + 1)
        value += unit.text
    trailing = len(block.lines) - old[-1].line_range.stop
    return value + {"strip": "", "clip": "\n", "keep": "\n" * (trailing + 1)}[block.chomp]


def _rewrite_block(
    block: BlockScalar,
    text: str,
    new_value: str,
    lines: list[tuple[str, str | None]],
    newline: str,
    path: str,
) -> list[TextEdit]:
    """Replace the header (chomp, digit) and the content by ``lines``.

    Each entry is ``(line, verbatim)``: the logical line without break, and the original bytes
    (break included) to copy instead, or ``None`` to write ``line + newline``.
    """
    chomp = choose_chomp(block.chomp, new_value)
    check_block_end(text, block.content_end, block.content_indent, chomp, path)
    stripped = [line[block.content_indent :] for line, _v in lines]
    digit: int | None = None
    if block.indent_indicator is None and _needs_indicator(stripped):
        digit = block.content_indent - block.parent_indent
        if not 1 <= digit <= 9:
            raise WriteRefused(
                f"cannot write {path}: its block scalar would need an indentation indicator "
                f"of {digit}, which YAML cannot express"
            )
    header = _modified_header(text[block.header_start : block.header_end], chomp, digit)
    content = "".join(
        verbatim if verbatim is not None and verbatim.endswith("\n") else line + newline
        for line, verbatim in lines
    )
    edits = _optional(_rewrite_line_span(text, block.header_start, block.header_end, header))
    if block.content_start == len(text) and not text.endswith("\n") and content:
        content = newline + content
    edits += _optional(_minimal_edit(text, block.content_start, block.content_end, content))
    return edits


def _modified_header(header: str, chomp: Chomp, digit: int | None) -> str:
    """Change only the chomp character and, if given, insert the digit after the indicator."""
    chomp_pos = next((i for i, ch in enumerate(header) if ch in "+-"), None)
    if chomp_pos is not None:
        header = header[:chomp_pos] + _CHOMP_CHARS[chomp] + header[chomp_pos + 1 :]
    else:
        header += _CHOMP_CHARS[chomp]
    if digit is not None:
        header = header[0] + str(digit) + header[1:]
    return header


def _empty_lines(
    block: BlockScalar, text: str, old_rows: range, count: int
) -> list[tuple[str, str | None]]:
    """``count`` empty lines, copying the old ones' bytes when there were as many."""
    if len(old_rows) == count:
        return [("", _verbatim(block, text, i)) for i in old_rows]
    return [("", None)] * count


def _verbatim(block: BlockScalar, text: str, index: int) -> str:
    """The original bytes of content line ``index``, its line break included."""
    start = block.line_starts[index]
    end = _line_end(text, start)
    return text[start : end + 1] if end < len(text) else text[start:end]


def _rewrite_line_span(text: str, start: int, end: int, new_text: str) -> TextEdit | None:
    """Replace ``text[start:end]`` (possibly spanning lines) keeping the comment's column.

    The comment column is measured on the line where ``end`` lies (FR-020).
    """
    first_line_start = text.rfind("\n", 0, start) + 1
    last_line_start = text.rfind("\n", 0, end) + 1 if end > start else first_line_start
    line_end = _line_end(text, end)
    if line_end > last_line_start and text[line_end - 1] == "\r":
        line_end -= 1
    last_line = text[last_line_start:line_end]
    prefix = text[first_line_start:start]
    new_line = replace_in_line(last_line, 0, end - last_line_start, prefix + new_text)
    return _minimal_edit(text, first_line_start, line_end, new_line)


def _minimal_edit(text: str, start: int, end: int, new_text: str) -> TextEdit | None:
    """The smallest edit turning ``text[start:end]`` into ``new_text``, or ``None``."""
    old = text[start:end]
    if old == new_text:
        return None
    prefix = 0
    limit = min(len(old), len(new_text))
    while prefix < limit and old[prefix] == new_text[prefix]:
        prefix += 1
    suffix = 0
    while suffix < limit - prefix and old[-1 - suffix] == new_text[-1 - suffix]:
        suffix += 1
    return TextEdit(start + prefix, end - suffix, new_text[prefix : len(new_text) - suffix])


def _optional(edit: TextEdit | None) -> list[TextEdit]:
    return [] if edit is None else [edit]


def _require_block(value: str) -> None:
    if not can_block(value):
        raise ValueError("value cannot be held by a block scalar; check can_block first")


def _preferred_chomp(value: str) -> Chomp:
    required = required_chomps(value)
    return next(c for c in _CHOMP_PREFERENCE if c in required)


def _trailing_newlines(value: str) -> int:
    return len(value) - len(value.rstrip("\n"))


def _body(value: str) -> str:
    return value[: len(value) - _trailing_newlines(value)]


def _split_body(body: str) -> list[str]:
    return body.split("\n") if body else []


def _trailing_empty_lines(value: str) -> int:
    """Empty lines after the body that ``keep`` needs for the value's trailing newlines."""
    trailing = _trailing_newlines(value)
    return trailing if trailing == len(value) else max(trailing - 1, 0)


def _needs_indicator(stripped_lines: list[str]) -> bool:
    """Whether auto-detection would misread the indentation of these (de-indented) lines."""
    for line in stripped_lines:
        if line:
            return line[0] == " "
    return False


def _indicator_digit(indent_step: int) -> str:
    if not 1 <= indent_step <= 9:
        raise ValueError(f"indentation step {indent_step} cannot be an indentation indicator")
    return str(indent_step)


def _words(paragraph: str) -> list[str]:
    """Split at single spaces with a non-white character on both sides."""
    words: list[str] = []
    start = 0
    for i, ch in enumerate(paragraph):
        if (
            ch == " "
            and 0 < i < len(paragraph) - 1
            and paragraph[i - 1] not in _WHITE
            and paragraph[i + 1] not in _WHITE
        ):
            words.append(paragraph[start:i])
            start = i + 1
    words.append(paragraph[start:])
    return words


def _is_blank(line: str, content_indent: int) -> bool:
    return line.strip(" ") == "" and len(line) <= content_indent


def _leading_spaces(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _line_end(text: str, pos: int) -> int:
    """Index of the ``"\\n"`` ending the line containing ``pos``, or ``len(text)``."""
    end = text.find("\n", pos)
    return len(text) if end < 0 else end


def _lines_from(text: str, pos: int) -> Iterator[tuple[int, str]]:
    """Yield ``(start, line)`` for each line from ``pos``; lines exclude ``"\\r\\n"``/``"\\n"``."""
    while pos < len(text):
        end = _line_end(text, pos)
        yield pos, text[pos:end].removesuffix("\r")
        pos = end + 1


def _join(lines: list[str], newline: str) -> str:
    return "".join(line + newline for line in lines)
