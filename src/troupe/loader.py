"""Build the SourceTree from the root file plus recursive local and remote includes (FR-007, FR-008;
spec S-1 to S-3, S-7, S-10).

Files are read fresh on every call (no caching across runs), as bytes decoded with strict UTF-8,
never in text mode, so CRLF and a BOM stay in ``SourceFile.text`` and parser indices match it
(research R-05, R-14). Remote content is fetched by ``remote.fetch`` with the same decoding.

Include rule: decided by ``troupe.includes``, never here (TROUPE-007; research R-3). A string
value of any style starting ``file:``, ``https://`` or ``http://`` is an include unless it is a
literal: tagged ``!literal``, or at a path the schema marks ``format: uri`` (S-7, S-10;
``includes.reads_as_include``). ``file:`` names a target relative to the directory of the
(resolved) local file containing it, or, inside remote content, relative to the containing URL
(S-1; ``includes.resolve_target``); a ``file:`` that would leave http(s) there is refused. A
remote string names its URL as written. A target whose path (for a URL: its URL path) ends
``.yml``/``.yaml`` (case-sensitive) is a ``YamlInclude`` whose content is embedded in place; any
other target is a ``TextInclude`` whose value is the target's exact text (S-2). Mapping keys are
never includes; a ``!literal`` key is refused. Everything reached through a remote include is
remote (``SourceFile.remote``).

Fetching (S-2; research R-10): each URL is fetched at most once per load. Fetched texts are kept
in the caller's ``fetched`` map, so every reload in one command reuses them; a failed fetch is a
``LoadError`` naming the URL, the including location and the path (contracts/cli.md). Include
cycles are detected on locations, URLs included.

Mapping form (FR-001 to FR-003): a mapping with a ``$ref`` key (any key quoting) is an include
whose include string is the ``$ref`` value; its other keys are *overrides*. A ``$ref`` key is
never data (spec D-1). With no overrides the include node itself is the value, exactly as in the
scalar form (YAML or text target). With overrides the value is ``merge.deep_merge`` of the
included content and the holder mapping. The target resolves by the rule above (same relative
path, missing-target, directory and cycle rules); the include node's ``holder`` is the mapping
that holds it. A ``$ref`` value is always an include, whatever the schema says (S-3). More load
errors, each naming the file and path:

- the ``$ref`` value is not an include string (``file:``, ``https://``, ``http://``; D-1), or is
  tagged ``!literal`` (S-3);
- overrides on a non-YAML target (contract *Overrides*);
- overrides on a YAML target whose content is a list or scalar, not a mapping (D-7; an empty
  target is an empty mapping and accepts overrides).

Paths (S-7): every node is converted at an ``_At``, which holds two paths. ``steps`` (a
``schema.Step`` list) is where the node appears in the resolved configuration and gives the
schema lookup: an included root and a merge-key source keep the steps of their mount point.
``segments`` is the path as written, ``<<`` included: it gives messages and ``Anchor.path``, the
anchor identity the write verifier compares, so it must not merge two written places into one.
An anchored node is converted once, where it is written, so an alias of a literal is a literal
at every alias.

Anchors and aliases (spec C1, C2, C3; research R-3, R-5): files are composed with
``allow_anchors=True``, so tags other than ``!literal``, undefined aliases and recursive aliases
are refused by ``yamlcore.compose`` (C2, FR-002). An anchored node is converted once, gets its
``Anchor`` and is recorded in a registry keyed by the raw node's ``id``; an alias becomes an
``AliasNode`` whose ``target`` (and ``anchored``) is that very node. Anchors precede their aliases
in a document, so the anchored node is always converted first. Anchors are per file: the registry
is scoped to one ``_load_yaml`` call, and an alias in an included file can only name an anchor of
that file. C3 refusals, each naming the file and line:

- an anchor on an include reference (an include string that is not a literal, or a ``$ref``
  mapping) or on a value containing one at any depth: aliasing would make one include reachable
  from several paths. An anchored literal is allowed (S-10);
- an anchored mapping key, or an alias used as a key: keys must stay plain names.

Merge keys (spec A-0, C13; research R-4): a key ``<<`` written plain (``'<<'`` is an ordinary
key) is a merge key. Its value must be an alias of a mapping, a mapping, or a list of those; the
mapping holding it becomes a ``merge.merge_keys`` view (``MergeKeyMapping``) over the concrete
mapping as written, ``<<`` entry included. A ``<<`` beside ``$ref`` in one mapping is refused
(C13). Both refusals name the file, path and line.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from troupe import includes, remote, yamlcore
from troupe.errors import FetchError, LoadError
from troupe.location import Location, Url
from troupe.merge import MERGE_KEY, REF_KEY, MergeSource, deep_merge, merge_keys
from troupe.paths import unwrap
from troupe.schema import Schema, Step
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

BOM = "\ufeff"
# Longest ``$ref`` value source text quoted in a D-1 message before it is cut with "...".
SHOWN_MAX: Final = 40
_REF_KINDS: Final = "'file:...', 'https://...' or 'http://...'"


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


def load(
    config_file: Path,
    overrides: Mapping[Location, str] | None = None,
    *,
    schema: Schema | None = None,
    fetched: dict[Url, str] | None = None,
) -> Node:
    """Load the configuration rooted at ``config_file`` into a SourceTree.

    Args:
        config_file: The theatre's root configuration file.
        overrides: Text to use instead of a source's contents, keyed by (resolved) file path or by
            URL. Used to re-load edited texts in memory and verify an edit before writing
            (research R-17); an overridden URL is not fetched.
        schema: The theatre's schema, if any: strings at paths it marks ``format: uri`` are
            literals, never includes (S-7). Validation is not done here.
        fetched: Remote texts already fetched in this command, by URL. This load reuses them and
            adds every text it fetches, so a caller that passes the same dict to every load of
            one command fetches each URL once (R-10). ``None`` means a fresh dict for this call.

    Returns:
        The root node. An empty document yields an empty block ``MappingNode``.

    Raises:
        LoadError: For unreadable or undecodable files, invalid YAML, a missing include target, a
            failed fetch or an include cycle; the message names the file(s) or URL(s).
    """
    return _Loader(overrides or {}, schema, {} if fetched is None else fetched).load_root(
        config_file
    )


def dotted(segments: list[str]) -> str:
    """Render path segments for messages (``(root)`` for the empty path)."""
    return ".".join(segments) if segments else "(root)"


@dataclass(frozen=True)
class _At:
    """Where a node is converted, as two paths that differ only inside a merge-key value.

    ``segments`` is the path as written: messages and ``Anchor.path`` (the anchor identity the
    verifier compares, research R-8 rule 1) use it, and a ``<<`` value is at ``holder.<<`` (its
    list items at ``holder.<<.i``). ``steps`` is the path in the resolved configuration, for the
    schema lookup (S-7): a ``<<`` value is mounted at its holding mapping, whose keys its keys
    become.
    """

    segments: tuple[str, ...] = ()
    steps: tuple[Step, ...] = ()

    def key(self, key: str) -> "_At":
        return _At((*self.segments, key), (*self.steps, ("key", key)))

    def index(self, index: int) -> "_At":
        return _At((*self.segments, str(index)), (*self.steps, ("index", index)))

    def merge_value(self) -> "_At":
        """The ``<<`` value: written under ``<<``, mounted at this mapping."""
        return _At((*self.segments, MERGE_KEY), self.steps)

    def merge_item(self, index: int) -> "_At":
        """An item of a ``<<`` list: written at its index, mounted at the holding mapping."""
        return _At((*self.segments, str(index)), self.steps)

    def text(self, *more: str) -> str:
        """``dotted`` of ``segments`` followed by ``more``, for messages."""
        return dotted([*self.segments, *more])


class _Loader:
    """State of one load: the SourceFile cache, the stack of YAML sources being expanded and the
    anchored nodes of the file being converted (``id(raw node) -> node``; module rule).
    """

    def __init__(
        self, overrides: Mapping[Location, str], schema: Schema | None, fetched: dict[Url, str]
    ) -> None:
        self._overrides: dict[Location, str] = {
            location.resolve() if isinstance(location, Path) else location: text
            for location, text in overrides.items()
        }
        self._schema = schema
        self._fetched = fetched
        self._files: dict[Location, SourceFile] = {}
        self._stack: list[Location] = []
        self._anchored: dict[int, Node] = {}

    def load_root(self, config_file: Path) -> Node:
        return self._load_yaml(self._source(config_file), _At())

    def _source(self, location: Location) -> SourceFile:
        """The one ``SourceFile`` of ``location`` in this load (identity matters to writers).

        A path is read from disk; a URL is taken from ``fetched`` or fetched and stored there.
        An override replaces either.

        Raises:
            LoadError: A local file cannot be read; ``FetchError`` for a failed fetch.
        """
        key = location.resolve() if isinstance(location, Path) else location
        cached = self._files.get(key)
        if cached is None:
            text = self._overrides.get(key)
            if text is not None:
                cached = SourceFile(path=key, text=text)
            elif isinstance(key, Path):
                cached = read_source(key)
            else:
                if key not in self._fetched:
                    self._fetched[key] = remote.fetch(key)
                cached = SourceFile(path=key, text=self._fetched[key])
            self._files[key] = cached
        return cached

    def _uri(self, steps: Sequence[Step] | None) -> bool:
        """Whether the schema marks the path ``steps`` ``format: uri`` (S-7); ``None``: no path."""
        return self._schema is not None and steps is not None and self._schema.uri_at(steps)

    def _load_yaml(self, file: SourceFile, at: _At) -> Node:
        if file.path in self._stack:
            chain = [*self._stack[self._stack.index(file.path) :], file.path]
            raise LoadError(f"include cycle at {at.text()}: {' -> '.join(str(p) for p in chain)}")
        self._stack.append(file.path)
        including_file_anchors = self._anchored
        self._anchored = {}  # anchors are per file (and per document)
        try:
            raw = yamlcore.compose(file.text, str(file.path), allow_anchors=True)
            if raw is None:
                start = 1 if file.text.startswith(BOM) else 0
                return MappingNode(origin=Origin(file, start, start), flow=False, entries=[])
            return self._convert(raw, file, at)
        finally:
            self._anchored = including_file_anchors
            self._stack.pop()

    def _convert(
        self, raw: RawNode, file: SourceFile, at: _At, *, merge_source: bool = False
    ) -> Node:
        """Convert ``raw``: an alias shares its anchored node; an anchored node is registered.

        ``merge_source``: ``raw`` is a ``<<`` value, so its list items are ``at.merge_item``.
        """
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
            return self._content(raw, file, at, merge_source=merge_source)
        if self._holds_include(raw, list(at.steps)):
            raise LoadError(
                f"cannot load {file.path}: anchor &{raw.anchor.name} at line"
                f" {_line(file, raw.anchor.start)} is on an include reference (or a value"
                " containing one); anchors may not share includes"
            )
        node = self._content(raw, file, at, merge_source=merge_source)
        # C3 (checked above) leaves only scalars, mappings and lists to be anchored.
        assert isinstance(node, ScalarNode | MappingNode | SequenceNode)
        node.anchor = Anchor(
            raw.anchor.name,
            Origin(file, raw.anchor.start, raw.anchor.end),
            at.segments,
        )
        self._anchored[id(raw)] = node
        return node

    def _content(
        self,
        raw: RawScalar | RawMapping | RawSequence,
        file: SourceFile,
        at: _At,
        *,
        merge_source: bool = False,
    ) -> Node:
        """Convert a scalar, mapping or list (its anchor, if any, is ``_convert``'s business)."""
        origin = Origin(file, raw.start, raw.end)
        if isinstance(raw, RawScalar):
            if raw.tag is not None:  # S-10: the text as a string, never resolved or included
                literal = Origin(file, raw.tag.start, raw.tag.end)
                return ScalarNode(origin=origin, value=raw.text, style=raw.style, literal=literal)
            value = yamlcore.resolve_plain(raw.text) if raw.style == "plain" else raw.text
            if isinstance(value, str) and includes.reads_as_include(
                value, tagged=False, uri=self._uri(at.steps)
            ):
                return self._include(value, origin, at)
            return ScalarNode(origin=origin, value=value, style=raw.style)
        if isinstance(raw, RawMapping):
            return self._mapping(raw, origin, at)
        items = [
            self._convert(item, file, at.merge_item(index) if merge_source else at.index(index))
            for index, item in enumerate(raw.items)
        ]
        return SequenceNode(origin=origin, flow=raw.flow, items=items)

    def _mapping(self, raw: RawMapping, origin: Origin, at: _At) -> Node:
        """Convert a mapping: plain, with a merge key, or a mapping-form include (module rule)."""
        file = origin.file
        for raw_key, _ in raw.pairs:
            if isinstance(raw_key, RawScalar) and raw_key.tag is not None:
                raise LoadError(
                    f"cannot load {file.path}: mapping key at line {_line(file, raw_key.start)}"
                    f" under {at.text()} is tagged !literal; keys are never includes"
                )
        ref_index = next(
            (index for index, (raw_key, _) in enumerate(raw.pairs) if _is_ref_key(raw_key)),
            None,
        )
        merge_index = next(
            (index for index, (raw_key, _) in enumerate(raw.pairs) if _is_merge_key(raw_key)),
            None,
        )
        if merge_index is not None and ref_index is not None:
            line = _line(file, raw.pairs[merge_index][0].start)
            raise LoadError(
                f"cannot load {file.path}: {at.text()}: a merge key '{MERGE_KEY}' cannot"
                f" be combined with '{REF_KEY}' (line {line})"
            )
        if merge_index is not None:
            return self._merge_mapping(raw, origin, at, merge_index)
        if ref_index is None:
            return MappingNode(origin=origin, flow=raw.flow, entries=self._entries(raw, file, at))
        include = self._ref_include(raw.pairs[ref_index][1], file, at)
        # The ``$ref`` value is converted once (above) and reused: converting it again would load
        # the target twice and confuse cycle detection.
        holder = MappingNode(
            origin=origin,
            flow=raw.flow,
            entries=self._entries(raw, file, at, converted={ref_index: include}),
        )
        include.holder = holder
        if len(holder.entries) == 1:
            return include  # no overrides: exactly the scalar form (FR-001)
        if isinstance(include, TextInclude):
            raise LoadError(
                f"cannot load {file.path}: {at.text()}: overrides need a YAML include,"
                f" but {include.target.path} is not a .yml/.yaml file"
            )
        content = unwrap(include.root)
        if not isinstance(content, MappingNode):
            kind = "list" if isinstance(content, SequenceNode) else "scalar"
            raise LoadError(
                f"cannot load {file.path}: {at.text()}: cannot override keys of"
                f" {include.target.path}: its content is a {kind}, not a mapping"
            )
        return deep_merge(include, holder, ref=include, origin=origin, flow=content.flow)

    def _merge_mapping(
        self, raw: RawMapping, origin: Origin, at: _At, merge_index: int
    ) -> MergeKeyMapping:
        """Convert a mapping holding a merge key ``<<`` into its view (spec A-0; module rule)."""
        file = origin.file
        raw_value = raw.pairs[merge_index][1]
        raw_items = raw_value.items if isinstance(raw_value, RawSequence) else [raw_value]
        for raw_item in raw_items:
            if not isinstance(raw_item, RawAlias | RawMapping):
                raise self._bad_merge_value(file, at, raw_item)
        written = MappingNode(origin=origin, flow=raw.flow, entries=self._entries(raw, file, at))
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
                raise self._bad_merge_value(file, at, raw_item)
            if isinstance(item, AliasNode):
                sources.append((item, content, item.origin))
            else:
                sources.append((None, content, key_origin))
        return merge_keys(written, sources)

    @staticmethod
    def _bad_merge_value(file: SourceFile, at: _At, raw_item: RawNode) -> LoadError:
        return LoadError(
            f"cannot load {file.path}: {at.text(MERGE_KEY)}: merge value must be a"
            f" mapping, an alias of one, or a list of those (line {_line(file, raw_item.start)})"
        )

    def _ref_include(self, raw: RawNode, file: SourceFile, at: _At) -> YamlInclude | TextInclude:
        """Resolve a ``$ref`` value; it is always an include string, never a literal (D-1, S-3).

        An anchored ``$ref`` value is an anchored include reference (spec C3).
        """
        if isinstance(raw, RawScalar) and raw.anchor is not None:
            raise LoadError(
                f"cannot load {file.path}: anchor &{raw.anchor.name} at line"
                f" {_line(file, raw.anchor.start)} is on an include reference (or a value"
                " containing one); anchors may not share includes"
            )
        if isinstance(raw, RawScalar) and raw.tag is not None:
            raise LoadError(
                f"cannot load {file.path}: {at.text(REF_KEY)} must be an include string,"
                f" not !literal (line {_line(file, raw.tag.start)})"
            )
        value = None
        if isinstance(raw, RawScalar):
            value = yamlcore.resolve_plain(raw.text) if raw.style == "plain" else raw.text
        if not (isinstance(value, str) and includes.include_kind(value) is not None):
            raise LoadError(
                f"cannot load {file.path}: {at.text(REF_KEY)} must be an include"
                f" string ({_REF_KINDS}), got {_shown(file.text[raw.start : raw.end])}"
            )
        return self._include(value, Origin(file, raw.start, raw.end), at)

    def _entries(
        self,
        raw: RawMapping,
        file: SourceFile,
        at: _At,
        converted: Mapping[int, Node] | None = None,
    ) -> list[MappingEntry]:
        """Convert ``raw``'s pairs; ``converted`` holds values already converted, by pair index.

        A ``<<`` value is at ``at.merge_value()`` (schema steps mounted at this mapping, whose keys
        its keys become), every other value at ``at.key(key)``.
        """
        entries: list[MappingEntry] = []
        seen: set[str] = set()
        done = converted or {}
        for index, (raw_key, raw_value) in enumerate(raw.pairs):
            line = _line(file, raw_key.start)
            if isinstance(raw_key, RawAlias) or raw_key.anchor is not None:
                raise LoadError(
                    f"cannot load {file.path}: mapping key at line {line} under"
                    f" {at.text()} has an anchor or is an alias"
                )
            if not isinstance(raw_key, RawScalar):
                raise LoadError(
                    f"cannot load {file.path}: mapping key at line {line} under"
                    f" {at.text()} is not a scalar"
                )
            key = raw_key.text
            if key in seen:
                raise LoadError(
                    f"cannot load {file.path}: duplicate key {at.text(key)} at line {line}"
                )
            seen.add(key)
            if index in done:
                value = done[index]
            elif _is_merge_key(raw_key):
                value = self._convert(raw_value, file, at.merge_value(), merge_source=True)
            else:
                value = self._convert(raw_value, file, at.key(key))
            entries.append(
                MappingEntry(
                    key=key,
                    key_origin=Origin(file, raw_key.start, raw_key.end),
                    key_style=raw_key.style,
                    value=value,
                )
            )
        return entries

    def _include(self, text: str, origin: Origin, at: _At) -> YamlInclude | TextInclude:
        """The include node for the include string ``text`` written at ``origin`` (S-1, S-2).

        Raises:
            LoadError: For a ``file:`` in remote content that leaves http(s), a missing or
                directory target, a failed fetch, or (from ``_load_yaml``) an include cycle.
        """
        including = origin.file.path
        target = includes.resolve_target(text, including)
        if isinstance(target, Url):
            try:
                target_file = self._source(target)
            except FetchError as err:
                raise LoadError(
                    f"cannot fetch {err.url} (included from {including}, at {at.text()}):"
                    f" {err.reason}"
                ) from err
            if includes.is_yaml_target(target):
                root = self._load_yaml(target_file, at)
                return YamlInclude(origin=origin, target=target_file, root=root)
            return TextInclude(origin=origin, target=target_file)
        if not target.exists() and target.resolve() not in self._overrides:
            raise LoadError(
                f"include target not found: {target} (included from {including}, at {at.text()})"
            )
        if includes.is_yaml_target(target):
            target_file = self._source(target)
            return YamlInclude(
                origin=origin, target=target_file, root=self._load_yaml(target_file, at)
            )
        if target.is_dir():
            raise LoadError(
                f"include target is a directory: {target}"
                f" (included from {including}, at {at.text()})"
            )
        return TextInclude(origin=origin, target=self._source(target))

    def _holds_include(self, raw: RawNode, steps: list[Step] | None) -> bool:
        """Whether ``raw``, at the path ``steps``, is or contains an include reference (C3).

        An include reference is a string that reads as an include there (the decision
        ``_content`` makes: never a ``!literal`` string or a ``format: uri`` path) or a mapping
        with a ``$ref`` key. Keys are never includes. Aliases are not followed: an alias's
        anchored node was checked where it is written. ``steps`` is ``None`` below a key that
        is not a scalar (no path; such a key is refused anyway).
        """
        if isinstance(raw, RawAlias):
            return False
        if isinstance(raw, RawScalar):
            if raw.tag is not None:
                return False
            value = yamlcore.resolve_plain(raw.text) if raw.style == "plain" else raw.text
            return isinstance(value, str) and includes.reads_as_include(
                value, tagged=False, uri=self._uri(steps)
            )
        if isinstance(raw, RawSequence):
            return any(
                self._holds_include(item, _step(steps, ("index", index)))
                for index, item in enumerate(raw.items)
            )
        for raw_key, raw_value in raw.pairs:
            if _is_ref_key(raw_key):
                return True
            if _is_merge_key(raw_key):
                value_steps = steps  # a ``<<`` value is mounted at its mapping (``_entries``)
                items = raw_value.items if isinstance(raw_value, RawSequence) else [raw_value]
                if any(self._holds_include(item, value_steps) for item in items):
                    return True
                continue
            key = raw_key.text if isinstance(raw_key, RawScalar) else None
            value_steps = None if key is None else _step(steps, ("key", key))
            if self._holds_include(raw_value, value_steps):
                return True
        return False


def _step(steps: list[Step] | None, step: Step) -> list[Step] | None:
    return None if steps is None else [*steps, step]


def _line(file: SourceFile, index: int) -> int:
    return file.text.count("\n", 0, index) + 1


def _is_ref_key(raw_key: RawNode) -> bool:
    """A ``$ref`` key, in any quoting style (D-1)."""
    return isinstance(raw_key, RawScalar) and raw_key.text == REF_KEY


def _is_merge_key(raw_key: RawNode) -> bool:
    """A merge key is ``<<`` written plain; a quoted ``'<<'`` is an ordinary key (A-0)."""
    return isinstance(raw_key, RawScalar) and raw_key.style == "plain" and raw_key.text == MERGE_KEY


def _shown(source: str) -> str:
    """Quote a ``$ref`` value's source text for a message: first line, at most ``SHOWN_MAX``."""
    if not source.strip():
        return "an empty value"
    lines = source.splitlines()
    first = lines[0]
    if len(first) > SHOWN_MAX or len(lines) > 1:
        first = first[:SHOWN_MAX] + "..."
    return first
