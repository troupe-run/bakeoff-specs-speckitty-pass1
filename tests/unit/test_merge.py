"""``merge.deep_merge`` on trees the real loader builds from real files (FR-002, research R-2).

Each test writes a theatre whose ``troupe.yml`` holds a mapping-form include of
``agents/coder.yaml`` and inspects the ``MergedMapping`` the loader returns for ``coder``.
"""

from pathlib import Path

from conftest import MakeTheatre
from troupe.loader import load
from troupe.merge import REF_KEY
from troupe.paths import unwrap
from troupe.theatre import locate
from troupe.tree import MappingNode, MergedMapping, Node, ScalarNode, SequenceNode, YamlInclude

CODER = "model: gpt\ntemperature: 0.7\ntools:\n  shell: true\nstop: [a, b]\n"


def _coder(make_theatre: MakeTheatre, overrides: str, coder: str = CODER) -> MergedMapping:
    """Load a theatre with ``coder: {$ref: ..., <overrides>}``; return the merged ``coder``."""
    return _theatre_and_coder(make_theatre, overrides, coder)[1]


def _theatre_and_coder(
    make_theatre: MakeTheatre, overrides: str, coder: str = CODER
) -> tuple[Path, MergedMapping]:
    theatre = make_theatre(
        {
            "troupe.yml": "coder:\n  $ref: file:agents/coder.yaml\n" + overrides,
            "agents/coder.yaml": coder,
        }
    )
    root = load(locate(theatre).config_file)
    assert isinstance(root, MappingNode)
    entry = root.get("coder")
    assert entry is not None
    assert isinstance(entry.value, MergedMapping)
    return theatre, entry.value


def _value(mapping: MappingNode, key: str) -> Node:
    entry = mapping.get(key)
    assert entry is not None, key
    return entry.value


def _scalar(mapping: MappingNode, key: str) -> ScalarNode:
    node = _value(mapping, key)
    assert isinstance(node, ScalarNode)
    return node


def _included_root(merged: MergedMapping) -> MappingNode:
    """The included file's own tree (the base side, unwrapped)."""
    assert isinstance(merged.base, YamlInclude)
    root = unwrap(merged.base)
    assert isinstance(root, MappingNode)
    return root


def test_override_scalar_replaces_included_scalar(make_theatre: MakeTheatre) -> None:
    merged = _coder(make_theatre, "  temperature: 0.3\n")

    assert _scalar(merged, "temperature").value == 0.3
    assert _scalar(merged, "model").value == "gpt"


def test_nested_mappings_merge_recursively_with_both_sides_kept(
    make_theatre: MakeTheatre,
) -> None:
    merged = _coder(
        make_theatre,
        "  tools:\n    web: true\n    limits:\n      max: 9\n",
        coder="tools:\n  shell: true\n  limits:\n    max: 5\n    min: 1\n",
    )

    tools = _value(merged, "tools")
    assert isinstance(tools, MergedMapping)
    assert tools.ref is None
    assert [(e.key, _scalar(tools, e.key).value) for e in tools.entries if e.key != "limits"] == [
        ("shell", True),
        ("web", True),
    ]
    limits = _value(tools, "limits")
    assert isinstance(limits, MergedMapping)
    assert [(e.key, _scalar(limits, e.key).value) for e in limits.entries] == [
        ("max", 9),
        ("min", 1),
    ]


def test_override_list_replaces_included_list_entirely(make_theatre: MakeTheatre) -> None:
    merged = _coder(make_theatre, "  stop: [c]\n")

    stop = _value(merged, "stop")
    assert isinstance(stop, SequenceNode)
    assert [item.value for item in stop.items if isinstance(item, ScalarNode)] == ["c"]
    assert len(stop.items) == 1


def test_override_mapping_replaces_included_scalar_and_vice_versa(
    make_theatre: MakeTheatre,
) -> None:
    merged = _coder(make_theatre, "  model:\n    name: claude\n  tools: none\n")

    model = _value(merged, "model")
    assert type(model) is MappingNode  # a plain override mapping, not a merge
    assert _scalar(model, "name").value == "claude"
    assert _scalar(merged, "tools").value == "none"


def test_merged_keys_are_included_order_then_override_only_keys(
    make_theatre: MakeTheatre,
) -> None:
    merged = _coder(make_theatre, "  zeta: 1\n  stop: [c]\n  alpha: 2\n  model: x\n")

    assert [entry.key for entry in merged.entries] == [
        "model",
        "temperature",
        "tools",
        "stop",
        "zeta",
        "alpha",
    ]


def test_ref_key_never_appears_in_merged_entries(make_theatre: MakeTheatre) -> None:
    merged = _coder(make_theatre, "  temperature: 0.3\n")

    assert REF_KEY not in [entry.key for entry in merged.entries]
    assert isinstance(merged.override, MappingNode)
    assert merged.override.get(REF_KEY) is not None  # the holder as written keeps it
    assert merged.ref is merged.base
    assert merged.ref is not None and merged.ref.holder is merged.override


def test_merged_entries_reuse_the_nodes_of_each_side(make_theatre: MakeTheatre) -> None:
    merged = _coder(make_theatre, "  temperature: 0.3\n")
    included = _included_root(merged)
    holder = merged.override
    assert isinstance(holder, MappingNode)

    assert _value(merged, "model") is _value(included, "model")
    assert merged.get("model") is included.get("model")
    assert _value(merged, "temperature") is _value(holder, "temperature")
    assert merged.get("temperature") is holder.get("temperature")
    assert _value(merged, "stop") is _value(included, "stop")


def test_override_scalar_origin_is_including_file_and_base_scalar_origin_is_included_file(
    make_theatre: MakeTheatre,
) -> None:
    theatre, merged = _theatre_and_coder(
        make_theatre, "  temperature: 0.3\n  tools:\n    web: true\n"
    )
    tools = _value(merged, "tools")
    assert isinstance(tools, MappingNode)
    including = (theatre / ".troupe/troupe.yml").resolve()
    included = (theatre / ".troupe/agents/coder.yaml").resolve()

    assert [
        _scalar(merged, "temperature").origin.file.path,
        _scalar(tools, "web").origin.file.path,
        _scalar(merged, "model").origin.file.path,
        _scalar(tools, "shell").origin.file.path,
    ] == [including, including, included, included]
    assert merged.origin.file.path == including
