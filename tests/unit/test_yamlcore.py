"""yamlcore: YAML 1.2 core-schema resolution and the spans ruamel reports (research R-13, R-14)."""

import math

import pytest

from troupe.errors import LoadError
from troupe.tree import Scalar
from troupe.yamlcore import RawMapping, RawNode, RawScalar, RawSequence, compose, resolve_plain


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("null", None),
        ("Null", None),
        ("NULL", None),
        ("~", None),
        ("", None),
        ("true", True),
        ("True", True),
        ("TRUE", True),
        ("false", False),
        ("FALSE", False),
        ("yes", "yes"),
        ("Yes", "Yes"),
        ("on", "on"),
        ("off", "off"),
        ("tRUE", "tRUE"),
        ("nULL", "nULL"),
        ("0", 0),
        ("-12", -12),
        ("+1", 1),
        ("017", 17),
        ("0o17", 15),
        ("0x1F", 31),
        ("0x1f", 31),
        ("0b101", "0b101"),
        ("1_000", "1_000"),
        ("0.2", 0.2),
        (".5", 0.5),
        ("1.", 1.0),
        ("1e3", 1000.0),
        ("-1.5E-2", -0.015),
        (".inf", math.inf),
        ("+.Inf", math.inf),
        ("-.INF", -math.inf),
        ("2001-12-14", "2001-12-14"),
        ("1:20", "1:20"),
        ("abc", "abc"),
        ("=", "="),
        ("<<", "<<"),
    ],
)
def test_resolve_plain_follows_yaml_1_2_core_schema(text: str, expected: Scalar) -> None:
    value = resolve_plain(text)

    assert (type(value), value) == (type(expected), expected)


@pytest.mark.parametrize("text", [".nan", ".NaN", ".NAN"])
def test_resolve_plain_nan_variants_are_float_nan(text: str) -> None:
    value = resolve_plain(text)

    assert isinstance(value, float)
    assert math.isnan(value)


def _scalars(node: RawNode) -> list[RawScalar]:
    if isinstance(node, RawScalar):
        return [node]
    if isinstance(node, RawMapping):
        return [s for pair in node.pairs for part in pair for s in _scalars(part)]
    return [s for item in node.items for s in _scalars(item)]


def _composed(text: str) -> RawNode:
    node = compose(text, "test.yaml")
    assert node is not None
    return node


def _slices(text: str) -> list[str]:
    return [text[s.start : s.end] for s in _scalars(_composed(text))]


def test_compose_reports_styles_and_unescaped_text() -> None:
    text = "a: plain\nb: 'it''s'\nc: \"x\\ty\"\nd: |\n  l\ne: >\n  f\n"

    scalars = _scalars(_composed(text))

    assert [(s.text, s.style) for s in scalars[1::2]] == [
        ("plain", "plain"),
        ("it's", "single"),
        ("x\ty", "double"),
        ("l\n", "literal"),
        ("f\n", "folded"),
    ]


def test_quoted_scalar_spans_include_quotes_and_exclude_comment() -> None:
    text = "a: 'x'  # c\nb: \"y\"\nc: plain   # c\n"

    assert _slices(text) == ["a", "'x'", "b", '"y"', "c", "plain"]


def test_bom_counts_as_index_zero() -> None:
    text = "\ufeffkey: value\n"

    scalars = _scalars(_composed(text))

    assert [(s.start, s.end) for s in scalars] == [(1, 4), (6, 11)]
    assert _slices(text) == ["key", "value"]


def test_crlf_counts_as_two_characters() -> None:
    text = "a: 1\r\nb: 'two'\r\nc:\r\n  - x\r\n"

    assert _slices(text) == ["a", "1", "b", "'two'", "c", "x"]
    assert _scalars(_composed(text))[3].start == 9


def test_block_scalar_span_runs_from_indicator_through_consumed_line_breaks() -> None:
    text = "a: |+\n  x\n\n\nb: >-\n  y\n# comment\nc: 1\n"

    assert _slices(text)[1] == "|+\n  x\n\n\n"
    assert _slices(text)[3] == ">-\n  y\n"


def test_block_collection_end_lies_past_trailing_blank_and_comment_lines() -> None:
    text = "a:\n  - b\n\n# c\nz: 1\n"
    root = _composed(text)
    assert isinstance(root, RawMapping)

    sequence = root.pairs[0][1]

    assert isinstance(sequence, RawSequence)
    assert text[sequence.start : sequence.end] == "- b\n\n# c\n"


def test_flow_collection_span_is_exactly_brackets() -> None:
    text = "a: [1, {b: c}]  # x\n"
    root = _composed(text)
    assert isinstance(root, RawMapping)

    flow = root.pairs[0][1]

    assert isinstance(flow, RawSequence)
    assert flow.flow
    assert text[flow.start : flow.end] == "[1, {b: c}]"


def test_empty_value_is_zero_width_plain_scalar() -> None:
    root = _composed("a:\nb: 1\n")
    assert isinstance(root, RawMapping)

    empty = root.pairs[0][1]

    assert isinstance(empty, RawScalar)
    assert (empty.text, empty.style, empty.end - empty.start) == ("", "plain", 0)


@pytest.mark.parametrize("text", ["", "# only a comment\n", "\ufeff"])
def test_empty_document_composes_to_none(text: str) -> None:
    assert compose(text, "test.yaml") is None


@pytest.mark.parametrize(
    "text",
    [
        "a: [1,\n",
        "a: 1\n b: 2\n",
        "a: 1\n---\nb: 2\n",
        "a: *undefined\n",
        "a: 'unterminated\n",
        "a: \x00\n",
    ],
)
def test_invalid_yaml_raises_load_error_naming_source(text: str) -> None:
    with pytest.raises(LoadError, match=r"cannot parse /x/troupe\.yml: "):
        compose(text, "/x/troupe.yml")


def test_parse_error_message_reports_one_based_line_of_problem() -> None:
    with pytest.raises(LoadError, match=r"mapping values are not allowed here at line 3$"):
        compose("a: 1\nb: 2\n  c: 3\nd: 4\n", "f.yaml")


@pytest.mark.parametrize("text", ["a: &x 1\nb: *x\n", "a: !!str 1\n", "a: &m\n  b: 1\n"])
def test_anchors_aliases_and_tags_are_refused(text: str) -> None:
    with pytest.raises(LoadError, match=r"f\.yaml: anchors and tags are not supported at line"):
        compose(text, "f.yaml")
