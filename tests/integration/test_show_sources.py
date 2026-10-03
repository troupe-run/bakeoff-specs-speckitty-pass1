"""``troupe config show [PATH] --sources`` through the real CLI (US3, FR-009 to FR-012).

Every line holding a scalar ends with `` # from <file>``, the file relative to the resolved
theatre directory with ``/`` separators (``../`` outside it); no other line gets a comment.
"""

import re
from pathlib import Path

import pytest
from test_show import YAML_VERSIONS, YamlVersion, parse

from conftest import MakeTheatre, run_cli

COMMENT = re.compile(r" # from [^#]+$")
BLOCK_HEADER = re.compile(r"(^|: |- )\|[0-9]?[-+]?$")

# contracts/cli.md "Example"
CONTRACT_FILES: dict[str, str | bytes] = {
    "troupe.yml": (
        "name: demo\nserver: file:server.yml\ntools: [a, b]\nprompt: file:prompts/sys.md\n"
    ),
    "server.yml": "port: 8080\n",
    "prompts/sys.md": "Be brief.\n",
}
CONTRACT_OUTPUT = (
    "name: demo # from .troupe/troupe.yml\n"
    "server:\n"
    "  port: 8080 # from .troupe/server.yml\n"
    "tools:\n"
    "  - a # from .troupe/troupe.yml\n"
    "  - b # from .troupe/troupe.yml\n"
    "prompt: | # from .troupe/prompts/sys.md\n"
    "  Be brief.\n"
)

# Scalars in the root file, a nested YAML include, a text include, lists, a list of mappings,
# empty collections and a multi-line string written in a file.
RICH: dict[str, str | bytes] = {
    "troupe.yml": (
        "name: demo\n"
        "server: file:server.yml\n"
        "tools: [a, b]\n"
        "prompt: file:prompts/sys.md\n"
        "agents:\n"
        "  coder: file:agents/coder.yaml\n"
        "notes: |\n"
        "  line one\n"
        "  line two\n"
        "team:\n"
        "  - name: Ada\n"
        "    role: lead\n"
        "  - [p, q]\n"
        "  - |-\n"
        "    item text\n"
        "    more\n"
        "empty_map: {}\n"
        "empty_list: []\n"
        "crlf: file:crlf.txt\n"
        "flags: ['true', '', 1e20, .nan]\n"
    ),
    "server.yml": "port: 8080\nhost: example.org\n",
    "prompts/sys.md": "You are helpful.\nBe brief.\n",
    "agents/coder.yaml": "name: Ada\nskills: [python, sql]\nempty: {}\n",
    "crlf.txt": b"a\r\nb\r\n",
}


def _show(theatre: Path, *args: str, cwd: Path | None = None) -> tuple[int, str, str]:
    result = run_cli("config", "show", *args, "--theatre", str(theatre), cwd=cwd)
    return result.code, result.out, result.err


def test_sources_example_from_contract(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(CONTRACT_FILES)

    assert _show(theatre, "--sources") == (0, CONTRACT_OUTPUT, "")


# US3 scenario 1
def test_sources_scalars_in_yaml_include_name_included_file(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(
        {
            "troupe.yml": "name: demo\nserver: file:server.yml\n",
            "server.yml": "port: 8080\nhost: example.org\n",
        }
    )

    assert _show(theatre, "--sources") == (
        0,
        "name: demo # from .troupe/troupe.yml\n"
        "server:\n"
        "  port: 8080 # from .troupe/server.yml\n"
        "  host: example.org # from .troupe/server.yml\n",
        "",
    )


# US3 scenario 2
def test_sources_text_include_comment_on_block_header_only(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(
        {"troupe.yml": "prompt: file:prompts/sys.md\n", "prompts/sys.md": "line one\nline two\n"}
    )

    code, out, err = _show(theatre, "--sources")

    assert (code, err) == (0, "")
    assert out == "prompt: | # from .troupe/prompts/sys.md\n  line one\n  line two\n"
    assert all("# from" not in line for line in out.splitlines()[1:])


# US3 scenario 3
def test_sources_list_items(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "tools: [a, b]\n"})

    assert _show(theatre, "tools", "--sources") == (
        0,
        "- a # from .troupe/troupe.yml\n- b # from .troupe/troupe.yml\n",
        "",
    )


def test_sources_list_of_mappings_comments_compact_item_line(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "team:\n  - name: Ada\n    role: lead\n"})

    assert _show(theatre, "team", "--sources") == (
        0,
        "- name: Ada # from .troupe/troupe.yml\n  role: lead # from .troupe/troupe.yml\n",
        "",
    )


# US3 scenario 4, FR-012 (DM 01M411YHFR2PMJEJWMHX4KN9C4)
def test_sources_scalar_path_prints_yaml_scalar_with_comment(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(RICH)

    assert _show(theatre, "server.port", "--sources") == (0, "8080 # from .troupe/server.yml\n", "")
    assert _show(theatre, "prompt", "--sources") == (
        0,
        "| # from .troupe/prompts/sys.md\n  You are helpful.\n  Be brief.\n",
        "",
    )
    # YAML spellings, not get's: quoted look-alike strings, '.0' exponents, '.nan'
    assert _show(theatre, "flags.0", "--sources") == (0, "'true' # from .troupe/troupe.yml\n", "")
    assert _show(theatre, "flags.2", "--sources") == (0, "1.0e+20 # from .troupe/troupe.yml\n", "")
    assert _show(theatre, "flags.3", "--sources") == (0, ".nan # from .troupe/troupe.yml\n", "")
    assert _show(theatre, "crlf", "--sources") == (
        0,
        '"a\\r\\nb\\r\\n" # from .troupe/crlf.txt\n',
        "",
    )


def test_sources_collection_lines_have_no_comment(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(RICH)
    plain = _show(theatre)
    sourced = _show(theatre, "--sources")
    assert (plain[0], plain[2], sourced[0], sourced[2]) == (0, "", 0, "")

    plain_lines, sourced_lines = plain[1].splitlines(), sourced[1].splitlines()
    assert len(plain_lines) == len(sourced_lines)
    body_above: int | None = None  # leading spaces of the literal-block header being read
    for bare, line in zip(plain_lines, sourced_lines, strict=True):
        indent = len(bare) - len(bare.lstrip(" "))
        in_body = body_above is not None and indent > body_above
        if not in_body:
            body_above = None
        if in_body or bare.endswith((":", "{}", "[]")):
            assert line == bare, line
        else:
            assert line.startswith(bare) and COMMENT.fullmatch(line[len(bare) :]), line
            if BLOCK_HEADER.search(bare):
                body_above = indent


# US3 scenario 5, NFR-001
@pytest.mark.parametrize("version", YAML_VERSIONS, ids=["yaml-1.2", "yaml-1.1"])
@pytest.mark.parametrize("path", [None, "server", "agents", "team", "flags"])
def test_sources_output_parses_to_same_data_as_plain_show(
    make_theatre: MakeTheatre, path: str | None, version: YamlVersion
) -> None:
    theatre = make_theatre(RICH)
    args = () if path is None else (path,)
    plain = _show(theatre, *args)
    sourced = _show(theatre, *args, "--sources")
    assert (plain[0], sourced[0]) == (0, 0)

    assert parse(sourced[1], version) == parse(plain[1], version)


@pytest.mark.parametrize("version", YAML_VERSIONS, ids=["yaml-1.2", "yaml-1.1"])
@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("prompt", "You are helpful.\nBe brief.\n"),
        ("crlf", "a\r\nb\r\n"),
        ("team.2", "item text\nmore"),
        ("flags.1", ""),
        ("server.port", 8080),
    ],
)
def test_sources_scalar_path_parses_back_to_the_scalar(
    make_theatre: MakeTheatre, path: str, value: object, version: YamlVersion
) -> None:
    theatre = make_theatre(RICH)

    code, out, err = _show(theatre, path, "--sources")

    assert (code, err) == (0, "")
    assert parse(out, version) == value


# FR-010
def test_sources_paths_are_relative_to_theatre_with_slashes(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(RICH)

    assert _show(theatre, "agents", "--sources") == (
        0,
        "coder:\n"
        "  name: Ada # from .troupe/agents/coder.yaml\n"
        "  skills:\n"
        "    - python # from .troupe/agents/coder.yaml\n"
        "    - sql # from .troupe/agents/coder.yaml\n"
        "  empty: {}\n",
        "",
    )


def test_sources_include_outside_theatre_uses_dotdot(
    make_theatre: MakeTheatre, tmp_path: Path
) -> None:
    theatre = make_theatre({"troupe.yml": "server: file:../../shared/server.yml\n"})
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "server.yml").write_text("port: 8080\n", encoding="utf-8")
    assert theatre.parent == tmp_path

    assert _show(theatre, "--sources") == (
        0,
        "server:\n  port: 8080 # from ../shared/server.yml\n",
        "",
    )


def test_sources_theatre_given_as_relative_path_still_labels_relative_to_theatre(
    make_theatre: MakeTheatre, tmp_path: Path
) -> None:
    theatre = make_theatre(CONTRACT_FILES)
    (tmp_path / "link").symlink_to(theatre, target_is_directory=True)

    assert _show(Path("."), "--sources", cwd=theatre) == (0, CONTRACT_OUTPUT, "")
    assert _show(Path("theatre"), "--sources", cwd=tmp_path) == (0, CONTRACT_OUTPUT, "")
    assert _show(Path("link"), "--sources", cwd=tmp_path) == (0, CONTRACT_OUTPUT, "")
    from_env = run_cli("config", "show", "--sources", cwd=tmp_path, env={"TROUPE_THEATRE": "link"})
    assert (from_env.code, from_env.out, from_env.err) == (0, CONTRACT_OUTPUT, "")
