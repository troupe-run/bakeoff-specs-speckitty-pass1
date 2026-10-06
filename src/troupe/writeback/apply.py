"""``apply_set``: plan, render and verify one ``set`` without touching the disk (FR-010..FR-020).

``apply_set`` composes the building blocks: ``placement.place`` decides where the change goes,
``scalars``/``comments``/``blocks``/``collections`` render ``TextEdit`` values, which are spliced
into the original texts. Before anything may be written, the new texts are re-loaded in memory
and verified (research R-17): the value at PATH must read back as the new value, and the rest of
the configuration (every node outside PATH: kind, keys, order, values, scalar styles, includes)
must be unchanged. Any mismatch is a refusal (exit 3), so a renderer bug can never become a
corrupted file. A ``set`` whose value is already the current value is a no-op: no texts at all.

Include overrides (mission include-overrides, FR-005 to FR-010; research R-5):

- Where a new key goes is decided by ``placement.place``: by default a new key under content
  from an included file becomes an override in the including file, with ``in_include``
  (``set --in-include``) it goes into the innermost included file that defines its ancestor
  (the step-1 rule, D-8). Existing values, list appends and keys inside list items are
  unaffected by ``in_include`` (D-9). Both are decided in ``placement``, not here.
- A first override on a scalar-form include converts it to mapping form
  (``ConvertInclude`` -> ``collections.convert_include_edits``, D-2 to D-5; a multi-line
  include string is refused there, D-11); the edit stays in one file (C-005).
- Writers only ever receive concrete collections: writing through a merged view
  (``MergedMapping``) is a programming error, asserted in ``_edits``.
- Verification allows exactly one structural change, and only on the route to PATH: a node
  that was an include (or a mapping of the included file) may become a merged view of the
  *same* include target (or of that same mapping) gaining the new override. Everywhere else a
  merged view must stay a merged view of the same ``$ref`` target, a plain mapping must stay
  plain, and an include must keep its form (scalar or mapping), so any other conversion is
  still a refusal. In a merged view the new key may sit only at the very end (an override) or
  at the end of one of its nested base blocks (``--in-include`` into a base side, D-8; chained
  mapping-form includes nest several, ``_orders``).

How an existing scalar is written (``ReplaceScalar``):

- a single-line value replaces exactly the scalar's span, in its current quoting style if that
  can represent it (``scalars.render_scalar``); the line's end-of-line comment keeps its column
  (``comments.replace_in_line``);
- a multi-line string replacing a plain or quoted scalar becomes a literal block, or a
  double-quoted scalar inside a flow collection (``blocks.replace_with_multiline``);
- a string replacing a literal or folded block scalar is written by ``blocks.replace_block``;
- a collection value, a value for an empty (zero-width) null, and a non-string value replacing a
  block scalar are kind changes (``collections.replace_value_edits``).

Anchors and aliases (step 6; spec FR-003-FR-005, C5, C7, C8, C11; research R-8):

- ``placement.place`` decides whether PATH is reached through an alias; without
  ``expand_alias`` that is a refusal (exit 3) before any rendering. A set at the anchored node
  is an ordinary write, so every alias of it sees the new value.
- Expand loop (``set --expand-alias``): while ``place`` returns ``ExpandAlias`` (outermost alias
  first, C7), ``aliases.expand_edits`` replaces that alias with its copy in the current text,
  and the configuration is re-loaded in memory from the texts so far (keyed by path: every load
  makes new ``SourceFile`` objects). At most ``MAX_EXPANSIONS`` rounds. The ordinary placement
  is then rendered against the expanded text; all edits land in one file (anchors are per file,
  C-005), written once. An unchanged VALUE is checked first and expands nothing (no-op).
- Verification runs once against the *original* tree, so expansion and set are verified (and
  recorded, C11) together. ``_same_outside`` has three alias rules: (1) an alias stays the same
  alias (name, merge flag, anchored node's path) and is not descended into, since its anchored
  node is compared at its own place; (2) with ``expand_alias`` a written alias on the route may
  become a copy, compared value by value with the anchored content and differing only at PATH;
  (3) anchor names are kept everywhere outside a copy, including on the value at PATH (C5), and
  a merge-key mapping stays one.

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

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from troupe import yamlcore
from troupe.errors import LoadError, PathError, WriteRefused
from troupe.leaves import same
from troupe.loader import load
from troupe.paths import unwrap, walk
from troupe.tree import (
    AliasNode,
    Anchor,
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
from troupe.values import Value
from troupe.writeback import TextEdit, apply_edits
from troupe.writeback.aliases import COMMENT, expand_edits
from troupe.writeback.blocks import can_block, parse_block, replace_block, replace_with_multiline
from troupe.writeback.collections import (
    convert_include_edits,
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
    ConvertInclude,
    ExpandAlias,
    Placement,
    ReplaceCollection,
    ReplaceScalar,
    ReplaceText,
    place,
)
from troupe.writeback.scalars import QuoteStyle, render_scalar, render_string

_QUOTE_STYLES: dict[str, QuoteStyle] = {"plain": "plain", "single": "single", "double": "double"}

MAX_EXPANSIONS = 64
"""Upper bound on aliases expanded by one ``set --expand-alias`` (R-8).

Each expansion removes one alias from PATH's route, so the loop ends after as many rounds as
PATH has aliases; the bound only guards against a placement bug looping forever.
"""


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
    root: Node,
    segments: list[str],
    dotted: str,
    value: Value,
    raw_value: str,
    *,
    in_include: bool = False,
    expand_alias: bool = False,
) -> WritePlan:
    """Plan ``set dotted VALUE`` on the configuration ``root`` loaded from disk.

    Args:
        root: The configuration as loaded (its origin file is the root configuration file).
        segments: The parsed PATH.
        dotted: PATH as the user wrote it, for messages.
        value: The parsed VALUE.
        raw_value: The VALUE argument exactly as typed (text includes, research R-16).
        in_include: ``set --in-include``: a new key goes into the included file instead of
            becoming an override in the including file (FR-010).
        expand_alias: ``set --expand-alias``: every alias on PATH is expanded into a copy of its
            anchored node, then VALUE is set in the copy (FR-005, C7); one write, one
            verification. Without it a PATH reached through an alias is refused (FR-004).

    Returns:
        The new file texts and the re-loaded tree, verified; no files for a no-op.

    Raises:
        WriteRefused: Exit 3; nothing may be written (include replacement, CRLF text include with
            a non-string VALUE, a path through an alias or merge key, an expansion refusal, a
            renderer refusal, or a failed verification).
        PathError: Exit 5 (see ``placement.place``).
    """
    placement = place(root, segments, dotted, in_include=in_include, expand_alias=expand_alias)
    if isinstance(placement, ReplaceText):
        return _plan_text(root, segments, dotted, placement.node, value, raw_value)
    if isinstance(placement, ReplaceScalar | ReplaceCollection) and _matches(placement.node, value):
        return WritePlan({}, None)
    if isinstance(placement, ExpandAlias):
        if _unchanged(root, segments, value):  # no-op first: nothing written, nothing expanded
            return WritePlan({}, None)
        return _plan_expansion(root, segments, dotted, value, placement, in_include=in_include)
    file, edits = _edits(placement, dotted, value)
    new_text = apply_edits(file.text, edits)
    if new_text == file.text:
        _refuse(dotted)
    files = {file: new_text}
    tree = _verify(root, segments, dotted, files, lambda node: _matches(node, value))
    return WritePlan(files, tree)


# --- Expanding aliases on PATH (R-8) ------------------------------------------------------------


def _unchanged(root: Node, segments: list[str], value: Value) -> bool:
    """Whether PATH exists and its resolved value already equals ``value``."""
    found = walk(root, segments)
    return not found.remaining and _matches(found.nodes[-1], value)


def _plan_expansion(
    root: Node,
    segments: list[str],
    dotted: str,
    value: Value,
    first: ExpandAlias,
    *,
    in_include: bool,
) -> WritePlan:
    """Expand every alias on PATH (outermost first, C7), then set VALUE in the copy.

    Each round splices one alias's copy into the file's text and re-loads the configuration in
    memory from the texts so far; placement then sees the copy and reports the next alias, or
    the ordinary placement of VALUE, which is rendered against the expanded text. The texts are
    keyed by path because each in-memory load creates new ``SourceFile`` objects. Anchors are per
    file (C-005), so every edit lands in the file of the outermost alias: one file, one write.
    A new key that step 5 would then write as an override in an including file (the alias is in
    an included file and ``in_include`` is not set) would make a second file: refused (exit 3).
    The result is verified once, against the original tree (expansion and set together).
    """
    original = first.alias.origin.file  # a ``SourceFile`` of ``root``: what ``write_files`` diffs
    config_file = root.origin.file.path
    texts: dict[Path, str] = {}
    comment_lines: list[tuple[int, str]] = []  # (line start, alias name) of each expansion
    current, placement = root, first
    for _ in range(MAX_EXPANSIONS):
        file = placement.alias.origin.file
        edits = expand_edits(
            file,
            placement.alias,
            placement.parent,
            placement.slot,
            detect_indent(file.text),
            path=dotted,
        )
        alias_start = placement.alias.origin.start
        comment_lines.append((file.text.rfind("\n", 0, alias_start) + 1, str(placement.alias.name)))
        texts[file.path] = apply_edits(file.text, edits)
        try:
            current = load(config_file, overrides=texts)
        except LoadError:
            _refuse(dotted)
        found = place(current, segments, dotted, in_include=in_include, expand_alias=True)
        if not isinstance(found, ExpandAlias):
            break
        placement = found
    else:
        raise WriteRefused(f"{dotted}: too many aliases to expand; no file changed")
    assert not isinstance(found, ReplaceText), "an anchored node never holds an include (C3)"
    file, edits = _edits(found, dotted, value)
    assert set(texts) == {original.path}, "anchors are per file: every copy in one file"
    if file.path != original.path:  # a new key that becomes an override in an including file
        raise WriteRefused(
            f"{dotted}: the alias *{first.alias.name} is expanded in {original.path}, but the new"
            f" key would be written as an override in {file.path}; an expansion and its set are"
            " one write of one file (use --in-include to add it to the copy); no file changed"
        )
    text = apply_edits(file.text, edits)
    for line_start, name in reversed(comment_lines):  # last line first: earlier starts hold
        text = _respace_comment(text, line_start, name, dotted)
    files = {original: text}
    tree = _verify(
        root, segments, dotted, files, lambda node: _matches(node, value), expand_alias=True
    )
    return WritePlan(files, tree)


def _respace_comment(text: str, line_start: int, name: str, dotted: str) -> str:
    """Put exactly the contract's two spaces before troupe's comment on an expanded line.

    Setting the value on the line that already carries the comment (a scalar alias at PATH, or a
    collection copy replaced by a scalar) keeps the comment's column, as for any comment
    (FR-020); the contract fixes the spacing of this one instead. Edits made after an expansion
    never start before its line, so ``line_start`` is still the start of that line.
    """
    line_end = text.find("\n", line_start)
    line_end = len(text) if line_end < 0 else line_end
    if line_end > line_start and text[line_end - 1] == "\r":
        line_end -= 1
    line = text[line_start:line_end]
    match = re.search(rf"[ \t]*# expanded from \*{re.escape(name)} by troupe$", line)
    if match is None:  # pragma: no cover - the comment is written on this line by expand_edits
        _refuse(dotted)
    respaced = line[: match.start()] + COMMENT.format(name=name)
    return text[:line_start] + respaced + text[line_end:]


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
    if isinstance(placement, ConvertInclude):
        if placement.parent is not None:
            _concrete(placement.parent, "ConvertInclude.parent")
        origin = placement.include.origin
        file = origin.file
        step = detect_indent(file.text)
        edits = convert_include_edits(
            file, placement.parent, placement.slot, origin, placement.keys, value, step, path=dotted
        )
        return file, edits
    if isinstance(placement, AddKeys):
        _concrete(placement.mapping, "AddKeys.mapping")
        file = placement.mapping.origin.file
        step = detect_indent(file.text)
        return file, new_key_edits(
            file, placement.mapping, placement.keys, value, step, path=dotted
        )
    if isinstance(placement, AppendItem):
        _concrete(placement.sequence, "AppendItem.sequence")
        file = placement.sequence.origin.file
        step = detect_indent(file.text)
        return file, new_item_edits(file, placement.sequence, value, step, path=dotted)
    if isinstance(placement, ReplaceCollection):
        _concrete(placement.parent, "ReplaceCollection.parent")
        _concrete(placement.node, "ReplaceCollection.node")
        file = placement.node.origin.file
        step = detect_indent(file.text)
        edits = replace_value_edits(
            file, placement.parent, placement.slot, placement.node, value, step, path=dotted
        )
        return file, edits
    if isinstance(placement, ReplaceScalar):
        _concrete(placement.parent, "ReplaceScalar.parent")
        return placement.node.origin.file, _scalar_edits(placement, dotted, value)
    raise AssertionError(f"unexpected placement {placement!r}")  # ReplaceText is handled earlier


def _concrete(collection: Node, role: str) -> None:
    """A merged view's origin may lie in another file: never write through one (plan Risks)."""
    assert not isinstance(collection, MergedMapping), f"{role} is a merged view, not a file's"


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
    string again is recognised as unchanged. Aliases are compared through (``unwrap``): an
    alias holds the value it resolves to.
    """
    node = _through_aliases(node)
    assert not isinstance(node, AliasNode)  # ``_through_aliases`` follows every alias
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


def _through_aliases(node: Node) -> Node:
    """Follow ``AliasNode.target`` (unlike ``unwrap``, an include stays an include)."""
    while isinstance(node, AliasNode):
        node = node.target
    return node


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
    *,
    expand_alias: bool = False,
) -> Node:
    """Re-load the configuration from the new texts and check the change is exactly the one asked.

    ``expand_alias`` allows the aliases on the route to PATH to have become copies (R-8 rule 2).
    A value at PATH that was anchored (and not reached through an alias) must keep its anchor
    name (C5).

    Returns:
        The re-loaded tree.

    Raises:
        WriteRefused: If the new texts do not load, the value at PATH does not read back or lost
            its anchor, or anything outside PATH differs.
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
    if _anchor_name(_target_anchor(root, segments)) != _anchor_name(
        _target_anchor(new_root, segments)
    ):
        _refuse(dotted)
    if not _same_outside(root, new_root, [], segments, expand_alias=expand_alias):
        _refuse(dotted)
    return new_root


def _target_anchor(root: Node, segments: list[str]) -> Anchor | None:
    """The anchor on the value at PATH, unless PATH is new or reached through an alias.

    Through an alias the value at PATH is either refused or written in a copy, which carries no
    anchors (C8), so there is nothing to keep.
    """
    found = walk(root, segments)
    if found.remaining or any(isinstance(node, AliasNode) for node in found.nodes):
        return None
    node = found.nodes[-1]
    return node.anchor if isinstance(node, ScalarNode | MappingNode | SequenceNode) else None


def _anchor_name(anchor: Anchor | None) -> str | None:
    return None if anchor is None else anchor.name


def _anchor_path(alias: AliasNode) -> tuple[str, ...] | None:
    """Where the anchored node an alias refers to is loaded (its identity, R-8 rule 1)."""
    anchored = alias.anchored
    if not isinstance(anchored, ScalarNode | MappingNode | SequenceNode):
        return None
    return None if anchored.anchor is None else anchored.anchor.path


def _same_alias(
    old: AliasNode, new: Node, here: list[str], target: list[str], *, expand_alias: bool
) -> bool:
    """R-8 rule 1: an alias stays the same alias of the same anchored node.

    The anchored node is compared at its own place, so this does not descend: a change at the
    anchor is not a change at every alias of it. A merge-derived value from an inline ``<<``
    mapping has no anchored node to be compared elsewhere, so its value is compared here.
    """
    if not (
        isinstance(new, AliasNode)
        and new.name == old.name
        and new.merge == old.merge
        and _anchor_path(new) == _anchor_path(old)
        and (new.written is None) == (old.written is None)
    ):
        return False
    if old.anchored is None:
        return _same_outside(old.target, new.target, here, target, expand_alias=expand_alias)
    return True


def _refuse(dotted: str) -> NoReturn:
    raise WriteRefused(f"{dotted}: cannot write this change byte-surgically; no file changed")


def _same_outside(
    old: Node,
    new: Node,
    here: list[str],
    target: list[str],
    *,
    expand_alias: bool,
    in_copy: bool = False,
) -> bool:
    """Whether ``old`` and ``new`` are identical except at ``target`` and below.

    Kinds, flow flags, keys and their order, scalar values (type-aware) and styles, include
    targets and include forms must all be equal. On the way to ``target`` a mapping may gain the
    key (at the position the merge rule gives it, ``_orders``) and a list the item that the
    ``set`` adds, and a mapping may become a merged view that
    gains its first override there (``_gains_override``, research R-5). A merged view must stay
    a merged view of the same ``$ref`` target (or of none) everywhere.

    Aliases and anchors (R-8):

    1. An alias outside the route, on it without ``expand_alias``, or merge-derived, must stay
       the same alias of the same anchored node (``_same_alias``), without descending.
    2. With ``expand_alias``, a written alias on the route may have become a copy: its anchored
       content is compared with the copy (``in_copy``), which may differ only at PATH.
    3. Anchor names on scalars, mappings and lists must be equal, except inside a copy, which
       has none (C8). A merge-key mapping must stay one.

    A copy is written in block style and its scalars may change their written form (C8), so
    inside a copy flow flags and scalar styles are not compared; values, keys and their order
    are.
    """
    if here == target:
        return True
    on_route = here == target[: len(here)]  # a strict prefix: ``here == target`` returned
    if isinstance(old, AliasNode):
        if on_route and expand_alias and not old.merge and not isinstance(new, AliasNode):
            content = _through_aliases(old)
            return _same_outside(
                content, new, here, target, expand_alias=expand_alias, in_copy=True
            )
        return _same_alias(old, new, here, target, expand_alias=expand_alias)
    if isinstance(new, AliasNode):
        return False
    if (
        isinstance(old, ScalarNode | MappingNode | SequenceNode)
        and isinstance(new, ScalarNode | MappingNode | SequenceNode)
        and not in_copy
        and _anchor_name(old.anchor) != _anchor_name(new.anchor)
    ):
        return False
    if isinstance(old, MergeKeyMapping) != isinstance(new, MergeKeyMapping):
        return False
    if isinstance(new, MergedMapping) and not isinstance(old, MergedMapping):
        if not (on_route and _gains_override(old, new)):
            return False
        old = unwrap(old)
        assert not isinstance(old, AliasNode)  # ``unwrap`` follows aliases
    elif isinstance(old, MergedMapping):
        if not isinstance(new, MergedMapping) or _ref_path(new) != _ref_path(old):
            return False
    if isinstance(old, ScalarNode):
        return (
            isinstance(new, ScalarNode)
            and (in_copy or new.style == old.style)
            and same(old.value, new.value)
        )
    if isinstance(old, TextInclude):
        return (
            isinstance(new, TextInclude)
            and (new.holder is None) == (old.holder is None)
            and new.target.path == old.target.path
            and new.target.text == old.target.text
        )
    if isinstance(old, YamlInclude):
        return (
            isinstance(new, YamlInclude)
            and (new.holder is None) == (old.holder is None)
            and new.target.path == old.target.path
            and _same_outside(old.root, new.root, here, target, expand_alias=expand_alias)
        )
    if isinstance(old, MappingNode):
        if not isinstance(new, MappingNode) or (new.flow != old.flow and not in_copy):
            return False
        old_keys = [entry.key for entry in old.entries]
        new_keys = [entry.key for entry in new.entries]
        if new_keys != old_keys:
            added = target[len(here)] if on_route else None
            if added is None or added in old_keys or new_keys not in _orders(old_keys, added, new):
                return False
        # Paired by key: the added key may sit before old keys in a merged view (``_orders``).
        new_values = {entry.key: entry.value for entry in new.entries}
        return all(
            _same_outside(
                entry.value,
                new_values[entry.key],
                [*here, entry.key],
                target,
                expand_alias=expand_alias,
                in_copy=in_copy,
            )
            for entry in old.entries
        )
    if not isinstance(new, SequenceNode) or (new.flow != old.flow and not in_copy):
        return False
    if len(new.items) != len(old.items):
        appended = on_route and target[len(here)] == str(len(old.items))
        if not appended or len(new.items) != len(old.items) + 1:
            return False
    return all(
        _same_outside(
            item,
            new.items[index],
            [*here, str(index)],
            target,
            expand_alias=expand_alias,
            in_copy=in_copy,
        )
        for index, item in enumerate(old.items)
    )


def _orders(old_keys: list[str], added: str, new: MappingNode) -> list[list[str]]:
    """The key orders ``new`` may have when it gains the key ``added`` (on the route only).

    A plain mapping gains it at the end. A merged view lists its base keys first, then the
    override-only keys (``troupe.merge``), and so does each merged view nested as a base (chained
    mapping-form includes, bead c3z), so the base keys of every level form a prefix of the view's
    keys. A key added to a base side (``--in-include``, D-8) therefore sits at the end of one of
    those nested base blocks: allowed only where that level's base side ends with ``added``. A key
    added as an override is override-only, so it sits at the very end.
    """
    orders = [[*old_keys, added]]
    view: MappingNode = new
    while isinstance(view, MergedMapping):
        base = unwrap(view.base)
        if not isinstance(base, MappingNode):  # pragma: no cover - the loader checks (D-7)
            break
        if base.entries and base.entries[-1].key == added:
            at = len(base.entries) - 1
            orders.append([*old_keys[:at], added, *old_keys[at:]])
        view = base
    return orders


def _gains_override(old: Node, new: MergedMapping) -> bool:
    """Whether ``new`` is ``old`` with a first override added (the one allowed conversion).

    - ``old`` is a YAML include (scalar or mapping form, no overrides yet): ``new`` must be the
      top of a mapping-form include of the same target (``ref.target.path``), i.e. a converted
      include or a ``$ref``-only mapping that got its first override. The included content
      must be a plain mapping (a merged one already takes overrides without conversion).
    - ``old`` is a plain mapping of an included file: ``new`` must be a nested merge
      (``ref is None``) whose base is that same mapping (same file, same position).

    The caller then compares ``old``'s content with the merged view as with any mapping, so the
    view may differ from it only by the key the ``set`` adds.
    """
    if isinstance(old, YamlInclude):
        return (
            new.ref is not None
            and new.ref.target.path == old.target.path
            and isinstance(content := unwrap(old), MappingNode)
            and not isinstance(content, MergedMapping)
        )
    if not isinstance(old, MappingNode) or new.ref is not None:
        return False
    base = new.base
    return (
        isinstance(base, MappingNode)
        and not isinstance(base, MergedMapping)
        and base.origin.file.path == old.origin.file.path
        and base.origin.start == old.origin.start
    )


def _ref_path(node: MergedMapping) -> Path | None:
    return None if node.ref is None else node.ref.target.path
