"""Leaves of the merged configuration (flatten) and leaf-level differences (diff, same)."""

import pytest

from conftest import MakeTheatre
from troupe.leaves import Change, JsonScalar, diff, flatten, same
from troupe.loader import load
from troupe.theatre import locate


def _leaves(make_theatre: MakeTheatre, files: dict[str, str | bytes]) -> dict[str, JsonScalar]:
    return flatten(load(locate(make_theatre(files)).config_file))


def test_flatten_lists_nested_mapping_and_list_leaves_in_document_order(
    make_theatre: MakeTheatre,
) -> None:
    leaves = _leaves(
        make_theatre,
        {
            "troupe.yml": (
                "model:\n  name: gpt\n  temperature: 0.2\n"
                "tools: [search, 3, true, null]\n"
                "retries: 1\n"
            )
        },
    )

    assert list(leaves.items()) == [
        ("model.name", "gpt"),
        ("model.temperature", 0.2),
        ("tools.0", "search"),
        ("tools.1", 3),
        ("tools.2", True),
        ("tools.3", None),
        ("retries", 1),
    ]


def test_flatten_puts_yaml_include_leaves_at_merged_paths(make_theatre: MakeTheatre) -> None:
    leaves = _leaves(
        make_theatre,
        {
            "troupe.yml": "agents:\n  coder: file:agents/coder.yaml\nafter: x\n",
            "agents/coder.yaml": "name: Cody\nskills:\n  - python\n",
        },
    )

    assert list(leaves.items()) == [
        ("agents.coder.name", "Cody"),
        ("agents.coder.skills.0", "python"),
        ("after", "x"),
    ]


def test_flatten_makes_text_include_one_leaf_holding_the_file_text(
    make_theatre: MakeTheatre,
) -> None:
    leaves = _leaves(
        make_theatre,
        {"troupe.yml": "prompt: file:prompt.md\n", "prompt.md": "Be kind.\r\nBe brief.\r\n"},
    )

    assert leaves == {"prompt": "Be kind.\r\nBe brief.\r\n"}


def test_flatten_gives_no_leaves_for_empty_collections(make_theatre: MakeTheatre) -> None:
    leaves = _leaves(make_theatre, {"troupe.yml": "a: {}\nb: []\nc: 1\n"})

    assert leaves == {"c": 1}


def test_flatten_of_empty_document_is_empty(make_theatre: MakeTheatre) -> None:
    assert _leaves(make_theatre, {"troupe.yml": ""}) == {}


@pytest.mark.parametrize(
    ("a", "b"),
    [(1, 1.0), (1, "1"), (True, 1), (False, 0), (None, ""), (0.0, False)],
)
def test_same_distinguishes_values_of_different_types(a: JsonScalar, b: JsonScalar) -> None:
    assert not same(a, b)
    assert not same(b, a)


@pytest.mark.parametrize("value", [1, 1.5, "x", True, None, float("nan"), float("inf")])
def test_same_holds_for_equal_values_including_nan(value: JsonScalar) -> None:
    assert same(value, value)


def test_diff_of_identical_leaves_is_empty() -> None:
    leaves: dict[str, JsonScalar] = {"a": 1, "b.0": "x", "c": None}

    assert diff(leaves, dict(leaves)) == []


def test_diff_reports_changed_leaf_as_set_with_old_and_new() -> None:
    assert diff({"a": 1, "b": 2}, {"a": 1, "b": 3}) == [Change("set", "b", 2, 3)]


def test_diff_reports_created_leaf_as_set_with_null_old() -> None:
    assert diff({"a": 1}, {"a": 1, "b": "new"}) == [Change("set", "b", None, "new")]


def test_diff_reports_created_null_leaf_as_set() -> None:
    assert diff({}, {"a": None}) == [Change("set", "a", None, None)]


def test_diff_reports_vanished_leaf_as_remove_with_null_new() -> None:
    assert diff({"a": 1, "b": None}, {"a": 1}) == [Change("remove", "b", None, None)]


def test_diff_reports_list_shrink_as_remove_of_the_last_index() -> None:
    before: dict[str, JsonScalar] = {"tools.0": "a", "tools.1": "b"}

    assert diff(before, {"tools.0": "a"}) == [Change("remove", "tools.1", "b", None)]


def test_diff_reports_type_change_as_set() -> None:
    assert diff({"a": 1}, {"a": "1"}) == [Change("set", "a", 1, "1")]


def test_diff_lists_sets_in_after_order_then_removes_in_before_order() -> None:
    before: dict[str, JsonScalar] = {"x": 1, "y": 2, "z": 3, "w": 4}
    after: dict[str, JsonScalar] = {"n": 0, "y": 20, "m": 5}

    assert diff(before, after) == [
        Change("set", "n", None, 0),
        Change("set", "y", 2, 20),
        Change("set", "m", None, 5),
        Change("remove", "x", 1, None),
        Change("remove", "z", 3, None),
        Change("remove", "w", 4, None),
    ]
