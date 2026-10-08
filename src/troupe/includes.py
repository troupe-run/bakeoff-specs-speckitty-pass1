"""The include rule: the one place that decides what an include string is and what it points at
(TROUPE-007; research R-3, R-8, R-9).

- ``include_kind`` tells a ``file:`` include from a remote (``https://``/``http://``) one.
- ``resolve_target`` turns an include string into the ``Location`` it names (spec S-1).
- ``is_yaml_target`` decides YAML or text by the suffix of the path or URL path (S-2).
- ``reads_as_include`` is the literal-versus-include rule for scalar strings (S-7, S-10).
- ``path_steps`` gives the key/index kind of each PATH segment, for ``Schema.uri_at``.
- ``mark_literals`` decides which VALUE strings ``set`` writes ``!literal`` and refuses
  ``--include`` on a ``format: uri`` path (S-11, S-12, S-13).

This module imports nothing that imports ``troupe.loader``, so the loader can import it.
"""

from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Final, Literal
from urllib.parse import urljoin, urlsplit

from troupe.errors import LoadError, WriteRefused
from troupe.location import Location, Url
from troupe.paths import unwrap, walk
from troupe.schema import Schema, Step
from troupe.tree import Node, SequenceNode
from troupe.values import Value

FILE_PREFIX: Final = "file:"
REMOTE_PREFIXES: Final = ("https://", "http://")
YAML_SUFFIXES: Final = (".yml", ".yaml")
_HTTP_SCHEMES: Final = ("http", "https")

type IncludeKind = Literal["file", "remote"]


def include_kind(text: str) -> IncludeKind | None:
    """Whether ``text`` looks like an include, and which kind (contracts/cli.md, S-1).

    A case-sensitive prefix test, as ``file:`` has always been tested: ``file:...`` is a file
    include, ``https://...`` or ``http://...`` a remote one; anything else (``HTTPS://x``,
    ``ftp://x``, `` file:x``) is not an include.
    """
    if text.startswith(FILE_PREFIX):
        return "file"
    if text.startswith(REMOTE_PREFIXES):
        return "remote"
    return None


def resolve_target(text: str, containing: Location) -> Location:
    """The location the include string ``text``, written in ``containing``, names (S-1).

    - A remote string is ``Url(text)``, exactly as written.
    - ``file:rest`` in a local file is ``containing.parent / rest``. It is not resolved: the
      loader checks existence and resolves it as before.
    - ``file:rest`` in remote content is ``Url(urljoin(containing.text, rest))`` (standard
      relative-URL resolution). The result is remote, and so read-only (S-1, S-4).

    Raises:
        LoadError: If ``file:`` inside remote content does not resolve to an http(s) URL
            (e.g. ``file:file:///etc/passwd``): remote content may never reach local disk
            (research A-3). The message names the include and the containing URL.
    """
    kind = include_kind(text)
    assert kind is not None, f"not an include string: {text!r}"
    if kind == "remote":
        return Url(text)
    rest = text[len(FILE_PREFIX) :]
    if isinstance(containing, Path):
        return containing.parent / rest
    joined = urljoin(containing.text, rest)
    if urlsplit(joined).scheme not in _HTTP_SCHEMES:
        raise LoadError(f"include {text!r} in {containing} does not resolve to an http(s) URL")
    return Url(joined)


def is_yaml_target(target: Location) -> bool:
    """Whether an include target is YAML (else text), by a case-sensitive suffix test (S-2).

    For a ``Url`` only the URL path counts, so query and fragment are ignored:
    ``https://h/team.yaml?v=2`` is YAML, ``https://h/team.yaml.txt`` and ``https://h/`` are text.
    """
    if isinstance(target, Path):
        return target.suffix in YAML_SUFFIXES
    return PurePosixPath(urlsplit(target.text).path).suffix in YAML_SUFFIXES


def reads_as_include(text: str, *, tagged: bool, uri: bool) -> bool:
    """Whether a scalar string value is read as an include (spec S-7, S-10): it looks like one,
    is not tagged ``!literal`` and its schema does not mark it ``format: uri``.

    Not used for ``$ref`` values: those are always includes (S-3).
    """
    return include_kind(text) is not None and not tagged and not uri


def path_steps(root: Node, segments: Sequence[str]) -> list[Step]:
    """The key/index kind of each PATH segment, for ``Schema.uri_at``.

    A segment that exists is an index when the container it is looked up in is a list, else a
    key (so a digit-named mapping key is a key). Of the segments that do not exist yet, the
    first is an index when the deepest existing node is a list (only the append index can be
    missing there), and every other one is a key, as ``placement.place`` creates them.

    Raises:
        PathError: From ``walk``, exactly when ``set`` would fail on the same path.
    """
    found = walk(root, list(segments))
    consumed = len(segments) - len(found.remaining)
    steps: list[Step] = [
        _step(found.nodes[depth], segment) for depth, segment in enumerate(segments[:consumed])
    ]
    for position, segment in enumerate(found.remaining):
        container = found.nodes[-1] if position == 0 else None
        steps.append(_step(container, segment))
    return steps


def _step(container: Node | None, segment: str) -> Step:
    if container is not None and isinstance(unwrap(container), SequenceNode):
        return ("index", int(segment))
    return ("key", segment)


class LiteralStr(str):
    """A VALUE string that ``set`` writes tagged ``!literal`` (spec S-11, S-13; research R-8).
    Only ``mark_literals`` creates it; renderers write ``!literal `` before it.

    It keeps ``==`` and ``hash`` of ``str``, so comparisons with plain strings still work.
    """

    __slots__ = ()


class IncludeStr(str):
    """A VALUE string that ``set --include`` writes untagged so that it is an include (S-12).
    Renderers treat it as a plain string; it exists so the no-op check can tell an include
    from a literal (research R-9).
    """

    __slots__ = ()


def mark_literals(
    value: Value,
    steps: Sequence[Step],
    schema: Schema | None,
    *,
    include: bool,
    dotted: str,
) -> Value:
    """Mark which VALUE strings ``set`` writes as literals or includes (S-11, S-12, S-13).

    Every string in ``value`` is judged at its own resulting path (``steps`` plus its nested
    keys and indexes); ``uri`` is whether ``schema`` marks that path ``format: uri``.

    - Without ``include``: an include-looking string that is not ``uri`` becomes a
      ``LiteralStr``. Example (S-13): ``set b file:p.md`` writes ``b: !literal file:p.md``.
    - With ``include``: an include-looking string becomes an ``IncludeStr``, written untagged
      and so read as an include.

    Result invariant: each string is a ``LiteralStr`` (written tagged, reads as a literal), an
    ``IncludeStr`` (written untagged, reads as an include) or a plain ``str`` (not
    include-looking, or literal by the schema's ``uri`` mark). Mappings keep their key order;
    the input is never mutated. A local text-include write (``_plan_text``) writes file text,
    never YAML, so it converts a ``LiteralStr`` back to a plain ``str``.

    Raises:
        WriteRefused: With ``include``, if an include-looking string's path is marked
            ``format: uri``: it would be a literal anyway (S-12). The message names ``dotted``
            and the nested path.
    """
    return _mark(value, list(steps), schema, include, [dotted])


def _mark(
    value: Value, steps: list[Step], schema: Schema | None, include: bool, shown: list[str]
) -> Value:
    if isinstance(value, dict):
        return {
            key: _mark(item, [*steps, ("key", key)], schema, include, [*shown, key])
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _mark(item, [*steps, ("index", index)], schema, include, [*shown, str(index)])
            for index, item in enumerate(value)
        ]
    if not isinstance(value, str) or include_kind(value) is None:
        return value
    uri = schema is not None and schema.uri_at(steps)
    if not include:
        return value if uri else LiteralStr(value)
    if uri:
        assert schema is not None
        raise WriteRefused(
            f"{shown[0]}: schema {schema.path} marks {'.'.join(shown)} as format uri,"
            " so it cannot be an include; no file changed"
        )
    return IncludeStr(value)
