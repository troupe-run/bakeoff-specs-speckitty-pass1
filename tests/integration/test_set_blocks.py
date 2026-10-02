"""``set`` with multi-line strings: literal and folded block scalars, through the real CLI.

Contract: FR-017 (multi-line string replacing a plain/quoted scalar is a literal block, ``|-``
without a trailing newline, double-quoted under a flow parent; an existing block scalar keeps its
indicator and chomping unless the value's trailing newlines require another) and FR-018 (folded
values: unchanged paragraphs keep their bytes, a changed paragraph is re-wrapped greedily at its
old longest content-line width, an over-long word takes its own line, a new paragraph wraps at
the value's longest old content line, a more-indented line exits 3). Every test compares the
complete bytes of every theatre file; after a successful ``set``, ``show`` prints the new value.
"""

import json
from pathlib import Path
from typing import Any

from conftest import CliResult, MakeTheatre, run_cli, snapshot

ROOT = ".troupe/troupe.yml"


def _set(theatre: Path, path: str, value: str) -> CliResult:
    return run_cli("config", "set", path, value, "--theatre", str(theatre))


def _show(theatre: Path, path: str) -> str:
    result = run_cli("config", "show", path, "--theatre", str(theatre))
    assert (result.code, result.err) == (0, ""), result.err
    return result.out


def _history(theatre: Path) -> list[dict[str, Any]]:
    result = run_cli("config", "history", "--theatre", str(theatre))
    assert (result.code, result.err) == (0, ""), result.err
    return [json.loads(line) for line in result.out.splitlines()]


def _check(
    make_theatre: MakeTheatre, before: str | bytes, path: str, value: str, after: str | bytes
) -> Path:
    """The theatre holds only the root file; assert its whole bytes and ``show PATH``.

    ``value`` is the VALUE argument; ``show`` must print what it parses to.
    """
    theatre = make_theatre({"troupe.yml": before})
    result = _set(theatre, path, value)
    assert (result.code, result.out, result.err) == (0, "", "")
    expected = after.encode("utf-8") if isinstance(after, str) else after
    assert snapshot(theatre) == {ROOT: expected}
    parsed = json.loads(value) if value.startswith('"') else value
    assert _show(theatre, path) == (parsed if parsed.endswith("\n") else parsed + "\n")
    return theatre


def _refused(make_theatre: MakeTheatre, before: str, path: str, value: str) -> None:
    theatre = make_theatre({"troupe.yml": before})
    imported = _history(theatre)

    result = _set(theatre, path, value)

    assert (result.code, result.out) == (3, "")
    assert path in result.err
    assert snapshot(theatre) == {ROOT: before.encode("utf-8")}
    assert _history(theatre) == imported


# --- Literal blocks (FR-017, US2 scenario 7) ----------------------------------------------------


def test_multi_line_string_replacing_plain_scalar_is_literal_block(
    make_theatre: MakeTheatre,
) -> None:
    _check(
        make_theatre,
        "notes: short\nnext: 1\n",
        "notes",
        '"line one\\nline two\\n"',
        "notes: |\n  line one\n  line two\nnext: 1\n",
    )


def test_multi_line_string_without_trailing_newline_is_strip_literal(
    make_theatre: MakeTheatre,
) -> None:
    _check(
        make_theatre,
        "notes: 'short'\nnext: 1\n",
        "notes",
        '"line one\\nline two"',
        "notes: |-\n  line one\n  line two\nnext: 1\n",
    )


def test_literal_header_keeps_the_comment_column(make_theatre: MakeTheatre) -> None:
    _check(
        make_theatre,
        "notes: short  # n\n",
        "notes",
        '"a\\nb\\n"',
        "notes: |      # n\n  a\n  b\n",
    )


def test_multi_line_list_item_is_literal_block_indented_below_dash(
    make_theatre: MakeTheatre,
) -> None:
    _check(
        make_theatre,
        "items:\n  - one\n  - two\n",
        "items.0",
        '"a\\nb\\n"',
        "items:\n  - |\n    a\n    b\n  - two\n",
    )


def test_literal_block_in_crlf_file_uses_crlf(make_theatre: MakeTheatre) -> None:
    _check(
        make_theatre,
        b"notes: short\r\nnext: 1\r\n",
        "notes",
        '"a\\nb\\n"',
        b"notes: |\r\n  a\r\n  b\r\nnext: 1\r\n",
    )


def test_multi_line_string_in_flow_collection_is_double_quoted(
    make_theatre: MakeTheatre,
) -> None:
    _check(
        make_theatre,
        "m: [a, b]  # c\n",
        "m.0",
        '"x\\ny"',
        'm: ["x\\ny", b] # c\n',
    )


def test_existing_literal_block_keeps_indicator_and_chomping(make_theatre: MakeTheatre) -> None:
    _check(
        make_theatre,
        "text: |\n  old one\n  old two\nnext: 1\n",
        "text",
        '"new\\nlines here\\n"',
        "text: |\n  new\n  lines here\nnext: 1\n",
    )


def test_existing_literal_block_changes_chomping_when_trailing_newline_goes(
    make_theatre: MakeTheatre,
) -> None:
    _check(
        make_theatre,
        "text: |  # c\n  a\nnext: 1\n",
        "text",
        '"b\\nc"',
        "text: |- # c\n  b\n  c\nnext: 1\n",
    )


def test_existing_strip_literal_becomes_clip_for_trailing_newline(
    make_theatre: MakeTheatre,
) -> None:
    _check(make_theatre, "text: |-\n  a\n", "text", '"b\\n"', "text: |\n  b\n")


def test_existing_literal_becomes_keep_for_two_trailing_newlines(
    make_theatre: MakeTheatre,
) -> None:
    _check(
        make_theatre,
        "text: |\n  a\nnext: 1\n",
        "text",
        '"b\\n\\n"',
        "text: |+\n  b\n\nnext: 1\n",
    )


def test_single_line_string_replacing_literal_stays_block_with_strip(
    make_theatre: MakeTheatre,
) -> None:
    _check(
        make_theatre, "text: |\n  a\n  b\nnext: 1\n", "text", "one", "text: |-\n  one\nnext: 1\n"
    )


def test_non_string_replacing_block_scalar_is_written_plain(make_theatre: MakeTheatre) -> None:
    _check(make_theatre, "text: |\n  a\n  b\nnext: 1\n", "text", "5", "text: 5\nnext: 1\n")


def test_block_scalar_set_to_its_value_is_a_no_op(make_theatre: MakeTheatre) -> None:
    before = "text: |\n  a\n  b\nnext: 1\n"
    theatre = make_theatre({"troupe.yml": before})
    imported = _history(theatre)
    mtime = (theatre / ROOT).stat().st_mtime_ns

    result = _set(theatre, "text", '"a\\nb\\n"')

    assert (result.code, result.out, result.err) == (0, "", "")
    assert snapshot(theatre) == {ROOT: before.encode("utf-8")}
    assert (theatre / ROOT).stat().st_mtime_ns == mtime
    assert _history(theatre) == imported


# --- Folded blocks (FR-018, US2 scenario 8) -----------------------------------------------------

FOLDED = (
    "text: >\n"
    "  The quick brown fox\n"
    "  jumps over.\n"
    "\n"
    "  Second\n"
    "  paragraph here stays.\n"
    "\n"
    "  Third one.\n"
    "next: 1\n"
)
P1 = "The quick brown fox jumps over."
P2 = "Second paragraph here stays."
P3 = "Third one."


def _value(*paragraphs: str) -> str:
    return json.dumps("\n".join(paragraphs) + "\n")


def test_folded_changed_paragraph_is_rewrapped_others_keep_bytes(
    make_theatre: MakeTheatre,
) -> None:
    # Paragraph 1's widest old line is 19 code points; paragraph 2's odd wrapping is kept.
    _check(
        make_theatre,
        FOLDED,
        "text",
        _value("The slow brown fox jumps over the lazy dog.", P2, P3),
        FOLDED.replace(
            "  The quick brown fox\n  jumps over.\n",
            "  The slow brown fox\n  jumps over the lazy\n  dog.\n",
        ),
    )


def test_folded_over_long_word_takes_its_own_line(make_theatre: MakeTheatre) -> None:
    # Paragraph 3's old width is 10.
    _check(
        make_theatre,
        FOLDED,
        "text",
        _value(P1, P2, "A supercalifragilistic word"),
        FOLDED.replace("  Third one.\n", "  A\n  supercalifragilistic\n  word\n"),
    )


def test_folded_new_paragraph_wraps_at_longest_old_line(make_theatre: MakeTheatre) -> None:
    # The value's longest old content line is "paragraph here stays." (21).
    _check(
        make_theatre,
        FOLDED,
        "text",
        _value(P1, P2, P3, "Fourth paragraph is new and fairly long text"),
        FOLDED.replace(
            "  Third one.\n",
            "  Third one.\n\n  Fourth paragraph is\n  new and fairly long\n  text\n",
        ),
    )


def test_folded_value_with_more_indented_line_exits_3(make_theatre: MakeTheatre) -> None:
    _refused(
        make_theatre,
        "text: >\n  normal line\n    indented line\nnext: 1\n",
        "text",
        '"other\\n"',
    )


def test_folded_change_introducing_more_indented_line_exits_3(
    make_theatre: MakeTheatre,
) -> None:
    _refused(make_theatre, FOLDED, "text", _value(P1, " indented", P3))
