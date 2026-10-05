"""``set`` adding keys and list items and changing a value's kind, through the real CLI.

Contract: FR-011 (deepest existing ancestor mapping, intermediate mappings), FR-012 (append),
FR-015 (new keys/values copy the preceding sibling's quoting), FR-016 (new collections; block at
the file's indentation, flow under a flow parent; scalar to block collection keeps the key line),
FR-019 (placement below trailing comments, above a less-indented line; flow append on the last
entry's line). Every test compares the complete bytes of every theatre file; after a successful
``set``, ``get`` reads the new leaf back.
"""

import json
from pathlib import Path
from typing import Any

from conftest import CliResult, MakeTheatre, run_cli, snapshot

type Files = dict[str, str | bytes]


def _set(theatre: Path, path: str, value: str, *flags: str) -> CliResult:
    return run_cli("config", "set", path, value, *flags, "--theatre", str(theatre))


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


def _check(
    make_theatre: MakeTheatre,
    files: Files,
    path: str,
    value: str,
    expected: Files,
    shown: dict[str, str],
    *,
    in_include: bool = False,
) -> Path:
    """Build ``files``, run ``set``, assert every file's bytes and ``get`` of each leaf."""
    theatre = make_theatre(files)
    flags = ["--in-include"] if in_include else []
    result = _set(theatre, path, value, *flags)
    assert (result.code, result.out, result.err) == (0, "", "")
    assert snapshot(theatre) == _bytes({**files, **expected})
    for leaf, printed in shown.items():
        assert _get(theatre, leaf) == printed
    return theatre


def _root(text: str) -> Files:
    return {"troupe.yml": text}


# --- New keys: placement (FR-011, FR-019, US2 scenario 6) ---------------------------------------


def test_new_key_goes_at_end_of_nested_mapping(make_theatre: MakeTheatre) -> None:
    _check(
        make_theatre,
        _root("model:\n  name: gpt\n  temperature: 0.2\ntools: [a]\n"),
        "model.top_p",
        "0.9",
        _root("model:\n  name: gpt\n  temperature: 0.2\n  top_p: 0.9\ntools: [a]\n"),
        {"model.top_p": "0.9\n"},
    )


def test_new_key_goes_below_trailing_comments_and_above_less_indented_comment(
    make_theatre: MakeTheatre,
) -> None:
    _check(
        make_theatre,
        _root(
            "model:\n"
            "  name: gpt\n"
            "  # trailing comment about model\n"
            "    # deeper comment\n"
            "# about tools\n"
            "tools: [a]\n"
        ),
        "model.temperature",
        "0.5",
        _root(
            "model:\n"
            "  name: gpt\n"
            "  # trailing comment about model\n"
            "    # deeper comment\n"
            "  temperature: 0.5\n"
            "# about tools\n"
            "tools: [a]\n"
        ),
        {"model.temperature": "0.5\n"},
    )


def test_new_root_key_goes_at_end_of_file_after_comments(make_theatre: MakeTheatre) -> None:
    _check(
        make_theatre,
        _root("a: 1\n# last words\n"),
        "b",
        "two",
        _root("a: 1\n# last words\nb: two\n"),
        {"b": "two\n"},
    )


def test_new_key_creates_intermediate_mappings_at_file_indentation(
    make_theatre: MakeTheatre,
) -> None:
    _check(
        make_theatre,
        _root("model:\n  name: gpt\nother: 1\n"),
        "model.limits.tokens.max",
        "100",
        _root("model:\n  name: gpt\n  limits:\n    tokens:\n      max: 100\nother: 1\n"),
        {"model.limits.tokens.max": "100\n"},
    )


def test_new_key_uses_four_space_file_indentation(make_theatre: MakeTheatre) -> None:
    _check(
        make_theatre,
        _root("model:\n    name: gpt\n"),
        "model.limits.max",
        "5",
        _root("model:\n    name: gpt\n    limits:\n        max: 5\n"),
        {"model.limits.max": "5\n"},
    )


def test_new_key_copies_preceding_sibling_key_and_value_quoting(
    make_theatre: MakeTheatre,
) -> None:
    _check(
        make_theatre,
        _root('env:\n  "HOME": "/home/a"\n'),
        "env.SHELL",
        "/bin/sh",
        _root('env:\n  "HOME": "/home/a"\n  "SHELL": "/bin/sh"\n'),
        {"env.SHELL": "/bin/sh\n"},
    )


def test_new_key_without_sibling_is_plain_or_minimally_quoted(make_theatre: MakeTheatre) -> None:
    _check(
        make_theatre,
        _root(""),
        "flag",
        '"yes: no"',
        _root("flag: 'yes: no'\n"),
        {"flag": "yes: no\n"},
    )


# Overrides (step 5) replaces rule 2 under set; the step-1 behaviour is now `--in-include`.


def test_new_key_under_included_mapping_becomes_override_in_including_file(
    make_theatre: MakeTheatre,
) -> None:
    files: Files = {
        "troupe.yml": "agents:\n  coder: file:agents/coder.yaml\n",
        "agents/coder.yaml": "name: Ada\n",
    }
    _check(
        make_theatre,
        files,
        "agents.coder.limits.level",
        "3",
        {
            "troupe.yml": (
                "agents:\n  coder:\n    $ref: file:agents/coder.yaml\n    limits:\n      level: 3\n"
            )
        },
        {"agents.coder.limits.level": "3\n", "agents.coder.name": "Ada\n"},
    )


def test_new_key_under_empty_included_file_becomes_override(make_theatre: MakeTheatre) -> None:
    files: Files = {"troupe.yml": "extra: file:extra.yml\n", "extra.yml": ""}
    _check(
        make_theatre,
        files,
        "extra.a",
        "1",
        {"troupe.yml": "extra:\n  $ref: file:extra.yml\n  a: 1\n"},
        {"extra.a": "1\n"},
    )


def test_in_include_new_key_goes_into_included_files_mapping(make_theatre: MakeTheatre) -> None:
    files: Files = {
        "troupe.yml": "agents:\n  coder: file:agents/coder.yaml\n",
        "agents/coder.yaml": "name: Ada\n",
    }
    _check(
        make_theatre,
        files,
        "agents.coder.limits.level",
        "3",
        {"agents/coder.yaml": "name: Ada\nlimits:\n  level: 3\n"},
        {"agents.coder.limits.level": "3\n"},
        in_include=True,
    )


def test_in_include_new_key_into_empty_included_file(make_theatre: MakeTheatre) -> None:
    files: Files = {"troupe.yml": "extra: file:extra.yml\n", "extra.yml": ""}
    _check(
        make_theatre,
        files,
        "extra.a",
        "1",
        {"extra.yml": "a: 1\n"},
        {"extra.a": "1\n"},
        in_include=True,
    )


def test_new_key_with_collection_value_is_block_style(make_theatre: MakeTheatre) -> None:
    _check(
        make_theatre,
        _root("model:\n  name: gpt\n"),
        "model.stop",
        "{words: [end, halt], max: 2}",
        _root("model:\n  name: gpt\n  stop:\n    words:\n      - end\n      - halt\n    max: 2\n"),
        {"model.stop.words.1": "halt\n", "model.stop.max": "2\n"},
    )


def test_new_key_with_multi_line_string_is_literal_block(make_theatre: MakeTheatre) -> None:
    _check(
        make_theatre,
        _root("a: 1\nb: 2\n"),
        "notes",
        '"one\\ntwo\\n"',
        _root("a: 1\nb: 2\nnotes: |\n  one\n  two\n"),
        {"notes": "one\ntwo\n"},
    )


def test_new_key_in_flow_mapping_is_flow_on_the_last_entry_line(
    make_theatre: MakeTheatre,
) -> None:
    _check(
        make_theatre,
        _root("m: {a: 1,  b: 2}  # c\n"),
        "m.x.y",
        "3",
        _root("m: {a: 1,  b: 2,  x: {y: 3}} # c\n"),
        {"m.x.y": "3\n"},
    )


def test_new_key_with_multi_line_string_in_flow_mapping_is_double_quoted(
    make_theatre: MakeTheatre,
) -> None:
    _check(
        make_theatre,
        _root("m: {a: 1}\n"),
        "m.text",
        '"one\\ntwo"',
        _root('m: {a: 1, text: "one\\ntwo"}\n'),
        {"m.text": "one\ntwo\n"},
    )


def test_new_key_in_empty_flow_mapping(make_theatre: MakeTheatre) -> None:
    _check(
        make_theatre,
        _root("m: {}\n"),
        "m.a",
        "1",
        _root("m: {a: 1}\n"),
        {"m.a": "1\n"},
    )


# --- List append (FR-012, FR-019, US2 scenario 5) -----------------------------------------------


def test_flow_list_append_goes_on_last_entry_line(make_theatre: MakeTheatre) -> None:
    _check(
        make_theatre,
        _root("tools: [a, b]\n"),
        "tools.2",
        "c",
        _root("tools: [a, b, c]\n"),
        {"tools.2": "c\n"},
    )


def test_multi_line_flow_list_append_keeps_comment_column(make_theatre: MakeTheatre) -> None:
    _check(
        make_theatre,
        _root("tools: [\n  a,\n  b   # last\n]\n"),
        "tools.2",
        "c",
        _root("tools: [\n  a,\n  b, c # last\n]\n"),
        {"tools.2": "c\n"},
    )


def test_append_to_empty_flow_list(make_theatre: MakeTheatre) -> None:
    _check(
        make_theatre,
        _root("tools: []\n"),
        "tools.0",
        "a",
        _root("tools: [a]\n"),
        {"tools.0": "a\n"},
    )


def test_block_list_append_goes_below_trailing_comments(make_theatre: MakeTheatre) -> None:
    _check(
        make_theatre,
        _root("tools:\n  - 'a'\n  # more later\nnext: 1\n"),
        "tools.1",
        "b",
        _root("tools:\n  - 'a'\n  # more later\n  - 'b'\nnext: 1\n"),
        {"tools.1": "b\n"},
    )


def test_flush_block_list_append(make_theatre: MakeTheatre) -> None:
    _check(
        make_theatre,
        _root("tools:\n- a\n- b\nnext: 1\n"),
        "tools.2",
        "c",
        _root("tools:\n- a\n- b\n- c\nnext: 1\n"),
        {"tools.2": "c\n"},
    )


def test_append_mapping_to_list_of_mappings(make_theatre: MakeTheatre) -> None:
    _check(
        make_theatre,
        _root("agents:\n  - name: a\n    level: 1\n"),
        "agents.1",
        "{name: b, level: 2}",
        _root("agents:\n  - name: a\n    level: 1\n  - name: b\n    level: 2\n"),
        {"agents.1.name": "b\n", "agents.1.level": "2\n"},
    )


def test_new_key_in_mapping_inside_list(make_theatre: MakeTheatre) -> None:
    _check(
        make_theatre,
        _root("agents:\n  - name: a\n  - name: b\n"),
        "agents.0.level",
        "1",
        _root("agents:\n  - name: a\n    level: 1\n  - name: b\n"),
        {"agents.0.level": "1\n"},
    )


def test_append_at_index_after_new_item_exits_5(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(_root("tools: [a, b]\n"))
    before = snapshot(theatre)

    result = _set(theatre, "tools.2.name", "c")

    assert (result.code, result.out) == (5, "")
    assert "tools.2" in result.err
    assert snapshot(theatre) == before


# --- Kind changes (FR-016) ----------------------------------------------------------------------


def test_scalar_to_block_mapping_keeps_key_line_through_comment(
    make_theatre: MakeTheatre,
) -> None:
    _check(
        make_theatre,
        _root("model: gpt  # which model\nnext: 1\n"),
        "model",
        "{name: gpt, size: 7}",
        _root("model:      # which model\n  name: gpt\n  size: 7\nnext: 1\n"),
        {"model.name": "gpt\n", "model.size": "7\n"},
    )


def test_block_list_to_scalar(make_theatre: MakeTheatre) -> None:
    _check(
        make_theatre,
        _root("tools:\n  - a\n  - b\nnext: 1\n"),
        "tools",
        "none",
        _root("tools: none\nnext: 1\n"),
        {"tools": "none\n"},
    )


def test_flow_list_replaced_by_list_under_block_parent_becomes_block(
    make_theatre: MakeTheatre,
) -> None:
    _check(
        make_theatre,
        _root("tools: [a, b]  # t\nnext: 1\n"),
        "tools",
        "[c]",
        _root("tools:         # t\n  - c\nnext: 1\n"),
        {"tools.0": "c\n"},
    )


def test_collection_in_flow_parent_is_replaced_in_flow_style(make_theatre: MakeTheatre) -> None:
    _check(
        make_theatre,
        _root("m: {a: 1, b: [x, y]}\n"),
        "m.b",
        "{k: v}",
        _root("m: {a: 1, b: {k: v}}\n"),
        {"m.b.k": "v\n"},
    )


def test_list_shrinks_to_shorter_list(make_theatre: MakeTheatre) -> None:
    theatre = _check(
        make_theatre,
        _root("tools:\n  - a\n  - b\n"),
        "tools",
        "[c]",
        _root("tools:\n  - c\n"),
        {"tools.0": "c\n"},
    )
    assert _set(theatre, "tools.1", "x").code == 0  # index 1 == new length: appends
