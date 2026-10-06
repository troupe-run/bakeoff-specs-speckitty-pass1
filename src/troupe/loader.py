"""Build the SourceTree from the files on disk: root file plus recursive includes (FR-007, FR-008).

Files are read fresh on every call (no caching across runs), as bytes decoded with strict UTF-8,
never in text mode, so CRLF and a BOM stay in ``SourceFile.text`` and parser indices match it
(research R-05, R-14).

Include rule (the one place it is decided): a string value of any style whose text starts with
``file:`` names a target relative to the directory of the (resolved) file containing it. A target
ending ``.yml``/``.yaml`` (case-sensitive) is a ``YamlInclude`` whose content is embedded in
place; any other target is a ``TextInclude`` whose value is the file's exact text. Mapping keys
are never includes.

Mapping form (FR-001 to FR-003): a mapping with a ``$ref`` key (any key quoting) is an include
whose include string is the ``$ref`` value; its other keys are *overrides*. A ``$ref`` key is
never data (spec D-1). With no overrides the include node itself is the value, exactly as in the
scalar form (YAML or text target). With overrides the value is ``merge.deep_merge`` of the
included content and the holder mapping. The target resolves by the rule above (same relative
path, missing-target, directory and cycle rules); the include node's ``holder`` is the mapping
that holds it. Three more load errors, each naming the file and path:

- the ``$ref`` value is not a string starting ``file:`` (D-1);
- overrides on a non-YAML target (contract *Overrides*);
- overrides on a YAML target whose content is a list or scalar, not a mapping (D-7; an empty
  target is an empty mapping and accepts overrides).

Anchors and aliases (spec C1, C2, C3; research R-3, R-5): files are composed with
``allow_anchors=True``, so tags, undefined aliases and recursive aliases are refused by
``yamlcore.compose`` (C2, FR-002). An anchored node is converted once, gets its ``Anchor`` and is
recorded in a registry keyed by the raw node's ``id``; an alias becomes an ``AliasNode`` whose
``target`` (and ``anchored``) is that very node. Anchors precede their aliases in a document, so
the anchored node is always converted first. Anchors are per file: the registry is scoped to one
``_load_yaml`` call, and an alias in an included file can only name an anchor of that file.
C3 refusals, each naming the file and line:

- an anchor on an include reference (an include string or a ``$ref`` mapping) or on a value
  containing one at any depth: aliasing would make one include reachable from several paths;
- an anchored mapping key, or an alias used as a key: keys must stay plain names.

Merge keys (spec A-0, C13; research R-4): a key ``<<`` written plain (``'<<'`` is an ordinary
key) is a merge key. Its value must be an alias of a mapping, a mapping, or a list of those; the
mapping holding it becomes a ``merge.merge_keys`` view (``MergeKeyMapping``) over the concrete
mapping as written, ``<<`` entry included. A ``<<`` beside ``$ref`` in one mapping is refused
(C13). Both refusals name the file, path and line.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Final

from troupe import yamlcore
from troupe.errors import LoadError
from troupe.merge import MERGE_KEY, REF_KEY, MergeSource, deep_merge, merge_keys
from troupe.paths import unwrap
from troupe.tree import (
    AliasNode,
    Anchor,
    MappingEntry,
    MappingNode,
    MergeKeyMapping,
    Node,
    Origin,
    ScalarNode,
    SequenceNode,
    SourceFile,
    TextInclude,
    YamlInclude,
)
from troupe.yamlcore import RawAlias, RawMapping, RawNode, RawScalar, RawSequence

INCLUDE_PREFIX = "file:"
YAML_SUFFIXES = (".yml", ".yaml")
BOM = "\ufeff"
# Longest ``$ref`` value source text quoted in a D-1 message before it is cut with "...".
SHOWN_MAX: Final = 40


def read_source(path: Path) -> SourceFile:
    """Read ``path`` as strict UTF-8 without newline translation.

    Raises:
        LoadError: If the file cannot be read or is not valid UTF-8; the message names the file.
    """
    resolved = path.resolve()
    try:
        data = resolved.read_bytes()
    except OSError as err:
        raise LoadError(f"cannot read {resolved}: {err.strerror or err}") from err
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as err:
        raise LoadError(f"cannot read {resolved}: not valid UTF-8 at byte {err.start}") from err
    return SourceFile(path=resolved, text=text)


def load(config_file: Path, overrides: Mapping[Path, str] | None = None) -> Node:
    """Load the configuration rooted at ``config_file`` into a SourceTree.

    Args:
        config_file: The theatre's root configuration file.
        overrides: Text to use instead of the disk contents, keyed by (resolved) file path. Used
            to re-load edited texts in memory and verify an edit before writing (research R-17).

    Returns:
        The root node. An empty document yields an empty block ``MappingNode``.

    Raises:
        LoadError: For unreadable or undecodable files, invalid YAML, a missing include target or
            an include cycle; the message names the file(s).
    """
    return _Loader(overrides or {}).load_root(config_file)


def dotted(segments: list[str]) -> str:
    """Render path segments for messages (``(root)`` for the empty path)."""
    return ".".join(segments) if segments else "(root)"


class _Loader:
    """State of one load: the SourceFile cache, the stack of YAML files being expanded and the
    anchored nodes of the file being converted (``id(raw node) -> node``; module rule).
    """

    def __init__(self, overrides: Mapping[Path, str]) -> None:
        self._overrides = {path.resolve(): text for path, text in overrides.items()}
        self._files: dict[Path, SourceFile] = {}
        self._stack: list[Path] = []
        self._anchored: dict[int, Node] = {}

    def load_root(self, config_file: Path) -> Node:
        return self._load_yaml(self._source(config_file), [])

    def _source(self, path: Path) -> SourceFile:
        resolved = path.resolve()
        cached = self._files.get(resolved)
        if cached is None:
            override = self._overrides.get(resolved)
            if override is None:
                cached = read_source(resolved)
            else:
                cached = SourceFile(path=resolved, text=override)
            self._files[resolved] = cached
        return cached

    def _load_yaml(self, file: SourceFile, segments: list[str]) -> Node:
        if file.path in self._stack:
            chain = [*self._stack[self._stack.index(file.path) :], file.path]
            raise LoadError(
                f"include cycle at {dotted(segments)}: {' -> '.join(str(p) for p in chain)}"
            )
        self._stack.append(file.path)
        including_file_anchors = self._anchored
        self._anchored = {}  # anchors are per file (and per document)
        try:
            raw = yamlcore.compose(file.text, str(file.path), allow_anchors=True)
            if raw is None:
                start = 1 if file.text.startswith(BOM) else 0
                return MappingNode(origin=Origin(file, start, start), flow=False, entries=[])
            return self._convert(raw, file, segments)
        finally:
            self._anchored = including_file_anchors
            self._stack.pop()

    def _convert(self, raw: RawNode, file: SourceFile, segments: list[str]) -> Node:
        """Convert ``raw``: an alias shares its anchored node; an anchored node is registered."""
        if isinstance(raw, RawAlias):
            anchored = self._anchored.get(id(raw.target))
            assert anchored is not None  # anchors precede their aliases (compose checks)
            return AliasNode(
                origin=Origin(file, raw.start, raw.end),
                name=raw.name,
                target=anchored,
                anchored=anchored,
            )
        if raw.anchor is None:
            return self._content(raw, file, segments)
        if _holds_include(raw):
            raise LoadError(
                f"cannot load {file.path}: anchor &{raw.anchor.name} at line"
                f" {_line(file, raw.anchor.start)} is on an include reference (or a value"
                " containing one); anchors may not share includes"
            )
        node = self._content(raw, file, segments)
        # C3 (checked above) leaves only scalars, mappings and lists to be anchored.
        assert isinstance(node, ScalarNode | MappingNode | SequenceNode)
        node.anchor = Anchor(
            raw.anchor.name,
            Origin(file, raw.anchor.start, raw.anchor.end),
            tuple(segments),
        )
        self._anchored[id(raw)] = node
        return node

    def _content(
        self, raw: RawScalar | RawMapping | RawSequence, file: SourceFile, segments: list[str]
    ) -> Node:
        """Convert a scalar, mapping or list (its anchor, if any, is ``_convert``'s business)."""
        origin = Origin(file, raw.start, raw.end)
        if isinstance(raw, RawScalar):
            value = yamlcore.resolve_plain(raw.text) if raw.style == "plain" else raw.text
            if isinstance(value, str) and value.startswith(INCLUDE_PREFIX):
                return self._include(value[len(INCLUDE_PREFIX) :], origin, segments)
            return ScalarNode(origin=origin, value=value, style=raw.style)
        if isinstance(raw, RawMapping):
            return self._mapping(raw, origin, segments)
        items = [
            self._convert(item, file, [*segments, str(index)])
            for index, item in enumerate(raw.items)
        ]
        return SequenceNode(origin=origin, flow=raw.flow, items=items)

    def _mapping(self, raw: RawMapping, origin: Origin, segments: list[str]) -> Node:
        """Convert a mapping: plain, with a merge key, or a mapping-form include (module rule)."""
        file = origin.file
        ref_index = next(
            (
                index
                for index, (raw_key, _) in enumerate(raw.pairs)
                if isinstance(raw_key, RawScalar) and raw_key.text == REF_KEY
            ),
            None,
        )
        merge_index = next(
            (index for index, (raw_key, _) in enumerate(raw.pairs) if _is_merge_key(raw_key)),
            None,
        )
        if merge_index is not None and ref_index is not None:
            line = _line(file, raw.pairs[merge_index][0].start)
            raise LoadError(
                f"cannot load {file.path}: {dotted(segments)}: a merge key '{MERGE_KEY}' cannot"
                f" be combined with '{REF_KEY}' (line {line})"
            )
        if merge_index is not None:
            return self._merge_mapping(raw, origin, segments, merge_index)
        if ref_index is None:
            return MappingNode(
                origin=origin, flow=raw.flow, entries=self._entries(raw, file, segments)
            )
        include = self._ref_include(raw.pairs[ref_index][1], file, segments)
        # The ``$ref`` value is converted once (above) and reused: converting it again would load
        # the target twice and confuse cycle detection.
        holder = MappingNode(
            origin=origin,
            flow=raw.flow,
            entries=self._entries(raw, file, segments, converted={ref_index: include}),
        )
        include.holder = holder
        if len(holder.entries) == 1:
            return include  # no overrides: exactly the scalar form (FR-001)
        if isinstance(include, TextInclude):
            raise LoadError(
                f"cannot load {file.path}: {dotted(segments)}: overrides need a YAML include,"
                f" but {include.target.path} is not a .yml/.yaml file"
            )
        content = unwrap(include.root)
        if not isinstance(content, MappingNode):
            kind = "list" if isinstance(content, SequenceNode) else "scalar"
            raise LoadError(
                f"cannot load {file.path}: {dotted(segments)}: cannot override keys of"
                f" {include.target.path}: its content is a {kind}, not a mapping"
            )
        return deep_merge(include, holder, ref=include, origin=origin, flow=content.flow)

    def _merge_mapping(
        self, raw: RawMapping, origin: Origin, segments: list[str], merge_index: int
    ) -> MergeKeyMapping:
        """Convert a mapping holding a merge key ``<<`` into its view (spec A-0; module rule)."""
        file = origin.file
        raw_value = raw.pairs[merge_index][1]
        raw_items = raw_value.items if isinstance(raw_value, RawSequence) else [raw_value]
        for raw_item in raw_items:
            if not isinstance(raw_item, RawAlias | RawMapping):
                raise self._bad_merge_value(file, segments, raw_item)
        written = MappingNode(
            origin=origin, flow=raw.flow, entries=self._entries(raw, file, segments)
        )
        value = written.entries[merge_index].value  # one entry per pair, in pair order
        if isinstance(raw_value, RawSequence):
            assert isinstance(value, SequenceNode)
            items = value.items
        else:
            items = [value]
        key_origin = written.entries[merge_index].key_origin
        sources: list[MergeSource] = []
        for raw_item, item in zip(raw_items, items, strict=True):
            content = unwrap(item)
            if not isinstance(content, MappingNode):
                raise self._bad_merge_value(file, segments, raw_item)
            if isinstance(item, AliasNode):
                sources.append((item, content, item.origin))
            else:
                sources.append((None, content, key_origin))
        return merge_keys(written, sources)

    @staticmethod
    def _bad_merge_value(file: SourceFile, segments: list[str], raw_item: RawNode) -> LoadError:
        return LoadError(
            f"cannot load {file.path}: {dotted([*segments, MERGE_KEY])}: merge value must be a"
            f" mapping, an alias of one, or a list of those (line {_line(file, raw_item.start)})"
        )

    def _ref_include(
        self, raw: RawNode, file: SourceFile, segments: list[str]
    ) -> YamlInclude | TextInclude:
        """Resolve a ``$ref`` value; it must be a string starting ``file:`` (spec D-1).

        An anchored ``$ref`` value is an anchored include reference (spec C3).
        """
        if isinstance(raw, RawScalar) and raw.anchor is not None:
            raise LoadError(
                f"cannot load {file.path}: anchor &{raw.anchor.name} at line"
                f" {_line(file, raw.anchor.start)} is on an include reference (or a value"
                " containing one); anchors may not share includes"
            )
        value = None
        if isinstance(raw, RawScalar):
            value = yamlcore.resolve_plain(raw.text) if raw.style == "plain" else raw.text
        if not (isinstance(value, str) and value.startswith(INCLUDE_PREFIX)):
            raise LoadError(
                f"cannot load {file.path}: {dotted([*segments, REF_KEY])} must be an include"
                f" string ('{INCLUDE_PREFIX}...'), got {_shown(file.text[raw.start : raw.end])}"
            )
        return self._include(
            value[len(INCLUDE_PREFIX) :], Origin(file, raw.start, raw.end), segments
        )

    def _entries(
        self,
        raw: RawMapping,
        file: SourceFile,
        segments: list[str],
        converted: Mapping[int, Node] | None = None,
    ) -> list[MappingEntry]:
        """Convert ``raw``'s pairs; ``converted`` holds values already converted, by pair index."""
        entries: list[MappingEntry] = []
        seen: set[str] = set()
        done = converted or {}
        for index, (raw_key, raw_value) in enumerate(raw.pairs):
            line = _line(file, raw_key.start)
            if isinstance(raw_key, RawAlias) or raw_key.anchor is not None:
                raise LoadError(
                    f"cannot load {file.path}: mapping key at line {line} under"
                    f" {dotted(segments)} has an anchor or is an alias"
                )
            if not isinstance(raw_key, RawScalar):
                raise LoadError(
                    f"cannot load {file.path}: mapping key at line {line} under"
                    f" {dotted(segments)} is not a scalar"
                )
            key = raw_key.text
            if key in seen:
                raise LoadError(
                    f"cannot load {file.path}: duplicate key {dotted([*segments, key])}"
                    f" at line {line}"
                )
            seen.add(key)
            entries.append(
                MappingEntry(
                    key=key,
                    key_origin=Origin(file, raw_key.start, raw_key.end),
                    key_style=raw_key.style,
                    value=done[index]
                    if index in done
                    else self._convert(raw_value, file, [*segments, key]),
                )
            )
        return entries

    def _include(
        self, target_text: str, origin: Origin, segments: list[str]
    ) -> YamlInclude | TextInclude:
        including = origin.file.path
        target = including.parent / target_text
        if not target.exists() and target.resolve() not in self._overrides:
            raise LoadError(
                f"include target not found: {target}"
                f" (included from {including}, at {dotted(segments)})"
            )
        if target.suffix in YAML_SUFFIXES:
            target_file = self._source(target)
            return YamlInclude(
                origin=origin, target=target_file, root=self._load_yaml(target_file, segments)
            )
        if target.is_dir():
            raise LoadError(
                f"include target is a directory: {target}"
                f" (included from {including}, at {dotted(segments)})"
            )
        return TextInclude(origin=origin, target=self._source(target))


def _line(file: SourceFile, index: int) -> int:
    return file.text.count("\n", 0, index) + 1


def _is_merge_key(raw_key: RawNode) -> bool:
    """A merge key is ``<<`` written plain; a quoted ``'<<'`` is an ordinary key (A-0)."""
    return isinstance(raw_key, RawScalar) and raw_key.style == "plain" and raw_key.text == MERGE_KEY


def _is_include_string(raw: RawScalar) -> bool:
    value = yamlcore.resolve_plain(raw.text) if raw.style == "plain" else raw.text
    return isinstance(value, str) and value.startswith(INCLUDE_PREFIX)


def _holds_include(raw: RawNode) -> bool:
    """Whether ``raw`` is or contains an include reference (spec C3).

    An include reference is an include string or a mapping with a ``$ref`` key. Keys are never
    includes. Aliases are not followed: an alias's anchored node was checked where it is written.
    """
    if isinstance(raw, RawAlias):
        return False
    if isinstance(raw, RawScalar):
        return _is_include_string(raw)
    if isinstance(raw, RawSequence):
        return any(_holds_include(item) for item in raw.items)
    return any(
        (isinstance(raw_key, RawScalar) and raw_key.text == REF_KEY) or _holds_include(raw_value)
        for raw_key, raw_value in raw.pairs
    )


def _shown(source: str) -> str:
    """Quote a ``$ref`` value's source text for a message: first line, at most ``SHOWN_MAX``."""
    if not source.strip():
        return "an empty value"
    lines = source.splitlines()
    first = lines[0]
    if len(first) > SHOWN_MAX or len(lines) > 1:
        first = first[:SHOWN_MAX] + "..."
    return first
