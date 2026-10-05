"""Where a ``set`` is written: the one place that decides it (TROUPE-007).

Contract ("Where the change is written", with *Overrides* and *In-include*):

- An existing value is changed in the file that contains it (FR-010): an overridden value in its
  override, any other value in the file it comes from. A scalar becomes ``ReplaceScalar``, a
  mapping or list ``ReplaceCollection`` and a text include ``ReplaceText`` (the target file's
  content is rewritten; see ``troupe.writeback.apply``).
- A value whose whole value comes from a YAML include (either form, with or without overrides)
  is never replaced (FR-012, exit 3); a path *inside* the included file is an ordinary path.
- *Overrides* (replaces step-1 rule 2): a new key whose deepest existing ancestor comes from an
  included file is written as an override in the **including file**, the file holding the
  include reference nearest that ancestor. A scalar-form include reference is first converted
  to mapping form (``ConvertInclude``); a mapping-form one gets the key in its holder mapping
  (``AddKeys``), inside an existing override mapping where one exists (FR-005, FR-007).
- *In-include*: with ``in_include`` a new key goes into the file holding its deepest existing
  ancestor (the step-1 rule, FR-010), i.e. the innermost included file that defines it.
- Lists: appending an item (a final index equal to the list's length; larger exits 5) or adding
  a key inside a list item is written in the file that holds the list (FR-009).

Algorithm for a new key (research R-3). Let D be the deepest existing ancestor mapping:

1. D is a merged view (both an included file and an override define it): the key goes to D's
   override side, or with ``in_include`` to its base side (``_on_side`` / ``_on_base``).
2. D is concrete and ``in_include`` is set, or D is in the root file: ``AddKeys(D, ...)``.
3. Otherwise find the nearest include reference R whose target is D's file (``_include_ref``).
   A list between R and D keeps the key in D's file. Else the key, prefixed by the route from R
   down to D, goes into R's holder mapping (descending existing override mappings) or, for a
   scalar-form R, into a ``ConvertInclude``.

Every placement carries concrete collections only, never a ``MergedMapping``: the parent of an
existing node is found by identity among the concrete sides (``concrete_parent``), never read
from a merged view, whose origin may be another file.

Choices made where the contract is silent (TROUPE-002, TROUPE-008):

- D-6: a PATH with a ``$ref`` segment is refused (exit 3): writing one would silently turn a
  mapping into an include or retarget one.
- D-8: a new key under a mapping both an include and an override define goes into that override
  mapping; with ``in_include`` into the innermost included file that defines it.
- D-10: replacing a mapping both an included file and an override define is refused (exit 3):
  writing either side alone would not read back as the value asked for.
- Nested includes: the target is the file holding the **nearest** include reference (product
  owner decision DM 01M46FYYFFXXZE893KWDP2WJCW).
- A key with an empty value (``key:``) holds a null scalar, not a mapping: a path through it is
  a path through a scalar (exit 5), never a request to turn the null into a mapping.
- Missing segments are only ever created as mapping keys. A digit-only missing segment below a
  mapping would need either a mapping with a digit-only key (out of contract, C-004) or a new
  list, which the contract does not describe, so it exits 5.
"""

from collections.abc import Iterator
from dataclasses import dataclass

from troupe.errors import PathError, WriteRefused
from troupe.merge import REF_KEY
from troupe.paths import Walk, is_index, unwrap, walk
from troupe.tree import (
    MappingNode,
    MergedMapping,
    Node,
    ScalarNode,
    SequenceNode,
    TextInclude,
    YamlInclude,
)
from troupe.writeback.scalars import Context

Collection = MappingNode | SequenceNode


@dataclass(frozen=True)
class ReplaceScalar:
    """Replace the existing scalar ``node`` at ``slot`` of ``parent``.

    Attributes:
        parent: The concrete collection holding the scalar (in the scalar's file).
        slot: Its key (mapping) or index (sequence).
        node: The scalar.
        context: ``"flow"`` if ``parent`` is a flow collection, else ``"block"``.
    """

    parent: Collection
    slot: str | int
    node: ScalarNode
    context: Context


@dataclass(frozen=True)
class ReplaceText:
    """Rewrite the target file of the text include ``node``."""

    node: TextInclude


@dataclass(frozen=True)
class ReplaceCollection:
    """Replace the existing mapping or list ``node`` at ``slot`` of the concrete ``parent``."""

    parent: Collection
    slot: str | int
    node: Collection


@dataclass(frozen=True)
class AddKeys:
    """Add ``keys[0]`` to ``mapping``; ``keys[1:]`` are intermediate mappings, the last the leaf.

    ``mapping`` is concrete; the new text goes into ``mapping.origin.file``: the file of the
    deepest existing ancestor (step 1, ``in_include``, list items) or a holder or override mapping
    in the including file (*Overrides*).
    """

    mapping: MappingNode
    keys: list[str]


@dataclass(frozen=True)
class AppendItem:
    """Append a new last item to ``sequence`` (FR-009)."""

    sequence: SequenceNode


@dataclass(frozen=True)
class ConvertInclude:
    """Convert scalar-form ``include`` (in ``parent`` at ``slot``) to mapping form; add ``keys``.

    Attributes:
        include: The scalar-form include; the edit goes into ``include.origin.file``.
        parent: The concrete collection holding it; ``None`` when the include is the whole
            document of its file.
        slot: Its key (mapping) or index (sequence, D-4); ``None`` with ``parent``.
        keys: As for ``AddKeys``, added as overrides after the new ``$ref`` entry.
    """

    include: YamlInclude
    parent: Collection | None
    slot: str | int | None
    keys: list[str]


Placement = ReplaceScalar | ReplaceText | ReplaceCollection | AddKeys | AppendItem | ConvertInclude


def place(root: Node, segments: list[str], dotted: str, *, in_include: bool = False) -> Placement:
    """Decide where ``set dotted VALUE`` is written.

    Args:
        root: The configuration as loaded from disk.
        segments: The parsed, non-empty PATH.
        dotted: PATH as the user wrote it, for messages.
        in_include: ``set --in-include``: a new key goes into the included file (contract
            *In-include*). It has no effect on existing values, list appends or refusals (D-9).

    Raises:
        WriteRefused: If PATH has a ``$ref`` segment (D-6), the whole value at PATH comes from a
            YAML include, or PATH names a mapping both an include and an override define (D-10);
            exit 3.
        PathError: If PATH runs through a scalar, null or text include, uses a non-index segment
            on a list, uses an index larger than the list's length, or needs a missing segment
            that cannot be created (exit 5).
    """
    if REF_KEY in segments:
        raise WriteRefused(
            f"{dotted}: '{REF_KEY}' is not a setting; it names an include (no file changed)"
        )
    found = walk(root, segments)
    if not found.remaining:
        return _existing(root, found.nodes[-1], dotted)
    deepest = unwrap(found.nodes[-1])
    remaining = found.remaining
    prefix = ".".join(segments[: len(segments) - len(remaining)]) or "(root)"
    if isinstance(deepest, SequenceNode):
        # ``walk`` only stops at a list on an index >= its length.
        index = int(remaining[0])
        if index == len(deepest.items) and len(remaining) == 1:
            return AppendItem(deepest)
        if index > len(deepest.items):
            raise PathError(
                f"{dotted}: index {index} is out of range for {prefix}"
                f" (length {len(deepest.items)}; only index {len(deepest.items)} appends)"
            )
        raise PathError(f"path not found: {dotted} (no {prefix}.{remaining[0]})")
    if not isinstance(deepest, MappingNode):  # pragma: no cover - ``walk`` raises first
        raise PathError(f"{dotted}: {prefix} is not a mapping")
    digit = next((segment for segment in remaining if is_index(segment)), None)
    if digit is not None:
        raise PathError(
            f"path not found: {dotted} (no {prefix}.{remaining[0]}; a missing list index"
            f" '{digit}' cannot be created)"
        )
    keys = list(remaining)
    if isinstance(deepest, MergedMapping):  # D-8
        if in_include:
            return _on_base(deepest.base, keys)
        return _on_side(root, deepest.override, [], keys)
    if in_include:
        return AddKeys(deepest, keys)
    reference = _include_ref(found, deepest)
    if reference is None:
        return AddKeys(deepest, keys)
    include, depth = reference
    route = segments[depth : len(found.nodes) - 1]
    if include.holder is not None:
        # Mapping form. With overrides ``include`` is the ``ref`` of a ``MergedMapping`` whose
        # ``override`` is this same holder, so both cases extend the holder along ``route``,
        # inside the override mappings that already exist there.
        return _on_side(root, include.holder, route, keys)
    return _convert(root, include, route + keys)


def concrete_parent(root: Node, node: Node) -> tuple[Collection, str | int] | None:
    """Return the concrete collection holding ``node`` and its slot, found by identity.

    Searches depth-first through concrete containers only: plain mappings' entries, sequences'
    items, included roots, and both sides of a ``MergedMapping`` *as found* (never its merged
    ``entries``, whose origin may be another file). Returns ``None`` if ``node`` is not a value
    inside any collection (it is the root of a document).
    """
    for parent, slot, value in _children(root):
        if value is node:
            return parent, slot
        below = concrete_parent(value, node)
        if below is not None:
            return below
    return None


def _children(node: Node) -> Iterator[tuple[Collection, str | int, Node]]:
    """Yield ``(collection, slot, value)`` for the values directly below ``node``, concretely."""
    if isinstance(node, MergedMapping):
        for side in (node.base, node.override):
            yield from _children(side)
    elif isinstance(node, MappingNode):
        for entry in node.entries:
            yield node, entry.key, entry.value
    elif isinstance(node, SequenceNode):
        for index, item in enumerate(node.items):
            yield node, index, item
    elif isinstance(node, YamlInclude):
        yield from _children(node.root)


def _existing(root: Node, node: Node, dotted: str) -> Placement:
    """Placement for a PATH that exists; ``node`` is the value as found."""
    if isinstance(node, YamlInclude):
        raise WriteRefused(
            f"{dotted}: value comes from include {node.target.path}; refusing to replace it"
            " (change a path inside it instead); no file changed"
        )
    if isinstance(node, MergedMapping):
        if node.ref is not None:
            raise WriteRefused(
                f"{dotted}: value comes from include {node.ref.target.path} with overrides;"
                " refusing to replace it (change a path inside it instead); no file changed"
            )
        base_file = unwrap(node.base).origin.file.path
        override_file = unwrap(node.override).origin.file.path
        raise WriteRefused(
            f"{dotted}: this mapping is defined both by {base_file} and by overrides in"
            f" {override_file}; replacing it as a whole is refused; no file changed"
        )
    if isinstance(node, TextInclude):
        return ReplaceText(node)
    found = concrete_parent(root, node)
    if found is None:  # pragma: no cover - a non-empty PATH always has a parent
        raise PathError(f"{dotted}: parent of the value is not a collection")
    parent, slot = found
    if isinstance(node, ScalarNode):
        return ReplaceScalar(parent, slot, node, "flow" if parent.flow else "block")
    return ReplaceCollection(parent, slot, node)


def _include_ref(found: Walk, deepest: MappingNode) -> tuple[YamlInclude, int] | None:
    """Return the nearest include reference of the concrete ``deepest`` and its depth, if any.

    Contract *Overrides*: a new key whose deepest existing ancestor comes from an included file
    is written "in the including file", the file holding the include reference nearest that
    ancestor (for nested includes possibly itself an included file; product owner decision
    DM 01M46FYYFFXXZE893KWDP2WJCW). "A new key inside a list item is written in the file that
    holds the list."

    Candidates are the ``YamlInclude`` nodes on the route (``found.nodes[0..k]``, include chains
    and both sides of merged mappings peeled) whose ``target`` is ``deepest``'s file (identity:
    the loader shares one ``SourceFile`` per path). The deepest one wins; at the same depth the
    innermost of a chain. Returns ``None`` when there is none (``deepest`` is in the root file)
    or when a list lies between it and ``deepest`` (list rule: the key stays in that file).
    """
    file = deepest.origin.file
    k = len(found.nodes) - 1
    for depth in range(k, -1, -1):
        matches = [
            node
            for node in _peel(found.nodes[depth])
            if isinstance(node, YamlInclude) and node.target is file
        ]
        if matches:
            if any(isinstance(unwrap(node), SequenceNode) for node in found.nodes[depth:k]):
                return None
            return matches[-1], depth
    return None


def _peel(node: Node) -> Iterator[Node]:
    """Yield ``node`` and what it is made of: include chain links and merged sides, outer first."""
    yield node
    if isinstance(node, YamlInclude):
        yield from _peel(node.root)
    elif isinstance(node, MergedMapping):
        yield from _peel(node.base)
        yield from _peel(node.override)


def _on_side(root: Node, node: Node, route: list[str], keys: list[str]) -> Placement:
    """Add ``route + keys`` on the override side ``node``, inside overrides that already exist.

    ``node`` is an override value as found: a plain mapping (gets the keys), a ``MergedMapping``
    (its override side), a mapping-form include (its holder) or a scalar-form include (converted).
    While the next ``route`` key already exists in the override mapping, descend into it.
    """
    if isinstance(node, MergedMapping):
        return _on_side(root, node.override, route, keys)
    if isinstance(node, YamlInclude):
        if node.holder is None:
            return _convert(root, node, route + keys)
        node = node.holder
    assert isinstance(node, MappingNode)  # an override side always unwraps to a mapping
    entry = node.get(route[0]) if route else None
    if entry is None:
        return AddKeys(node, route + keys)
    return _on_side(root, entry.value, route[1:], keys)


def _on_base(node: Node, keys: list[str]) -> Placement:
    """``in_include`` under a merged mapping: the innermost included file that defines it (D-8)."""
    content = unwrap(node)
    if isinstance(content, MergedMapping):
        return _on_base(content.base, keys)
    assert isinstance(content, MappingNode)  # a base side always unwraps to a mapping
    return AddKeys(content, keys)


def _convert(root: Node, include: YamlInclude, keys: list[str]) -> ConvertInclude:
    """Convert the scalar-form ``include`` where it is written and add ``keys`` (FR-005, D-4)."""
    found = concrete_parent(root, include)
    if found is None:
        return ConvertInclude(include, None, None, keys)
    parent, slot = found
    return ConvertInclude(include, parent, slot, keys)
