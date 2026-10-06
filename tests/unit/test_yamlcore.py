"""yamlcore: YAML 1.2 core-schema resolution, the spans of composed nodes (research R-13, R-14),
and anchors and aliases from parser events (research R-1, R-2)."""

import math
from pathlib import Path

import pytest
from ruamel.yaml import YAML
from ruamel.yaml.nodes import MappingNode, Node, SequenceNode

from troupe.errors import LoadError
from troupe.tree import Scalar
from troupe.yamlcore import (
    RawAlias,
    RawMapping,
    RawNode,
    RawScalar,
    RawSequence,
    compose,
    resolve_plain,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


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
    if isinstance(node, RawSequence):
        return [s for item in node.items for s in _scalars(item)]
    return []


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
def test_anchors_and_aliases_are_refused_by_default(text: str) -> None:
    with pytest.raises(LoadError, match=r"f\.yaml: anchors and tags are not supported at line 1$"):
        compose(text, "f.yaml")


def test_default_refusal_names_the_line_of_the_first_anchor_alias_or_tag() -> None:
    with pytest.raises(LoadError, match=r"anchors and tags are not supported at line 3$"):
        compose("a: 1\nb: 2\nc: !t x\nd: &x 1\ne: *x\n", "f.yaml")


def test_default_reports_an_undefined_alias_as_before() -> None:
    with pytest.raises(
        LoadError, match=r"^cannot parse f\.yaml: found undefined alias 'u' at line 2$"
    ):
        compose("a: &x 1\nb: *u\n", "f.yaml")


def test_parse_error_after_an_anchor_wins_over_the_refusal() -> None:
    with pytest.raises(LoadError, match=r"^cannot parse f\.yaml: expected the node content"):
        compose("a: &x 1\nb: [1,\n", "f.yaml")


def test_second_document_is_refused_with_rumels_message() -> None:
    with pytest.raises(
        LoadError, match=r"^cannot parse f\.yaml: but found another document at line 2$"
    ):
        compose("a: 1\n---\nb: 2\n", "f.yaml")


# --- Anchors and aliases (allow_anchors=True) ----------------------------------------------------

REPORTER = "defaults: &d\n  model: opus\ncoder:\n  settings: *d\n"


def _allowed(text: str) -> RawNode:
    node = compose(text, "f.yaml", allow_anchors=True)
    assert node is not None
    return node


def _value(text: str, key: str) -> RawNode:
    root = _allowed(text)
    assert isinstance(root, RawMapping)
    return next(v for k, v in root.pairs if isinstance(k, RawScalar) and k.text == key)


def test_alias_records_its_own_span_and_target() -> None:
    root = _allowed(REPORTER)
    assert isinstance(root, RawMapping)
    defaults = root.pairs[0][1]
    coder = root.pairs[1][1]
    assert isinstance(coder, RawMapping)

    alias = coder.pairs[0][1]

    assert isinstance(alias, RawAlias)
    assert (alias.name, REPORTER[alias.start : alias.end]) == ("d", "*d")
    assert alias.target is defaults


def test_anchor_records_the_ampersand_token_span() -> None:
    anchor = _value(REPORTER, "defaults")
    assert isinstance(anchor, RawMapping)
    assert anchor.anchor is not None

    assert (anchor.anchor.name, REPORTER[anchor.anchor.start : anchor.anchor.end]) == ("d", "&d")


def test_anchored_block_mapping_starts_at_its_first_key() -> None:
    mapping = _value(REPORTER, "defaults")

    assert REPORTER[mapping.start : mapping.end] == "model: opus\n"


def _same_span_as_without_anchor(value: str, anchor: str = "&a ") -> None:
    plain = _value(f"k: {value}\n", "k")
    anchored = _value(f"k: {anchor}{value}\n", "k")

    assert (anchored.start, anchored.end) == (plain.start + len(anchor), plain.end + len(anchor))


@pytest.mark.parametrize("value", ["\n  - x\n  - y", "\n- x", "\n  # comment\n\n  - x"])
def test_anchored_block_sequence_starts_at_its_first_dash(value: str) -> None:
    text = f"k: &a{value}\n"

    sequence = _value(text, "k")

    assert isinstance(sequence, RawSequence)
    assert text[sequence.start] == "-"
    _same_span_as_without_anchor(value, "&a")


@pytest.mark.parametrize(("value", "bracket"), [("[1, 2]", "["), ("{b: 1}", "{"), ("\n  [1]", "[")])
def test_anchored_flow_collection_starts_at_bracket(value: str, bracket: str) -> None:
    text = f"k: &a {value}\n"

    collection = _value(text, "k")

    assert text[collection.start] == bracket
    _same_span_as_without_anchor(value)


@pytest.mark.parametrize(
    ("value", "anchor"),
    [
        ("plain words", "&a "),
        ("'single'", "&a "),
        ('"double"', "&a "),
        ("|\n  literal\n", "&a "),
        (">-\n  folded\n", "&a "),
        ("'two spaces'", "&a  "),
        ("\n  next line", "&a"),
        ("\n  # comment\n  after comment", "&a"),
    ],
)
def test_anchored_scalar_span_excludes_the_anchor(value: str, anchor: str) -> None:
    scalar = _value(f"k: {anchor}{value}\n", "k")

    assert isinstance(scalar, RawScalar)
    assert scalar.anchor is not None
    _same_span_as_without_anchor(value, anchor)


@pytest.mark.parametrize(
    ("text", "anchor_end"), [("a: &x\nb: 1\n", 5), ("a: &x", 5), ("- [&x , b]\n", 5)]
)
def test_anchored_empty_value_is_zero_width_null_after_anchor(text: str, anchor_end: int) -> None:
    root = _allowed(text)
    if isinstance(root, RawMapping):
        empty = root.pairs[0][1]
    else:
        assert isinstance(root, RawSequence)
        flow = root.items[0]
        assert isinstance(flow, RawSequence)
        empty = flow.items[0]

    assert isinstance(empty, RawScalar)
    assert empty.anchor is not None
    assert (empty.text, empty.style, empty.start, empty.end) == (
        "",
        "plain",
        anchor_end,
        anchor_end,
    )
    assert resolve_plain(empty.text) is None


def test_redefined_anchor_applies_to_later_aliases() -> None:
    text = "a: &x 1\nb: *x\nc: &x 2\nd: *x\n"

    b, d = _value(text, "b"), _value(text, "d")

    assert isinstance(b, RawAlias)
    assert isinstance(d, RawAlias)
    assert (b.target, d.target) == (_value(text, "a"), _value(text, "c"))
    assert isinstance(d.target, RawScalar)
    assert d.target.text == "2"


def test_anchor_redefined_inside_its_own_node_is_the_more_recent_one() -> None:
    root = _allowed("- &x [&x 1]\n- *x\n")
    assert isinstance(root, RawSequence)

    alias = root.items[1]

    assert isinstance(alias, RawAlias)
    assert isinstance(alias.target, RawScalar)
    assert alias.target.text == "1"


def test_undefined_alias_is_refused_naming_line() -> None:
    with pytest.raises(LoadError, match=r"^cannot parse f\.yaml: undefined alias \*u at line 2$"):
        compose("a: &x 1\nb: *u\n", "f.yaml", allow_anchors=True)


@pytest.mark.parametrize("text", ["a: 1\nb: &x [*x]\n", "a: 1\nb: &x\n  c: *x\n"])
def test_recursive_alias_is_refused_naming_line(text: str) -> None:
    line = text.count("\n", 0, text.index("*x")) + 1
    with pytest.raises(
        LoadError, match=rf"^cannot parse f\.yaml: recursive alias \*x at line {line}$"
    ):
        compose(text, "f.yaml", allow_anchors=True)


@pytest.mark.parametrize(
    "text",
    [
        "a: 1\nb: !!str 1\n",
        "a: 1\nb: !t x\n",
        "a: 1\nb: !<tag:x.org,2000:t> y\n",
        "a: 1\nb: &x !t 1\n",
    ],
)
def test_tags_are_refused_when_anchors_are_allowed(text: str) -> None:
    with pytest.raises(
        LoadError, match=r"^cannot parse f\.yaml: tags are not supported at line 2$"
    ):
        compose(text, "f.yaml", allow_anchors=True)


def test_unanchored_nodes_carry_no_anchor() -> None:
    root = _allowed("a: [1, {b: c}]\n")

    assert isinstance(root, RawMapping)
    assert root.anchor is None
    assert all(s.anchor is None for s in _scalars(root))


# --- Spans without anchors match ruamel's own composer (R-2 regression guard) --------------------

_CORPUS = [
    "a: plain\nb: 'it''s'\nc: \"x\\ty\"\nd: |\n  l\ne: >\n  f\n",
    "a: |+\n  x\n\n\nb: >-\n  y\n# comment\nc: 1\n",
    "a: |-\n  x\n\nb: |\n  y\n",
    "keep: |+\n  x\n\n",
    "a: [1, {b: c}]  # x\n",
    "a:\nb: 1\nc:\n- \n- x\nd:",
    "a:\n  - b\n\n# c\nz: 1\n",
    "\ufeffkey: value\n",
    "a: 1\r\nb: 'two'\r\nc:\r\n  - x\r\n",
    "# head\nmodel:\n  # inner\n  name: x   # trailing\n  tools: [a, b]\nlist:\n- a\n-   b\n",
    "a:\n  b:\n    c: 1\n  d: 2\n\n\n",
    "multi: line\n  plain\nnext: 1\n",
    "? complex\n: value\n",
    "- - a\n  - b\n- {x: y}\n- ''\n",
    "{a: 1, b: [x, y]}\n",
    "[]\n",
    "plain\n",
    (FIXTURES / "pre_lineage" / "troupe.yml").read_text(encoding="utf-8"),
]


def _ruamel_spans(node: Node) -> list[tuple[int, int]]:
    spans = [(node.start_mark.index, node.end_mark.index)]
    if isinstance(node, MappingNode):
        spans += [
            span
            for key, value in node.value
            for part in (key, value)
            for span in _ruamel_spans(part)
        ]
    elif isinstance(node, SequenceNode):
        spans += [span for item in node.value for span in _ruamel_spans(item)]
    return spans


def _raw_spans(node: RawNode) -> list[tuple[int, int]]:
    spans = [(node.start, node.end)]
    if isinstance(node, RawMapping):
        spans += [span for pair in node.pairs for part in pair for span in _raw_spans(part)]
    elif isinstance(node, RawSequence):
        spans += [span for item in node.items for span in _raw_spans(item)]
    return spans


@pytest.mark.parametrize("allow_anchors", [False, True])
@pytest.mark.parametrize("text", _CORPUS)
def test_spans_without_anchors_are_unchanged(text: str, allow_anchors: bool) -> None:
    expected = YAML(typ="safe", pure=True).compose(text)

    composed = compose(text, "f.yaml", allow_anchors=allow_anchors)

    assert composed is not None
    assert _raw_spans(composed) == _ruamel_spans(expected)
