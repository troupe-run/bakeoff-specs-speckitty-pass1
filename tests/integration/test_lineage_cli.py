"""User Story 1 and its edge cases, proved through ``troupe config history`` output.

Each test builds a theatre, imports it with one ``history`` run, runs the CLI as a child process,
then reads the lineage back from ``history``: every line is checked against the contract by
``_valid_record`` (contracts/cli.md, history-event.schema.json). ``TROUPE_ACTOR`` and the login
variables are always set or stripped explicitly, so the developer's shell cannot change a result.
"""

import os
import pwd
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from test_history import _valid_record

from conftest import CliResult, MakeTheatre, run_cli, snapshot

FILES: dict[str, str | bytes] = {
    "troupe.yml": (
        "limits:\n"
        "  max: 5\n"
        "model:\n"
        "  name: gpt\n"
        "tools: [a, b]\n"
        "agents:\n"
        "  coder: file:agents/coder.yaml\n"
    ),
    "agents/coder.yaml": "name: Ada\n",
}
IMPORTED = 5  # leaves in FILES
UNKNOWN = {"kind": "unknown", "id": None}
LOGIN_VARS = ("LOGNAME", "USER", "LNAME", "USERNAME")
INVALID_ACTORS = ["robot:x", "human:", "agent:", "alice", "", "Human:alice"]


def _history_text(theatre: Path) -> str:
    result = run_cli("config", "history", "--theatre", str(theatre))
    assert (result.code, result.err) == (0, ""), result.err
    return result.out


def _history(theatre: Path) -> list[dict[str, Any]]:
    return [_valid_record(line) for line in _history_text(theatre).splitlines()]


def _imported(make_theatre: MakeTheatre) -> Path:
    theatre = make_theatre(FILES)
    assert len(_history(theatre)) == IMPORTED
    return theatre


def _set(
    theatre: Path,
    *args: str,
    env: dict[str, str] | None = None,
    unset: tuple[str, ...] = (),
) -> CliResult:
    return run_cli("config", "set", *args, "--theatre", str(theatre), env=env, unset=unset)


def _new_events(theatre: Path, *args: str, env: dict[str, str]) -> list[dict[str, Any]]:
    """Run a successful ``set`` and return the ``history`` lines it added."""
    before = len(_history(theatre))
    result = _set(theatre, *args, env=env)
    assert (result.code, result.out, result.err) == (0, "", ""), result.err
    return _history(theatre)[before:]


def test_agent_set_with_reason_is_attributed_to_the_agent_via_cli(
    make_theatre: MakeTheatre,
) -> None:  # US1-1
    theatre = _imported(make_theatre)
    import_change = _history(theatre)[0]["change"]

    [event] = _new_events(
        theatre,
        "limits.max",
        "10",
        "--reason",
        "raise limit",
        env={"TROUPE_ACTOR": "agent:planner"},
    )

    assert (event["op"], event["path"], event["old"], event["new"]) == ("set", "limits.max", 5, 10)
    assert event["actor"] == {"kind": "agent", "id": "planner"}
    assert (event["via"], event["reason"]) == ("cli", "raise limit")
    assert event["at"].endswith("Z")
    assert event["change"] != import_change


def test_human_actor_without_reason_has_null_reason(make_theatre: MakeTheatre) -> None:  # US1-2
    theatre = _imported(make_theatre)

    [event] = _new_events(theatre, "limits.max", "10", env={"TROUPE_ACTOR": "human:alice"})

    assert event["actor"] == {"kind": "human", "id": "alice"}
    assert (event["via"], event["reason"]) == ("cli", None)


def test_unset_actor_is_the_login_name(make_theatre: MakeTheatre) -> None:  # US1-3
    theatre = _imported(make_theatre)

    result = _set(
        theatre, "limits.max", "10", env={"LOGNAME": "bob", "USER": "bob"}, unset=LOGIN_VARS
    )

    assert (result.code, result.err) == (0, "")
    event = _history(theatre)[-1]
    assert (event["path"], event["actor"], event["via"]) == (
        "limits.max",
        {"kind": "human", "id": "bob"},
        "cli",
    )


def test_unset_actor_without_login_variables_is_the_password_database_name(
    make_theatre: MakeTheatre,
) -> None:  # US1-3: the same fallback getpass uses, computed independently
    theatre = _imported(make_theatre)
    expected = pwd.getpwuid(os.getuid()).pw_name

    result = _set(theatre, "limits.max", "10", unset=LOGIN_VARS)

    assert (result.code, result.err) == (0, "")
    event = _history(theatre)[-1]
    assert (event["path"], event["actor"]) == ("limits.max", {"kind": "human", "id": expected})


# Runs the real CLI entry point in a child whose password database has no entry for its uid, the
# operating-system condition in which no login name exists once the login variables are unset.
NO_PASSWD_ENTRY = (
    "import pwd\n"
    "def _missing(uid):\n"
    "    raise KeyError(f'getpwuid(): uid not found: {uid}')\n"
    "pwd.getpwuid = _missing\n"
    "from troupe.cli import main\n"
    "raise SystemExit(main())\n"
)


def test_unset_actor_with_no_determinable_login_is_human_with_null_id(
    make_theatre: MakeTheatre,
) -> None:  # US1-5, FR-004 (DM 01M436TX68S2MGE4DN9AM02KTJ)
    theatre = _imported(make_theatre)
    removed = {"TROUPE_ACTOR", "TROUPE_THEATRE", *LOGIN_VARS}
    env = {key: value for key, value in os.environ.items() if key not in removed}

    args = ["config", "set", "limits.max", "10", "--theatre", str(theatre)]
    completed = subprocess.run(
        [sys.executable, "-c", NO_PASSWD_ENTRY, *args],
        capture_output=True,
        env=env,
        check=False,
    )

    assert (completed.returncode, completed.stderr) == (0, b"")
    event = _history(theatre)[-1]
    assert (event["path"], event["new"], event["via"]) == ("limits.max", 10, "cli")
    assert event["actor"] == {"kind": "human", "id": None}


def test_empty_reason_is_stored_as_empty_string(make_theatre: MakeTheatre) -> None:  # edge case
    theatre = _imported(make_theatre)

    [event] = _new_events(
        theatre, "limits.max", "10", "--reason", "", env={"TROUPE_ACTOR": "human:alice"}
    )

    assert event["reason"] == ""
    assert '"reason": "", ' in _history_text(theatre).splitlines()[-1]


def test_reason_with_quotes_newlines_and_non_ascii_round_trips(
    make_theatre: MakeTheatre,
) -> None:  # edge case
    theatre = _imported(make_theatre)
    reason = 'it\'s "urgent"\nsecond line\twith tab, Zoë 日本 \\ end'

    [event] = _new_events(
        theatre, "limits.max", "10", "--reason", reason, env={"TROUPE_ACTOR": "agent:planner"}
    )

    assert event["reason"] == reason
    line = _history_text(theatre).splitlines()[-1]
    assert '"reason": "it\'s \\"urgent\\"\\nsecond line\\twith tab, Zoë 日本 \\\\ end"' in line


def test_actor_id_is_everything_after_the_first_colon(make_theatre: MakeTheatre) -> None:
    theatre = _imported(make_theatre)

    [first] = _new_events(theatre, "limits.max", "10", env={"TROUPE_ACTOR": "human:alice:x"})
    [second] = _new_events(theatre, "limits.max", "11", env={"TROUPE_ACTOR": "agent:my planner"})

    assert first["actor"] == {"kind": "human", "id": "alice:x"}
    assert second["actor"] == {"kind": "agent", "id": "my planner"}


@pytest.mark.parametrize(
    ("path", "code"),
    [pytest.param("agents.coder", 3, id="refused"), pytest.param("tools.7", 5, id="failed")],
)
def test_refused_set_keeps_its_reconcile_but_not_its_reason(
    make_theatre: MakeTheatre, path: str, code: int
) -> None:  # edge case, FR-014
    theatre = _imported(make_theatre)
    root = theatre / ".troupe" / "troupe.yml"
    root.write_text(str(FILES["troupe.yml"]).replace("name: gpt", "name: claude"), "utf-8")

    result = _set(
        theatre, path, "x", "--reason", "secret-why", env={"TROUPE_ACTOR": "agent:planner"}
    )

    assert (result.code, result.out) == (code, "")
    assert path in result.err
    text = _history_text(theatre)
    [reconciled] = _history(theatre)[IMPORTED:]
    assert (reconciled["path"], reconciled["new"]) == ("model.name", "claude")
    assert (reconciled["via"], reconciled["actor"], reconciled["reason"]) == ("file", UNKNOWN, None)
    assert "secret-why" not in text
    assert '"via": "cli"' not in text


def test_noop_set_with_reason_records_nothing(make_theatre: MakeTheatre) -> None:  # US1-6
    theatre = _imported(make_theatre)
    before = _history_text(theatre)

    result = _set(
        theatre, "limits.max", "5", "--reason", "same", env={"TROUPE_ACTOR": "human:alice"}
    )

    assert (result.code, result.out, result.err) == (0, "", "")
    assert _history_text(theatre) == before


@pytest.mark.parametrize("value", INVALID_ACTORS)
def test_invalid_actor_exits_2_and_history_is_unchanged(
    make_theatre: MakeTheatre, value: str
) -> None:  # US1-4, SC-006
    theatre = _imported(make_theatre)
    root = theatre / ".troupe" / "troupe.yml"
    root.write_text(str(FILES["troupe.yml"]).replace("max: 5", "max: 6"), "utf-8")  # pending
    history_before = _history_text(theatre)  # history does not reconcile
    files_before = snapshot(theatre)
    message = (
        f"troupe: TROUPE_ACTOR: invalid value '{value}': expected 'human:<id>' or 'agent:<id>'\n"
    )

    for command in (
        ("set", "limits.max", "10", "--reason", "r"),
        ("get", "limits.max"),
        ("show",),
        ("history",),
    ):
        result = run_cli("config", *command, "--theatre", str(theatre), env={"TROUPE_ACTOR": value})

        assert (result.code, result.out, result.err) == (2, "", message), command
        assert _history_text(theatre) == history_before, command
        assert snapshot(theatre) == files_before, command
