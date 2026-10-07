"""The one place that decides "the configuration is loaded and valid" (research R-10, TROUPE-007).

``load_configuration`` is the single entry point every session uses. Its order is fixed:

1. ``schema.load_schema(state_dir)``: the schema is read *first*, because it decides which
   strings are literals (``format: uri``, spec S-7) and so what the loader fetches or reads as
   an include. An unreadable or invalid schema is a ``LoadError`` naming the schema file (S-8).
2. ``loader.load(config_file, overrides, schema=..., fetched=...)``: local files are read and
   remote includes fetched, each URL at most once per command (``fetched`` is shared, R-10).
3. Validation: when a schema exists, the resolved configuration (``to_data``) must match it,
   else ``LoadError("configuration does not match schema <file> at <path>: <message>")``.

Every failure here is a ``LoadError`` (exit 4). ``set`` needs exit 3 for a result that would not
match the schema (S-9); it gets that by calling ``violation`` itself on its in-memory reload and
raising its own ``WriteRefused``, rather than by catching the message produced here.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

from troupe.errors import LoadError
from troupe.loader import load
from troupe.location import Location, Url
from troupe.paths import unwrap
from troupe.schema import Schema, Violation, load_schema
from troupe.theatre import Theatre
from troupe.tree import MappingNode, Node, ScalarNode, SequenceNode, TextInclude
from troupe.values import Value


@dataclass(frozen=True)
class Loaded:
    """A configuration that loaded and matches its schema (if any).

    Attributes:
        tree: The SourceTree of the configuration.
        schema: The theatre's schema, or ``None`` when ``troupe.schema.json`` does not exist.
        fetched: The remote texts this command has fetched, by URL. The very dict passed to
            ``load_configuration`` (or a new one), so every later reload in the same command that
            passes it on reuses the same snapshot of the remote content.
    """

    tree: Node
    schema: Schema | None
    fetched: dict[Url, str] = field(compare=False)


def load_configuration(
    theatre: Theatre,
    overrides: Mapping[Location, str] | None = None,
    fetched: dict[Url, str] | None = None,
) -> Loaded:
    """Read the schema, load the configuration, then validate it (in that order).

    Args:
        theatre: The located theatre.
        overrides: Texts to use instead of sources' contents (see ``loader.load``).
        fetched: Remote texts already fetched in this command; filled with every new fetch.
            ``None`` means a new dict, returned in ``Loaded.fetched``.

    Raises:
        LoadError: If the schema file is invalid, the configuration cannot be loaded or a fetch
            fails, or the configuration does not match the schema (exit 4).
    """
    shared: dict[Url, str] = {} if fetched is None else fetched
    schema = load_schema(theatre.state_dir)
    tree = load(theatre.config_file, overrides, schema=schema, fetched=shared)
    if schema is not None:
        found = violation(tree, schema)
        if found is not None:
            raise LoadError(
                f"configuration does not match schema {schema.path} at {found.path}: "
                f"{found.message}"
            )
    return Loaded(tree, schema, shared)


def violation(tree: Node, schema: Schema) -> Violation | None:
    """Validate the resolved configuration ``tree`` against ``schema``; the first failure."""
    return schema.validate(to_data(tree))


def to_data(node: Node) -> Value:
    """The resolved configuration under ``node`` as plain JSON-like data (spec S-8).

    This is what every read sees: includes, aliases and merged views (overrides, merge keys)
    resolved through ``paths.unwrap`` and the mappings' ``entries``; a text include is its
    target's exact text (as ``values.scalar_of`` reads it). A ``!literal`` string is a plain
    string here: the tag only says "not an include". Floats such as NaN and infinity pass
    through unchanged; jsonschema treats them as numbers.
    """
    content = unwrap(node)
    if isinstance(content, ScalarNode):
        return content.value
    if isinstance(content, TextInclude):
        return content.target.text
    if isinstance(content, MappingNode):
        return {entry.key: to_data(entry.value) for entry in content.entries}
    assert isinstance(content, SequenceNode)  # unwrap never returns an include or an alias
    return [to_data(item) for item in content.items]
