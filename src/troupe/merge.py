"""The deep-merge rule for mapping-form includes: the one place it is decided (FR-002, R-2).

A mapping-form include (``coder: {$ref: file:agents/coder.yaml, temperature: 0.3}``) reads as
the included content with the holder's other keys (*overrides*) deep-merged over it. This module
is pure: it builds a ``MergedMapping`` view from two already-loaded sides and reads no files.
``troupe.loader`` recognises ``$ref`` and calls ``deep_merge``; nothing else merges.
"""

from typing import Final

from troupe.paths import unwrap
from troupe.tree import MappingEntry, MappingNode, MergedMapping, Node, Origin, YamlInclude

REF_KEY: Final = "$ref"


def deep_merge(
    base: Node, override: Node, *, ref: YamlInclude | None, origin: Origin, flow: bool
) -> MergedMapping:
    """Merge ``override`` over ``base`` (both as found; both unwrap to mappings).

    Rules (contract *Overrides*; spec FR-002, D-7; research R-2):

    - A key only in the base keeps the base entry; a key only in the override keeps the override
      entry. A ``$ref`` key is never data and never appears in the view (D-1).
    - A key in both whose values both unwrap to mappings merges recursively into a nested
      ``MergedMapping`` (``ref=None``), under the override entry's key text, key origin and key
      style.
    - Otherwise the override entry replaces the base entry: scalars and lists in the override
      replace, and so does a mapping over a scalar or a scalar over a mapping.
    - Key order: the base's keys in base order (each at its base position, even when
      overridden), then override-only keys in override order (spec Assumptions).

    ``MappingEntry`` objects and value nodes of both sides are reused, never copied: callers rely
    on identity to find the concrete side a node lives in.

    Args:
        base: The included side as found (usually a ``YamlInclude``).
        override: The override side as found (the holder mapping at the top of an include).
        ref: The ``$ref`` include when this is the top of a mapping-form include, else ``None``.
        origin: The view's origin: the override side's (the holder's span at the top).
        flow: The view's shape: ``unwrap(base).flow`` (research R-1).
    """
    base_map = unwrap(base)
    override_map = unwrap(override)
    assert isinstance(base_map, MappingNode)  # the loader checks before merging (D-7)
    assert isinstance(override_map, MappingNode)
    overrides = [entry for entry in override_map.entries if entry.key != REF_KEY]
    by_key = {entry.key: entry for entry in overrides}
    entries = [_merge_entry(entry, by_key.get(entry.key)) for entry in base_map.entries]
    base_keys = {entry.key for entry in base_map.entries}
    entries.extend(entry for entry in overrides if entry.key not in base_keys)
    return MergedMapping(
        origin=origin,
        flow=flow,
        entries=entries,
        base=base,
        override=override,
        ref=ref,
    )


def _merge_entry(base: MappingEntry, override: MappingEntry | None) -> MappingEntry:
    """The view's entry for a base key: base as is, override as is, or a nested merge."""
    if override is None:
        return base
    base_value = unwrap(base.value)
    if not (
        isinstance(base_value, MappingNode) and isinstance(unwrap(override.value), MappingNode)
    ):
        return override
    merged = deep_merge(
        base.value,
        override.value,
        ref=None,
        origin=override.value.origin,
        flow=base_value.flow,
    )
    return MappingEntry(
        key=override.key,
        key_origin=override.key_origin,
        key_style=override.key_style,
        value=merged,
    )
