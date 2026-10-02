"""writeback.blocks: literal and folded block scalars (FR-017, FR-018, research R-11).

Every test applies the edits to a whole file text, re-composes the result with ``yamlcore`` and
checks the value read back is exactly the new value, and that the bytes the change must not touch
are identical.
"""

import random
import re

import pytest

from troupe.errors import WriteRefused
from troupe.writeback import TextEdit, apply_edits
from troupe.writeback.blocks import (
    BlockScalar,
    Chomp,
    can_block,
    choose_chomp,
    folded_paragraphs,
    greedy_wrap,
    literal_header,
    literal_lines,
    parse_block,
    render_new_multiline,
    replace_block,
    replace_folded,
    replace_literal,
    replace_with_multiline,
    required_chomps,
)
from troupe.yamlcore import RawMapping, RawNode, RawScalar, RawSequence, compose

PATH = "agents.writer.notes"


def _node_at(text: str, *keys: str | int) -> RawScalar:
    """Compose ``text`` and walk ``keys`` (mapping keys or sequence indices) to a scalar."""
    node: RawNode | None = compose(text, "test.yml")
    for key in keys:
        if isinstance(key, int):
            assert isinstance(node, RawSequence)
            node = node.items[key]
        else:
            assert isinstance(node, RawMapping)
            node = next(v for k, v in node.pairs if isinstance(k, RawScalar) and k.text == key)
    assert isinstance(node, RawScalar)
    return node


def _block(text: str, *keys: str | int, parent_indent: int = 0) -> BlockScalar:
    node = _node_at(text, *keys)
    return parse_block(text, node.start, parent_indent)


def _assert_value(text: str, value: str, *keys: str | int) -> RawScalar:
    node = _node_at(text, *keys)
    assert node.text == value
    return node


# --- T025: literal rendering and chomping --------------------------------------------------


@pytest.mark.parametrize(
    ("value", "chomps"),
    [
        ("a\nb", {"strip"}),
        ("a\nb\n", {"clip", "keep"}),
        ("a\nb\n\n", {"keep"}),
        ("\n", {"keep"}),
        ("\n\n", {"keep"}),
        ("", {"strip", "clip", "keep"}),
    ],
)
def test_required_chomps_follow_trailing_newlines(value: str, chomps: set[str]) -> None:
    assert required_chomps(value) == chomps


@pytest.mark.parametrize(
    ("current", "value", "chosen"),
    [
        ("keep", "a\n", "keep"),
        ("clip", "a\n", "clip"),
        ("strip", "a\n", "clip"),
        ("clip", "a", "strip"),
        ("strip", "a\n\n", "keep"),
        ("keep", "", "keep"),
    ],
)
def test_choose_chomp_keeps_current_unless_the_value_requires_another(
    current: Chomp, value: str, chosen: Chomp
) -> None:
    assert choose_chomp(current, value) == chosen


def test_literal_lines_indent_non_empty_lines_and_leave_empty_lines_empty() -> None:
    assert literal_lines("a\n\n b\n", 4) == ["    a", "", "     b"]


def test_literal_lines_keep_adds_one_empty_line_per_extra_trailing_newline() -> None:
    assert literal_lines("a\n\n\n", 2) == ["  a", "", ""]


def test_literal_lines_of_only_newlines_are_that_many_empty_lines() -> None:
    assert literal_lines("\n\n", 2) == ["", ""]


@pytest.mark.parametrize(
    ("value", "chomp", "header"),
    [
        ("a\n", "clip", "|"),
        ("a", "strip", "|-"),
        ("a\n\n", "keep", "|+"),
        (" a\n", "clip", "|2"),
        (" a", "strip", "|2-"),
        ("\n  a\n", "clip", "|2"),
        ("   \na\n", "clip", "|2"),
        ("\ta\n", "clip", "|"),
    ],
)
def test_literal_header_adds_indentation_indicator_only_for_space_led_first_line(
    value: str, chomp: Chomp, header: str
) -> None:
    assert literal_header(value, chomp, 2) == header


def test_literal_header_indicator_is_the_indent_step() -> None:
    assert literal_header(" a\n", "clip", 4) == "|4"


def test_literal_header_refuses_an_indent_step_no_digit_can_express() -> None:
    with pytest.raises(ValueError, match="indentation"):
        literal_header(" a\n", "clip", 10)


@pytest.mark.parametrize(
    ("value", "ok"),
    [
        ("a\tb\nc\n", True),
        ("é日本😀\n", True),
        ("a\rb\n", False),
        ("a\x07\n", False),
        ("\ufeffa\n", False),
        ("a\u2028b\n", False),
    ],
)
def test_can_block_rejects_characters_a_block_scalar_cannot_hold(value: str, ok: bool) -> None:
    assert can_block(value) is ok


# --- T025/T028: multi-line string replacing a plain or quoted scalar -------------------------


def test_plain_scalar_becomes_literal_block_and_comment_keeps_its_column() -> None:
    text = "name: w\nnotes: short  # c\nnext: 1\n"
    node = _node_at(text, "notes")
    value = "line one\nline two\n"
    result = apply_edits(
        text,
        replace_with_multiline(
            text, node.start, node.end, value, context="block", parent_indent=0, path=PATH
        ),
    )
    assert result == "name: w\nnotes: |      # c\n  line one\n  line two\nnext: 1\n"
    assert result.index("# c") - result.index("notes") == text.index("# c") - text.index("notes")
    _assert_value(result, value, "notes")


def test_value_without_trailing_newline_is_written_with_strip_chomping() -> None:
    text = "notes: 'old'\n"
    node = _node_at(text, "notes")
    result = apply_edits(
        text,
        replace_with_multiline(
            text, node.start, node.end, "a\nb", context="block", parent_indent=0, path=PATH
        ),
    )
    assert result == "notes: |-\n  a\n  b\n"
    _assert_value(result, "a\nb", "notes")


def test_value_with_two_trailing_newlines_is_written_with_keep_and_one_empty_line() -> None:
    text = 'notes: "old"\nnext: 1\n'
    node = _node_at(text, "notes")
    result = apply_edits(
        text,
        replace_with_multiline(
            text, node.start, node.end, "a\nb\n\n", context="block", parent_indent=0, path=PATH
        ),
    )
    assert result == "notes: |+\n  a\n  b\n\nnext: 1\n"
    _assert_value(result, "a\nb\n\n", "notes")


def test_nested_key_content_is_indented_one_step_past_the_key() -> None:
    text = "agents:\n  writer:\n    notes: x\n    model: m\n"
    node = _node_at(text, "agents", "writer", "notes")
    result = apply_edits(
        text,
        replace_with_multiline(
            text, node.start, node.end, "a\nb\n", context="block", parent_indent=4, path=PATH
        ),
    )
    assert result == "agents:\n  writer:\n    notes: |\n      a\n      b\n    model: m\n"
    _assert_value(result, "a\nb\n", "agents", "writer", "notes")


def test_sequence_item_content_is_indented_one_step_past_the_dash() -> None:
    text = "items:\n  - x\n  - y\n"
    node = _node_at(text, "items", 0)
    result = apply_edits(
        text,
        replace_with_multiline(
            text, node.start, node.end, "a\nb\n", context="block", parent_indent=2, path=PATH
        ),
    )
    assert result == "items:\n  - |\n    a\n    b\n  - y\n"
    _assert_value(result, "a\nb\n", "items", 0)


def test_file_indent_step_is_used_for_content() -> None:
    text = "notes: x\n"
    node = _node_at(text, "notes")
    result = apply_edits(
        text,
        replace_with_multiline(
            text,
            node.start,
            node.end,
            "a\nb\n",
            context="block",
            parent_indent=0,
            indent_step=4,
            path=PATH,
        ),
    )
    assert result == "notes: |\n    a\n    b\n"
    _assert_value(result, "a\nb\n", "notes")


def test_space_led_first_line_gets_an_indentation_indicator() -> None:
    text = "notes: x\nnext: 1\n"
    node = _node_at(text, "notes")
    value = "  indented\nflush\n"
    result = apply_edits(
        text,
        replace_with_multiline(
            text, node.start, node.end, value, context="block", parent_indent=0, path=PATH
        ),
    )
    assert result == "notes: |2\n    indented\n  flush\nnext: 1\n"
    _assert_value(result, value, "notes")


def test_crlf_file_gets_crlf_line_breaks_for_inserted_lines() -> None:
    text = "notes: x\r\nnext: 1\r\n"
    node = _node_at(text, "notes")
    result = apply_edits(
        text,
        replace_with_multiline(
            text,
            node.start,
            node.end,
            "a\nb\n",
            context="block",
            parent_indent=0,
            newline="\r\n",
            path=PATH,
        ),
    )
    assert result == "notes: |\r\n  a\r\n  b\r\nnext: 1\r\n"
    _assert_value(result, "a\nb\n", "notes")


def test_scalar_on_last_line_without_line_break_gets_its_body_after_a_new_break() -> None:
    text = "notes: x"
    node = _node_at(text, "notes")
    result = apply_edits(
        text,
        replace_with_multiline(
            text, node.start, node.end, "a\nb\n", context="block", parent_indent=0, path=PATH
        ),
    )
    assert result == "notes: |\n  a\n  b\n"
    _assert_value(result, "a\nb\n", "notes")


def test_multi_line_plain_scalar_is_replaced_entirely() -> None:
    text = "notes: one\n  two  # c\nnext: 1\n"
    node = _node_at(text, "notes")
    result = apply_edits(
        text,
        replace_with_multiline(
            text, node.start, node.end, "a\nb\n", context="block", parent_indent=0, path=PATH
        ),
    )
    assert result == "notes: | # c\n  a\n  b\nnext: 1\n"
    _assert_value(result, "a\nb\n", "notes")


def test_keep_chomping_refused_when_blank_lines_follow_that_it_would_absorb() -> None:
    text = "notes: x\n\nnext: 1\n"
    node = _node_at(text, "notes")
    with pytest.raises(WriteRefused, match=PATH) as info:
        replace_with_multiline(
            text, node.start, node.end, "a\n\n", context="block", parent_indent=0, path=PATH
        )
    assert info.value.exit_code == 3


def test_clip_chomping_leaves_following_blank_lines_outside_the_value() -> None:
    text = "notes: x\n\nnext: 1\n"
    node = _node_at(text, "notes")
    result = apply_edits(
        text,
        replace_with_multiline(
            text, node.start, node.end, "a\n", context="block", parent_indent=0, path=PATH
        ),
    )
    assert result == "notes: |\n  a\n\nnext: 1\n"
    _assert_value(result, "a\n", "notes")


def test_refused_when_a_following_indented_comment_would_become_content() -> None:
    text = "notes: x\n    # indented note\nnext: 1\n"
    node = _node_at(text, "notes")
    with pytest.raises(WriteRefused, match=PATH):
        replace_with_multiline(
            text, node.start, node.end, "a\n", context="block", parent_indent=0, path=PATH
        )


def test_multi_line_value_in_flow_collection_is_double_quoted() -> None:
    text = "tags: [a, b]  # c\n"
    node = _node_at(text, "tags", 1)
    result = apply_edits(
        text,
        replace_with_multiline(
            text, node.start, node.end, "x\ny\n", context="flow", parent_indent=0, path=PATH
        ),
    )
    assert result == 'tags: [a, "x\\ny\\n"] # c\n'
    _assert_value(result, "x\ny\n", "tags", 1)


# --- T028: new keys -------------------------------------------------------------------------


def test_new_multiline_value_in_block_context_is_a_literal_header_and_body() -> None:
    assert render_new_multiline("a\nb", "block", 4) == ("|-", ["    a", "    b"])


def test_new_multiline_value_in_flow_context_is_double_quoted_with_escapes() -> None:
    header, body = render_new_multiline('say "hi"\nbye\n', "flow", 4)
    assert (header, body) == ('"say \\"hi\\"\\nbye\\n"', [])
    _assert_value(f"k: {{a: {header}}}\n", 'say "hi"\nbye\n', "k", "a")


def test_new_multiline_block_rendering_reads_back_as_a_new_key() -> None:
    value = " lead\n\nx\n\n\n"
    header, body = render_new_multiline(value, "block", 2)
    text = "a: 1\nnew: " + header + "\n" + "".join(line + "\n" for line in body) + "b: 2\n"
    _assert_value(text, value, "new")


# --- T026: existing block scalars -----------------------------------------------------------


def test_parse_block_reads_header_comment_and_content_extent() -> None:
    text = "a: >-  # note\n  one\n  two\n\nb: 1\n"
    block = _block(text, "a")
    assert (block.indicator, block.chomp, block.indent_indicator) == (">", "strip", None)
    assert text[block.header_start : block.header_end] == ">-"
    assert text[block.content_start : block.content_end] == "  one\n  two\n"
    assert block.content_indent == 2
    assert block.lines == ["  one", "  two"]


def test_parse_block_keep_includes_trailing_empty_lines() -> None:
    text = "a: |+\n  one\n\nb: 1\n"
    block = _block(text, "a")
    assert text[block.content_start : block.content_end] == "  one\n\n"


@pytest.mark.parametrize("header", ["|2-", "|-2"])
def test_parse_block_reads_indicator_and_chomp_in_either_order(header: str) -> None:
    text = f"x:\n  a: {header}\n     sp\n"
    block = _block(text, "x", "a", parent_indent=2)
    assert (block.chomp, block.indent_indicator, block.content_indent) == ("strip", 2, 4)
    assert block.lines == ["     sp"]


def test_literal_block_content_is_replaced_and_indicator_kept() -> None:
    text = "a: |  # c\n  old one\n  old two\nb: 1\n"
    block = _block(text, "a")
    result = apply_edits(text, replace_literal(block, text, "new\nlines\n", "\n", PATH))
    assert result == "a: |  # c\n  new\n  lines\nb: 1\n"
    _assert_value(result, "new\nlines\n", "a")


def test_literal_block_switches_to_strip_when_value_lacks_final_newline() -> None:
    text = "a: |    # c\n  old\nb: 1\n"
    block = _block(text, "a")
    result = apply_edits(text, replace_literal(block, text, "x\ny", "\n", PATH))
    assert result == "a: |-   # c\n  x\n  y\nb: 1\n"
    _assert_value(result, "x\ny", "a")


def test_literal_keep_block_stays_keep_when_value_has_one_trailing_newline() -> None:
    text = "a: |+\n  old\n\n\nb: 1\n"
    block = _block(text, "a")
    result = apply_edits(text, replace_literal(block, text, "x\n", "\n", PATH))
    assert result == "a: |+\n  x\nb: 1\n"
    _assert_value(result, "x\n", "a")


def test_literal_strip_block_switches_to_clip_for_one_trailing_newline() -> None:
    text = "a: |-\n  old\nb: 1\n"
    block = _block(text, "a")
    result = apply_edits(text, replace_literal(block, text, "x\n", "\n", PATH))
    assert result == "a: |\n  x\nb: 1\n"
    _assert_value(result, "x\n", "a")


def test_literal_block_trailing_blank_line_before_next_key_is_preserved() -> None:
    text = "a: |\n  old\n\nb: 1\n"
    block = _block(text, "a")
    result = apply_edits(text, replace_literal(block, text, "x\ny\n", "\n", PATH))
    assert result == "a: |\n  x\n  y\n\nb: 1\n"
    _assert_value(result, "x\ny\n", "a")


def test_literal_block_switch_to_keep_refused_when_blank_lines_follow() -> None:
    text = "a: |\n  old\n\nb: 1\n"
    block = _block(text, "a")
    with pytest.raises(WriteRefused, match=PATH):
        replace_literal(block, text, "x\n\n", "\n", PATH)


def test_value_without_newline_replacing_a_block_stays_a_block_with_strip() -> None:
    text = "a: |\n  old\nb: 1\n"
    block = _block(text, "a")
    result = apply_edits(text, replace_literal(block, text, "single", "\n", PATH))
    assert result == "a: |-\n  single\nb: 1\n"
    _assert_value(result, "single", "a")


def test_literal_block_gains_indicator_when_new_first_line_is_space_led() -> None:
    text = "x:\n  a: |-  # c\n    old\n"
    block = _block(text, "x", "a", parent_indent=2)
    result = apply_edits(text, replace_literal(block, text, "  sp\nflush", "\n", PATH))
    assert result == "x:\n  a: |2- # c\n      sp\n    flush\n"
    _assert_value(result, "  sp\nflush", "x", "a")


def test_existing_indicator_is_kept_and_content_written_at_its_indent() -> None:
    text = "a: |4\n      sp\nb: 1\n"
    block = _block(text, "a")
    result = apply_edits(text, replace_literal(block, text, "flush\n", "\n", PATH))
    assert result == "a: |4\n    flush\nb: 1\n"
    _assert_value(result, "flush\n", "a")


def test_sequence_item_block_is_replaced() -> None:
    text = "items:\n  - |\n    old\n  - y\n"
    block = _block(text, "items", 0, parent_indent=2)
    result = apply_edits(text, replace_literal(block, text, "p\nq\n", "\n", PATH))
    assert result == "items:\n  - |\n    p\n    q\n  - y\n"
    _assert_value(result, "p\nq\n", "items", 0)


def test_block_without_content_lines_gets_content_at_one_indent_step() -> None:
    text = "a: |\nb: 1\n"
    block = _block(text, "a")
    result = apply_edits(text, replace_literal(block, text, "x\n", "\n", PATH))
    assert result == "a: |\n  x\nb: 1\n"
    _assert_value(result, "x\n", "a")


def test_literal_block_in_crlf_file_keeps_crlf() -> None:
    text = "a: |\r\n  old\r\nb: 1\r\n"
    block = _block(text, "a")
    result = apply_edits(text, replace_literal(block, text, "x\ny\n", "\r\n", PATH))
    assert result == "a: |\r\n  x\r\n  y\r\nb: 1\r\n"
    _assert_value(result, "x\ny\n", "a")


def test_replace_block_dispatches_on_indicator() -> None:
    text = "a: |\n  old\nb: >\n  old\n"
    lit = _block(text, "a")
    fol = _block(text, "b")
    assert replace_block(lit, text, "n\n", "\n", PATH) == replace_literal(
        lit, text, "n\n", "\n", PATH
    )
    assert replace_block(fol, text, "n\n", "\n", PATH) == replace_folded(
        fol, text, "n\n", "\n", PATH
    )


def test_replace_refuses_a_value_a_block_cannot_hold() -> None:
    text = "a: |\n  old\n"
    block = _block(text, "a")
    with pytest.raises(ValueError, match="block scalar"):
        replace_literal(block, text, "a\rb\n", "\n", PATH)


# --- T027: folded paragraphs and greedy re-wrap ---------------------------------------------


def test_greedy_wrap_fills_lines_up_to_the_width() -> None:
    assert greedy_wrap("aa bb cc dd ee", 8) == ["aa bb cc", "dd ee"]


def test_greedy_wrap_puts_a_word_longer_than_the_width_on_its_own_line() -> None:
    assert greedy_wrap("a extraordinarily b", 5) == ["a", "extraordinarily", "b"]


def test_greedy_wrap_never_breaks_inside_a_run_of_spaces() -> None:
    lines = greedy_wrap("ab  cd ef", 3)
    assert lines == ["ab  cd", "ef"]
    assert all(not line[0].isspace() for line in lines)


def test_folded_paragraphs_split_on_empty_lines_and_measure_width() -> None:
    lines = ["  one two", "  three", "", "  four", "    spaced"]
    paragraphs = folded_paragraphs(lines, 2)
    assert [(p.text, p.spaced, p.width) for p in paragraphs] == [
        ("one two three", False, 7),
        ("four", False, 4),
        ("  spaced", True, 8),
    ]
    assert [p.line_range for p in paragraphs] == [range(0, 2), range(3, 4), range(4, 5)]


FOLDED = (
    "a: >  # note\n"
    "  The first paragraph stays\n"
    "  exactly as it was.\n"
    "\n"
    "  The second paragraph is\n"
    "  about to change.\n"
    "\n"
    "  The last one stays too.\n"
    "b: 1\n"
)
P1 = "The first paragraph stays exactly as it was."
P2 = "The second paragraph is about to change."
P3 = "The last one stays too."


def test_folded_fixture_reads_as_three_paragraphs() -> None:
    _assert_value(FOLDED, f"{P1}\n{P2}\n{P3}\n", "a")


def test_folded_changed_middle_paragraph_is_rewrapped_at_its_old_width() -> None:
    block = _block(FOLDED, "a")
    new_p2 = "The second paragraph has now changed into something quite a bit longer."
    value = f"{P1}\n{new_p2}\n{P3}\n"
    result = apply_edits(FOLDED, replace_folded(block, FOLDED, value, "\n", PATH))
    # old width of the middle paragraph = len("The second paragraph is") = 23
    assert result == (
        "a: >  # note\n"
        "  The first paragraph stays\n"
        "  exactly as it was.\n"
        "\n"
        "  The second paragraph\n"
        "  has now changed into\n"
        "  something quite a bit\n"
        "  longer.\n"
        "\n"
        "  The last one stays too.\n"
        "b: 1\n"
    )
    assert all(len(line) - 2 <= 23 for line in result.splitlines()[4:8])
    _assert_value(result, value, "a")


def test_folded_long_word_takes_its_own_line() -> None:
    block = _block(FOLDED, "a")
    new_p2 = "A " + "x" * 30 + " b"
    value = f"{P1}\n{new_p2}\n{P3}\n"
    result = apply_edits(FOLDED, replace_folded(block, FOLDED, value, "\n", PATH))
    assert "\n  A\n  " + "x" * 30 + "\n  b\n" in result
    _assert_value(result, value, "a")


def test_folded_added_paragraph_wraps_at_the_longest_old_content_line() -> None:
    block = _block(FOLDED, "a")
    words = " ".join(f"w{i}" for i in range(20))
    value = f"{P1}\n{P2}\n{P3}\n{words}\n"
    result = apply_edits(FOLDED, replace_folded(block, FOLDED, value, "\n", PATH))
    old_body = FOLDED[: FOLDED.index("b: 1")]
    assert result.startswith(old_body)
    added = result[len(old_body) : result.index("b: 1")].splitlines()
    assert added[0] == ""
    # longest old content line: "The first paragraph stays" (25)
    assert max(len(line) - 2 for line in added[1:]) <= 25
    assert len(added[1]) - 2 > 25 - 4
    _assert_value(result, value, "a")


def test_folded_removed_paragraph_disappears_and_others_keep_bytes() -> None:
    block = _block(FOLDED, "a")
    value = f"{P1}\n{P3}\n"
    result = apply_edits(FOLDED, replace_folded(block, FOLDED, value, "\n", PATH))
    assert result == (
        "a: >  # note\n"
        "  The first paragraph stays\n"
        "  exactly as it was.\n"
        "\n"
        "  The last one stays too.\n"
        "b: 1\n"
    )
    _assert_value(result, value, "a")


def test_folded_inserted_paragraph_leaves_later_paragraphs_unchanged() -> None:
    block = _block(FOLDED, "a")
    value = f"{P1}\nInserted.\n{P2}\n{P3}\n"
    result = apply_edits(FOLDED, replace_folded(block, FOLDED, value, "\n", PATH))
    assert "  The second paragraph is\n  about to change.\n" in result
    _assert_value(result, value, "a")


def test_folded_chomp_switches_and_header_comment_keeps_its_column() -> None:
    block = _block(FOLDED, "a")
    value = f"{P1}\n{P2}\n{P3}"
    result = apply_edits(FOLDED, replace_folded(block, FOLDED, value, "\n", PATH))
    assert result == FOLDED.replace("a: >  # note", "a: >- # note")
    _assert_value(result, value, "a")


def test_folded_more_empty_lines_between_paragraphs() -> None:
    block = _block(FOLDED, "a")
    value = f"{P1}\n\n\n{P2}\n{P3}\n"
    result = apply_edits(FOLDED, replace_folded(block, FOLDED, value, "\n", PATH))
    assert "exactly as it was.\n\n\n\n  The second" in result
    _assert_value(result, value, "a")


def test_folded_empty_lines_keep_their_bytes_when_count_unchanged() -> None:
    text = "a: >\n  one\n \n  two\n"
    block = _block(text, "a")
    result = apply_edits(text, replace_folded(block, text, "one\nthree\n", "\n", PATH))
    assert result == "a: >\n  one\n \n  three\n"
    _assert_value(result, "one\nthree\n", "a")


def test_folded_crlf_file_keeps_unchanged_lines_and_uses_crlf_for_new_ones() -> None:
    text = FOLDED.replace("\n", "\r\n")
    block = _block(text, "a")
    value = f"{P1}\nShort.\n{P3}\n"
    result = apply_edits(text, replace_folded(block, text, value, "\r\n", PATH))
    assert result == (
        "a: >  # note\r\n"
        "  The first paragraph stays\r\n"
        "  exactly as it was.\r\n"
        "\r\n"
        "  Short.\r\n"
        "\r\n"
        "  The last one stays too.\r\n"
        "b: 1\r\n"
    )
    _assert_value(result, value, "a")


def test_folded_keep_block_trailing_empty_lines() -> None:
    text = "a: >+\n  one\n\nb: 1\n"
    block = _block(text, "a")
    result = apply_edits(text, replace_folded(block, text, "one two\n\n\n", "\n", PATH))
    assert result == "a: >+\n  one\n  two\n\n\nb: 1\n"  # re-wrapped at old width 3
    _assert_value(result, "one two\n\n\n", "a")


def test_folded_leading_empty_lines_in_value() -> None:
    text = "a: >\n  one\nb: 1\n"
    block = _block(text, "a")
    result = apply_edits(text, replace_folded(block, text, "\n\none\n", "\n", PATH))
    assert result == "a: >\n\n\n  one\nb: 1\n"
    _assert_value(result, "\n\none\n", "a")


# --- T028: folded refusals ------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        f"{P1}\n  indented\n{P3}\n",
        f"{P1}\n\tTab led\n{P3}\n",
        f"{P1}\n{P2}\n{P3}\n   \n",
    ],
)
def test_folded_change_introducing_a_more_indented_line_is_refused(value: str) -> None:
    block = _block(FOLDED, "a")
    with pytest.raises(WriteRefused, match=PATH) as info:
        replace_folded(block, FOLDED, value, "\n", PATH)
    assert info.value.exit_code == 3
    assert "more-indented" in info.value.message


SPACED = "a: >\n  intro text\n\n    code line\n  outro\nb: 1\n"


def test_folded_value_with_more_indented_line_reads_as_expected() -> None:
    _assert_value(SPACED, "intro text\n\n  code line\noutro\n", "a")


def _assert_more_indented_refusal(text: str, value: str) -> None:
    block = _block(text, "a")
    with pytest.raises(WriteRefused, match=PATH) as info:
        replace_folded(block, text, value, "\n", PATH)
    assert info.value.exit_code == 3
    assert "more-indented" in info.value.message


def test_folded_change_elsewhere_in_value_with_more_indented_line_is_refused() -> None:
    _assert_more_indented_refusal(SPACED, "new intro\n\n  code line\ndone\n")


def test_folded_changed_more_indented_line_is_refused() -> None:
    _assert_more_indented_refusal(SPACED, "intro text\n\n  other code\noutro\n")


def test_folded_removing_the_more_indented_line_is_refused() -> None:
    _assert_more_indented_refusal(SPACED, "intro text\noutro\n")


def test_folded_more_indented_line_moving_first_is_refused() -> None:
    _assert_more_indented_refusal(SPACED, "  code line\noutro\n")


WHITESPACE_ONLY = "a: >\n  one\n     \n  two\nb: 1\n"


def test_folded_whitespace_only_line_deeper_than_content_is_more_indented() -> None:
    _assert_value(WHITESPACE_ONLY, "one\n   \ntwo\n", "a")
    block = _block(WHITESPACE_ONLY, "a")
    assert [p.spaced for p in folded_paragraphs(block.lines, 2)] == [False, True, False]


def test_folded_change_to_value_with_whitespace_only_extra_line_is_refused() -> None:
    _assert_more_indented_refusal(WHITESPACE_ONLY, "one\n   \nthree\n")


@pytest.mark.parametrize("text", [SPACED, WHITESPACE_ONLY])
def test_folded_value_with_more_indented_line_written_unchanged_is_a_no_op(text: str) -> None:
    block = _block(text, "a")
    assert replace_folded(block, text, _node_at(text, "a").text, "\n", PATH) == []


SWAP = "a: >  # c\n  one two\n  three four five\n\n  six seven\n  eight\nb: 1\n"


def test_folded_swapped_paragraphs_both_keep_their_bytes() -> None:
    _assert_value(SWAP, "one two three four five\nsix seven eight\n", "a")
    block = _block(SWAP, "a")
    value = "six seven eight\none two three four five\n"
    result = apply_edits(SWAP, replace_folded(block, SWAP, value, "\n", PATH))
    assert result == "a: >  # c\n  six seven\n  eight\n\n  one two\n  three four five\nb: 1\n"
    _assert_value(result, value, "a")


def test_folded_moved_paragraph_keeps_its_bytes_next_to_a_changed_one() -> None:
    block = _block(FOLDED, "a")
    value = f"{P3}\n{P1}\nBrand new text.\n"
    result = apply_edits(FOLDED, replace_folded(block, FOLDED, value, "\n", PATH))
    assert "  The first paragraph stays\n  exactly as it was.\n" in result
    assert result.startswith("a: >  # note\n  The last one stays too.\n\n")
    _assert_value(result, value, "a")


# --- Properties: random edits always read back and keep untouched bytes ---------------------


def _random_paragraph(rng: random.Random) -> str:
    return " ".join(
        "".join(rng.choice("abcdefgh") for _ in range(rng.randint(1, 12)))
        for _ in range(rng.randint(1, 15))
    )


@pytest.mark.parametrize("seed", range(40))
def test_random_folded_and_literal_rewrites_read_back_exactly(seed: int) -> None:
    rng = random.Random(seed)
    paragraphs = [_random_paragraph(rng) for _ in range(rng.randint(1, 5))]
    old_value = "\n".join(paragraphs) + "\n"
    head = "top: 1\nx:\n  # keep me\n"
    tail = "  y: 2\nz: 3\n"
    for indicator in (">", "|"):
        # Write the old value with this module itself, then rewrite it randomly.
        start_text = head + f"  a: {indicator}\n    seed\n" + tail
        block = _block(start_text, "x", "a", parent_indent=2)
        text = apply_edits(start_text, replace_block(block, start_text, old_value, "\n", PATH))
        _assert_value(text, old_value, "x", "a")
        new_paragraphs = [p if rng.random() < 0.5 else _random_paragraph(rng) for p in paragraphs]
        if rng.random() < 0.5:
            new_paragraphs.insert(rng.randint(0, len(new_paragraphs)), _random_paragraph(rng))
        if len(new_paragraphs) > 1 and rng.random() < 0.3:
            del new_paragraphs[rng.randrange(len(new_paragraphs))]
        new_value = "\n".join(new_paragraphs) + rng.choice(["", "\n", "\n\n"])
        block = _block(text, "x", "a", parent_indent=2)
        edits = replace_block(block, text, new_value, "\n", PATH)
        result = apply_edits(text, edits)
        _assert_value(result, new_value, "x", "a")
        assert result.startswith(head + f"  a: {indicator}")
        assert result.endswith(tail)
        assert all(isinstance(edit, TextEdit) for edit in edits)


_TRICKY_WORDS = ["a", "bb", "dddddddd", "e#f", "z ", "x  y", "q\tr", "- d", "k: v"]


def _hand_written_folded(rng: random.Random, newline: str) -> tuple[str, str]:
    """A folded block written by hand (text lines, more-indented lines, blank lines)."""
    lines = ["    begin"]  # a more-indented first line would need an indentation indicator
    for _ in range(rng.randint(1, 8)):
        roll = rng.random()
        if roll < 0.25:
            lines.append("")
        elif roll < 0.35:
            lines.append("      " + rng.choice(_TRICKY_WORDS))
        else:
            lines.append(
                "    " + " ".join(rng.choice(_TRICKY_WORDS) for _ in range(rng.randint(1, 4)))
            )
    lines.append("    end")
    chomp = rng.choice(["", "-", "+"])
    tail = rng.choice(["  y: 2\n", "z: 3\n", "", "\n  # note\nz: 3\n"])
    text = "top: 1\nx:\n  a: >" + chomp + "  # c\n" + "\n".join(lines) + "\n" + tail
    return text.replace("\n", newline), tail.replace("\n", newline)


@pytest.mark.parametrize("seed", range(60))
def test_random_edits_of_hand_written_folded_blocks_read_back_or_refuse(seed: int) -> None:
    rng = random.Random(seed)
    newline = rng.choice(["\n", "\r\n"])
    text, tail = _hand_written_folded(rng, newline)
    old_value = _node_at(text, "x", "a").text
    parts = re.split(r"(\n+)", old_value.rstrip("\n"))
    for i in range(0, len(parts), 2):
        if rng.random() < 0.4 and not parts[i].startswith(" "):
            parts[i] = " ".join(rng.choice(_TRICKY_WORDS) for _ in range(rng.randint(1, 10)))
    if rng.random() < 0.3:
        parts.insert(0, "inserted paragraph\n\n")
    new_value = "".join(parts) + "\n" * rng.randint(0, 2)
    block = _block(text, "x", "a", parent_indent=2)
    assert replace_folded(block, text, old_value, newline, PATH) == []  # no-op is no edit
    has_more_indented = any(p.spaced for p in folded_paragraphs(block.lines, 4))
    try:
        edits = replace_folded(block, text, new_value, newline, PATH)
    except WriteRefused as refusal:
        # Refusals this generator can trigger: an old more-indented line (any change to such a
        # value), or keep chomping absorbing the blank lines after the block.
        assert ("more-indented" in refusal.message) is has_more_indented
        assert has_more_indented or "blank lines" in refusal.message
        return
    assert not has_more_indented or new_value == old_value
    result = apply_edits(text, edits)
    _assert_value(result, new_value, "x", "a")
    assert result.startswith("top: 1" + newline + "x:" + newline + "  a: >")
    assert result.endswith(tail)
