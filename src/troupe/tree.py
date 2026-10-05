"""SourceTree node types: the merged configuration, where every node knows its source span.

The tree is rebuilt from the files on disk by ``troupe.loader.load`` for every command. Each node
carries an ``Origin``: the ``SourceFile`` that contains its bytes and the code-point span
``file.text[start:end]`` it was parsed from. A node reached through a YAML include belongs to the
included file. This module is stdlib-only so that every other module can depend on it.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Scalar = str | int | float | bool | None
ScalarStyle = Literal["plain", "single", "double", "literal", "folded"]


@dataclass(eq=False)
class SourceFile:
    """One file read from disk (identity semantics: one object per resolved path per load).

    Attributes:
        path: Absolute, resolved path.
        text: Strict UTF-8 decoded text with original newlines; a leading BOM stays as U+FEFF, so
            parser indices and ``text`` agree character for character (research R-14).
    """

    path: Path
    text: str


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


@dataclass
class ScalarNode:
    """A scalar; ``value`` is resolved per the YAML 1.2 core schema (plain) or a string."""

    origin: Origin
    value: Scalar
    style: ScalarStyle


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

    def get(self, key: str) -> MappingEntry | None:
        """Return the entry whose key is ``key``, or ``None``."""
        return next((entry for entry in self.entries if entry.key == key), None)


@dataclass
class SequenceNode:
    """An ordered list (block or flow)."""

    origin: Origin
    flow: bool
    items: list["Node"]


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


# A plain union (not a ``type`` alias) so that ``isinstance(x, Node)`` works. ``MergedMapping`` is
# a ``MappingNode`` subclass, so it is already covered and needs no member of its own (R-1).
Node = ScalarNode | MappingNode | SequenceNode | YamlInclude | TextInclude
