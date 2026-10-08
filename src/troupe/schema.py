"""The configuration schema, ``<state dir>/troupe.schema.json`` (spec S-7, S-8; research R-6).

This module is the one place that knows about the schema (TROUPE-007). It works on plain JSON
data (dicts, lists, scalars) and on path steps; it does not know the tree, files or the loader.

- ``load_schema`` reads and checks the schema file. Any problem is a ``LoadError`` naming it.
- ``Schema.uri_at`` answers whether the schema marks a configuration path ``"format": "uri"``.
- ``Schema.validate`` validates data as JSON Schema 2020-12 and returns the first violation.

Offline by construction (research A-4): every ``$ref``/``$dynamicRef`` must be a fragment within
the file, and the validator gets an empty ``referencing.Registry``, so nothing is ever fetched.
``format`` is an annotation only: the validator has no ``format_checker`` (S-8).
"""

import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from referencing import Registry
from referencing.exceptions import NoSuchAnchor, PointerToNowhere, Unresolvable

from troupe.errors import LoadError

SCHEMA_FILE_NAME: Final = "troupe.schema.json"
DRAFT_2020_12: Final = "https://json-schema.org/draft/2020-12/schema"

# Keywords whose value maps *names* to subschemas: a ``$ref`` key directly inside one of these is
# a name (e.g. a property called ``$ref``), not a reference keyword. Defensive only: the
# meta-schema check runs first and requires these values to be schemas, so through
# ``load_schema`` a string there is already refused; the exemption keeps the walk honest.
_NAME_KEYWORDS: Final = frozenset(
    {"properties", "patternProperties", "$defs", "definitions", "dependentSchemas"}
)
_REFERENCE_KEYWORDS: Final = ("$ref", "$dynamicRef")

type Step = tuple[Literal["key"], str] | tuple[Literal["index"], int]
"""One configuration path step; the caller knows whether it is a mapping key or a list index."""


@dataclass(frozen=True)
class Violation:
    """The first failure of a validation."""

    path: str  # dotted configuration path of the failing instance, "(root)" for the root
    message: str  # jsonschema's error.message


@dataclass(frozen=True)
class Schema:
    """A checked schema document; build it through ``load_schema``."""

    path: Path  # absolute, as read
    document: dict[str, Any] | bool  # 2020-12 allows a boolean root schema
    _validator: Draft202012Validator = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        # No format_checker: ``format`` is an annotation (S-8). The empty Registry resolves
        # nothing outside this document, so no reference is ever fetched (A-4).
        validator = Draft202012Validator(self.document, registry=Registry())
        object.__setattr__(self, "_validator", validator)

    def uri_at(self, steps: Sequence[Step]) -> bool:
        """Whether the schema found for ``steps`` is an object with ``"format": "uri"``.

        Spec S-7: the contract names exactly properties, items and additionalProperties. From
        the root schema, a key step ``k`` goes to ``properties[k]`` when present, otherwise to
        ``additionalProperties`` when it is a schema object; an index step goes to ``items``
        when it is a schema object. Nothing else is followed: not ``$ref``,
        ``allOf``/``anyOf``/``oneOf``, ``if``/``then``/``else``, ``patternProperties``,
        ``prefixItems``, ``dependentSchemas`` or ``unevaluatedProperties``. A boolean or missing
        subschema gives ``False``. Only the exact value ``"uri"`` counts (not ``uri-reference``,
        not ``iri``).
        """
        current: object = self.document
        for kind, name in steps:
            if not isinstance(current, dict):
                return False
            if kind == "key":
                properties = current.get("properties")
                if isinstance(properties, dict) and name in properties:
                    current = properties[name]
                else:
                    current = current.get("additionalProperties")
            else:
                current = current.get("items")
            if not isinstance(current, dict):
                return False
        return isinstance(current, dict) and current.get("format") == "uri"

    def validate(self, data: object) -> Violation | None:
        """Validate plain JSON ``data``; ``None`` if valid, else the first violation.

        The first violation is the first failure in path order, made deterministic (research
        R-6): errors are ordered by their instance path (list indexes before keys at the same
        position, indexes numerically, keys by text), so a shorter path that is a prefix of a
        longer one comes first; then by the smallest validator keyword name, then by message.
        """
        try:
            errors = list(self._validator.iter_errors(data))
        except Unresolvable as error:
            # Safety net: a remote reference cannot get here through ``load_schema``, but a
            # fragment pointing nowhere (``#/$defs/missing``, ``#foo``) is only found when it
            # is used.
            reason = f"cannot resolve {_unresolved(error)}"
            raise LoadError(f"cannot load schema {self.path}: {reason}") from None
        if not errors:
            return None
        first = min(errors, key=_order)
        return Violation(_dotted(first.absolute_path), first.message)


def load_schema(state_dir: Path) -> Schema | None:
    """Read and check ``<state_dir>/troupe.schema.json``; ``None`` if there is no such file.

    Raises ``LoadError("cannot load schema <file>: <reason>")`` when the file is not a file, is
    unreadable, is not strict UTF-8 JSON, is not an object or boolean, names another ``$schema``,
    fails the 2020-12 meta-schema, or holds a reference that is not a fragment within the file.
    """
    path = state_dir / SCHEMA_FILE_NAME
    if not path.exists():
        return None
    if not path.is_file():
        raise _refused(path, "not a file")
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise _refused(path, error.strerror or str(error)) from None
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise _refused(path, f"not valid UTF-8 at byte {error.start}") from None
    try:
        document: object = json.loads(text, parse_constant=_refuse_constant)
    except _NonJsonConstant:
        raise _refused(path, "not valid JSON: NaN/Infinity are not JSON") from None
    except json.JSONDecodeError as error:
        reason = f"not valid JSON: {error.msg} at line {error.lineno} column {error.colno}"
        raise _refused(path, reason) from None
    if not isinstance(document, dict | bool):
        raise _refused(path, "the schema must be a JSON object or boolean")
    if isinstance(document, dict) and "$schema" in document:
        declared = document["$schema"]
        if declared != DRAFT_2020_12:
            shown = declared if isinstance(declared, str) else json.dumps(declared)
            raise _refused(path, f"$schema must be {DRAFT_2020_12}, got {shown}")
    try:
        Draft202012Validator.check_schema(document)
    except SchemaError as error:
        reason = (
            f"not a valid JSON Schema 2020-12: {error.message} at {_pointer(error.absolute_path)}"
        )
        raise _refused(path, reason) from None
    for keyword, value, parts in _references(document, (), names=False):
        if not value.startswith("#"):
            raise _refused(
                path,
                f"{keyword} {value} at {_pointer(parts)} is not a fragment within this file"
                " (references to other documents are not fetched)",
            )
    return Schema(path, document)


class _NonJsonConstant(Exception):
    """``NaN``, ``Infinity`` or ``-Infinity`` in the schema text."""


def _refuse_constant(name: str) -> object:
    raise _NonJsonConstant(name)


def _refused(path: Path, reason: str) -> LoadError:
    return LoadError(f"cannot load schema {path}: {reason}")


def _references(
    node: object, parts: tuple[str | int, ...], *, names: bool
) -> Iterator[tuple[str, str, tuple[str | int, ...]]]:
    """Yield ``(keyword, value, pointer parts)`` for every string ``$ref``/``$dynamicRef``.

    Conservative walk (TROUPE-002): every dict is treated as a schema object, except a dict
    that is the value of a name keyword (``properties``, ``patternProperties``, ``$defs``,
    ``definitions``, ``dependentSchemas``), whose keys are names. So a property *named* ``$ref``
    is not a reference, while a ``$ref`` key inside data such as ``enum``, ``const``,
    ``default`` or ``examples`` is checked too: refusing such a schema is safer than guessing.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            if not names and key in _REFERENCE_KEYWORDS and isinstance(value, str):
                yield key, value, (*parts, key)
            yield from _references(value, (*parts, key), names=not names and key in _NAME_KEYWORDS)
    elif isinstance(node, list):
        for position, item in enumerate(node):
            yield from _references(item, (*parts, position), names=False)


def _pointer(parts: Iterator[str | int] | Sequence[str | int]) -> str:
    """A JSON pointer (RFC 6901) to a place in the schema document; ``(root)`` for the root."""
    escaped = [str(part).replace("~", "~0").replace("/", "~1") for part in parts]
    return "/" + "/".join(escaped) if escaped else "(root)"


def _unresolved(error: Unresolvable) -> str:
    """The reference as the user wrote it, for an ``Unresolvable`` raised during validation.

    jsonschema (4.26) raises its own ``Unresolvable`` subclass and chains referencing's original
    error as ``__cause__``. That original error knows what was written: a ``PointerToNowhere``
    holds the bare JSON pointer in ``ref`` and a ``NoSuchAnchor`` holds an empty ``ref`` and the
    anchor name, so both are shown as the fragment ``#...``. Never empty: an unknown cause
    without a ``ref`` is shown by its ``repr``.
    """
    cause = error.__cause__ if isinstance(error.__cause__, Unresolvable) else error
    if isinstance(cause, NoSuchAnchor):
        return f"#{cause.anchor}"
    if isinstance(cause, PointerToNowhere):
        return f"#{cause.ref}"
    return cause.ref or repr(cause)


def _order(error: ValidationError) -> tuple[tuple[tuple[int, int | str], ...], str, str]:
    path = tuple(
        (0, part) if isinstance(part, int) else (1, str(part)) for part in error.absolute_path
    )
    # Tuple comparison already puts a path before any longer path it is a prefix of.
    return (path, str(error.validator), error.message)


def _dotted(parts: Sequence[str | int]) -> str:
    """Render an instance path like ``loader.dotted`` (``(root)`` for the root)."""
    return ".".join(str(part) for part in parts) if parts else "(root)"
