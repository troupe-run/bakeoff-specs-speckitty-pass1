"""``set PATH VALUE`` on existing scalars, includes and errors, through the real CLI (US2).

Every test compares the complete bytes of every file of the theatre (history store excluded)
after the command: the changed file against its whole expected text, every other file against its
original bytes (NFR-001). Refusals and errors must leave every byte unchanged (NFR-002) and print
nothing on stdout. After a successful ``set``, ``get PATH`` prints the new value.
"""

import json
from pathlib import Path
from typing import Any

from conftest import (
    HISTORY_PREFIX,
    CliResult,
    MakeTheatre,
    all_files,
    core,
    run_cli,
    snapshot,
)

type Files = dict[str, str | bytes]


def _set(theatre: Path, path: str, value: str) -> CliResult:
    return run_cli("config", "set", path, value, "--theatre", str(theatre))


def _get(theatre: Path, path: str) -> str:
    result = run_cli("config", "get", path, "--theatre", str(theatre))
    assert (result.code, result.err) == (0, ""), result.err
    return result.out


def _history(theatre: Path) -> list[dict[str, Any]]:
    result = run_cli("config", "history", "--theatre", str(theatre))
    assert (result.code, result.err) == (0, ""), result.err
    return [json.loads(line) for line in result.out.splitlines()]


def _bytes(files: Files) -> dict[str, bytes]:
    return {
        f".troupe/{rel}": content.encode("utf-8") if isinstance(content, str) else content
        for rel, content in files.items()
    }


def _set_ok(theatre: Path, path: str, value: str, expected: Files, shown: str) -> None:
    """Run ``set``; assert success, the whole theatre's bytes, and ``get PATH``."""
    result = _set(theatre, path, value)
    assert (result.code, result.out, result.err) == (0, "", "")
    assert snapshot(theatre) == _bytes(expected)
    assert _get(theatre, path) == shown


def _set_fails(theatre: Path, path: str, value: str, code: int, names: str) -> CliResult:
    """Run ``set``; assert the exit code, empty stdout, a message naming ``names``, no change."""
    before = snapshot(theatre)
    result = _set(theatre, path, value)
    assert result.code == code
    assert result.out == ""
    assert result.err.startswith("troupe: ") and result.err.count("\n") == 1
    assert names in result.err
    assert snapshot(theatre) == before
    return result


FIXTURE: Files = {
    "troupe.yml": (
        "model:\n"
        '  name: "claude"   # default model\n'
        "  temperature: 0.2  # creativity\n"
        "  stop:\n"
        "tools: [read, write]\n"
        "agents:\n"
        "  coder: file:agents/coder.yaml\n"
        "prompt: file:prompts/sys.md\n"
    ),
    "agents/coder.yaml": "name: Ada\nskills: file:skills/coder.yml\n",
    "agents/skills/coder.yml": "primary: python  # main\n",
    "prompts/sys.md": "You are helpful.\n",
}


def _fixture(**changes: str | bytes) -> Files:
    """FIXTURE with whole files replaced; keys use ``__`` for ``/`` and ``_`` for ``.``."""
    files = dict(FIXTURE)
    for key, content in changes.items():
        files[key.replace("__", "/").replace("_", ".")] = content
    return files


def _root(text: str) -> Files:
    return {**FIXTURE, "troupe.yml": text}


# --- Comment column (FR-020, US2 scenario 1) ----------------------------------------------------


def test_comment_keeps_column_then_gets_one_space_then_stays_at_its_new_column(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre(FIXTURE)
    line = "  temperature: 0.2  # creativity\n"

    def root_with(new_line: str) -> Files:
        return _root(str(FIXTURE["troupe.yml"]).replace(line, new_line))

    _set_ok(
        theatre,
        "model.temperature",
        "0.75",
        root_with("  temperature: 0.75 # creativity\n"),
        "0.75\n",
    )
    _set_ok(
        theatre,
        "model.temperature",
        "0.12345",
        root_with("  temperature: 0.12345 # creativity\n"),
        "0.12345\n",
    )
    # The comment's previous column is now the one it had after the last write.
    _set_ok(
        theatre,
        "model.temperature",
        "0.2",
        root_with("  temperature: 0.2     # creativity\n"),
        "0.2\n",
    )


def test_comment_column_counts_code_points_not_bytes(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "a: ab     # c\nb: 1\n"})

    _set_ok(theatre, "a", "éé", {"troupe.yml": "a: éé     # c\nb: 1\n"}, "éé\n")
    _set_ok(theatre, "a", "ééé", {"troupe.yml": "a: ééé    # c\nb: 1\n"}, "ééé\n")


def test_line_without_comment_changes_only_the_value(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "a: 1\nb:   22\nc: 3\n"})

    _set_ok(theatre, "b", "333", {"troupe.yml": "a: 1\nb:   333\nc: 3\n"}, "333\n")


# --- Quoting (FR-015, US2 scenario 2) -----------------------------------------------------------


def test_double_quoted_value_keeps_double_quotes(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    expected = str(FIXTURE["troupe.yml"]).replace('"claude"   #', '"Grace"    #')
    _set_ok(theatre, "model.name", "Grace", _root(expected), "Grace\n")


def test_single_quoted_value_keeps_single_quotes_and_doubles_apostrophe(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre({"troupe.yml": "name: 'Ada'\n"})

    _set_ok(theatre, "name", "it's", {"troupe.yml": "name: 'it''s'\n"}, "it's\n")


def test_plain_value_that_cannot_stay_plain_falls_back_to_single_quotes(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre({"troupe.yml": "a: abc\n"})

    _set_ok(theatre, "a", '"a: b"', {"troupe.yml": "a: 'a: b'\n"}, "a: b\n")


def test_plain_value_set_to_string_true_is_single_quoted(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "a: abc\n"})

    _set_ok(theatre, "a", '"true"', {"troupe.yml": "a: 'true'\n"}, "true\n")
    assert core(_history(theatre))[-1] == {
        "seq": 2,
        "op": "set",
        "path": "a",
        "old": "abc",
        "new": "true",
    }


def test_int_set_to_numeric_string_is_quoted(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "port: 8080\n"})

    _set_ok(theatre, "port", '"9090"', {"troupe.yml": "port: '9090'\n"}, "9090\n")


def test_quoted_string_set_to_int_is_written_plain(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": 'port: "8080"\n'})

    _set_ok(theatre, "port", "9090", {"troupe.yml": "port: 9090\n"}, "9090\n")


def test_non_string_scalars_are_written_plain_canonical(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "a: 'x'\n"})

    _set_ok(theatre, "a", "true", {"troupe.yml": "a: true\n"}, "true\n")
    _set_ok(theatre, "a", "~", {"troupe.yml": "a: null\n"}, "null\n")
    _set_ok(theatre, "a", "0x1F", {"troupe.yml": "a: 31\n"}, "31\n")


def test_plain_string_with_tab_falls_back_to_single_quotes(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "a: x\n"})

    _set_ok(theatre, "a", '"a\\tb"', {"troupe.yml": "a: 'a\tb'\n"}, "a\tb\n")


def test_double_quoted_output_escapes_only_backslash_quote_and_controls(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre({"troupe.yml": 'a: "x"\n'})

    _set_ok(
        theatre,
        "a",
        '"tab\\there é \\"q\\" \\\\ bell\\a"',
        {"troupe.yml": 'a: "tab\\there é \\"q\\" \\\\ bell\\a"\n'},
        'tab\there é "q" \\ bell\a\n',
    )


def test_control_character_forces_double_quotes(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "a: x  # c\n"})

    _set_ok(theatre, "a", '"a\\x01b"', {"troupe.yml": 'a: "a\\x01b" # c\n'}, "a\x01b\n")


def test_flow_context_value_with_comma_is_quoted(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "m: {a: 1, b: x}\n"})

    _set_ok(theatre, "m.b", '"y, z"', {"troupe.yml": "m: {a: 1, b: 'y, z'}\n"}, "y, z\n")


def test_block_list_item_is_replaced_in_place(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "tools:\n  - a  # first\n  - b\n"})

    _set_ok(theatre, "tools.0", "zz", {"troupe.yml": "tools:\n  - zz # first\n  - b\n"}, "zz\n")


def test_multi_line_plain_scalar_is_replaced_by_one_line(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "a: this is\n  long\nb: 1\n"})

    _set_ok(theatre, "a", "short", {"troupe.yml": "a: short\nb: 1\n"}, "short\n")


def test_value_on_line_after_its_key_is_replaced_there(make_theatre: MakeTheatre) -> None:
    # Unusual but legal layout: the value is on its own line below the key.
    theatre = make_theatre({"troupe.yml": "a:\n  value  # c\nb: 1\n"})

    _set_ok(theatre, "a", "other", {"troupe.yml": "a:\n  other  # c\nb: 1\n"}, "other\n")


def test_crlf_file_keeps_crlf_line_endings(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": b"a: 1\r\nb: x  # c\r\nc: 3\r\n"})

    _set_ok(theatre, "b", "yyyy", {"troupe.yml": b"a: 1\r\nb: yyyy # c\r\nc: 3\r\n"}, "yyyy\n")


def test_file_with_byte_order_mark_keeps_it(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "\ufeffa: 1\nb: 2\n"})

    _set_ok(theatre, "a", "10", {"troupe.yml": "\ufeffa: 10\nb: 2\n"}, "10\n")


def test_empty_null_value_gets_scalar_on_key_line(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    expected = str(FIXTURE["troupe.yml"]).replace("  stop:\n", "  stop: END\n")
    _set_ok(theatre, "model.stop", "END", _root(expected), "END\n")


# --- YAML includes (FR-010, FR-013, US2 scenario 3) ---------------------------------------------


def test_value_in_yaml_include_changes_only_the_included_file(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    expected = _fixture(agents__coder_yaml="name: Grace\nskills: file:skills/coder.yml\n")
    _set_ok(theatre, "agents.coder.name", "Grace", expected, "Grace\n")


def test_value_in_nested_include_in_subdirectory_changes_that_file(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre(FIXTURE)

    expected = _fixture(agents__skills__coder_yml="primary: rust    # main\n")
    _set_ok(theatre, "agents.coder.skills.primary", "rust", expected, "rust\n")


def test_replacing_a_whole_yaml_include_exits_3_and_changes_nothing(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre(FIXTURE)
    imported = _history(theatre)

    result = _set_fails(theatre, "agents.coder", "x", 3, "agents.coder")

    assert "agents/coder.yaml" in result.err
    assert _history(theatre) == imported


def test_replacing_a_nested_whole_include_exits_3(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    _set_fails(theatre, "agents.coder.skills", "{primary: go}", 3, "agents.coder.skills")


# --- Text includes (FR-010, research R-16, US2 scenario 4) --------------------------------------


def _text_theatre(make_theatre: MakeTheatre, content: str | bytes) -> Path:
    return make_theatre({**FIXTURE, "prompts/sys.md": content})


def test_lf_text_include_content_becomes_the_string_exactly(make_theatre: MakeTheatre) -> None:
    theatre = _text_theatre(make_theatre, "You are helpful.\n")

    expected = _fixture(prompts__sys_md="line one\nline two\n")
    _set_ok(theatre, "prompt", '"line one\\nline two\\n"', expected, "line one\nline two\n")


def test_crlf_text_include_gets_crlf_line_endings(make_theatre: MakeTheatre) -> None:
    theatre = _text_theatre(make_theatre, b"old\r\n")

    expected = _fixture(prompts__sys_md=b"a\r\nb\r\n")
    _set_ok(theatre, "prompt", '"a\\nb\\n"', expected, "a\r\nb\r\n")


def test_crlf_text_include_with_non_string_value_exits_3(make_theatre: MakeTheatre) -> None:
    theatre = _text_theatre(make_theatre, b"old\r\n")
    imported = _history(theatre)

    _set_fails(theatre, "prompt", "5", 3, "prompt")
    _set_fails(theatre, "prompt", "{a: 1}", 3, "prompt")

    assert _history(theatre) == imported


def test_lf_text_include_with_int_value_gets_the_argument_text(make_theatre: MakeTheatre) -> None:
    theatre = _text_theatre(make_theatre, "You are helpful.\n")

    _set_ok(theatre, "prompt", "5", _fixture(prompts__sys_md="5"), "5\n")
    assert _history(theatre)[-1]["new"] == "5"


def test_lf_text_include_with_float_value_keeps_the_typed_text(make_theatre: MakeTheatre) -> None:
    theatre = _text_theatre(make_theatre, "no line break")

    _set_ok(theatre, "prompt", "0.20", _fixture(prompts__sys_md="0.20"), "0.20\n")


def test_lf_text_include_with_mapping_value_gets_the_argument_text(
    make_theatre: MakeTheatre,
) -> None:
    theatre = _text_theatre(make_theatre, "You are helpful.\n")

    _set_ok(theatre, "prompt", "{a: 1}", _fixture(prompts__sys_md="{a: 1}"), "{a: 1}\n")
    record = core(_history(theatre))[-1]
    assert record == {
        "seq": record["seq"],
        "op": "set",
        "path": "prompt",
        "old": "You are helpful.\n",
        "new": "{a: 1}",
    }


def test_lf_text_include_with_list_value_gets_the_argument_text(make_theatre: MakeTheatre) -> None:
    theatre = _text_theatre(make_theatre, "You are helpful.\n")

    _set_ok(theatre, "prompt", "[a,  b]", _fixture(prompts__sys_md="[a,  b]"), "[a,  b]\n")


def test_text_include_set_to_its_current_text_is_a_no_op(make_theatre: MakeTheatre) -> None:
    theatre = _text_theatre(make_theatre, "same\n")
    target = theatre / ".troupe/prompts/sys.md"
    imported = _history(theatre)
    mtime = target.stat().st_mtime_ns

    _set_ok(theatre, "prompt", '"same\\n"', FIXTURE | {"prompts/sys.md": "same\n"}, "same\n")

    assert target.stat().st_mtime_ns == mtime
    assert _history(theatre) == imported


# --- Path and usage errors ----------------------------------------------------------------------


def test_index_beyond_list_length_exits_5(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    _set_fails(theatre, "tools.5", "c", 5, "tools.5")


def test_path_through_a_scalar_exits_5(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    _set_fails(theatre, "model.temperature.x", "1", 5, "model.temperature")


def test_path_through_an_empty_null_value_exits_5(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    _set_fails(theatre, "model.stop.x", "1", 5, "model.stop")


def test_path_through_a_text_include_exits_5(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    _set_fails(theatre, "prompt.x", "1", 5, "prompt")


def test_key_segment_on_a_list_exits_5(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    _set_fails(theatre, "tools.name", "1", 5, "tools.name")


def test_missing_list_index_under_new_key_exits_5(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    _set_fails(theatre, "model.extra.0", "1", 5, "model.extra.0")


def test_missing_root_file_exits_4_and_creates_nothing(tmp_path: Path) -> None:
    result = _set(tmp_path, "a", "1")

    assert (result.code, result.out) == (4, "")
    assert "troupe.yml" in result.err
    assert all_files(tmp_path) == set()


def test_block_style_value_exits_2_before_loading(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    _set_fails(theatre, "model.name", "a: 1", 2, "a: 1")

    assert not any(rel.startswith(HISTORY_PREFIX) for rel in all_files(theatre))


def test_empty_path_segment_exits_2(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    _set_fails(theatre, "model..name", "x", 2, "model..name")


def test_errors_append_no_event(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)
    imported = _history(theatre)

    _set_fails(theatre, "tools.9", "x", 5, "tools.9")
    _set_fails(theatre, "agents.coder", "x", 3, "agents.coder")

    assert _history(theatre) == imported


# --- No-op (FR-023, research R-17) --------------------------------------------------------------


def test_set_to_current_value_writes_nothing_and_records_nothing(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre(FIXTURE)
    imported = _history(theatre)
    root = theatre / ".troupe/troupe.yml"
    mtime = root.stat().st_mtime_ns

    _set_ok(theatre, "model.temperature", "0.2", FIXTURE, "0.2\n")
    _set_ok(theatre, "model.name", "claude", FIXTURE, "claude\n")
    _set_ok(theatre, "model.stop", "null", FIXTURE, "null\n")
    assert _set(theatre, "tools", "[read, write]").code == 0

    assert root.stat().st_mtime_ns == mtime
    assert snapshot(theatre) == _bytes(FIXTURE)
    assert _history(theatre) == imported


def test_set_to_equal_value_of_other_type_is_not_a_no_op(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "a: 1\n"})

    _set_ok(theatre, "a", "1.0", {"troupe.yml": "a: 1.0\n"}, "1.0\n")
    _set_ok(theatre, "a", '"1.0"', {"troupe.yml": "a: '1.0'\n"}, "1.0\n")


# --- Verify before write (research R-17) --------------------------------------------------------


def test_change_that_would_alter_another_path_is_refused_by_verification(
    make_theatre: MakeTheatre,
) -> None:
    # Both paths show the same file; rewriting it for one would change the other too.
    theatre = make_theatre({"troupe.yml": "a: file:p.md\nb: file:p.md\n", "p.md": "x\n"})
    imported = _history(theatre)

    result = _set_fails(theatre, "a", '"y\\n"', 3, "a")

    assert "byte-surgically" in result.err
    assert _history(theatre) == imported


def test_include_flag_naming_a_missing_target_is_refused_naming_the_target(
    make_theatre: MakeTheatre,
) -> None:
    # S-12 (was step 1's generic refusal): the message names the missing include target.
    theatre = make_theatre({"troupe.yml": "a: 1\n"})
    before = snapshot(theatre)

    result = run_cli(
        "config", "set", "--include", "b", "file:missing.md", "--theatre", str(theatre)
    )

    missing = (theatre / ".troupe" / "missing.md").resolve()
    assert (result.code, result.out) == (3, "")
    assert result.err.startswith("troupe: b: ") and result.err.count("\n") == 1
    assert f"include target not found: {missing}" in result.err
    assert result.err.endswith("; no file changed\n")
    assert snapshot(theatre) == before


def test_include_flag_with_a_value_naming_an_existing_text_file_writes_an_include(
    make_theatre: MakeTheatre,
) -> None:
    # The step-1 behaviour, now asked for with ``--include`` (S-12, S-13).
    theatre = make_theatre({"troupe.yml": "a: 1\n", "p.md": "hello\n"})

    result = run_cli("config", "set", "--include", "b", "file:p.md", "--theatre", str(theatre))

    assert (result.code, result.out, result.err) == (0, "", "")
    assert snapshot(theatre) == _bytes({"troupe.yml": "a: 1\nb: file:p.md\n", "p.md": "hello\n"})
    assert _get(theatre, "b") == "hello\n"


def test_value_naming_an_existing_text_file_is_written_as_a_literal_string(
    make_theatre: MakeTheatre,
) -> None:
    # S-13: without ``--include`` an include-looking VALUE is written tagged ``!literal``.
    theatre = make_theatre({"troupe.yml": "a: 1\n", "p.md": "hello\n"})

    _set_ok(
        theatre,
        "b",
        "file:p.md",
        {"troupe.yml": "a: 1\nb: !literal file:p.md\n", "p.md": "hello\n"},
        "file:p.md\n",
    )
