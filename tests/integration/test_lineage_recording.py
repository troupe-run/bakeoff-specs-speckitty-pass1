"""Lineage recording (FR-002..FR-011, FR-014), through the real CLI and the real history store.

Each test runs ``troupe config`` as a child process. The lineage is read back with
``stored_records``, which opens the theatre's real event store, because ``history`` does not print
lineage yet (WP04).
"""

from pathlib import Path

import pytest

from conftest import (
    MakeTheatre,
    WatchProcess,
    all_files,
    history_events,
    run_cli,
    snapshot,
    stored_records,
)
from troupe.lineage import UNKNOWN_ACTOR, Actor

ROOT = "model:\n  name: gpt\n  temperature: 0.2\nlimits:\n  max: 5\n  min: 0\n"
IMPORTED = 4  # leaves in ROOT
HISTORY_DB = ".troupe/history.sqlite"

INVALID_ACTORS = ["", "alice", "human:", "agent:", "Human:alice", "robot:x"]
COMMANDS = [
    pytest.param(("get", "model.name"), id="get"),
    pytest.param(("show",), id="show"),
    pytest.param(("set", "model.name", "x"), id="set"),
    pytest.param(("history",), id="history"),
    pytest.param(("watch",), id="watch"),
]


def _run(theatre: Path, *args: str, actor: str | None = None) -> tuple[int, str, str]:
    """Run ``troupe config <args> --theatre <theatre>``; return (code, stdout, stderr).

    ``watch`` runs as a ``WatchProcess`` with a deadline, so a bug that lets it start cannot hang
    the test run.
    """
    env = None if actor is None else {"TROUPE_ACTOR": actor}
    if args[0] == "watch":
        with WatchProcess("--theatre", str(theatre), env=env) as watch:
            return watch.wait_exit(timeout=10.0)
    result = run_cli("config", *args, "--theatre", str(theatre), env=env)
    return result.code, result.out, result.err


def _imported(make_theatre: MakeTheatre) -> Path:
    theatre = make_theatre({"troupe.yml": ROOT})
    assert len(history_events(theatre)) == IMPORTED
    return theatre


def _assert_rejected(code: int, out: str, err: str) -> None:
    assert (code, out) == (2, "")
    assert err.count("\n") == 1 and err.endswith("\n"), err
    assert err.startswith("troupe: TROUPE_ACTOR: invalid value"), err


@pytest.mark.parametrize("value", INVALID_ACTORS)
@pytest.mark.parametrize("command", COMMANDS)
def test_invalid_troupe_actor_exits_2_naming_the_variable_for_every_command(
    make_theatre: MakeTheatre, command: tuple[str, ...], value: str
) -> None:
    theatre = make_theatre({"troupe.yml": ROOT})
    before = snapshot(theatre)

    _assert_rejected(*_run(theatre, *command, actor=value))

    assert snapshot(theatre) == before
    assert not any(rel.startswith(HISTORY_DB) for rel in all_files(theatre))


@pytest.mark.parametrize("broken", [False, True], ids=["no-theatre", "broken-troupe-yml"])
def test_invalid_troupe_actor_is_reported_before_a_missing_or_broken_configuration(
    tmp_path: Path, make_theatre: MakeTheatre, broken: bool
) -> None:
    theatre = make_theatre({"troupe.yml": "a: [\n"}) if broken else tmp_path / "nowhere"

    assert run_cli("config", "get", "a", "--theatre", str(theatre)).code == 4
    _assert_rejected(*_run(theatre, "get", "a", actor="robot:x"))


def test_invalid_troupe_actor_records_nothing_in_an_imported_theatre(
    make_theatre: MakeTheatre,
) -> None:
    theatre = _imported(make_theatre)
    recorded = stored_records(theatre)
    (theatre / ".troupe" / "troupe.yml").write_text(ROOT.replace("max: 5", "max: 6"), "utf-8")

    _assert_rejected(*_run(theatre, "get", "limits.max", actor="alice"))

    assert stored_records(theatre) == recorded
    # The hand edit was real: a valid command reconciles it.
    assert run_cli("config", "get", "limits.max", "--theatre", str(theatre)).out == "6\n"
    assert len(stored_records(theatre)) == IMPORTED + 1


def test_reason_option_is_rejected_on_commands_other_than_set(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": ROOT})

    result = run_cli("config", "get", "model.name", "--reason", "r", "--theatre", str(theatre))

    assert (result.code, result.out) == (2, "")
    assert not any(rel.startswith(HISTORY_DB) for rel in all_files(theatre))


def test_set_records_cli_lineage_with_actor_and_reason(make_theatre: MakeTheatre) -> None:
    theatre = _imported(make_theatre)

    result = run_cli(
        "config",
        "set",
        "limits.max",
        "10",
        "--reason",
        "raise limit",
        "--theatre",
        str(theatre),
        env={"TROUPE_ACTOR": "agent:planner"},
    )

    assert (result.code, result.out, result.err) == (0, "", "")
    last = stored_records(theatre)[-1]
    assert (last.op, last.path, last.old, last.new) == ("set", "limits.max", 5, 10)
    assert last.lineage.actor == Actor("agent", "planner")
    assert (last.lineage.via, last.lineage.reason) == ("cli", "raise limit")
    assert last.lineage.at.endswith("Z")


def test_set_without_troupe_actor_uses_login_name(make_theatre: MakeTheatre) -> None:
    theatre = _imported(make_theatre)

    result = run_cli(
        "config",
        "set",
        "limits.max",
        "10",
        "--theatre",
        str(theatre),
        env={"LOGNAME": "bob", "USER": "bob"},
        unset=("LNAME", "USERNAME"),
    )

    assert (result.code, result.err) == (0, "")
    last = stored_records(theatre)[-1]
    assert (last.lineage.actor, last.lineage.via, last.lineage.reason) == (
        Actor("human", "bob"),
        "cli",
        None,
    )


def test_reconcile_before_set_and_import_are_separate_changes(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": ROOT})
    env = {"TROUPE_ACTOR": "agent:planner"}
    assert run_cli("config", "get", "model.name", "--theatre", str(theatre), env=env).code == 0
    edited = ROOT.replace("name: gpt", "name: claude").replace("temperature: 0.2", "temperature: 1")
    (theatre / ".troupe" / "troupe.yml").write_text(edited, "utf-8")

    result = run_cli(
        "config", "set", "limits", "{max: 10, min: 1}", "--theatre", str(theatre), env=env
    )

    assert (result.code, result.err) == (0, "")
    records = stored_records(theatre)
    groups = {
        via: [r for r in records if r.lineage.via == via] for via in ("import", "file", "cli")
    }
    assert [len(group) for group in groups.values()] == [IMPORTED, 2, 2]
    assert sum(len(group) for group in groups.values()) == len(records)
    for group in groups.values():
        assert len({(r.lineage.change, r.lineage.at) for r in group}) == 1
    assert len({group[0].lineage.change for group in groups.values()}) == 3
    assert {r.lineage.actor for r in groups["import"] + groups["file"]} == {UNKNOWN_ACTOR}
    assert {r.lineage.actor for r in groups["cli"]} == {Actor("agent", "planner")}
    assert [(r.path, r.new) for r in groups["file"]] == [
        ("model.name", "claude"),
        ("model.temperature", 1),
    ]


def test_noop_set_records_nothing(make_theatre: MakeTheatre) -> None:
    theatre = _imported(make_theatre)
    recorded = stored_records(theatre)

    result = run_cli(
        "config", "set", "limits.max", "5", "--reason", "why", "--theatre", str(theatre)
    )

    assert (result.code, result.err) == (0, "")
    assert stored_records(theatre) == recorded
