"""Reconcile first (User Story 1, FR-002..FR-007, NFR-004), through the real CLI.

Hand edits made while nothing ran are recorded by the next ``get``, ``show`` or ``set`` before it
does its own work; ``history`` never reconciles. The number in each test's comment is the US1
acceptance scenario it covers. Wherever a reconcile runs, the files are compared byte for byte
with what the hand edit left (a reconcile never writes a file).
"""

import json
from pathlib import Path
from typing import Any

import pytest

from conftest import CliResult, MakeTheatre, core, run_cli, snapshot

type Files = dict[str, str | bytes]

ROOT = (
    "model:\n"
    "  name: gpt\n"
    "  temperature: 0.2\n"
    "tools: [a, b]\n"
    "agents:\n"
    "  coder: file:agents/coder.yaml\n"
    "prompt: file:sys.md\n"
)
FIXTURE: Files = {
    "troupe.yml": ROOT,
    "agents/coder.yaml": "name: Ada\nlevel: 3\n",
    "sys.md": "Be kind.\n",
}
IMPORTED = 7  # leaves in FIXTURE, so the first non-import event has seq 8


def _history(theatre: Path) -> list[dict[str, Any]]:
    result = run_cli("config", "history", "--theatre", str(theatre))
    assert (result.code, result.err) == (0, ""), result.err
    return [json.loads(line) for line in result.out.splitlines()]


def _get(theatre: Path, path: str) -> CliResult:
    return run_cli("config", "get", path, "--theatre", str(theatre))


def _set(theatre: Path, path: str, value: str) -> CliResult:
    return run_cli("config", "set", path, value, "--theatre", str(theatre))


def _event(seq: int, op: str, path: str, old: object, new: object) -> dict[str, Any]:
    return {"seq": seq, "op": op, "path": path, "old": old, "new": new}


def _imported(make_theatre: MakeTheatre) -> Path:
    """Build the fixture theatre and import it with ``history`` (which records nothing else)."""
    theatre = make_theatre(FIXTURE)
    assert len(_history(theatre)) == IMPORTED
    return theatre


def _edit(theatre: Path, rel: str, text: str) -> dict[str, bytes]:
    """Hand-edit ``.troupe/<rel>`` and return the snapshot of the edited theatre."""
    (theatre / ".troupe" / rel).write_text(text, encoding="utf-8")
    return snapshot(theatre)


def _edit_root(theatre: Path, old: str, new: str) -> dict[str, bytes]:
    assert old in ROOT
    return _edit(theatre, "troupe.yml", ROOT.replace(old, new))


def test_get_after_hand_edit_prints_new_value_and_records_one_set(
    make_theatre: MakeTheatre,
) -> None:  # 1
    theatre = _imported(make_theatre)
    edited = _edit_root(theatre, "temperature: 0.2", "temperature: 0.5")

    shown = _get(theatre, "model.temperature")

    assert (shown.code, shown.out, shown.err) == (0, "0.5\n", "")
    assert core(_history(theatre)[IMPORTED:]) == [_event(8, "set", "model.temperature", 0.2, 0.5)]
    assert snapshot(theatre) == edited


def test_key_added_by_hand_records_set_with_old_null(make_theatre: MakeTheatre) -> None:  # 2
    theatre = _imported(make_theatre)
    edited = _edit_root(theatre, "  temperature: 0.2\n", "  temperature: 0.2\n  top_p: 0.9\n")

    assert _get(theatre, "model.temperature").code == 0

    assert core(_history(theatre)[IMPORTED:]) == [_event(8, "set", "model.top_p", None, 0.9)]
    assert snapshot(theatre) == edited


def test_list_item_deleted_by_hand_records_remove(make_theatre: MakeTheatre) -> None:  # 3
    theatre = _imported(make_theatre)
    edited = _edit_root(theatre, "tools: [a, b]", "tools: [a]")

    assert _get(theatre, "model.name").code == 0

    assert core(_history(theatre)[IMPORTED:]) == [_event(8, "remove", "tools.1", "b", None)]
    assert snapshot(theatre) == edited


def test_formatting_and_comment_only_edits_then_get_record_nothing(
    make_theatre: MakeTheatre,
) -> None:  # 4
    theatre = _imported(make_theatre)
    imported = _history(theatre)
    edited = _edit(
        theatre,
        "troupe.yml",
        "# hand-written comment\n"
        "model: {name: 'gpt', temperature: 0.20}\n"
        "tools:\n"
        "    - a\n"
        '    - "b"  # still b\n'
        "\n"
        "agents:\n"
        "  coder: file:agents/coder.yaml\n"
        "prompt: file:sys.md\n",
    )

    assert _get(theatre, "model.temperature").out == "0.2\n"

    assert _history(theatre) == imported
    assert snapshot(theatre) == edited


def test_text_include_edited_by_hand_records_one_set_with_old_and_new_text(
    make_theatre: MakeTheatre,
) -> None:  # 5
    theatre = _imported(make_theatre)
    edited = _edit(theatre, "sys.md", "Be brief.\n")

    assert _get(theatre, "model.name").code == 0

    assert core(_history(theatre)[IMPORTED:]) == [
        _event(8, "set", "prompt", "Be kind.\n", "Be brief.\n")
    ]
    assert snapshot(theatre) == edited


def test_history_never_reconciles_but_the_next_get_does(make_theatre: MakeTheatre) -> None:  # 6
    theatre = _imported(make_theatre)
    imported = _history(theatre)
    edited = _edit(theatre, "agents/coder.yaml", "name: Grace\nlevel: 3\n")

    assert _history(theatre) == imported
    assert _history(theatre) == imported
    assert _get(theatre, "agents.coder.name").out == "Grace\n"

    assert core(_history(theatre)) == [
        *core(imported),
        _event(8, "set", "agents.coder.name", "Ada", "Grace"),
    ]
    assert snapshot(theatre) == edited


def test_set_after_hand_edit_records_reconcile_event_then_set_event(
    make_theatre: MakeTheatre,
) -> None:  # 7
    theatre = _imported(make_theatre)
    _edit_root(theatre, "temperature: 0.2", "temperature: 0.5")

    result = _set(theatre, "model.temperature", "0.7")

    assert (result.code, result.out, result.err) == (0, "", "")
    assert core(_history(theatre)[IMPORTED:]) == [
        _event(8, "set", "model.temperature", 0.2, 0.5),
        _event(9, "set", "model.temperature", 0.5, 0.7),
    ]
    assert snapshot(theatre)[".troupe/troupe.yml"] == ROOT.replace(
        "temperature: 0.2", "temperature: 0.7"
    ).encode("utf-8")


@pytest.mark.parametrize(
    ("path", "value", "code"),
    [
        pytest.param("agents.coder", "x", 3, id="refused-whole-yaml-include"),
        pytest.param("tools.7", "x", 5, id="path-error"),
    ],
)
def test_set_failing_after_reconcile_keeps_reconcile_events_and_records_no_set(
    make_theatre: MakeTheatre, path: str, value: str, code: int
) -> None:  # 8, D-7
    theatre = _imported(make_theatre)
    edited = _edit_root(theatre, "name: gpt", "name: hand")

    result = _set(theatre, path, value)

    assert (result.code, result.out) == (code, "")
    assert path in result.err
    assert core(_history(theatre)[IMPORTED:]) == [_event(8, "set", "model.name", "gpt", "hand")]
    assert snapshot(theatre) == edited


@pytest.mark.parametrize(
    ("rel", "good", "bad"),
    [
        pytest.param(
            "troupe.yml",
            ROOT.replace("name: gpt", "name: hand"),
            ROOT.replace("name: gpt", "name: [unclosed"),
            id="root-file",
        ),
        pytest.param(
            "agents/coder.yaml",
            "name: Grace\nlevel: 3\n",
            "name: [unclosed\nlevel: 3\n",
            id="included-file",
        ),
    ],
)
@pytest.mark.parametrize("command", ["get", "show", "set"])
def test_unloadable_hand_edit_exits_4_names_the_file_and_records_nothing(
    make_theatre: MakeTheatre, command: str, rel: str, good: str, bad: str
) -> None:  # 9
    theatre = _imported(make_theatre)
    imported = _history(theatre)
    broken = _edit(theatre, rel, bad)
    args = ["model.temperature", "0.7"] if command == "set" else ["model.temperature"]

    result = run_cli("config", command, *args, "--theatre", str(theatre))

    assert (result.code, result.out) == (4, "")
    assert str(theatre / ".troupe" / rel) in result.err
    assert snapshot(theatre) == broken

    # ``history`` loads too, so while the file is broken it exits 4 as well...
    broken_history = run_cli("config", "history", "--theatre", str(theatre))
    assert (broken_history.code, broken_history.out) == (4, "")
    assert str(theatre / ".troupe" / rel) in broken_history.err
    assert snapshot(theatre) == broken

    # ...so it can only be read once the file is repaired; the failed
    # command recorded nothing and ``history`` itself does not reconcile the repaired edit.
    _edit(theatre, rel, good)
    assert _history(theatre) == imported
    assert _get(theatre, "model.temperature").out == "0.2\n"
    assert len(_history(theatre)) == IMPORTED + 1


def test_two_gets_after_one_hand_edit_record_it_once(make_theatre: MakeTheatre) -> None:  # 10
    theatre = _imported(make_theatre)
    edited = _edit_root(theatre, "temperature: 0.2", "temperature: 0.5")

    assert _get(theatre, "model.temperature").out == "0.5\n"
    assert _get(theatre, "model.temperature").out == "0.5\n"

    assert core(_history(theatre)[IMPORTED:]) == [_event(8, "set", "model.temperature", 0.2, 0.5)]
    assert snapshot(theatre) == edited


def test_set_usage_error_with_pending_hand_edit_exits_2_and_records_nothing(
    make_theatre: MakeTheatre,
) -> None:
    theatre = _imported(make_theatre)
    imported = _history(theatre)
    edited = _edit_root(theatre, "temperature: 0.2", "temperature: 0.5")

    result = _set(theatre, "a..b", "1")

    assert (result.code, result.out) == (2, "")
    assert "a..b" in result.err
    assert _history(theatre) == imported
    assert snapshot(theatre) == edited


def test_history_built_by_step_one_commands_reconciles_on_get(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre(FIXTURE)
    assert len(_history(theatre)) == IMPORTED
    assert _set(theatre, "model.temperature", "0.5").code == 0
    assert _set(theatre, "tools.2", "c").code == 0
    edited = _edit(
        theatre,
        "troupe.yml",
        ROOT.replace("temperature: 0.2", "temperature: 0.9").replace("[a, b]", "[a, c]"),
    )

    assert _get(theatre, "model.temperature").out == "0.9\n"

    assert core(_history(theatre)[IMPORTED:]) == [
        _event(8, "set", "model.temperature", 0.2, 0.5),
        _event(9, "set", "tools.2", None, "c"),
        _event(10, "set", "model.temperature", 0.5, 0.9),
        _event(11, "set", "tools.1", "b", "c"),
        _event(12, "remove", "tools.2", "c", None),
    ]
    assert snapshot(theatre) == edited
