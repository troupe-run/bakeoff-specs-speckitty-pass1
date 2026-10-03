"""History events recorded by ``set`` (FR-008, FR-022, FR-023, US3), through the real CLI.

A ``set`` appends one ``set`` event per leaf it changes or creates and one ``remove`` event per
leaf that no longer exists, after its write succeeded. A ``set`` first reconciles, recording any
hand edits as their own events, so its own ``old`` is the current file value (FR-007 of mission
troupe-config-sync-files). No-op, refused and failed ``set`` commands append nothing of their own.
Every test also compares the complete bytes of every theatre file.
"""

import json
from pathlib import Path
from typing import Any

from conftest import CliResult, MakeTheatre, run_cli, snapshot

type Files = dict[str, str | bytes]

FIXTURE: Files = {
    "troupe.yml": (
        "model:\n"
        "  name: gpt\n"
        "  temperature: 0.2\n"
        "models: [x]\n"
        "tools: [a, b]\n"
        "agents:\n"
        "  coder: file:agents/coder.yaml\n"
    ),
    "agents/coder.yaml": "name: Ada\n",
}

IMPORT = [
    {"seq": 1, "op": "import", "path": "model.name", "old": None, "new": "gpt"},
    {"seq": 2, "op": "import", "path": "model.temperature", "old": None, "new": 0.2},
    {"seq": 3, "op": "import", "path": "models.0", "old": None, "new": "x"},
    {"seq": 4, "op": "import", "path": "tools.0", "old": None, "new": "a"},
    {"seq": 5, "op": "import", "path": "tools.1", "old": None, "new": "b"},
    {"seq": 6, "op": "import", "path": "agents.coder.name", "old": None, "new": "Ada"},
]


def _set(theatre: Path, path: str, value: str) -> CliResult:
    return run_cli("config", "set", path, value, "--theatre", str(theatre))


def _set_ok(theatre: Path, path: str, value: str) -> None:
    result = _set(theatre, path, value)
    assert (result.code, result.out, result.err) == (0, "", "")


def _history(theatre: Path, *path: str) -> list[dict[str, Any]]:
    result = run_cli("config", "history", *path, "--theatre", str(theatre))
    assert (result.code, result.err) == (0, ""), result.err
    return [json.loads(line) for line in result.out.splitlines()]


def _bytes(files: Files) -> dict[str, bytes]:
    return {
        f".troupe/{rel}": content.encode("utf-8") if isinstance(content, str) else content
        for rel, content in files.items()
    }


def _root(text: str) -> Files:
    return {**FIXTURE, "troupe.yml": text}


def _event(seq: int, op: str, path: str, old: object, new: object) -> dict[str, Any]:
    return {"seq": seq, "op": op, "path": path, "old": old, "new": new}


def test_first_set_on_fresh_theatre_imports_then_records_the_set(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre(FIXTURE)

    _set_ok(theatre, "model.temperature", "0.5")

    assert snapshot(theatre) == _bytes(
        _root(str(FIXTURE["troupe.yml"]).replace("temperature: 0.2", "temperature: 0.5"))
    )
    assert _history(theatre) == [*IMPORT, _event(7, "set", "model.temperature", 0.2, 0.5)]


def test_set_event_line_is_exact_json(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)
    _set_ok(theatre, "model.temperature", "0.5")

    result = run_cli("config", "history", "model.temperature", "--theatre", str(theatre))

    assert result.out == (
        '{"seq": 2, "op": "import", "path": "model.temperature", "old": null, "new": 0.2}\n'
        '{"seq": 7, "op": "set", "path": "model.temperature", "old": 0.2, "new": 0.5}\n'
    )


def test_set_after_hand_edit_records_the_hand_edit_then_the_set(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre(FIXTURE)
    assert _history(theatre) == IMPORT
    hand_edited = str(FIXTURE["troupe.yml"]).replace("name: gpt", "name: hand")
    (theatre / ".troupe/troupe.yml").write_text(hand_edited, encoding="utf-8")
    assert _history(theatre) == IMPORT  # ``history`` never reconciles, so nothing is recorded yet

    _set_ok(theatre, "model.name", "set")

    assert snapshot(theatre) == _bytes(_root(hand_edited.replace("name: hand", "name: set")))
    assert _history(theatre) == [
        *IMPORT,
        _event(7, "set", "model.name", "gpt", "hand"),  # the set's reconcile
        _event(8, "set", "model.name", "hand", "set"),  # the set's own event
    ]


def test_list_shrink_records_set_and_remove(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    _set_ok(theatre, "tools", "[c]")

    assert snapshot(theatre) == _bytes(
        _root(str(FIXTURE["troupe.yml"]).replace("tools: [a, b]\n", "tools:\n  - c\n"))
    )
    assert _history(theatre)[6:] == [
        _event(7, "set", "tools.0", "a", "c"),
        _event(8, "remove", "tools.1", "b", None),
    ]


def test_new_key_records_set_with_old_null(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    _set_ok(theatre, "model.limits", "{max: 5, min: null}")

    assert snapshot(theatre) == _bytes(
        _root(
            str(FIXTURE["troupe.yml"]).replace(
                "  temperature: 0.2\n", "  temperature: 0.2\n  limits:\n    max: 5\n    min: null\n"
            )
        )
    )
    assert _history(theatre)[6:] == [
        _event(7, "set", "model.limits.max", None, 5),
        _event(8, "set", "model.limits.min", None, None),
    ]


def test_scalar_replaced_by_mapping_records_new_leaves_and_removal(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre(FIXTURE)

    _set_ok(theatre, "model.name", "{id: gpt, rev: 2}")

    assert snapshot(theatre) == _bytes(
        _root(
            str(FIXTURE["troupe.yml"]).replace(
                "  name: gpt\n", "  name:\n    id: gpt\n    rev: 2\n"
            )
        )
    )
    assert _history(theatre)[6:] == [
        _event(7, "set", "model.name.id", None, "gpt"),
        _event(8, "set", "model.name.rev", None, 2),
        _event(9, "remove", "model.name", "gpt", None),
    ]


def test_append_records_set_for_new_item(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    _set_ok(theatre, "tools.2", "c")

    assert snapshot(theatre) == _bytes(
        _root(str(FIXTURE["troupe.yml"]).replace("[a, b]", "[a, b, c]"))
    )
    assert _history(theatre)[6:] == [_event(7, "set", "tools.2", None, "c")]


def test_set_inside_include_records_merged_path(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    _set_ok(theatre, "agents.coder.name", "Grace")

    assert snapshot(theatre) == _bytes({**FIXTURE, "agents/coder.yaml": "name: Grace\n"})
    assert _history(theatre)[6:] == [_event(7, "set", "agents.coder.name", "Ada", "Grace")]


def test_seq_continues_across_commands_and_filter_selects_subtree(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre(FIXTURE)

    _set_ok(theatre, "model.temperature", "0.5")
    _set_ok(theatre, "models.0", "y")
    _set_ok(theatre, "model.name", "o1")

    assert snapshot(theatre) == _bytes(
        _root(
            "model:\n"
            "  name: o1\n"
            "  temperature: 0.5\n"
            "models: [y]\n"
            "tools: [a, b]\n"
            "agents:\n"
            "  coder: file:agents/coder.yaml\n"
        )
    )
    assert [record["seq"] for record in _history(theatre)] == list(range(1, 10))
    assert _history(theatre, "model") == [
        IMPORT[0],
        IMPORT[1],
        _event(7, "set", "model.temperature", 0.2, 0.5),
        _event(9, "set", "model.name", "gpt", "o1"),
    ]


def test_no_op_refused_and_failed_sets_record_nothing(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    assert _set(theatre, "model.temperature", "0.2").code == 0
    assert _set(theatre, "agents.coder", "x").code == 3
    assert _set(theatre, "tools.7", "x").code == 5
    assert _set(theatre, "model.name", "[unclosed").code == 2

    assert snapshot(theatre) == _bytes(FIXTURE)
    assert _history(theatre) == IMPORT


def test_text_include_set_records_written_text(make_theatre: MakeTheatre) -> None:
    files: Files = {"troupe.yml": "prompt: file:p.md\n", "p.md": "old\n"}
    theatre = make_theatre(files)

    _set_ok(theatre, "prompt", "[a, b]")

    assert snapshot(theatre) == _bytes({**files, "p.md": "[a, b]"})
    assert _history(theatre) == [
        _event(1, "import", "prompt", None, "old\n"),
        _event(2, "set", "prompt", "old\n", "[a, b]"),
    ]
