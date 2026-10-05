"""``set --in-include`` (US4), through the real CLI and real files.

Contract *In-include* (spec FR-010, FR-011, D-8, D-9): with ``--in-include`` a new key goes into
the file holding its deepest existing ancestor, the innermost included file that defines it (the
step-1 rule); existing values change where they live, exactly as without the flag; the flag is
accepted only by ``set``, anywhere among its arguments, and combines with ``--reason``. Every
successful test compares the bytes of every theatre file.
"""

from pathlib import Path

import pytest

from conftest import CliResult, MakeTheatre, history_events, run_cli, snapshot

type Files = dict[str, str | bytes]

CODER = "agents/coder.yaml"
CONTRACT_EXAMPLE: Files = {
    "troupe.yml": "coder: file:agents/coder.yaml  # c\n",
    CODER: "model: gpt\n",
}


def _set(theatre: Path, *args: str, env: dict[str, str] | None = None) -> CliResult:
    return run_cli("config", "set", *args, "--theatre", str(theatre), env=env)


def _get(theatre: Path, path: str) -> str:
    result = run_cli("config", "get", path, "--theatre", str(theatre))
    assert (result.code, result.err) == (0, ""), result.err
    return result.out


def _bytes(files: Files) -> dict[str, bytes]:
    return {
        f".troupe/{rel}": content.encode("utf-8") if isinstance(content, str) else content
        for rel, content in files.items()
    }


def _check_in_include(
    make_theatre: MakeTheatre,
    files: Files,
    path: str,
    value: str,
    expected: Files,
    shown: dict[str, str],
) -> Path:
    """Build ``files``, run ``set --in-include``, assert every file's bytes and ``get``."""
    theatre = make_theatre(files)
    result = _set(theatre, "--in-include", path, value)
    assert (result.code, result.out, result.err) == (0, "", "")
    assert snapshot(theatre) == _bytes({**files, **expected})
    for leaf, printed in shown.items():
        assert _get(theatre, leaf) == printed
    return theatre


def test_in_include_appends_new_key_to_included_file(make_theatre: MakeTheatre) -> None:
    _check_in_include(
        make_theatre,
        CONTRACT_EXAMPLE,
        "coder.temperature",
        "0.3",
        {CODER: "model: gpt\ntemperature: 0.3\n"},
        {"coder.temperature": "0.3\n", "coder.model": "gpt\n"},
    )


def test_in_include_nested_writes_innermost_file(make_theatre: MakeTheatre) -> None:
    files: Files = {
        "troupe.yml": "coder: file:agents/coder.yaml\n",
        CODER: "model: file:models/base.yaml\n",
        "agents/models/base.yaml": "name: gpt\n",
    }
    _check_in_include(
        make_theatre,
        files,
        "coder.model.temperature",
        "0.3",
        {"agents/models/base.yaml": "name: gpt\ntemperature: 0.3\n"},
        {"coder.model.temperature": "0.3\n", "coder.model.name": "gpt\n"},
    )


def test_in_include_without_include_equals_plain_set(make_theatre: MakeTheatre) -> None:
    files: Files = {"troupe.yml": "a:\n  x: 1  # keep\nb: 2\n"}
    flagged = make_theatre(files)
    result = _set(flagged, "--in-include", "a.b", "1")
    assert (result.code, result.out, result.err) == (0, "", "")
    with_flag = snapshot(flagged)

    plain = make_theatre(files)  # the same directory, rebuilt from the same files
    result = _set(plain, "a.b", "1")
    assert (result.code, result.out, result.err) == (0, "", "")

    assert (
        with_flag == snapshot(plain) == _bytes({"troupe.yml": "a:\n  x: 1  # keep\n  b: 1\nb: 2\n"})
    )


def test_in_include_on_overridden_existing_value_changes_override(
    make_theatre: MakeTheatre,
) -> None:
    files: Files = {
        "troupe.yml": "coder:\n  $ref: file:agents/coder.yaml\n  temperature: 0.3\n",
        CODER: "model: gpt\ntemperature: 0.7\n",
    }
    _check_in_include(
        make_theatre,
        files,
        "coder.temperature",
        "0.5",
        {"troupe.yml": "coder:\n  $ref: file:agents/coder.yaml\n  temperature: 0.5\n"},
        {"coder.temperature": "0.5\n"},
    )


@pytest.mark.parametrize(
    "args",
    [
        ("get", "--in-include", "coder.model"),
        ("show", "--in-include"),
        ("history", "--in-include"),
        ("watch", "--in-include"),
    ],
    ids=["get", "show", "history", "watch"],
)
def test_in_include_is_rejected_by_other_subcommands(
    make_theatre: MakeTheatre, args: tuple[str, ...]
) -> None:
    theatre = make_theatre(CONTRACT_EXAMPLE)

    result = run_cli("config", *args, "--theatre", str(theatre))

    assert (result.code, result.out) == (2, "")
    assert result.err.startswith("troupe: ") and result.err.count("\n") == 1
    assert "--in-include" in result.err
    assert snapshot(theatre) == _bytes(CONTRACT_EXAMPLE)


def test_in_include_with_reason_records_lineage(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(CONTRACT_EXAMPLE)
    imported = len(history_events(theatre))

    result = _set(
        theatre,
        "--in-include",
        "coder.temperature",
        "0.3",
        "--reason",
        "shared default",
        env={"TROUPE_ACTOR": "human:alice"},
    )

    assert (result.code, result.out, result.err) == (0, "", "")
    assert snapshot(theatre) == _bytes(
        {**CONTRACT_EXAMPLE, CODER: "model: gpt\ntemperature: 0.3\n"}
    )
    [event] = history_events(theatre)[imported:]
    assert (event["op"], event["path"], event["old"], event["new"]) == (
        "set",
        "coder.temperature",
        None,
        0.3,
    )
    assert (event["via"], event["reason"]) == ("cli", "shared default")
    assert event["actor"] == {"kind": "human", "id": "alice"}


@pytest.mark.parametrize(
    "args",
    [
        ("--in-include", "coder.temperature", "0.3"),
        ("coder.temperature", "--in-include", "0.3"),
        ("coder.temperature", "0.3", "--in-include"),
    ],
    ids=["before", "between", "after"],
)
def test_in_include_flag_position_is_free(make_theatre: MakeTheatre, args: tuple[str, ...]) -> None:
    theatre = make_theatre(CONTRACT_EXAMPLE)

    result = _set(theatre, *args)

    assert (result.code, result.out, result.err) == (0, "", "")
    assert snapshot(theatre) == _bytes(
        {**CONTRACT_EXAMPLE, CODER: "model: gpt\ntemperature: 0.3\n"}
    )


# --- A new base key sits before the override-only keys in the merged view (review cycle 1) -----


def test_in_include_new_key_under_include_with_override_only_keys(
    make_theatre: MakeTheatre,
) -> None:
    files: Files = {
        "troupe.yml": "coder: {$ref: file:agents/coder.yaml, top_p: 0.8}\n",
        CODER: "model: gpt\ntemperature: 0.7\n",
    }
    _check_in_include(
        make_theatre,
        files,
        "coder.max_tokens",
        "100",
        {CODER: "model: gpt\ntemperature: 0.7\nmax_tokens: 100\n"},
        {"coder.max_tokens": "100\n", "coder.top_p": "0.8\n"},
    )


def test_in_include_new_key_under_nested_merged_mapping(make_theatre: MakeTheatre) -> None:
    files: Files = {
        "troupe.yml": "coder:\n  $ref: file:c.yaml\n  limits:\n    x: 1\n",
        "c.yaml": "limits:\n  a: 1\n",
    }
    _check_in_include(
        make_theatre,
        files,
        "coder.limits.b",
        "2",
        {"c.yaml": "limits:\n  a: 1\n  b: 2\n"},
        {"coder.limits.a": "1\n", "coder.limits.b": "2\n", "coder.limits.x": "1\n"},
    )


def test_quickstart_runs_end_to_end(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(CONTRACT_EXAMPLE | {CODER: "model: gpt\ntemperature: 0.7\n"})
    steps: list[tuple[tuple[str, ...], Files]] = [
        (
            ("coder.top_p", "0.9"),
            {"troupe.yml": "coder:  # c\n  $ref: file:agents/coder.yaml\n  top_p: 0.9\n"},
        ),
        (("coder.temperature", "0.5"), {CODER: "model: gpt\ntemperature: 0.5\n"}),
        (
            ("coder.top_p", "0.8"),
            {"troupe.yml": "coder:  # c\n  $ref: file:agents/coder.yaml\n  top_p: 0.8\n"},
        ),
        (
            ("--in-include", "coder.max_tokens", "100"),
            {CODER: "model: gpt\ntemperature: 0.5\nmax_tokens: 100\n"},
        ),
    ]
    expected = _bytes({**CONTRACT_EXAMPLE, CODER: "model: gpt\ntemperature: 0.7\n"})
    for args, changed in steps:
        result = _set(theatre, *args)
        assert (result.code, result.out, result.err) == (0, "", ""), args
        expected |= _bytes(changed)
        assert snapshot(theatre) == expected, args

    shown = run_cli("config", "show", "coder", "--sources", "--theatre", str(theatre))
    assert (shown.code, shown.err) == (0, "")
    assert shown.out == (
        "model: gpt # from .troupe/agents/coder.yaml\n"
        "temperature: 0.5 # from .troupe/agents/coder.yaml\n"
        "max_tokens: 100 # from .troupe/agents/coder.yaml\n"
        "top_p: 0.8 # from .troupe/troupe.yml\n"
    )
    history = run_cli("config", "history", "--theatre", str(theatre))
    assert (history.code, history.err) == (0, "")
