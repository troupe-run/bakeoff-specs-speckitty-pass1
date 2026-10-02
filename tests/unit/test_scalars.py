"""writeback.scalars: quoting representability, style choice and rendering (FR-015, R-10)."""

import itertools
import math
import random

import pytest

from troupe.tree import Scalar
from troupe.writeback.scalars import (
    Context,
    QuoteStyle,
    can_plain,
    can_single,
    choose_style,
    render_nonstring,
    render_scalar,
    render_string,
)
from troupe.yamlcore import RawMapping, RawScalar, RawSequence, compose, resolve_plain


def _read_back(rendered: str, context: Context) -> RawScalar:
    """Compose ``rendered`` as a block mapping value or a flow sequence item."""
    root = compose(f"k: {rendered}\n" if context == "block" else f"[{rendered}]\n", "test")
    if isinstance(root, RawMapping):
        node = root.pairs[0][1]
    else:
        assert isinstance(root, RawSequence)
        node = root.items[0]
    assert isinstance(node, RawScalar)
    return node


@pytest.mark.parametrize(
    "s", ["abc", "hello world", "a-b", "x:y", "it's", "a#b", "é日本😀", "1.2.3"]
)
@pytest.mark.parametrize("context", ["block", "flow"])
def test_can_plain_accepts_ordinary_text(s: str, context: Context) -> None:
    assert can_plain(s, context)


@pytest.mark.parametrize(
    "s",
    [
        "true",
        "False",
        "0.2",
        "42",
        "0x1F",
        "null",
        "~",
        ".inf",
        "",
        " lead",
        "trail ",
        "a: b",
        "a #b",
        "end:",
        "#x",
        "-",
        "?",
        ":",
        "- x",
        "? x",
        "[x",
        "{x",
        "'q",
        '"q',
        "&a",
        "*a",
        "!t",
        "|",
        ">",
        "%x",
        "@x",
        "`x",
        "---",
        "---x",
        "...x",
        "line\nbreak",
        "cr\rhere",
        "tab\there",
        "bell\a",
        "bom\ufeff",
        "ls\u2028x",
        "nel\x85x",
        "ps\u2029x",
        "\xa0lead",
        "trail\u3000",
        "pua\ue000\x01",
    ],
)
@pytest.mark.parametrize("context", ["block", "flow"])
def test_can_plain_refuses_text_that_would_not_read_back_as_the_same_string(
    s: str, context: Context
) -> None:
    assert not can_plain(s, context)


@pytest.mark.parametrize("s", ["a,b", "a[b", "a]b", "a{b", "a}b"])
def test_can_plain_refuses_flow_indicators_only_in_flow_context(s: str) -> None:
    assert can_plain(s, "block")
    assert not can_plain(s, "flow")


@pytest.mark.parametrize("s", ["-v", ":x", "-x y", "--x", ":-", "-1a"])
@pytest.mark.parametrize("context", ["block", "flow"])
def test_can_plain_accepts_leading_indicator_followed_by_a_safe_character(
    s: str, context: Context
) -> None:
    assert can_plain(s, context)
    assert (_read_back(s, context).text, _read_back(s, context).style) == (s, "plain")


def test_can_plain_accepts_question_mark_start_only_where_it_reads_back_as_plain() -> None:
    # In a flow collection "?x" composes as a single-pair mapping, so the round-trip check refuses.
    assert can_plain("?x", "block")
    assert not can_plain("?x", "flow")


@pytest.mark.parametrize(
    "s",
    [
        "\U0001f469\u200d\U0001f4bb dev",  # emoji ZWJ sequence
        "a\u200bb",  # zero-width space
        "a\xa0b",  # no-break space
        "a\u3000b",  # ideographic space
        "soft\xadhyphen",
        "ltr\u200emark",
        "pua\ue000\U000f0000",
    ],
)
@pytest.mark.parametrize("context", ["block", "flow"])
def test_can_plain_accepts_yaml_printable_non_ascii_characters(s: str, context: Context) -> None:
    assert can_plain(s, context)


@pytest.mark.parametrize(
    "s",
    ["", "it's", " spaced ", "a: b", "#x", "tab\there", "é日本", "true", "\xa0lead", "a\u200db"],
)
def test_can_single_accepts_single_line_printable_text(s: str) -> None:
    assert can_single(s)


@pytest.mark.parametrize(
    "s",
    [
        "a\nb",
        "a\rb",
        "bell\a",
        "esc\x1b",
        "del\x7f",
        "c1\x9f",
        "nel\x85",
        "ls\u2028",
        "ps\u2029",
        "\ufeff",
        "\ufffe",
        "\ud800",
    ],
)
def test_can_single_refuses_line_breaks_and_characters_needing_escapes(s: str) -> None:
    assert not can_single(s)


@pytest.mark.parametrize(
    ("s", "preferred", "expected"),
    [
        ("Grace", "double", "double"),
        ("Grace", "single", "single"),
        ("Grace", "plain", "plain"),
        ("it's", "single", "single"),
        ("a: b", "plain", "single"),
        ("true", "plain", "single"),
        ("tab\there", "plain", "single"),
        ("two\nlines", "plain", "double"),
        ("two\nlines", "single", "double"),
        ("abc", None, "plain"),
        ("a: b", None, "single"),
        ("0.2", None, "single"),
        ("bell\a", None, "double"),
        ("\U0001f469\u200d\U0001f4bb dev", None, "plain"),
        ("a\xa0b", "single", "single"),
        ("a\u200bb", None, "plain"),
        ("-v", None, "plain"),
        (":x", None, "plain"),
        ("\xa0lead", None, "single"),
        ("ls\u2028x", None, "double"),
    ],
)
def test_choose_style_keeps_preferred_style_else_plain_single_double(
    s: str, preferred: QuoteStyle | None, expected: QuoteStyle
) -> None:
    assert choose_style(s, preferred, "block") == expected


def test_choose_style_depends_on_context_for_flow_indicators() -> None:
    assert choose_style("a,b", "plain", "block") == "plain"
    assert choose_style("a,b", "plain", "flow") == "single"


def test_single_quoted_rendering_doubles_embedded_quotes() -> None:
    assert render_scalar("it's", "single", "block") == "'it''s'"


@pytest.mark.parametrize(
    ("s", "expected"),
    [
        ('a"b\\c', '"a\\"b\\\\c"'),
        ("tab\there", '"tab\\there"'),
        ("two\nlines\r\n", '"two\\nlines\\r\\n"'),
        ("\0\a\b\v\f\x1b", '"\\0\\a\\b\\v\\f\\e"'),
        ("é日本😀", '"é日本😀"'),
        ("it's # not a comment", '"it\'s # not a comment"'),
        ("\x01\x7f\x9f", '"\\x01\\x7f\\x9f"'),
        ("\x85", '"\\N"'),
        ("\u2028", '"\\L"'),
        ("\u2029", '"\\P"'),
        ("nbsp\xa0bom\ufeff", '"nbsp\xa0bom\ufeff"'),
        ("\ufffe", '"\\ufffe"'),
    ],
)
def test_double_quoted_rendering_escapes_only_backslash_quote_and_control_characters(
    s: str, expected: str
) -> None:
    assert render_string(s, "double") == expected


@pytest.mark.parametrize(
    "s",
    [
        "abc",
        "it's",
        "a: b",
        "true",
        "0.2",
        "",
        " lead",
        "tab\there",
        "two\nlines\n",
        'q"uo\\te',
        "\0\a\b\v\f\x1b\x01\x7f\x85\x9f",
        "\u2028\u2029",
        "é日本😀",
        "a,b]",
        "nbsp\xa0bom\ufeff",
        "\U0001f469\u200d\U0001f4bb dev",
        "a\u200bb",
        "\xa0lead",
        "-v",
        ":x",
        "?x",
    ],
)
@pytest.mark.parametrize("preferred", [None, "plain", "single", "double"])
@pytest.mark.parametrize("context", ["block", "flow"])
def test_rendered_string_reads_back_as_the_same_string(
    s: str, preferred: QuoteStyle | None, context: Context
) -> None:
    style = choose_style(s, preferred, context)
    node = _read_back(render_string(s, style), context)
    assert (node.text, node.style) == (s, style)
    if style == "plain":
        assert resolve_plain(node.text) == s


# Characters that stress plain/single-quoted representability: indicators, whitespace, the
# non-ASCII YAML-printable range, and characters that are not printable or that act as line breaks.
_TRICKY = (
    "-?:,[]{}#&*!|>'\"%@`. a1\t\n\r\x00\x01\x7f\x85\x9f\xa0\xad"
    "\u200b\u200d\u2028\u2029\u3000\ud7ff\ue000\ufeff\ufffd\ufffe\U0001f600\U0010ffff"
)


def _sample_strings() -> list[str]:
    short = ["".join(p) for n in (1, 2) for p in itertools.product(_TRICKY, repeat=n)]
    rng = random.Random(20261002)
    longer = ["".join(rng.choices(_TRICKY, k=rng.randint(3, 8))) for _ in range(1500)]
    return short + longer


_SAMPLES = _sample_strings()


@pytest.mark.parametrize("context", ["block", "flow"])
def test_every_string_can_plain_accepts_reads_back_as_the_identical_plain_string(
    context: Context,
) -> None:
    accepted = [s for s in _SAMPLES if can_plain(s, context)]
    assert accepted  # the sample must exercise the accepting branch
    for s in accepted:
        node = _read_back(s, context)
        assert (node.text, node.style) == (s, "plain"), repr(s)
        assert resolve_plain(node.text) == s, repr(s)


@pytest.mark.parametrize("context", ["block", "flow"])
def test_every_string_can_single_accepts_reads_back_as_the_identical_string(
    context: Context,
) -> None:
    accepted = [s for s in _SAMPLES if can_single(s)]
    assert accepted
    for s in accepted:
        node = _read_back(render_string(s, "single"), context)
        assert (node.text, node.style) == (s, "single"), repr(s)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, "true"),
        (False, "false"),
        (None, "null"),
        (42, "42"),
        (-7, "-7"),
        (0.75, "0.75"),
        (1e20, "1e+20"),
        (1e-05, "1e-05"),
        (2.0, "2.0"),
        (-0.0, "-0.0"),
        (math.inf, ".inf"),
        (-math.inf, "-.inf"),
        (math.nan, ".nan"),
    ],
)
def test_non_strings_render_as_plain_canonical_text(value: Scalar, expected: str) -> None:
    assert not isinstance(value, str)
    assert render_nonstring(value) == expected
    for preferred in (None, "plain", "single", "double"):
        assert render_scalar(value, preferred, "block") == expected


@pytest.mark.parametrize("value", [True, None, 42, 0.75, 1e20, -0.0, math.inf, -math.inf])
def test_non_string_rendering_reads_back_as_the_same_value(value: Scalar) -> None:
    assert not isinstance(value, str)
    node = _read_back(render_nonstring(value), "block")
    assert node.style == "plain"
    resolved = resolve_plain(node.text)
    assert type(resolved) is type(value)
    assert resolved == value


def test_nan_rendering_reads_back_as_nan() -> None:
    resolved = resolve_plain(render_nonstring(math.nan))
    assert isinstance(resolved, float)
    assert math.isnan(resolved)
