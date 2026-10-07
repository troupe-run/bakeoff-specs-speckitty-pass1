"""``placement.place`` through anchors, aliases and merge keys (spec US2, US3, FR-003, FR-004,
FR-007, A-0, C4, C6, C7; research R-4, R-6).

Each test writes a theatre, loads it with ``troupe.loader.load`` and calls ``place`` directly:
until the applier handles ``ExpandAlias`` (WP05) the rule is checked at the placement level.
"""

import dataclasses
from pathlib import Path

import pytest

from conftest import MakeTheatre
from troupe.errors import WriteRefused
from troupe.loader import load
from troupe.location import Location
from troupe.paths import parse_path, unwrap
from troupe.tree import (
    AliasNode,
    MappingNode,
    MergedMapping,
    MergeKeyMapping,
    Node,
    SequenceNode,
)
from troupe.writeback.placement import (
    AddKeys,
    ExpandAlias,
    Placement,
    ReplaceCollection,
    ReplaceScalar,
    concrete_parent,
    place,
)

type Files = dict[str, str | bytes]

SHARED = (
    "defaults: &d\n"
    "  model: opus\n"
    "  temperature: 0.2\n"
    "coder:\n"
    "  settings: *d\n"
    "reviewer:\n"
    "  settings: *d\n"
)
MERGED = "base: &b\n  model: opus\n  temperature: 0.2\ncoder:\n  <<: *b\n  model: gpt\n"


def _load(make_theatre: MakeTheatre, files: Files | str) -> Node:
    if isinstance(files, str):
        files = {"troupe.yml": files}
    theatre = make_theatre(files)
    return load(theatre / ".troupe" / "troupe.yml")


def _place(
    root: Node, path: str, *, in_include: bool = False, expand_alias: bool = False
) -> Placement:
    """Place ``set path``; assert the placement holds concrete nodes only."""
    placement = place(
        root, parse_path(path), path, in_include=in_include, expand_alias=expand_alias
    )
    for field in dataclasses.fields(placement):
        value = getattr(placement, field.name)
        assert not isinstance(value, MergedMapping | MergeKeyMapping), field.name
    return placement


def _refusal(root: Node, path: str, *, expand_alias: bool = False) -> str:
    with pytest.raises(WriteRefused) as caught:
        place(root, parse_path(path), path, expand_alias=expand_alias)
    assert caught.value.exit_code == 3
    message = caught.value.message
    assert message.startswith(f"{path}: ")
    assert message.endswith("no file changed")
    return message


def _at(root: Node, *keys: str) -> Node:
    """The value at ``keys`` as found (intermediate steps unwrapped)."""
    node = root
    for key in keys:
        mapping = unwrap(node)
        assert isinstance(mapping, MappingNode)
        entry = mapping.get(key)
        assert entry is not None, key
        node = entry.value
    return node


def _rel(path: Location) -> str:
    assert isinstance(path, Path)  # these fixtures are local files
    state = next(parent for parent in path.parents if parent.name == ".troupe")
    return path.relative_to(state).as_posix()


# --- The anchored node reached directly: ordinary rules (FR-003, US2) ---------------------------


def test_set_at_anchor_places_in_the_anchored_mapping(make_theatre: MakeTheatre) -> None:
    root = _load(make_theatre, SHARED)

    placement = _place(root, "defaults.model")

    assert isinstance(placement, ReplaceScalar)
    assert placement.parent is _at(root, "defaults")
    assert placement.slot == "model"
    # The parent is found at the anchor, never through ``coder``'s alias.
    alias = _at(root, "coder", "settings")
    assert isinstance(alias, AliasNode)
    assert concrete_parent(root, placement.node) == (_at(root, "defaults"), "model")


def test_set_of_anchored_scalar_places_a_scalar_replacement(make_theatre: MakeTheatre) -> None:
    root = _load(make_theatre, "model: &m opus\ncoder:\n  model: *m\n")

    placement = _place(root, "model")

    assert isinstance(placement, ReplaceScalar)
    assert placement.parent is root
    assert placement.slot == "model"
    assert placement.node is _at(root, "model")


def test_replacing_the_anchored_mapping_is_an_ordinary_collection_replacement(
    make_theatre: MakeTheatre,
) -> None:
    root = _load(make_theatre, SHARED)

    placement = _place(root, "defaults")

    assert isinstance(placement, ReplaceCollection)
    assert placement.parent is root
    assert placement.slot == "defaults"


def test_new_key_under_anchored_mapping_is_added_there(make_theatre: MakeTheatre) -> None:
    root = _load(make_theatre, SHARED)

    placement = _place(root, "defaults.top_p")

    assert isinstance(placement, AddKeys)
    assert placement.mapping is _at(root, "defaults")
    assert placement.keys == ["top_p"]


# --- Through a written alias (US3, C4, C6) ------------------------------------------------------


def test_path_through_alias_is_refused_mentioning_expand_alias(
    make_theatre: MakeTheatre,
) -> None:
    root = _load(make_theatre, SHARED)
    alias = _at(root, "coder", "settings")
    assert isinstance(alias, AliasNode)

    message = _refusal(root, "coder.settings.model")

    assert message == (
        f"coder.settings.model: coder.settings is the alias *d in {alias.origin.file.path}"
        " line 5, shared with its anchor &d; refusing to change it for every user (use"
        " --expand-alias to give this path its own copy); no file changed"
    )


def test_scalar_alias_at_path_is_refused(make_theatre: MakeTheatre) -> None:
    root = _load(make_theatre, "model: &m opus\ncoder:\n  model: *m\n")

    message = _refusal(root, "coder.model")

    assert "coder.model: coder.model is the alias *m in " in message
    assert " line 3, " in message
    assert "--expand-alias" in message


def test_new_key_below_alias_is_refused(make_theatre: MakeTheatre) -> None:
    root = _load(make_theatre, SHARED)

    assert "coder.settings is the alias *d" in _refusal(root, "coder.settings.top_p")
    assert "coder.settings is the alias *d" in _refusal(root, "coder.settings.limits.max")


def test_new_key_below_a_mapping_inside_an_alias_is_refused(make_theatre: MakeTheatre) -> None:
    text = "defaults: &d\n  limits:\n    max: 1\ncoder:\n  settings: *d\n"
    root = _load(make_theatre, text)

    assert "coder.settings is the alias *d" in _refusal(root, "coder.settings.limits.min")


def test_alias_refusal_wins_over_unchanged_value(make_theatre: MakeTheatre) -> None:
    # ``opus`` is already the value: ``place`` refuses before the applier's no-op check.
    root = _load(make_theatre, SHARED)

    assert "--expand-alias" in _refusal(root, "coder.settings.model")


def test_list_append_through_alias_is_refused(make_theatre: MakeTheatre) -> None:
    root = _load(make_theatre, "tools: &t [a, b]\ncoder:\n  tools: *t\n")

    assert "coder.tools is the alias *t" in _refusal(root, "coder.tools.2")


# --- Merge keys (A-0, FR-007, US3-4, US3-5) -----------------------------------------------------


def test_merged_value_is_refused_with_and_without_expand_alias(
    make_theatre: MakeTheatre,
) -> None:
    root = _load(make_theatre, MERGED)

    assert _refusal(root, "coder.temperature") == (
        "coder.temperature: coder.temperature comes through the merge key '<<' (from *b);"
        " refusing to change a shared value (use --expand-alias to give it its own copy);"
        " no file changed"
    )
    assert _refusal(root, "coder.temperature", expand_alias=True) == (
        "coder.temperature: coder.temperature comes through the merge key '<<' (from *b);"
        " merge keys are never written, so it cannot be expanded; no file changed"
    )


def test_inline_merge_source_is_named_as_an_inline_mapping(make_theatre: MakeTheatre) -> None:
    root = _load(make_theatre, "coder:\n  <<: {model: opus}\n  temperature: 0.2\n")

    assert "(from an inline mapping)" in _refusal(root, "coder.model")


def test_written_key_beside_merge_key_is_replaced_in_place(make_theatre: MakeTheatre) -> None:
    root = _load(make_theatre, MERGED)
    coder = _at(root, "coder")
    assert isinstance(coder, MergeKeyMapping)

    placement = _place(root, "coder.model")

    assert isinstance(placement, ReplaceScalar)
    assert placement.parent is coder.written
    assert placement.slot == "model"


def test_new_key_beside_merge_key_is_added_to_the_written_mapping(
    make_theatre: MakeTheatre,
) -> None:
    root = _load(make_theatre, MERGED)
    coder = _at(root, "coder")
    assert isinstance(coder, MergeKeyMapping)

    placement = _place(root, "coder.top_p")

    assert isinstance(placement, AddKeys)
    assert placement.mapping is coder.written
    assert placement.keys == ["top_p"]


def test_replacing_a_mapping_with_a_merge_key_is_refused(make_theatre: MakeTheatre) -> None:
    root = _load(make_theatre, MERGED)

    assert _refusal(root, "coder") == (
        "coder: this mapping uses the merge key '<<'; replacing it as a whole would rewrite"
        " the merge key, which troupe never writes; no file changed"
    )


def test_creating_a_merge_key_is_refused(make_theatre: MakeTheatre) -> None:
    root = _load(make_theatre, "coder:\n  model: opus\n")

    assert "never writes merge keys" in _refusal(root, "coder.<<")


# --- ExpandAlias (C7) ---------------------------------------------------------------------------


def test_expand_alias_returns_the_outermost_written_alias_with_its_parent_and_slot(
    make_theatre: MakeTheatre,
) -> None:
    text = (
        "limits: &l\n  max: 5\ndefaults: &d\n  model: opus\n  limits: *l\ncoder:\n  settings: *d\n"
    )
    root = _load(make_theatre, text)

    placement = _place(root, "coder.settings.limits.max", expand_alias=True)

    assert isinstance(placement, ExpandAlias)
    assert placement.alias is _at(root, "coder", "settings")
    assert placement.alias.name == "d"
    assert placement.parent is _at(root, "coder")
    assert placement.slot == "settings"


def test_expand_alias_with_an_unchanged_value_still_expands(make_theatre: MakeTheatre) -> None:
    # The applier's no-op check (WP05) decides that nothing is written.
    root = _load(make_theatre, SHARED)

    placement = _place(root, "coder.settings.model", expand_alias=True)

    assert isinstance(placement, ExpandAlias)
    assert placement.slot == "settings"


def test_scalar_alias_is_expanded_at_its_own_slot(make_theatre: MakeTheatre) -> None:
    root = _load(make_theatre, "model: &m opus\ncoder:\n  model: *m\n")

    placement = _place(root, "coder.model", expand_alias=True)

    assert isinstance(placement, ExpandAlias)
    assert placement.parent is _at(root, "coder")
    assert placement.slot == "model"


def test_list_item_alias_is_expanded_with_its_sequence_parent(make_theatre: MakeTheatre) -> None:
    text = "defaults: &d\n  model: opus\nagents:\n  - *d\n  - name: x\n"
    root = _load(make_theatre, text)

    assert "agents.0 is the alias *d" in _refusal(root, "agents.0.model")
    placement = _place(root, "agents.0.model", expand_alias=True)

    assert isinstance(placement, ExpandAlias)
    assert isinstance(placement.parent, SequenceNode)
    assert placement.parent is _at(root, "agents")
    assert placement.slot == 0


# --- Aliases on a side of an include with overrides (T012) --------------------------------------

INCLUDE_WITH_ALIAS: Files = {
    "troupe.yml": (
        "defaults: &d\n  model: opus\ncoder:\n  $ref: file:agents/coder.yaml\n  settings: *d\n"
    ),
    "agents/coder.yaml": "settings:\n  model: gpt\n  temperature: 0.7\n",
}


def test_alias_on_the_override_side_of_an_include_is_detected(
    make_theatre: MakeTheatre,
) -> None:
    root = _load(make_theatre, INCLUDE_WITH_ALIAS)
    holder = _at(root, "coder")
    assert isinstance(holder, MergedMapping)
    alias = unwrap(holder.override)
    assert isinstance(alias, MappingNode)
    settings = alias.get("settings")
    assert settings is not None and isinstance(settings.value, AliasNode)

    # A new key would land in the anchored mapping.
    assert "coder.settings is the alias *d" in _refusal(root, "coder.settings.top_p")
    # An existing value the alias side supplies.
    assert "coder.settings is the alias *d" in _refusal(root, "coder.settings.model")
    expanded = _place(root, "coder.settings.top_p", expand_alias=True)
    assert isinstance(expanded, ExpandAlias)
    assert expanded.alias is settings.value
    assert expanded.slot == "settings"
    assert _rel(expanded.parent.origin.file.path) == "troupe.yml"


def test_value_the_included_side_supplies_is_not_through_the_alias(
    make_theatre: MakeTheatre,
) -> None:
    # Over-refusing guard: ``temperature`` comes from the included file, not from ``*d``.
    root = _load(make_theatre, INCLUDE_WITH_ALIAS)

    placement = _place(root, "coder.settings.temperature")

    assert isinstance(placement, ReplaceScalar)
    assert _rel(placement.parent.origin.file.path) == "agents/coder.yaml"


def test_alias_on_the_base_side_is_detected_with_in_include(make_theatre: MakeTheatre) -> None:
    files: Files = {
        "troupe.yml": "coder:\n  $ref: file:agents/coder.yaml\n  settings:\n    model: gpt\n",
        "agents/coder.yaml": "defaults: &d\n  model: opus\nsettings: *d\n",
    }
    root = _load(make_theatre, files)

    with pytest.raises(WriteRefused) as caught:
        place(root, ["coder", "settings", "top_p"], "coder.settings.top_p", in_include=True)
    assert "coder.settings is the alias *d" in caught.value.message
    # Without ``in_include`` the key goes to the override mapping: not through the alias.
    placement = _place(root, "coder.settings.top_p")
    assert isinstance(placement, AddKeys)
    assert _rel(placement.mapping.origin.file.path) == "troupe.yml"


def test_alias_inside_an_included_file_is_detected_on_the_route(
    make_theatre: MakeTheatre,
) -> None:
    # Includes are never inside anchored nodes (C3), but an included file may hold aliases.
    files: Files = {
        "troupe.yml": "coder: file:agents/coder.yaml\n",
        "agents/coder.yaml": "defaults: &d\n  model: opus\nsettings: *d\n",
    }
    root = _load(make_theatre, files)

    message = _refusal(root, "coder.settings.model")

    assert "coder.settings is the alias *d in " in message
    assert "agents/coder.yaml line 3" in message
