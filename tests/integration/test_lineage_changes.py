"""User Stories 2 and 3: unknown-actor import/file events and grouping by change, via ``history``.

Every test runs the real CLI (and, for ``watch``, a real ``WatchProcess``) and reads the result
back from ``troupe config history``; every line is checked against the contract by
``_valid_record``. Lines are grouped by their ``change`` with ``by_change``, which keeps the order
in which each change first appears.
"""

import time
from pathlib import Path
from typing import Any

import pytest
from test_history import _valid_record

from conftest import MakeTheatre, WatchProcess, recorded_within, run_cli

type Event = dict[str, Any]

ROOT = "a: 1\nb: 2\nc: 3\n"
UNKNOWN = {"kind": "unknown", "id": None}
SHARED = ("actor", "via", "at", "reason")  # every event of one change carries the same values


def by_change(events: list[Event]) -> dict[str, list[Event]]:
    """Group ``events`` by ``change``, keeping first-appearance order of groups and events."""
    groups: dict[str, list[Event]] = {}
    for event in events:
        groups.setdefault(event["change"], []).append(event)
    return groups


def _history(theatre: Path) -> list[Event]:
    result = run_cli("config", "history", "--theatre", str(theatre))
    assert (result.code, result.err) == (0, ""), result.err
    return [_valid_record(line) for line in result.out.splitlines()]


def _run_ok(theatre: Path, *args: str, actor: str | None = None) -> None:
    env = None if actor is None else {"TROUPE_ACTOR": actor}
    result = run_cli("config", *args, "--theatre", str(theatre), env=env)
    assert (result.code, result.err) == (0, ""), result.err


def _edit(theatre: Path, old: str, new: str) -> float:
    """Replace ``old`` by ``new`` in the root file; return ``time.monotonic()`` after the write."""
    root = theatre / ".troupe" / "troupe.yml"
    text = root.read_text("utf-8")
    assert old in text
    root.write_text(text.replace(old, new), "utf-8")
    return time.monotonic()


def _assert_uniform(group: list[Event]) -> None:
    assert len({tuple(repr(event[key]) for key in SHARED) for event in group}) == 1, group


@pytest.mark.parametrize(
    "command", [pytest.param(("history",), id="history"), pytest.param(("get", "a"), id="get")]
)
def test_first_command_imports_as_one_change_with_unknown_actor(
    make_theatre: MakeTheatre, command: tuple[str, ...]
) -> None:  # US2-1
    theatre = make_theatre({"troupe.yml": ROOT})

    _run_ok(theatre, *command, actor="agent:planner")

    events = _history(theatre)
    assert [(e["op"], e["path"]) for e in events] == [("import", p) for p in ("a", "b", "c")]
    [group] = by_change(events).values()
    _assert_uniform(group)
    assert (group[0]["via"], group[0]["actor"], group[0]["reason"]) == ("import", UNKNOWN, None)


def test_hand_edit_is_recorded_via_file_with_unknown_actor_even_when_troupe_actor_is_set(
    make_theatre: MakeTheatre,
) -> None:  # US2-2
    theatre = make_theatre({"troupe.yml": ROOT})
    imported = _history(theatre)
    _edit(theatre, "b: 2", "b: 20")

    _run_ok(theatre, "get", "b", actor="human:alice")

    [event] = _history(theatre)[len(imported) :]
    assert (event["op"], event["path"], event["old"], event["new"]) == ("set", "b", 2, 20)
    assert (event["via"], event["actor"], event["reason"]) == ("file", UNKNOWN, None)
    assert event["change"] != imported[0]["change"]


def test_set_replacing_several_leaves_is_one_change_sharing_actor_via_at_reason(
    make_theatre: MakeTheatre,
) -> None:  # US3-1
    theatre = make_theatre({"troupe.yml": "tools: [x, y]\n"})
    imported = _history(theatre)

    _run_ok(theatre, "set", "tools", "[a, b, c]", "--reason", "new tools", actor="agent:p")

    own = _history(theatre)[len(imported) :]
    assert [(e["path"], e["new"]) for e in own] == [
        ("tools.0", "a"),
        ("tools.1", "b"),
        ("tools.2", "c"),
    ]
    [group] = by_change(own).values()
    _assert_uniform(group)
    assert (group[0]["actor"], group[0]["via"], group[0]["reason"]) == (
        {"kind": "agent", "id": "p"},
        "cli",
        "new tools",
    )


def test_reconcile_and_set_in_one_command_are_two_changes(make_theatre: MakeTheatre) -> None:
    # US3-2
    theatre = make_theatre({"troupe.yml": "a: 1\nb: 2\nlimits: {max: 5, min: 0, step: 1}\n"})
    imported = _history(theatre)
    _edit(theatre, "a: 1\nb: 2", "a: 10\nb: 20")

    _run_ok(theatre, "set", "limits", "{max: 6, min: 1, step: 2}", actor="agent:planner")

    groups = list(by_change(_history(theatre)).values())
    assert [len(group) for group in groups] == [len(imported), 2, 3]
    for group in groups:
        _assert_uniform(group)
    _, reconcile, own = groups
    assert [e["path"] for e in reconcile] == ["a", "b"]
    assert (reconcile[0]["via"], reconcile[0]["actor"], reconcile[0]["reason"]) == (
        "file",
        UNKNOWN,
        None,
    )
    assert [e["path"] for e in own] == ["limits.max", "limits.min", "limits.step"]
    assert (own[0]["via"], own[0]["actor"]) == ("cli", {"kind": "agent", "id": "planner"})


def test_import_and_set_on_a_new_theatre_are_two_changes(make_theatre: MakeTheatre) -> None:
    # US3-3
    theatre = make_theatre({"troupe.yml": ROOT})

    _run_ok(theatre, "set", "a", "9", actor="human:alice")

    groups = list(by_change(_history(theatre)).values())
    assert [[e["via"] for e in group] for group in groups] == [["import"] * 3, ["cli"]]


def test_change_ids_are_never_reused_across_commands(make_theatre: MakeTheatre) -> None:
    # US3-4, SC-003
    theatre = make_theatre({"troupe.yml": ROOT})
    _run_ok(theatre, "history")  # 1: import
    _run_ok(theatre, "set", "a", "2", actor="agent:p")  # 2
    _run_ok(theatre, "set", "a", "2", actor="agent:p")  # no-op: records nothing
    _edit(theatre, "b: 2", "b: 3")
    _run_ok(theatre, "get", "b")  # 3: reconcile
    _run_ok(theatre, "set", "c", "4")  # 4: no TROUPE_ACTOR
    _edit(theatre, "a: 2", "a: 5")
    _run_ok(theatre, "set", "b", "{x: 1, y: 2}", "--reason", "r", actor="human:h")  # 5, 6
    _run_ok(theatre, "show")  # nothing pending: records nothing
    _edit(theatre, "c: 4", "c: 6")
    _run_ok(theatre, "show")  # 7: reconcile
    _run_ok(theatre, "set", "a", "7", actor="agent:p")  # 8: same actor and value shape as 2
    _run_ok(theatre, "set", "a", "8", actor="agent:p")  # 9
    _edit(theatre, "a: 8", "a: 9")
    _run_ok(theatre, "history")  # history does not reconcile: records nothing
    _run_ok(theatre, "get", "a")  # 10: reconcile

    groups = list(by_change(_history(theatre)).values())

    assert len(groups) == 10
    for group in groups:
        _assert_uniform(group)
    assert [group[0]["via"] for group in groups] == [
        "import",
        "cli",
        "file",
        "cli",
        "file",
        "cli",
        "file",
        "cli",
        "cli",
        "file",
    ]
    seqs = [e["seq"] for group in groups for e in group]
    assert seqs == sorted(seqs)  # no producer is split around another one


# --- watch (US2-3, FR-011) ----------------------------------------------------------------------


def test_each_watch_reconcile_is_its_own_change(make_theatre: MakeTheatre) -> None:  # US2-3
    theatre = make_theatre({"troupe.yml": ROOT})
    imported = _history(theatre)
    with WatchProcess("--theatre", str(theatre), env={"TROUPE_ACTOR": "agent:x"}) as watch:
        watch.wait_ready()
        first_at = _edit(theatre, "a: 1\nb: 2", "a: 10\nb: 20")  # one write, two leaves
        assert len(recorded_within(theatre, first_at)) == len(imported) + 2
        second_at = _edit(theatre, "c: 3", "c: 30")
        assert len(recorded_within(theatre, second_at)) == len(imported) + 3
        code, _, err = watch.stop()

    assert (code, err) == (0, "")
    reconciles = list(by_change(_history(theatre)[len(imported) :]).values())
    assert [[e["path"] for e in group] for group in reconciles] == [["a", "b"], ["c"]]
    for group in reconciles:
        _assert_uniform(group)
        assert (group[0]["via"], group[0]["actor"], group[0]["reason"]) == ("file", UNKNOWN, None)


def test_watch_rejects_invalid_actor_before_announcing(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": ROOT})

    with WatchProcess("--theatre", str(theatre), env={"TROUPE_ACTOR": "robot:x"}) as watch:
        code, out, err = watch.wait_exit(timeout=10.0)

    assert (code, out) == (2, "")
    assert err == (
        "troupe: TROUPE_ACTOR: invalid value 'robot:x': expected 'human:<id>' or 'agent:<id>'\n"
    )
