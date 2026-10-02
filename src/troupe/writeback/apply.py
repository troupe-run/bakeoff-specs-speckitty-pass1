"""``apply_set``: plan, render and verify one ``set`` without touching the disk (FR-010..FR-020).

``apply_set`` composes the building blocks: ``placement.place`` decides where the change goes,
``scalars``/``comments``/``blocks``/``collections`` render ``TextEdit`` values, which are spliced
into the original texts. Before anything may be written, the new texts are re-loaded in memory
and verified (research R-17): the value at PATH must read back as the new value, and the rest of
the configuration (every node outside PATH: kind, keys, order, values, scalar styles, includes)
must be unchanged. Any mismatch is a refusal (exit 3), so a renderer bug can never become a
corrupted file. A ``set`` whose value is already the current value is a no-op: no texts at all.

How an existing scalar is written (``ReplaceScalar``):

- a single-line value replaces exactly the scalar's span, in its current quoting style if that
  can represent it (``scalars.render_scalar``); the line's end-of-line comment keeps its column
  (``comments.replace_in_line``);
- a multi-line string replacing a plain or quoted scalar becomes a literal block, or a
  double-quoted scalar inside a flow collection (``blocks.replace_with_multiline``);
- a string replacing a literal or folded block scalar is written by ``blocks.replace_block``;
- a collection value, a value for an empty (zero-width) null, and a non-string value replacing a
  block scalar are kind changes (``collections.replace_value_edits``).

Text includes follow research R-16 (revised): with a CRLF target VALUE must be a string, written
with CRLF line endings (else exit 3); with an LF or break-free target a string is written as
parsed and any non-string VALUE (scalar, mapping or list) as the VALUE argument exactly as typed.

Choices made where the contract is silent (TROUPE-002, TROUPE-008):

- A string a block scalar cannot hold (control characters other than tab) replacing a plain or
  quoted scalar in block context is written double-quoted on the scalar's line.
- A string ``file:...`` written as a value becomes an include when the files are read again; it
  is verified as written text (the include string), not as the included content.
- Comparisons (no-op and verification) are type-aware (``leaves.same``: ``1``, ``1.0``, ``"1"``
  and ``true`` differ) and ignore mapping key order only in the no-op check, where the
  configuration means the same either way.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from troupe import yamlcore
from troupe.errors import LoadError, PathError, WriteRefused
from troupe.leaves import same
from troupe.loader import load
from troupe.paths import walk
from troupe.tree import (
    MappingNode,
    Node,
    ScalarNode,
    SequenceNode,
    SourceFile,
    TextInclude,
    YamlInclude,
)
from troupe.values import Value
from troupe.writeback import TextEdit, apply_edits
from troupe.writeback.blocks import can_block, parse_block, replace_block, replace_with_multiline
from troupe.writeback.collections import (
    detect_indent,
    entry_column,
    new_item_edits,
    new_key_edits,
    replace_value_edits,
)
from troupe.writeback.comments import replace_in_line
from troupe.writeback.fileio import detect_newline, to_crlf, uses_crlf
from troupe.writeback.placement import (
    AddKeys,
    AppendItem,
    Placement,
    ReplaceCollection,
    ReplaceScalar,
    ReplaceText,
    place,
)
from troupe.writeback.scalars import QuoteStyle, render_scalar, render_string

_QUOTE_STYLES: dict[str, QuoteStyle] = {"plain": "plain", "single": "single", "double": "double"}


@dataclass(frozen=True)
class WritePlan:
    """The verified result of a ``set`` (data-model "Write plan").

    Attributes:
        files: The complete new text of every file that changes; empty for a no-op.
        tree: The configuration re-loaded from the new texts (the tree as it will be on disk once
            ``files`` are written); ``None`` for a no-op.
    """

    files: dict[SourceFile, str]
    tree: Node | None


def apply_set(
    root: Node, segments: list[str], dotted: str, value: Value, raw_value: str
) -> WritePlan:
    """Plan ``set dotted VALUE`` on the configuration ``root`` loaded from disk.

    Args:
        root: The configuration as loaded (its origin file is the root configuration file).
        segments: The parsed PATH.
        dotted: PATH as the user wrote it, for messages.
        value: The parsed VALUE.
        raw_value: The VALUE argument exactly as typed (text includes, research R-16).

    Returns:
        The new file texts and the re-loaded tree, verified; no files for a no-op.

    Raises:
        WriteRefused: Exit 3; nothing may be written (include replacement, CRLF text include with
            a non-string VALUE, a renderer refusal, or a failed verification).
        PathError: Exit 5 (see ``placement.place``).
    """
    placement = place(root, segments, dotted)
    if isinstance(placement, ReplaceText):
        return _plan_text(root, segments, dotted, placement.node, value, raw_value)
    if isinstance(placement, ReplaceScalar | ReplaceCollection) and _matches(placement.node, value):
        return WritePlan({}, None)
    file, edits = _edits(placement, dotted, value)
    new_text = apply_edits(file.text, edits)
    if new_text == file.text:
        _refuse(dotted)
    files = {file: new_text}
    tree = _verify(root, segments, dotted, files, lambda node: _matches(node, value))
    return WritePlan(files, tree)


# --- Text includes (R-16) -----------------------------------------------------------------------


def _plan_text(
    root: Node,
    segments: list[str],
    dotted: str,
    node: TextInclude,
    value: Value,
    raw_value: str,
) -> WritePlan:
    target = node.target
    if uses_crlf(target.text):
        if not isinstance(value, str):
            raise WriteRefused(
                f"{dotted}: text include {target.path} uses CRLF line endings, so VALUE must be"
                " a string; no file changed"
            )
        content = to_crlf(value)
    else:
        content = value if isinstance(value, str) else raw_value
    if content == target.text:
        return WritePlan({}, None)
    files = {target: content}

    def reads_back(new: Node) -> bool:
        return isinstance(new, TextInclude) and new.target.text == content

    return WritePlan(files, _verify(root, segments, dotted, files, reads_back))


# --- Rendering ----------------------------------------------------------------------------------


def _edits(placement: Placement, dotted: str, value: Value) -> tuple[SourceFile, list[TextEdit]]:
    """Return the file the change goes into and its edits."""
    if isinstance(placement, AddKeys):
        file = placement.mapping.origin.file
        step = detect_indent(file.text)
        return file, new_key_edits(
            file, placement.mapping, placement.keys, value, step, path=dotted
        )
    if isinstance(placement, AppendItem):
        file = placement.sequence.origin.file
        step = detect_indent(file.text)
        return file, new_item_edits(file, placement.sequence, value, step, path=dotted)
    if isinstance(placement, ReplaceCollection):
        file = placement.node.origin.file
        step = detect_indent(file.text)
        edits = replace_value_edits(
            file, placement.parent, placement.slot, placement.node, value, step, path=dotted
        )
        return file, edits
    if isinstance(placement, ReplaceScalar):
        return placement.node.origin.file, _scalar_edits(placement, dotted, value)
    raise AssertionError(f"unexpected placement {placement!r}")  # ReplaceText is handled earlier


def _scalar_edits(placement: ReplaceScalar, dotted: str, value: Value) -> list[TextEdit]:
    node = placement.node
    file = node.origin.file
    text = file.text
    step = detect_indent(text)
    start, end = node.origin.start, node.origin.end
    is_block = node.style in ("literal", "folded")
    kind_change = isinstance(value, dict | list) or start == end
    if kind_change or (is_block and not (isinstance(value, str) and can_block(value))):
        return replace_value_edits(
            file, placement.parent, placement.slot, node, value, step, path=dotted
        )
    parent_indent = entry_column(text, placement.parent)
    newline = detect_newline(text)
    if is_block:
        assert isinstance(value, str)
        block = parse_block(text, start, parent_indent, step)
        return replace_block(block, text, value, newline, dotted)
    if isinstance(value, str) and "\n" in value:
        if placement.context == "flow" or can_block(value):
            return replace_with_multiline(
                text,
                start,
                end,
                value,
                context=placement.context,
                parent_indent=parent_indent,
                path=dotted,
                indent_step=step,
                newline=newline,
            )
        return [_replace_span(text, start, end, render_string(value, "double"))]
    assert not isinstance(value, dict | list)
    rendered = render_scalar(value, _QUOTE_STYLES.get(node.style), placement.context)
    return [_replace_span(text, start, end, rendered)]


def _replace_span(text: str, start: int, end: int, new_text: str) -> TextEdit:
    """Replace ``text[start:end]``; the comment on the line where the span ends keeps its column.

    The span may cover several lines (a multi-line plain or quoted scalar); they become one.
    """
    first = text.rfind("\n", 0, start) + 1
    last = text.rfind("\n", 0, end) + 1
    line_end = text.find("\n", end)
    line_end = len(text) if line_end < 0 else line_end
    if line_end > last and text[line_end - 1] == "\r":
        line_end -= 1
    new_line = replace_in_line(text[last:line_end], 0, end - last, text[first:start] + new_text)
    return TextEdit(first, line_end, new_line)


# --- Comparison and verification (R-17) ---------------------------------------------------------


def _matches(node: Node, value: Value) -> bool:
    """Whether ``node`` holds ``value`` as written: deep, type-aware, key order ignored.

    An include node holds the include string it was written as (``file:...``), so writing that
    string again is recognised as unchanged.
    """
    if isinstance(node, ScalarNode):
        return not isinstance(value, dict | list) and same(node.value, value)
    if isinstance(node, YamlInclude | TextInclude):
        written = _include_string(node)
        return isinstance(value, str) and written is not None and written == value
    if isinstance(node, MappingNode):
        if not isinstance(value, dict) or len(value) != len(node.entries):
            return False
        return all(
            entry.key in value and _matches(entry.value, value[entry.key]) for entry in node.entries
        )
    if not isinstance(value, list) or len(value) != len(node.items):
        return False
    return all(
        _matches(item, item_value) for item, item_value in zip(node.items, value, strict=True)
    )


def _include_string(node: YamlInclude | TextInclude) -> str | None:
    """The string an include node was written as (``file:...``), or ``None`` if unreadable."""
    try:
        raw = yamlcore.compose(node.origin.source, "<include string>")
    except LoadError:
        return None
    return raw.text if isinstance(raw, yamlcore.RawScalar) else None


def _verify(
    root: Node,
    segments: list[str],
    dotted: str,
    files: Mapping[SourceFile, str],
    reads_back: Callable[[Node], bool],
) -> Node:
    """Re-load the configuration from the new texts and check the change is exactly the one asked.

    Returns:
        The re-loaded tree.

    Raises:
        WriteRefused: If the new texts do not load, the value at PATH does not read back, or
            anything outside PATH differs.
    """
    config_file = root.origin.file.path
    overrides: dict[Path, str] = {file.path: text for file, text in files.items()}
    try:
        new_root = load(config_file, overrides=overrides)
        found = walk(new_root, segments)
    except (LoadError, PathError):
        _refuse(dotted)
    if found.remaining or not reads_back(found.nodes[-1]):
        _refuse(dotted)
    if not _same_outside(root, new_root, [], segments):
        _refuse(dotted)
    return new_root


def _refuse(dotted: str) -> NoReturn:
    raise WriteRefused(f"{dotted}: cannot write this change byte-surgically; no file changed")


def _same_outside(old: Node, new: Node, here: list[str], target: list[str]) -> bool:
    """Whether ``old`` and ``new`` are identical except at ``target`` and below.

    Kinds, flow flags, keys and their order, scalar values (type-aware) and styles, and include
    targets must all be equal. On the way to ``target`` a mapping may gain the key and a list the
    item that the ``set`` adds.
    """
    if here == target:
        return True
    on_route = here == target[: len(here)]
    if isinstance(old, ScalarNode):
        return isinstance(new, ScalarNode) and new.style == old.style and same(old.value, new.value)
    if isinstance(old, TextInclude):
        return (
            isinstance(new, TextInclude)
            and new.target.path == old.target.path
            and new.target.text == old.target.text
        )
    if isinstance(old, YamlInclude):
        return (
            isinstance(new, YamlInclude)
            and new.target.path == old.target.path
            and _same_outside(old.root, new.root, here, target)
        )
    if isinstance(old, MappingNode):
        if not isinstance(new, MappingNode) or new.flow != old.flow:
            return False
        old_keys = [entry.key for entry in old.entries]
        new_keys = [entry.key for entry in new.entries]
        if new_keys != old_keys:
            added = target[len(here)] if on_route else None
            if added is None or added in old_keys or new_keys != [*old_keys, added]:
                return False
        return all(
            _same_outside(entry.value, new.entries[index].value, [*here, entry.key], target)
            for index, entry in enumerate(old.entries)
        )
    if not isinstance(new, SequenceNode) or new.flow != old.flow:
        return False
    if len(new.items) != len(old.items):
        appended = on_route and target[len(here)] == str(len(old.items))
        if not appended or len(new.items) != len(old.items) + 1:
            return False
    return all(
        _same_outside(item, new.items[index], [*here, str(index)], target)
        for index, item in enumerate(old.items)
    )
