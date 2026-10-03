"""``troupe config get PATH`` through the real CLI (US1, FR-001-003, FR-013): exact stdout bytes.

Every step-1/2 ``show PATH`` scalar case, proven for ``get`` (NFR-004).
"""

import json
from pathlib import Path
from typing import Any

from conftest import HISTORY_PREFIX, MakeTheatre, all_files, run_cli, snapshot

FIXTURE: dict[str, str | bytes] = {
    "troupe.yml": (
        "model:\n"
        "  temperature: 0.2  # creativity\n"
        "  name: gpt\n"
        "  stream: true\n"
        "  stop: null\n"
        "  max_tokens: 42\n"
        "tools: [a, b]\n"
        "agents:\n"
        "  coder: file:agents/coder.yaml\n"
        "prompt: file:prompts/sys.md\n"
        "notes: |\n"
        "  line one\n"
        "  line two\n"
    ),
    "agents/coder.yaml": "name: Ada\nskills: file:skills/coder.yml\n",
    "agents/skills/coder.yml": "primary: python\n",
    "prompts/sys.md": "You are helpful.\nBe brief.\n",
}


def _get(theatre: Path, path: str) -> tuple[int, str, str]:
    result = run_cli("config", "get", path, "--theatre", str(theatre))
    return result.code, result.out, result.err


def _history(theatre: Path) -> list[dict[str, Any]]:
    result = run_cli("config", "history", "--theatre", str(theatre))
    assert result.code == 0, result.err
    return [json.loads(line) for line in result.out.splitlines()]


# US1 scenario 1
def test_get_float_prints_repr(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    assert _get(theatre, "model.temperature") == (0, "0.2\n", "")


def test_get_float_uses_python_repr_for_exponents_and_specials(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre({"troupe.yml": "big: 1e20\none: 1.\nneg: -.inf\nnan: .NaN\n"})

    assert _get(theatre, "big") == (0, "1e+20\n", "")
    assert _get(theatre, "one") == (0, "1.0\n", "")
    assert _get(theatre, "neg") == (0, "-inf\n", "")
    assert _get(theatre, "nan") == (0, "nan\n", "")


def test_get_string_appends_newline(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    assert _get(theatre, "model.name") == (0, "gpt\n", "")


def test_get_quoted_string_prints_unquoted_text(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "a: \"0.2\"\nb: 'it''s'\nc: \"tab\\there\"\n"})

    assert _get(theatre, "a") == (0, "0.2\n", "")
    assert _get(theatre, "b") == (0, "it's\n", "")
    assert _get(theatre, "c") == (0, "tab\there\n", "")


def test_get_string_ending_in_newline_prints_exactly(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    assert _get(theatre, "notes") == (0, "line one\nline two\n", "")


def test_get_bool_null_int(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    assert _get(theatre, "model.stream") == (0, "true\n", "")
    assert _get(theatre, "model.stop") == (0, "null\n", "")
    assert _get(theatre, "model.max_tokens") == (0, "42\n", "")


def test_get_yaml_core_schema_strings(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "a: yes\nb: 2001-12-14\nc: 1_000\nd: off\n"})

    assert _get(theatre, "a") == (0, "yes\n", "")
    assert _get(theatre, "b") == (0, "2001-12-14\n", "")
    assert _get(theatre, "c") == (0, "1_000\n", "")
    assert _get(theatre, "d") == (0, "off\n", "")


# US1 scenario 2
def test_get_value_inside_yaml_include(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    assert _get(theatre, "agents.coder.name") == (0, "Ada\n", "")


def test_get_nested_include_relative_to_including_file(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    assert _get(theatre, "agents.coder.skills.primary") == (0, "python\n", "")


# US1 scenario 3
def test_get_text_include_prints_exact_file_text(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    assert _get(theatre, "prompt") == (0, "You are helpful.\nBe brief.\n", "")


def test_get_text_include_preserves_crlf_bytes(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "prompt: file:sys.md\n", "sys.md": b"a\r\nb\r\n"})

    assert _get(theatre, "prompt") == (0, "a\r\nb\r\n", "")


def test_get_text_include_without_final_newline_gets_one(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "prompt: file:sys.md\n", "sys.md": "no newline"})

    assert _get(theatre, "prompt") == (0, "no newline\n", "")


def test_get_text_include_that_looks_like_yaml_is_a_string(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "data: file:data.txt\n", "data.txt": "a: 1\n"})

    assert _get(theatre, "data") == (0, "a: 1\n", "")


# US1 scenario 4
def test_get_list_item_by_index(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    assert _get(theatre, "tools.1") == (0, "b\n", "")


def test_get_list_exits_5_naming_path_and_pointing_to_config_show(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre(FIXTURE)

    code, out, err = _get(theatre, "tools")

    assert (code, out) == (5, "")
    assert err == "troupe: tools is a list, not a scalar; use 'troupe config show tools'\n"


def test_get_mapping_exits_5_naming_path_and_pointing_to_config_show(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre(FIXTURE)

    code, out, err = _get(theatre, "model")

    assert (code, out) == (5, "")
    assert err == "troupe: model is a mapping, not a scalar; use 'troupe config show model'\n"


def test_get_whole_yaml_include_exits_5_as_mapping_pointing_to_config_show(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre(FIXTURE)

    code, out, err = _get(theatre, "agents.coder")

    assert (code, out) == (5, "")
    assert err == (
        "troupe: agents.coder is a mapping, not a scalar; use 'troupe config show agents.coder'\n"
    )


# US1 scenario 5
def test_get_missing_path_exits_5(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    for path in ("model.missing", "nothing.here", "tools.2"):
        code, out, err = _get(theatre, path)
        assert (code, out) == (5, ""), path
        assert err.startswith("troupe: ") and path in err, err


def test_get_through_scalar_exits_5(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    code, out, err = _get(theatre, "model.name.first")

    assert (code, out) == (5, "")
    assert "model.name.first" in err


def test_get_through_text_include_exits_5(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    code, out, err = _get(theatre, "prompt.0")

    assert (code, out) == (5, "")
    assert "prompt.0" in err


def test_get_invalid_path_exits_2_and_creates_nothing(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)
    before = all_files(theatre)

    code, out, err = _get(theatre, "model..temperature")

    assert (code, out) == (2, "")
    assert "model..temperature" in err
    assert all_files(theatre) == before


def test_get_with_sources_option_is_a_usage_error(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    result = run_cli("config", "get", "model.name", "--sources", "--theatre", str(theatre))

    assert (result.code, result.out) == (2, "")
    assert "--sources" in result.err


# US1 scenario 6
def test_get_missing_include_target_exits_4_naming_file(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "agents:\n  coder: file:agents/coder.yaml\n"})

    code, out, err = _get(theatre, "agents.coder.name")

    assert (code, out) == (4, "")
    assert "agents/coder.yaml" in err
    assert not any(rel.startswith(HISTORY_PREFIX) for rel in all_files(theatre))


def test_get_include_cycle_exits_4(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(
        {
            "troupe.yml": "a: file:a.yml\n",
            "a.yml": "b: file:b.yml\n",
            "b.yml": "a: file:a.yml\n",
        }
    )

    code, out, err = _get(theatre, "a.b.a")

    assert (code, out) == (4, "")
    assert "cycle" in err and "a.yml" in err


def test_get_without_root_file_exits_4_naming_file(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"other.yml": "a: 1\n"})

    code, out, err = _get(theatre, "a")

    assert (code, out) == (4, "")
    assert "troupe.yml" in err


def test_get_with_both_root_files_exits_4_naming_both(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "a: 1\n", "troupe.yaml": "a: 2\n"})

    code, out, err = _get(theatre, "a")

    assert (code, out) == (4, "")
    assert "troupe.yml" in err and "troupe.yaml" in err


# US1 scenario 7
def test_get_reads_hand_edits_after_import(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)
    assert _get(theatre, "agents.coder.name") == (0, "Ada\n", "")

    coder = theatre / ".troupe" / "agents" / "coder.yaml"
    coder.write_text("name: Grace\nskills: file:skills/coder.yml\n", encoding="utf-8")

    assert _get(theatre, "agents.coder.name") == (0, "Grace\n", "")


def test_first_get_imports_theatre(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "a: 1\nb: [x]\n"})

    assert _get(theatre, "a") == (0, "1\n", "")
    assert any(rel.startswith(HISTORY_PREFIX) for rel in all_files(theatre))
    imported = _history(theatre)
    assert [(r["op"], r["path"], r["new"]) for r in imported] == [
        ("import", "a", 1),
        ("import", "b.0", "x"),
    ]

    assert _get(theatre, "a") == (0, "1\n", "")
    assert _history(theatre) == imported


def test_get_changes_no_configuration_file(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)
    before = snapshot(theatre)

    assert _get(theatre, "prompt")[0] == 0
    assert _get(theatre, "model")[0] == 5

    assert snapshot(theatre) == before
