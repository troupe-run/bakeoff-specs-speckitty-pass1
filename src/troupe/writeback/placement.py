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

Anchors, aliases and merge keys (step 6; spec FR-003, FR-004, FR-007, A-0, C4, C6; research
R-4, R-6). "Reached through an alias" is decided here and nowhere else:

- An anchored node reached directly (``defaults.model`` under ``defaults: &d``) is an ordinary
  node: the rules above apply, and the write lands at the anchor (FR-003).
- The route scan (``_route_aliases``) finds the first, i.e. outermost, ``AliasNode`` on the
  concrete route to PATH's value (or, for a new key, to its deepest existing ancestor). It is
  the first ``AliasNode`` among ``walk``'s nodes, plus aliases hidden as a side of a step-5
  merged view when that side is the one the route actually takes. This covers PATH itself
  being an alias (C4), an alias above PATH, a new key whose deepest existing ancestor is or lies
  below an alias (C6) and values that come through a merge key ``<<``.
- The write-side scan: a new key written on a side that is not on the route (the override or
  base side of a merged view, or the ``route`` inside an include's holder mapping) is decided
  the same way when that side is or passes an alias (``_on_side``, ``_on_base``).
- One decision (``_through_alias``) for both scans: through ``<<`` is refused (exit 3) with or
  without ``expand_alias``, since merge keys are never written; through a written alias it is
  refused (exit 3, the message mentions ``--expand-alias``) unless ``expand_alias`` is set, in
  which case the placement is ``ExpandAlias`` for that outermost written alias (C7).
- Merge keys are never written (A-0, FR-007): replacing a whole mapping that holds ``<<`` is
  refused (exit 3), and so is creating a new key named ``<<``. A new key beside a ``<<`` goes into
  the written mapping (``MergeKeyMapping.written``), after its last written entry, so the
  ``<<`` line is untouched. Writers never receive a merge-key view (R-4).
- Refusal ordering: after the D-6 ``$ref`` refusal and ``walk``'s path errors, the alias
  decision comes before every other rule, and before ``apply``'s no-op check: a ``set`` through
  an alias whose VALUE equals the current value is still refused (exit 3), because the user
  asked to change a shared path. With ``expand_alias`` and an equal value, ``ExpandAlias`` is
  returned and the applier's no-op check (research R-8) writes nothing.
- An include reference is never inside an anchored node (C3, enforced by the loader), so no
  include reference is reachable only through an alias; ``_peel`` does not descend aliases.

Remote content is read-only (step 7; spec S-4, S-5; research R-7). One message builder,
``remote_refusal``, names the outermost remote include on the route: the first one met from the
root, whose include string is written in a local file. It is used at two checkpoints:

1. Here, in ``place``, right after the D-6 ``$ref`` refusal and ``walk``, and **before** the alias
   decision: an existing PATH whose value comes from remote content (a scalar or collection in a
   remote file, a remote YAML or text include, a merged view with a remote side) is refused, so a
   value reached through an alias inside remote content reports the include line to change, not
   ``--expand-alias``. A new key is not refused here: S-5 makes it a local override.
2. In ``apply.apply_set``, on the files a plan would actually write (list appends and keys inside
   items of remote lists, ``--in-include`` into remote content, ``--expand-alias`` copies).

``fileio.write_files`` refuses any remote ``SourceFile`` as the last net.
"""

from collections.abc import Iterator
from dataclasses import dataclass

from troupe.errors import PathError, WriteRefused
from troupe.location import Location
from troupe.merge import MERGE_KEY, REF_KEY
from troupe.paths import Walk, is_index, unwrap, walk
from troupe.tree import (
    AliasNode,
    MappingNode,
    MergedMapping,
    MergeKeyMapping,
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


@dataclass(frozen=True)
class ExpandAlias:
    """Replace the written alias ``alias`` (at ``slot`` of ``parent``) by a copy of its anchor.

    Returned only with ``expand_alias``, for the outermost alias on the route or write side
    (C7). The alias is always a written ``*name`` (never merge-derived: those are refused) and
    ``parent`` is the concrete collection holding it, in ``alias.origin.file``. Whether the copy
    can be written (flow parent, comment, line position; C9) is the text writer's decision.
    """

    alias: AliasNode
    parent: Collection
    slot: str | int


Placement = (
    ReplaceScalar
    | ReplaceText
    | ReplaceCollection
    | AddKeys
    | AppendItem
    | ConvertInclude
    | ExpandAlias
)


def place(
    root: Node,
    segments: list[str],
    dotted: str,
    *,
    in_include: bool = False,
    expand_alias: bool = False,
) -> Placement:
    """Decide where ``set dotted VALUE`` is written.

    Args:
        root: The configuration as loaded from disk.
        segments: The parsed, non-empty PATH.
        dotted: PATH as the user wrote it, for messages.
        in_include: ``set --in-include``: a new key goes into the included file (contract
            *In-include*). It has no effect on existing values, list appends or refusals (D-9).
        expand_alias: ``set --expand-alias``: a route through a written alias gives
            ``ExpandAlias`` instead of a refusal (R-6). Merge keys are refused either way.

    Refusal order: the D-6 ``$ref`` refusal, ``walk``'s path errors, the remote rule (an
    existing value from remote content, S-4), the alias rule, then every other rule.

    Raises:
        WriteRefused: If PATH has a ``$ref`` segment (D-6), names an existing value that comes
            from remote content (S-4, message from ``remote_refusal``), is reached through an
            alias without ``expand_alias`` or through a merge key ``<<`` (R-6), names a mapping
            holding ``<<`` or would create a key ``<<`` (A-0), the whole value at PATH comes
            from a YAML include, or PATH names a mapping both an include and an override define
            (D-10); exit 3.
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
        remote = _remote_location(found.nodes[-1])
        if remote is not None:  # checkpoint 1 (R-7): before the alias rule
            raise remote_refusal(found, dotted, remote)
    consumed = segments[: len(found.nodes) - 1]
    through = _route_aliases(found, consumed)
    if through is not None:
        alias, depth = through
        return _through_alias(root, alias, _dotted(segments[:depth]), dotted, expand_alias)
    request = _Request(root, dotted, expand_alias)
    if not found.remaining:
        return _existing(root, found.nodes[-1], dotted)
    deepest = unwrap(found.nodes[-1])
    remaining = found.remaining
    prefix = _dotted(consumed)
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
    if MERGE_KEY in remaining:
        raise WriteRefused(
            f"{dotted}: '{MERGE_KEY}' is the merge key; troupe never writes merge keys;"
            " no file changed"
        )
    keys = list(remaining)
    if isinstance(deepest, MergedMapping):  # D-8
        if in_include:
            return _on_base(request, deepest.base, prefix, keys)
        return _on_side(request, deepest.override, prefix, [], keys)
    if in_include:
        return AddKeys(_written(deepest), keys)
    reference = _include_ref(found, deepest)
    if reference is None:
        return AddKeys(_written(deepest), keys)
    include, depth = reference
    route = segments[depth : len(found.nodes) - 1]
    if include.holder is not None:
        # Mapping form. With overrides ``include`` is the ``ref`` of a ``MergedMapping`` whose
        # ``override`` is this same holder, so both cases extend the holder along ``route``,
        # inside the override mappings that already exist there.
        return _on_side(request, include.holder, _dotted(segments[:depth]), route, keys)
    return _convert(root, include, route + keys)


def remote_include_on_route(found: Walk) -> YamlInclude | TextInclude | None:
    """The first include with a remote target on the route ``found.nodes``, from the root.

    Include chains and both sides of merged views are looked through (``_peel``); the ``ref`` of
    a merged view counts as its include. Being the first, it is the outermost remote include, the
    one whose include string is written in a local file (S-4).
    """
    for node in found.nodes:
        for part in _peel(node):
            include = part.ref if isinstance(part, MergedMapping) else part
            if isinstance(include, YamlInclude | TextInclude) and include.target.remote:
                # Nested remote includes lie inside this one, so its own line is local (S-4).
                assert not include.origin.file.remote
                return include
    return None


def remote_refusal(found: Walk, dotted: str, written: Location) -> WriteRefused:
    """The refusal for a ``set`` that would change remote content ``written`` (S-4, R-7).

    The message quotes the outermost remote include on the route exactly as written
    (``origin.source``, quotes included; for the mapping form the ``$ref`` value) with its local
    file and line. Should no remote include be on the route (the root file is always local, so
    this cannot happen) the message names ``written`` instead.
    """
    include = remote_include_on_route(found)
    if include is None:  # pragma: no cover - remote content is only reached through an include
        return WriteRefused(
            f"{dotted}: the change would write remote content {written}; no file changed"
        )
    origin = include.origin
    line = origin.file.text.count("\n", 0, origin.start) + 1
    return WriteRefused(
        f"{dotted}: value comes from remote include {origin.source} ({origin.file.path} line"
        f" {line}); troupe does not change remote content — change that include line instead;"
        " no file changed"
    )


def _remote_location(node: Node) -> Location | None:
    """Where the existing value ``node`` (as found) comes from, if that is remote content.

    Its own file (an alias: the ``*name`` token's file), the target of an include, or a side of a
    merged view (the ``$ref`` include or an included base). A local override's value is local.
    """
    if isinstance(node, YamlInclude | TextInclude) and node.target.remote:
        return node.target.path
    if isinstance(node, MergedMapping):
        for part in _peel(node):
            if not isinstance(part, MergedMapping) and part.origin.file.remote:
                return part.origin.file.path
            if isinstance(part, YamlInclude) and part.target.remote:
                return part.target.path
    file = node.origin.file
    return file.path if file.remote else None


def concrete_parent(root: Node, node: Node) -> tuple[Collection, str | int] | None:
    """Return the concrete collection holding ``node`` and its slot, found by identity.

    Searches depth-first through concrete containers only: plain mappings' entries, sequences'
    items, included roots, both sides of a ``MergedMapping`` *as found* (never its merged
    ``entries``, whose origin may be another file) and the ``written`` mapping of a
    ``MergeKeyMapping`` (never its view). Aliases are values, never containers, so an anchored
    node and everything in it are found at the anchor (R-6). Returns ``None`` if ``node`` is not
    a value inside any collection (it is the root of a document).
    """
    for parent, slot, value in _children(root):
        if value is node:
            return parent, slot
        below = concrete_parent(value, node)
        if below is not None:
            return below
    return None


def _children(node: Node) -> Iterator[tuple[Collection, str | int, Node]]:
    """Yield ``(collection, slot, value)`` for the values directly below ``node``, concretely.

    An ``AliasNode`` yields nothing. The subclass checks come before the ``MappingNode`` one.
    """
    if isinstance(node, MergedMapping):
        for side in (node.base, node.override):
            yield from _children(side)
    elif isinstance(node, MergeKeyMapping):
        # The concrete entries, the ``<<`` entry included (R-4).
        yield from _children(node.written)
    elif isinstance(node, MappingNode):
        for entry in node.entries:
            yield node, entry.key, entry.value
    elif isinstance(node, SequenceNode):
        for index, item in enumerate(node.items):
            yield node, index, item
    elif isinstance(node, YamlInclude):
        yield from _children(node.root)


@dataclass(frozen=True)
class _Request:
    """What the write-side scan needs to decide an alias it meets (``_through_alias``)."""

    root: Node
    dotted: str
    expand_alias: bool


def _dotted(segments: list[str]) -> str:
    return ".".join(segments) or "(root)"


def _written(mapping: MappingNode) -> MappingNode:
    """The concrete mapping new keys go into: ``written`` for a merge-key view (R-4, FR-007)."""
    return mapping.written if isinstance(mapping, MergeKeyMapping) else mapping


def _route_aliases(found: Walk, consumed: list[str]) -> tuple[AliasNode, int] | None:
    """Return the outermost alias on the route to ``found.nodes[-1]`` and its depth, if any.

    The depth ``i`` is the number of segments that lead to the alias (its prefix is
    ``consumed[:i]``). Without merged views on the route this is the first ``AliasNode`` among
    ``found.nodes[1:]``. A step-5 merged view keeps the sides as found, so an alias written as
    one side (``settings: *d`` beside an include) is not among ``found.nodes``; it counts only
    when the route really goes through that side (identity search, ``_aliases_to``).
    """
    aliases = _aliases_to(found.nodes[0], consumed, found.nodes[-1], 0)
    if aliases is None:  # pragma: no cover - the walked node is always on its route
        aliases = [
            (node, depth)
            for depth, node in enumerate(found.nodes[1:], start=1)
            if isinstance(node, AliasNode)
        ]
    return aliases[0] if aliases else None


def _aliases_to(
    node: Node, segments: list[str], target: Node, depth: int
) -> list[tuple[AliasNode, int]] | None:
    """Aliases met, outermost first, going from ``node`` (at ``depth``) down to ``target``.

    ``node`` and ``target`` are as found. Merged views are crossed through their nested views
    when the next value is one, else through whichever side (override first) leads to
    ``target``. Returns ``None`` if ``target`` is not reached along ``segments``.
    """
    if isinstance(node, AliasNode):
        if node is target:
            return [(node, depth)]
        below = _aliases_to(node.target, segments, target, depth)
        return None if below is None else [(node, depth), *below]
    if node is target:
        return []
    if isinstance(node, YamlInclude):
        return _aliases_to(node.root, segments, target, depth)
    if not segments:
        return None
    if isinstance(node, MergedMapping):
        entry = node.get(segments[0])
        if entry is not None and isinstance(entry.value, MergedMapping):
            return _aliases_to(entry.value, segments[1:], target, depth + 1)
        for side in (node.override, node.base):
            below = _aliases_to(side, segments, target, depth)
            if below is not None:
                return below
        return None
    if isinstance(node, MappingNode):
        entry = node.get(segments[0])
        if entry is None:
            return None
        return _aliases_to(entry.value, segments[1:], target, depth + 1)
    if isinstance(node, SequenceNode) and is_index(segments[0]):
        index = int(segments[0])
        if index >= len(node.items):
            return None
        return _aliases_to(node.items[index], segments[1:], target, depth + 1)
    return None


def _through_alias(
    root: Node, alias: AliasNode, prefix: str, dotted: str, expand_alias: bool
) -> ExpandAlias:
    """Decide a write reached through ``alias`` at ``prefix`` (R-6): expand it or refuse.

    Raises:
        WriteRefused: Through a merge key ``<<`` (always), or through a written alias without
            ``expand_alias``; exit 3, messages as in ``contracts/cli.md``.
    """
    if alias.merge:
        source = "an inline mapping" if alias.name is None else f"*{alias.name}"
        lead = f"{dotted}: {prefix} comes through the merge key '{MERGE_KEY}' (from {source})"
        if expand_alias:
            raise WriteRefused(
                f"{lead}; merge keys are never written, so it cannot be expanded; no file changed"
            )
        raise WriteRefused(
            f"{lead}; refusing to change a shared value (use --expand-alias to give it its own"
            " copy); no file changed"
        )
    if not expand_alias:
        file = alias.origin.file
        line = file.text.count("\n", 0, alias.origin.start) + 1
        raise WriteRefused(
            f"{dotted}: {prefix} is the alias *{alias.name} in {file.path} line {line}, shared"
            f" with its anchor &{alias.name}; refusing to change it for every user (use"
            " --expand-alias to give this path its own copy); no file changed"
        )
    found = concrete_parent(root, alias)
    if found is None:  # pragma: no cover - a written alias is always a value in a collection
        raise PathError(f"{dotted}: parent of the alias *{alias.name} is not a collection")
    parent, slot = found
    return ExpandAlias(alias, parent, slot)


def _existing(root: Node, node: Node, dotted: str) -> Placement:
    """Placement for a PATH that exists; ``node`` is the value as found (never an alias)."""
    assert not isinstance(node, AliasNode)  # decided by ``_through_alias`` first
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
    if isinstance(node, MergeKeyMapping):  # A-0, FR-007
        raise WriteRefused(
            f"{dotted}: this mapping uses the merge key '{MERGE_KEY}'; replacing it as a whole"
            " would rewrite the merge key, which troupe never writes; no file changed"
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
    Aliases are not peeled: an include reference is never inside an anchored node (C3), so
    none is reachable only through an alias.
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
    """Yield ``node`` and what it is made of: include chain links and merged sides, outer first.

    An ``AliasNode`` is yielded but not descended: aliases are not include chains (C3).
    """
    yield node
    if isinstance(node, YamlInclude):
        yield from _peel(node.root)
    elif isinstance(node, MergedMapping):
        yield from _peel(node.base)
        yield from _peel(node.override)


def _on_side(
    request: _Request, node: Node, at: str, route: list[str], keys: list[str]
) -> Placement:
    """Add ``route + keys`` on the override side ``node``, inside overrides that already exist.

    ``node`` is an override value as found, at the dotted prefix ``at``: a plain mapping (gets
    the keys), a ``MergedMapping`` (its override side), a mapping-form include (its holder), a
    scalar-form include (converted) or an alias (the write would land in the anchored node, so
    ``_through_alias`` decides). While the next ``route`` key already exists in the override
    mapping, descend into it.
    """
    if isinstance(node, AliasNode):
        return _through_alias(request.root, node, at, request.dotted, request.expand_alias)
    if isinstance(node, MergedMapping):
        return _on_side(request, node.override, at, route, keys)
    if isinstance(node, YamlInclude):
        if node.holder is None:
            return _convert(request.root, node, route + keys)
        node = node.holder
    assert isinstance(node, MappingNode)  # an override side always unwraps to a mapping
    entry = node.get(route[0]) if route else None
    if entry is None:
        return AddKeys(_written(node), route + keys)
    return _on_side(request, entry.value, f"{at}.{route[0]}", route[1:], keys)


def _on_base(request: _Request, node: Node, at: str, keys: list[str]) -> Placement:
    """``in_include`` under a merged mapping: the innermost included file that defines it (D-8).

    A base side that is an alias would put the key into the anchored node: ``_through_alias``.
    """
    if isinstance(node, AliasNode):
        return _through_alias(request.root, node, at, request.dotted, request.expand_alias)
    if isinstance(node, YamlInclude):
        return _on_base(request, node.root, at, keys)
    if isinstance(node, MergedMapping):
        return _on_base(request, node.base, at, keys)
    assert isinstance(node, MappingNode)  # a base side always unwraps to a mapping
    return AddKeys(_written(node), keys)


def _convert(root: Node, include: YamlInclude, keys: list[str]) -> ConvertInclude:
    """Convert the scalar-form ``include`` where it is written and add ``keys`` (FR-005, D-4)."""
    found = concrete_parent(root, include)
    if found is None:
        return ConvertInclude(include, None, None, keys)
    parent, slot = found
    return ConvertInclude(include, parent, slot, keys)
