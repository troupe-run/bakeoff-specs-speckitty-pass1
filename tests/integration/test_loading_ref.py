"""Loading mapping-form includes (``$ref``) through the real CLI: FR-001, FR-003, spec D-1/D-7.

Spec US1 scenarios 5 and 6 and the Edge Cases. Every refusal is checked the same way: exit 4,
empty stdout, one stderr line ``troupe: ...`` naming the file, and no theatre file changed.
"""

from pathlib import Path

import pytest

from conftest import MakeTheatre, run_cli, snapshot

type Files = dict[str, str | bytes]

CODER = "model: gpt\ntools:\n  shell: true\nstop: [a, b]\n"
PROMPT = "Be brief.\nReally.\n"


def _cli(theatre: Path, *args: str) -> tuple[int, str, str]:
    result = run_cli("config", *args, "--theatre", str(theatre))
    return result.code, result.out, result.err


def _reads(theatre: Path) -> list[tuple[int, str, str]]:
    """Every read the step offers on the include at ``coder``/``prompt``, plus ``show``."""
    return [
        _cli(theatre, "show"),
        _cli(theatre, "show", "--sources"),
        _cli(theatre, "show", "coder"),
        _cli(theatre, "get", "coder.model"),
        _cli(theatre, "get", "coder.stop.1"),
    ]


def _assert_load_refused(theatre: Path, *names: str) -> str:
    """Run a loading command; assert exit 4, no stdout, one ``troupe:`` line naming ``names``."""
    before = snapshot(theatre)
    code, out, err = _cli(theatre, "show")
    assert (code, out) == (4, "")
    assert err.startswith("troupe: ") and err.endswith("\n") and err.count("\n") == 1, err
    for name in names:
        assert name in err, (name, err)
    assert snapshot(theatre) == before
    return err


@pytest.mark.parametrize(
    ("scalar_form", "mapping_form"),
    [
        ("coder: file:agents/coder.yaml\n", "coder:\n  $ref: file:agents/coder.yaml\n"),
        ("{coder: file:agents/coder.yaml}\n", "{coder: {$ref: file:agents/coder.yaml}}\n"),
    ],
    ids=["block", "flow"],
)
def test_ref_alone_reads_like_scalar_form_yaml_include(
    make_theatre: MakeTheatre, scalar_form: str, mapping_form: str
) -> None:
    theatre = make_theatre({"troupe.yml": scalar_form, "agents/coder.yaml": CODER})
    expected = _reads(theatre)
    (theatre / ".troupe" / "troupe.yml").write_text(mapping_form, encoding="utf-8")

    assert expected[0] == (
        0,
        "coder:\n  model: gpt\n  tools:\n    shell: true\n  stop:\n    - a\n    - b\n",
        "",
    )
    assert _reads(theatre) == expected


def test_ref_alone_of_text_file_is_its_text(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "prompt:\n  $ref: file:p.md\n", "p.md": PROMPT})

    assert _cli(theatre, "get", "prompt") == (0, PROMPT, "")
    assert _cli(theatre, "show", "--sources") == (
        0,
        "prompt: | # from .troupe/p.md\n  Be brief.\n  Really.\n",
        "",
    )


def test_ref_with_siblings_on_text_target_exits_4_naming_file(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "prompt:\n  $ref: file:p.md\n  x: 1\n", "p.md": PROMPT})

    err = _assert_load_refused(theatre, str(theatre / ".troupe" / "troupe.yml"), "p.md")
    assert "prompt" in err and "not a .yml/.yaml file" in err


@pytest.mark.parametrize(
    ("value", "shown"),
    [
        ("5", "5"),
        ("agents/coder.yaml", "agents/coder.yaml"),
        ("[a]", "[a]"),
        ("{x: 1}", "{x: 1}"),
        ("null", "null"),
        ('"file"', '"file"'),
    ],
)
def test_ref_value_not_an_include_string_exits_4_naming_file_and_path(
    make_theatre: MakeTheatre, value: str, shown: str
) -> None:
    theatre = make_theatre(
        {"troupe.yml": f"agents:\n  coder:\n    $ref: {value}\n", "agents/coder.yaml": CODER}
    )

    err = _assert_load_refused(
        theatre, str(theatre / ".troupe" / "troupe.yml"), "agents.coder.$ref"
    )
    assert err.endswith(f"got {shown}\n"), err


@pytest.mark.parametrize(("content", "kind"), [("- a\n- b\n", "list"), ("just text\n", "scalar")])
def test_overrides_on_list_or_scalar_content_exit_4_naming_target(
    make_theatre: MakeTheatre, content: str, kind: str
) -> None:
    theatre = make_theatre(
        {
            "troupe.yml": "coder:\n  $ref: file:agents/coder.yaml\n  x: 1\n",
            "agents/coder.yaml": content,
        }
    )

    err = _assert_load_refused(
        theatre,
        str(theatre / ".troupe" / "troupe.yml"),
        str(theatre / ".troupe" / "agents" / "coder.yaml"),
    )
    assert f"its content is a {kind}, not a mapping" in err


def test_overrides_on_empty_target_are_accepted_as_empty_mapping(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre(
        {"troupe.yml": "coder:\n  $ref: file:agents/coder.yaml\n  x: 1\n", "agents/coder.yaml": ""}
    )

    assert _cli(theatre, "show", "--sources") == (
        0,
        "coder:\n  x: 1 # from .troupe/troupe.yml\n",
        "",
    )
    assert _cli(theatre, "get", "coder.x") == (0, "1\n", "")


def test_missing_ref_target_exits_4(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "coder:\n  $ref: file:agents/missing.yaml\n  x: 1\n"})

    err = _assert_load_refused(
        theatre, str(theatre / ".troupe" / "agents" / "missing.yaml"), "troupe.yml"
    )
    assert "include target not found" in err


def test_cycle_through_ref_exits_4(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(
        {
            "troupe.yml": "coder:\n  $ref: file:agents/coder.yaml\n",
            "agents/coder.yaml": "model: gpt\nback:\n  $ref: file:../troupe.yml\n  x: 1\n",
        }
    )

    err = _assert_load_refused(theatre, "troupe.yml", "coder.yaml")
    assert "include cycle" in err


@pytest.mark.parametrize("key", ['"$ref"', "'$ref'"])
def test_quoted_ref_key_is_recognised(make_theatre: MakeTheatre, key: str) -> None:
    theatre = make_theatre(
        {
            "troupe.yml": f"coder:\n  {key}: file:agents/coder.yaml\n  x: 1\n",
            "agents/coder.yaml": CODER,
        }
    )

    assert _cli(theatre, "show", "coder") == (
        0,
        "model: gpt\ntools:\n  shell: true\nstop:\n  - a\n  - b\nx: 1\n",
        "",
    )
