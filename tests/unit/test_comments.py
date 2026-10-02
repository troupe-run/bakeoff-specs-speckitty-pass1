"""writeback.comments: end-of-line comments keep their column on a changed line (FR-020)."""

import pytest

from troupe.writeback.comments import find_comment_start, replace_in_line


def _replace(line: str, old: str, new: str) -> str:
    """Replace the last occurrence of ``old`` before any comment with ``new``."""
    start = line.rindex(old, 0, find_comment_start(line, 0) or len(line))
    return replace_in_line(line, start, start + len(old), new)


@pytest.mark.parametrize(
    ("line", "from_col", "expected"),
    [
        ("a: 1 # c", 4, 5),
        ("a: 1", 4, None),
        ("# whole line", 0, 0),
        ("a: x#y", 3, None),
        ("a: 'x # y'  # c", 3, 12),
        ('a: "x # y"  # c', 3, 12),
        ("a: 'it''s # no'  # c", 3, 17),
        ('a: "say \\" # no"  # c', 3, 18),
        ("a: [it's, b] # c", 4, 13),
        ('{"k":"v # no"} # c', 1, 15),
    ],
)
def test_find_comment_start_skips_hashes_inside_quotes_and_words(
    line: str, from_col: int, expected: int | None
) -> None:
    assert find_comment_start(line, from_col) == expected


def test_shorter_value_moves_comment_back_to_its_column() -> None:
    assert _replace("  temperature: 0.75 # c", "0.75", "0.2") == "  temperature: 0.2  # c"


def test_longer_value_within_the_gap_keeps_the_comment_column() -> None:
    assert _replace("a: 0.2  # c", "0.2", "0.75") == "a: 0.75 # c"


def test_value_reaching_the_comment_column_leaves_exactly_one_space() -> None:
    assert _replace("a: 1 # c", "1", "12345") == "a: 12345 # c"


def test_value_exactly_at_the_comment_column_leaves_exactly_one_space() -> None:
    assert _replace("a: 1  # c", "1", "123") == "a: 123 # c"


def test_same_length_value_changes_only_the_value() -> None:
    assert _replace("a: 1    # c  ", "1", "2") == "a: 2    # c  "


def test_line_without_comment_changes_only_the_value() -> None:
    assert _replace("a: 1   ", "1", "12345") == "a: 12345   "


def test_hash_inside_quoted_value_is_not_treated_as_a_comment() -> None:
    assert _replace('a: "x # y"  # c', '"x # y"', '"z"') == 'a: "z"      # c'


def test_flow_item_change_keeps_the_comment_column() -> None:
    line = "tools: [a, b]    # c"
    start = line.index("b]")
    assert replace_in_line(line, start, start + 1, "bbb") == "tools: [a, bbb]  # c"


def test_flow_item_change_keeps_text_between_value_and_comment() -> None:
    line = "tools: [a, b]  # c"
    start = line.index("a,")
    assert replace_in_line(line, start, start + 1, "") == "tools: [, b]   # c"


def test_columns_count_unicode_code_points() -> None:
    assert _replace("név: é  # c", "é", "日本") == "név: 日本 # c"
    assert _replace("név: 日本語    # c", "日本語", "😀") == "név: 😀      # c"
    line = _replace("k: 😀😀 # c", "😀😀", "😀")
    assert line == "k: 😀  # c"
    assert line.index("#") == 6
