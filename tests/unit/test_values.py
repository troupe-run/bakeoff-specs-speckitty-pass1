"""VALUE parsing (FR-004) and scalar printing (FR-005)."""

import math

import pytest

from troupe.errors import UsageError
from troupe.tree import Scalar
from troupe.values import Value, format_scalar, parse_value


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
