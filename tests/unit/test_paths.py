"""paths: parsing, include-transparent walking and lookup errors (FR-003)."""

from pathlib import Path

import pytest

from troupe.errors import PathError, UsageError
from troupe.loader import load
from troupe.paths import is_index, lookup, parse_path, unwrap, walk
from troupe.tree import MappingNode, Node, ScalarNode, SequenceNode, TextInclude, YamlInclude


@pytest.fixture
def root(tmp_path: Path) -> Node:
    (tmp_path / "agents.yaml").write_text("lead:\n  name: ada\n", encoding="utf-8")
    (tmp_path / "prompt.txt").write_text("hello\n", encoding="utf-8")
    (tmp_path / "troupe.yml").write_text(
        "model:\n  temperature: 0.2\n"
        "agents: file:agents.yaml\n"
        "prompt: file:prompt.txt\n"
        "tools:\n  - grep\n  - sed\n"
        "'7': seven\n",
        encoding="utf-8",
    )
    return load(tmp_path / "troupe.yml")


def test_parse_path_splits_on_dots() -> None:
    assert parse_path("a.b.0") == ["a", "b", "0"]


@pytest.mark.parametrize("text", ["", "a..b", ".a", "a."])
def test_parse_path_with_empty_segment_is_usage_error_naming_path(text: str) -> None:
    with pytest.raises(UsageError, match=f"invalid path '{text}'"):
        parse_path(text)


@pytest.mark.parametrize(
    ("segment", "expected"),
    [("0", True), ("12", True), ("1a", False), ("-1", False), ("²", False), ("", False)],
)
def test_is_index_accepts_ascii_digits_only(segment: str, expected: bool) -> None:
    assert is_index(segment) is expected


def test_walk_full_path_has_no_remaining_and_one_node_per_segment(root: Node) -> None:
    result = walk(root, ["model", "temperature"])

    assert result.remaining == []
    assert len(result.nodes) == 3
    assert result.nodes[0] is root
    leaf = result.nodes[-1]
    assert isinstance(leaf, ScalarNode)
    assert leaf.value == 0.2


def test_walk_through_yaml_include_continues_at_its_root(root: Node) -> None:
    result = walk(root, ["agents", "lead", "name"])

    assert result.remaining == []
    assert isinstance(result.nodes[1], YamlInclude)
    leaf = result.nodes[-1]
    assert isinstance(leaf, ScalarNode)
    assert (leaf.value, leaf.origin.file.path.name) == ("ada", "agents.yaml")


def test_walk_keeps_include_node_and_unwrap_returns_embedded_root(root: Node) -> None:
    found = walk(root, ["agents"]).nodes[-1]

    assert isinstance(found, YamlInclude)
    assert isinstance(unwrap(found), MappingNode)
    assert unwrap(found) is found.root


def test_walk_indexes_list(root: Node) -> None:
    leaf = walk(root, ["tools", "1"]).nodes[-1]

    assert isinstance(leaf, ScalarNode)
    assert leaf.value == "sed"


def test_walk_digit_segment_on_mapping_is_key_lookup(root: Node) -> None:
    leaf = walk(root, ["7"]).nodes[-1]

    assert isinstance(leaf, ScalarNode)
    assert leaf.value == "seven"


def test_walk_stops_at_missing_key_with_remaining_segments(root: Node) -> None:
    result = walk(root, ["model", "missing", "deeper"])

    assert result.remaining == ["missing", "deeper"]
    assert isinstance(result.nodes[-1], MappingNode)


def test_walk_stops_at_out_of_range_index_with_remaining(root: Node) -> None:
    result = walk(root, ["tools", "2", "x"])

    assert result.remaining == ["2", "x"]
    assert isinstance(result.nodes[-1], SequenceNode)


def test_walk_non_digit_segment_on_list_is_path_error(root: Node) -> None:
    with pytest.raises(PathError, match=r"^tools\.first: tools is a list; expected an index"):
        walk(root, ["tools", "first"])


def test_walk_through_scalar_is_path_error_naming_prefix(root: Node) -> None:
    with pytest.raises(PathError, match=r"^model\.temperature\.x: model\.temperature is a scalar"):
        walk(root, ["model", "temperature", "x"])


def test_walk_into_text_include_is_path_error(root: Node) -> None:
    with pytest.raises(PathError, match=r"^prompt\.x: prompt is a scalar"):
        walk(root, ["prompt", "x"])


def test_lookup_returns_text_include_as_found(root: Node) -> None:
    assert isinstance(lookup(root, ["prompt"], "prompt"), TextInclude)


def test_lookup_missing_path_is_path_error_naming_path(root: Node) -> None:
    with pytest.raises(PathError, match=r"^path not found: model\.top_p \(no model\.top_p\)"):
        lookup(root, ["model", "top_p"], "model.top_p")


def test_lookup_out_of_range_index_is_path_error(root: Node) -> None:
    with pytest.raises(PathError, match=r"path not found: tools\.5"):
        lookup(root, ["tools", "5"], "tools.5")
