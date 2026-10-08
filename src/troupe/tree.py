"""SourceTree node types: the merged configuration, where every node knows its source span.

The tree is rebuilt from the files on disk by ``troupe.loader.load`` for every command. Each node
carries an ``Origin``: the ``SourceFile`` that contains its bytes and the code-point span
``file.text[start:end]`` it was parsed from. A node reached through a YAML include belongs to the
included file. This module imports only the stdlib and the dependency-free
``troupe.location``, so that every other module can depend on it.

Anchors, aliases and merge keys (spec A-0, C1; research R-3, R-4):

- An anchored scalar, mapping or list is one ordinary node with ``anchor`` set (the ``&name``
  token and the merged path where it is loaded). It is converted once and shared: every alias of
  it refers to that same object, so writers and the verifier may compare it with ``is``.
- ``AliasNode`` stands where an alias is written (``*name``), or where a value arrives through a
  merge key ``<<`` (``merge=True``). It is transparent to readers (``paths.unwrap`` follows
  ``target``) and is never a concrete container: writers never look inside it.
- ``MergeKeyMapping`` is a mapping holding ``<<``: ``entries`` is the merged view (written keys
  plus merged-in keys, each wrapped in a merge-derived ``AliasNode``); ``written`` is the
  concrete mapping as written, ``<<`` entry included. Writers only ever receive ``written``.
"""

from dataclasses import dataclass, field
from typing import Literal

from troupe.location import Location, Url

Scalar = str | int | float | bool | None
ScalarStyle = Literal["plain", "single", "double", "literal", "folded"]


@dataclass(eq=False)
class SourceFile:
    """One source read by a load: a file on disk or fetched remote content (research R-1).

    Identity semantics: one object per location per load.

    Attributes:
        path: Where the source lives: an absolute, resolved ``Path`` for a file on disk, or a
            ``Url`` for remote content, which troupe never writes (spec S-4).
        text: Strict UTF-8 decoded text with original newlines; a leading BOM stays as U+FEFF, so
            parser indices and ``text`` agree character for character (research R-14).
    """

    path: Location
    text: str

    @property
    def remote(self) -> bool:
        """Whether this is remote content (read-only; never watched or written)."""
        return isinstance(self.path, Url)


@dataclass(frozen=True)
class Origin:
    """Where a node's bytes live: ``file.text[start:end]`` (code-point indices, end exclusive).

    Spans are recorded exactly as the parser reports them; see ``troupe.yamlcore`` for where the
    ends of block scalars, block collections and empty values land.
    """

    file: SourceFile
    start: int
    end: int

    @property
    def source(self) -> str:
        """The source text the span covers."""
        return self.file.text[self.start : self.end]


@dataclass(frozen=True)
class Anchor:
    """An anchor written on a node (spec C1; research R-3).

    Attributes:
        name: The anchor name, without ``&``.
        origin: Exactly the ``&name`` token.
        path: The merged path where the anchored node is loaded (the verifier's identity rule).
    """

    name: str
    origin: Origin
    path: tuple[str, ...]


@dataclass
class ScalarNode:
    """A scalar; ``value`` is resolved per the YAML 1.2 core schema (plain) or a string.

    ``literal`` is the span of a ``!literal`` tag written on it (the tag token and the blanks
    after it, up to ``origin.start``), else ``None``; ``value`` is then always the scalar's text
    as a ``str`` (spec S-10; research R-5). Writers keep or drop the tag by this span (R-8).
    """

    origin: Origin
    value: Scalar
    style: ScalarStyle
    anchor: Anchor | None = field(default=None, kw_only=True)
    literal: Origin | None = field(default=None, kw_only=True)


@dataclass
class MappingEntry:
    """One ``key: value`` pair; ``key`` is the key text as written (unescaped)."""

    key: str
    key_origin: Origin
    key_style: ScalarStyle
    value: "Node"


@dataclass
class MappingNode:
    """An ordered mapping (block or flow)."""

    origin: Origin
    flow: bool
    entries: list[MappingEntry]
    anchor: Anchor | None = field(default=None, kw_only=True)

    def get(self, key: str) -> MappingEntry | None:
        """Return the entry whose key is ``key``, or ``None``."""
        return next((entry for entry in self.entries if entry.key == key), None)


@dataclass
class SequenceNode:
    """An ordered list (block or flow)."""

    origin: Origin
    flow: bool
    items: list["Node"]
    anchor: Anchor | None = field(default=None, kw_only=True)


@dataclass
class YamlInclude:
    """A ``file:`` string naming a ``.yml``/``.yaml`` target whose content is embedded here.

    ``origin`` is the span of the ``file:`` string in the including file; ``root`` is the
    target's converted root node (an empty mapping for an empty target). ``holder`` is the
    mapping that holds this include as ``$ref`` (mapping form, with or without overrides);
    ``None`` for the scalar form (FR-001). It is excluded from ``==`` and ``repr`` because the
    holder's ``$ref`` entry points back at this include.
    """

    origin: Origin
    target: SourceFile
    root: "Node"
    holder: "MappingNode | None" = field(default=None, compare=False, repr=False)


@dataclass
class TextInclude:
    """A ``file:`` string naming any other target; its value is ``target.text`` exactly.

    ``holder`` is the mapping that holds this include as ``$ref`` (mapping form; a text include
    never has overrides); ``None`` for the scalar form. Excluded from ``==`` and ``repr`` as for
    ``YamlInclude``.
    """

    origin: Origin
    target: SourceFile
    holder: "MappingNode | None" = field(default=None, compare=False, repr=False)


@dataclass(kw_only=True)
class MergedMapping(MappingNode):
    """A mapping-form include with overrides, or a mapping both sides of a merge define.

    ``entries`` is the merged view (see ``troupe.merge``). ``base`` and ``override`` are the two
    sides *as found* (a plain mapping, a ``YamlInclude`` or another ``MergedMapping``). ``ref`` is
    the ``$ref`` include at the top of a mapping-form include, else ``None``; ``override`` is then
    the holder mapping as written (its ``$ref`` entry is not in ``entries``).
    ``origin`` is the override side's origin; ``flow`` is the base side's (research R-1).
    Never write through a merged view: writers resolve a concrete side (``writeback.placement``).
    Construct with keywords only.
    """

    base: "Node"
    override: "Node"
    ref: "YamlInclude | None"


@dataclass(kw_only=True)
class MergeKeyMapping(MappingNode):
    """A mapping holding a merge key ``<<`` (spec A-0; research R-4; built by ``merge.merge_keys``).

    ``entries`` is the view: ``written``'s entries in order, with the ``<<`` entry replaced in
    place by the merged-in entries no written key (and no earlier source) shadows; each merged-in
    value is a merge-derived ``AliasNode``. ``written`` is the concrete mapping as written,
    including its ``<<`` entry; ``origin`` and ``flow`` are ``written``'s.
    Never write through the view: writers resolve to ``written``. Construct with keywords only.
    """

    written: MappingNode


@dataclass(eq=False)
class AliasNode:
    """A value reached through an alias: a written ``*name``, or a merge key ``<<`` (R-3).

    Transparent to readers (``paths.unwrap`` follows ``target``); never a concrete container,
    so writers never look inside it. Identity semantics, like ``SourceFile``.

    Attributes:
        origin: The ``*name`` token. For a merge-derived node: the alias token inside the ``<<``
            value, or the ``<<`` key's span for an inline ``<<`` mapping.
        name: The alias name (without ``*``); ``None`` only for an inline ``<<`` mapping.
        target: The node reached. For a written alias the anchored node itself
            (``target is anchored``); for a merge-derived one the merged-in entry's value.
        anchored: The anchored node; ``None`` for an inline ``<<`` mapping.
        merge: ``True`` when reached through ``<<`` (never expanded).
        written: For a merge-derived node, the written alias inside the ``<<`` value it comes
            from, if any; ``None`` for a written alias.
    """

    origin: Origin
    name: str | None
    target: "Node"
    anchored: "Node | None"
    merge: bool = False
    written: "AliasNode | None" = None


# A plain union (not a ``type`` alias) so that ``isinstance(x, Node)`` works. ``MergedMapping`` is
# a ``MappingNode`` subclass, so it is already covered and needs no member of its own (R-1);
# so is ``MergeKeyMapping`` (R-4).
Node = ScalarNode | MappingNode | SequenceNode | YamlInclude | TextInclude | AliasNode
