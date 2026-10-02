"""Build the SourceTree from the files on disk: root file plus recursive includes (FR-007, FR-008).

Files are read fresh on every call (no caching across runs), as bytes decoded with strict UTF-8,
never in text mode, so CRLF and a BOM stay in ``SourceFile.text`` and parser indices match it
(research R-05, R-14).

Include rule (the one place it is decided): a string value of any style whose text starts with
``file:`` names a target relative to the directory of the (resolved) file containing it. A target
ending ``.yml``/``.yaml`` (case-sensitive) is a ``YamlInclude`` whose content is embedded in
place; any other target is a ``TextInclude`` whose value is the file's exact text. Mapping keys
are never includes.
"""

from collections.abc import Mapping
from pathlib import Path

from troupe import yamlcore
from troupe.errors import LoadError
from troupe.tree import (
    MappingEntry,
    MappingNode,
    Node,
    Origin,
    ScalarNode,
    SequenceNode,
    SourceFile,
    TextInclude,
    YamlInclude,
)
from troupe.yamlcore import RawMapping, RawNode, RawScalar

INCLUDE_PREFIX = "file:"
YAML_SUFFIXES = (".yml", ".yaml")
BOM = "\ufeff"


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
    """State of one load: the SourceFile cache and the stack of YAML files being expanded."""

    def __init__(self, overrides: Mapping[Path, str]) -> None:
        self._overrides = {path.resolve(): text for path, text in overrides.items()}
        self._files: dict[Path, SourceFile] = {}
        self._stack: list[Path] = []

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
        try:
            raw = yamlcore.compose(file.text, str(file.path))
            if raw is None:
                start = 1 if file.text.startswith(BOM) else 0
                return MappingNode(origin=Origin(file, start, start), flow=False, entries=[])
            return self._convert(raw, file, segments)
        finally:
            self._stack.pop()

    def _convert(self, raw: RawNode, file: SourceFile, segments: list[str]) -> Node:
        origin = Origin(file, raw.start, raw.end)
        if isinstance(raw, RawScalar):
            value = yamlcore.resolve_plain(raw.text) if raw.style == "plain" else raw.text
            if isinstance(value, str) and value.startswith(INCLUDE_PREFIX):
                return self._include(value[len(INCLUDE_PREFIX) :], origin, segments)
            return ScalarNode(origin=origin, value=value, style=raw.style)
        if isinstance(raw, RawMapping):
            return MappingNode(
                origin=origin, flow=raw.flow, entries=self._entries(raw, file, segments)
            )
        items = [
            self._convert(item, file, [*segments, str(index)])
            for index, item in enumerate(raw.items)
        ]
        return SequenceNode(origin=origin, flow=raw.flow, items=items)

    def _entries(
        self, raw: RawMapping, file: SourceFile, segments: list[str]
    ) -> list[MappingEntry]:
        entries: list[MappingEntry] = []
        seen: set[str] = set()
        for raw_key, raw_value in raw.pairs:
            line = file.text.count("\n", 0, raw_key.start) + 1
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
                    value=self._convert(raw_value, file, [*segments, key]),
                )
            )
        return entries

    def _include(self, target_text: str, origin: Origin, segments: list[str]) -> Node:
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
