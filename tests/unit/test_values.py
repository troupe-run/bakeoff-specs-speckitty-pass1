"""VALUE parsing (FR-004), scalar printing (FR-005) and scalar detection (FR-001/FR-013)."""

import math
from pathlib import Path

import pytest

from troupe.errors import UsageError
from troupe.loader import load
from troupe.paths import lookup
from troupe.tree import Node, Scalar
from troupe.values import ScalarValue, Value, format_scalar, parse_value, scalar_of


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0.2", 0.2),
        ("-5", -5),
        ("0x1F", 31),
        ("true", True),
        ("False", False),
        ("null", None),
        ("~", None),
        ("", None),
        ("abc", "abc"),
        ('"0.2"', "0.2"),
        ("'true'", "true"),
        ("yes", "yes"),
        ("2001-12-14", "2001-12-14"),
        ("1_000", "1_000"),
        ("hello world", "hello world"),
        ('"line one\\nline two\\n"', "line one\nline two\n"),
        ("{a: 1}", {"a": 1}),
        ("[a, b]", ["a", "b"]),
        ("[]", []),
        ("{}", {}),
        ("{a: [1, {b: null}], 'c d': \"x\"}", {"a": [1, {"b": None}], "c d": "x"}),
        ("{1: one}", {"1": "one"}),
        ("  0.2  # trailing comment", 0.2),
    ],
)
def test_parse_value_resolves_one_yaml_core_flow_node(text: str, expected: Value) -> None:
    parsed = parse_value(text)

    assert parsed == expected
    assert type(parsed) is type(expected)


def test_parse_value_keeps_bool_and_int_types_inside_collections() -> None:
    parsed = parse_value("[1, true, 1.0]")

    assert isinstance(parsed, list)
    assert [type(item) for item in parsed] == [int, bool, float]


@pytest.mark.parametrize("text", [".inf", "-.Inf", ".nan"])
def test_parse_value_resolves_special_floats(text: str) -> None:
    parsed = parse_value(text)

    assert isinstance(parsed, float)
    assert not math.isfinite(parsed)


@pytest.mark.parametrize(
    "text",
    [
        "a: 1",
        "a: 1\nb: 2\n",
        "- a",
        "- a\n- b\n",
        "|\n  text\n",
        ">\n  text\n",
    ],
)
def test_parse_value_rejects_block_nodes_with_usage_error(text: str) -> None:
    with pytest.raises(UsageError, match="VALUE is not a single YAML flow node") as info:
        parse_value(text)

    assert repr(text) in info.value.message


@pytest.mark.parametrize(
    "text",
    [
        "[a, b",
        "{a: 1",
        '"unterminated',
        "a\n---\nb",
        "&x 1",
        "!!str 1",
        "*x",
    ],
)
def test_parse_value_rejects_unparsable_text_with_usage_error_naming_value(text: str) -> None:
    with pytest.raises(UsageError) as info:
        parse_value(text)

    assert info.value.exit_code == 2
    assert "VALUE" in info.value.message
    assert repr(text) in info.value.message


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        # A lone alias has no anchor before it: unchanged from before anchors were composed.
        ("*d", "found undefined alias 'd' at line 1"),
        ("&a 1", "anchors and tags are not supported at line 1"),
        ("[&a 1, *a]", "anchors and tags are not supported at line 1"),
        ("!t x", "anchors and tags are not supported at line 1"),
    ],
)
def test_parse_value_rejects_anchor_alias_and_tag_with_usage_error(text: str, problem: str) -> None:
    with pytest.raises(UsageError) as info:
        parse_value(text)

    assert info.value.exit_code == 2
    assert info.value.message == f"cannot parse VALUE {text!r}: {problem}"


@pytest.mark.parametrize("text", ["{a: 1, a: 2}", "{[a]: 1}"])
def test_parse_value_rejects_ambiguous_mapping_keys(text: str) -> None:
    with pytest.raises(UsageError) as info:
        parse_value(text)

    assert repr(text) in info.value.message


@pytest.mark.parametrize(
    ("value", "printed"),
    [
        ("Ada", "Ada\n"),
        ("", "\n"),
        ("line one\nline two\n", "line one\nline two\n"),
        ("a\r\nb\r\n", "a\r\nb\r\n"),
        ("no newline\r", "no newline\r\n"),
        ("0.2", "0.2\n"),
        (True, "true\n"),
        (False, "false\n"),
        (None, "null\n"),
        (0, "0\n"),
        (42, "42\n"),
        (-7, "-7\n"),
        (0.2, "0.2\n"),
        (1.0, "1.0\n"),
        (1e20, "1e+20\n"),
        (math.inf, "inf\n"),
        (-math.inf, "-inf\n"),
        (math.nan, "nan\n"),
    ],
)
def test_format_scalar_prints_per_contract(value: Scalar, printed: str) -> None:
    assert format_scalar(value) == printed


def _node_at(tmp_path: Path, files: dict[str, str], path: str) -> Node:
    for rel, text in files.items():
        (tmp_path / rel).write_text(text, encoding="utf-8")
    return lookup(load(tmp_path / "troupe.yml"), path.split("."), path)


def test_scalar_of_null_scalar_is_a_scalar_with_none_value(tmp_path: Path) -> None:
    node = _node_at(tmp_path, {"troupe.yml": "stop: null\n"}, "stop")

    assert scalar_of(node) == ScalarValue(None)


def test_scalar_of_text_include_is_its_text(tmp_path: Path) -> None:
    files = {"troupe.yml": "prompt: file:sys.md\n", "sys.md": "a: 1\n"}

    assert scalar_of(_node_at(tmp_path, files, "prompt")) == ScalarValue("a: 1\n")


@pytest.mark.parametrize("path", ["model", "tools", "agent"])
def test_scalar_of_mapping_and_list_is_none(tmp_path: Path, path: str) -> None:
    files = {
        "troupe.yml": "model:\n  t: 0.2\ntools: [a]\nagent: file:agent.yml\n",
        "agent.yml": "name: Ada\n",
    }

    assert scalar_of(_node_at(tmp_path, files, path)) is None


def test_scalar_of_unwraps_yaml_include_with_scalar_root(tmp_path: Path) -> None:
    files = {"troupe.yml": "level: file:level.yml\n", "level.yml": "3\n"}

    assert scalar_of(_node_at(tmp_path, files, "level")) == ScalarValue(3)
