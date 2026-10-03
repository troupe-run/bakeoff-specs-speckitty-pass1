"""``troupe config show [PATH]`` through the real CLI (US2, FR-003 to FR-006, FR-013 to FR-015).

Exact stdout bytes where the spec gives them; elsewhere stdout is parsed back as YAML by both a
YAML 1.2 and a YAML 1.1 reader (research D-10) and compared with data written out by hand.
"""

import json
import math
import warnings
from pathlib import Path
from typing import Any

import pytest
from ruamel.yaml import YAML

from conftest import HISTORY_PREFIX, MakeTheatre, all_files, run_cli, snapshot

type YamlVersion = tuple[int, int]
YAML_VERSIONS: list[YamlVersion] = [(1, 2), (1, 1)]

FIXTURE: dict[str, str | bytes] = {
    "troupe.yml": (
        "model:\n"
        "  temperature: 0.2  # creativity\n"
        "  name: gpt\n"
        "  stream: true\n"
        "  stop: null\n"
        "  max_tokens: 42\n"
        "  big: 1e20\n"
        "  low: -.inf\n"
        "  odd: .nan\n"
        "tools: [a, b]\n"
        "agents:\n"
        "  coder: file:agents/coder.yaml\n"
        "prompt: file:prompts/sys.md\n"
        "notes: |\n"
        "  line one\n"
        "  line two\n"
        "looks_typed: ['true', '123', '', 2001-12-14, yes, 1_000]\n"
        "'key: odd': x\n"
        "crlf: file:crlf.txt\n"
        "empty_map: {}\n"
        "empty_list: []\n"
        "team:\n"
        "  - name: Ada\n"
        "    role: lead\n"
        "  - [x, y]\n"
    ),
    "agents/coder.yaml": "name: Ada\nskills: file:skills/coder.yml\n",
    "agents/skills/coder.yml": "primary: python\n",
    "prompts/sys.md": "You are helpful.\nBe brief.\n",
    "crlf.txt": b"a\r\nb\r\n",
}

NAN = object()  # stands for every NaN when comparing data (NaN != NaN)

# The whole resolved FIXTURE, written out by hand (includes replaced by their content).
RESOLVED: dict[str, Any] = {
    "model": {
        "temperature": 0.2,
        "name": "gpt",
        "stream": True,
        "stop": None,
        "max_tokens": 42,
        "big": 1e20,
        "low": -math.inf,
        "odd": NAN,
    },
    "tools": ["a", "b"],
    "agents": {"coder": {"name": "Ada", "skills": {"primary": "python"}}},
    "prompt": "You are helpful.\nBe brief.\n",
    "notes": "line one\nline two\n",
    "looks_typed": ["true", "123", "", "2001-12-14", "yes", "1_000"],
    "key: odd": "x",
    "crlf": "a\r\nb\r\n",
    "empty_map": {},
    "empty_list": [],
    "team": [{"name": "Ada", "role": "lead"}, ["x", "y"]],
}


def without_nan(data: object) -> object:
    """``data`` with every NaN float replaced by ``NAN``, so ``==`` can compare it."""
    if isinstance(data, float) and math.isnan(data):
        return NAN
    if isinstance(data, dict):
        return {key: without_nan(value) for key, value in data.items()}
    if isinstance(data, list):
        return [without_nan(item) for item in data]
    return data


def parse(text: str, version: YamlVersion) -> object:
    """Load ``text`` with ruamel safe-load as a YAML ``version`` reader, NaN made comparable."""
    reader = YAML(typ="safe", pure=True)
    reader.version = version
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # 1.1 readers warn about some numbers
        return without_nan(reader.load(text))


def _show(theatre: Path, *args: str) -> tuple[int, str, str]:
    result = run_cli("config", "show", *args, "--theatre", str(theatre))
    return result.code, result.out, result.err


def _get(theatre: Path, path: str) -> tuple[int, str, str]:
    result = run_cli("config", "get", path, "--theatre", str(theatre))
    return result.code, result.out, result.err


def _history(theatre: Path) -> list[dict[str, Any]]:
    result = run_cli("config", "history", "--theatre", str(theatre))
    assert result.code == 0, result.err
    return [json.loads(line) for line in result.out.splitlines()]


# --- US2 scenario 4, FR-004: a scalar prints exactly what get prints ----------------------------


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("model.max_tokens", id="int"),
        pytest.param("model.temperature", id="float"),
        pytest.param("model.big", id="float-exponent"),
        pytest.param("model.low", id="float-inf"),
        pytest.param("model.odd", id="float-nan"),
        pytest.param("model.stream", id="bool"),
        pytest.param("model.stop", id="null"),
        pytest.param("model.name", id="plain-string"),
        pytest.param("looks_typed.0", id="string-that-looks-typed"),
        pytest.param("notes", id="string-ending-in-newline"),
        pytest.param("prompt", id="text-include"),
        pytest.param("crlf", id="crlf-text-include"),
        pytest.param("agents.coder.name", id="inside-yaml-include"),
    ],
)
def test_show_scalar_prints_exactly_what_get_prints(make_theatre: MakeTheatre, path: str) -> None:
    theatre = make_theatre(FIXTURE)

    got = _get(theatre, path)

    assert got[0] == 0, got
    assert _show(theatre, path) == got


def test_show_scalar_keeps_get_float_spellings(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    assert _show(theatre, "model.big") == (0, "1e+20\n", "")
    assert _show(theatre, "model.low") == (0, "-inf\n", "")
    assert _show(theatre, "model.odd") == (0, "nan\n", "")


def test_show_scalar_yaml_include_root_prints_like_get(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "port: file:port.yml\n", "port.yml": "8080\n"})

    assert _show(theatre, "port") == _get(theatre, "port") == (0, "8080\n", "")


# --- US2 scenarios 1 to 3, FR-005/FR-006: sections as block YAML --------------------------------


def test_show_mapping_prints_block_yaml(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(
        {"troupe.yml": "server: file:server.yml\n", "server.yml": "port: 8080\nhost: example.org\n"}
    )

    assert _show(theatre, "server") == (0, "port: 8080\nhost: example.org\n", "")


def test_show_flow_list_prints_block_sequence(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "tools: [a, b]\n"})

    assert _show(theatre, "tools") == (0, "- a\n- b\n", "")


def test_show_whole_configuration_includes_text_include_as_literal_block(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre(
        {"troupe.yml": "prompt: file:sys.md\n", "sys.md": "line one\nline two\n"}
    )

    code, out, err = _show(theatre)

    assert (code, err) == (0, "")
    assert "prompt: |\n  line one\n  line two\n" in out


def test_show_whole_configuration_exact_layout(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(
        {
            "troupe.yml": (
                "name: demo\n"
                "server: file:server.yml\n"
                "tools: [a, b]\n"
                "team:\n  - {name: Ada, role: lead}\n  - [p, q]\n"
                "empty: {}\n"
                "flag: 'true'\n"
            ),
            "server.yml": "port: 8080\n",
        }
    )

    assert _show(theatre) == (
        0,
        "name: demo\n"
        "server:\n"
        "  port: 8080\n"
        "tools:\n"
        "  - a\n"
        "  - b\n"
        "team:\n"
        "  - name: Ada\n"
        "    role: lead\n"
        "  - - p\n"
        "    - q\n"
        "empty: {}\n"
        "flag: 'true'\n",
        "",
    )


# --- US2 scenario 5, NFR-001: read-back equals the resolved configuration ------------------------


@pytest.mark.parametrize("version", YAML_VERSIONS, ids=["yaml-1.2", "yaml-1.1"])
def test_show_without_path_parses_back_to_resolved_configuration(
    make_theatre: MakeTheatre, version: YamlVersion
) -> None:
    theatre = make_theatre(FIXTURE)

    code, out, err = _show(theatre)

    assert (code, err) == (0, "")
    assert parse(out, version) == RESOLVED


@pytest.mark.parametrize("version", YAML_VERSIONS, ids=["yaml-1.2", "yaml-1.1"])
@pytest.mark.parametrize("path", ["model", "agents", "agents.coder", "looks_typed", "team"])
def test_show_section_parses_back_to_resolved_section(
    make_theatre: MakeTheatre, path: str, version: YamlVersion
) -> None:
    theatre = make_theatre(FIXTURE)
    expected: Any = RESOLVED
    for segment in path.split("."):
        expected = expected[segment]

    code, out, err = _show(theatre, path)

    assert (code, err) == (0, "")
    assert parse(out, version) == expected


def test_show_keys_in_file_order(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(
        {"troupe.yml": "zeta: 1\nalpha: file:inc.yml\nmid: 2\n", "inc.yml": "b: 1\na: 2\n"}
    )

    assert _show(theatre) == (0, "zeta: 1\nalpha:\n  b: 1\n  a: 2\nmid: 2\n", "")


def test_show_whole_yaml_include_prints_its_content(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    assert _show(theatre, "agents.coder") == (0, "name: Ada\nskills:\n  primary: python\n", "")


def test_show_empty_root_prints_empty_mapping(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": ""})

    assert _show(theatre) == (0, "{}\n", "")


# --- FR-003, US2 scenario 6, NFR-002: errors ----------------------------------------------------


def test_show_missing_path_exits_5_naming_path(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    for path in ("missing", "model.missing", "tools.2"):
        code, out, err = _show(theatre, path)
        assert (code, out) == (5, ""), path
        assert err.startswith("troupe: ") and path in err and err.count("\n") == 1, err


def test_show_path_through_scalar_exits_5(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    for path in ("model.name.first", "prompt.0"):
        code, out, err = _show(theatre, path)
        assert (code, out) == (5, ""), path
        assert err.startswith("troupe: ") and path in err, err


def test_show_invalid_path_exits_2_and_creates_nothing(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)
    before = all_files(theatre)

    code, out, err = _show(theatre, "model..temperature")

    assert (code, out) == (2, "")
    assert "model..temperature" in err
    assert all_files(theatre) == before


def test_show_unloadable_configuration_exits_4_naming_file(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "agents:\n  coder: file:agents/coder.yaml\n"})

    for args in ((), ("agents",), ("--sources",)):
        code, out, err = _show(theatre, *args)
        assert (code, out) == (4, ""), args
        assert "agents/coder.yaml" in err and err.count("\n") == 1, err
    assert not any(rel.startswith(HISTORY_PREFIX) for rel in all_files(theatre))


# --- FR-013, FR-014: reconcile first, read-only ---------------------------------------------------


def test_show_reads_hand_edits_and_records_them_first(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "a: 1\nb: file:b.yml\n", "b.yml": "c: old\n"})
    imported = _history(theatre)
    (theatre / ".troupe" / "b.yml").write_text("c: new\n", encoding="utf-8")

    assert _show(theatre) == (0, "a: 1\nb:\n  c: new\n", "")

    assert [(e["op"], e["path"], e["old"], e["new"]) for e in _history(theatre)] == [
        *[(e["op"], e["path"], e["old"], e["new"]) for e in imported],
        ("set", "b.c", "old", "new"),
    ]


def test_show_changes_no_configuration_file(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)
    before = snapshot(theatre)

    for args in ((), ("model",), ("prompt",), ("--sources",), ("model", "--sources")):
        assert _show(theatre, *args)[0] == 0, args
    assert _show(theatre, "missing")[0] == 5

    assert snapshot(theatre) == before


# --- FR-015: help -----------------------------------------------------------------------------


def test_help_lists_show_with_sources_option() -> None:
    config_help = run_cli("config", "--help")
    show_help = run_cli("config", "show", "--help")

    assert (config_help.code, show_help.code) == (0, 0)
    assert "print PATH, or everything, as YAML" in config_help.out
    assert "[PATH]" in show_help.out and "--sources" in show_help.out
    assert "# from <file>" in show_help.out
