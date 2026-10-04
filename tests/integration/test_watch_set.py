"""``set`` while ``watch`` runs, and near-simultaneous reconciles (US3, FR-015, FR-016, NFR-003).

A ``set`` during ``watch`` records exactly the events a ``set`` alone is contracted to record
(see ``test_set_history.py``); its write-back is never recorded again. When ``watch`` and a
command reconcile around the same time, each difference is recorded exactly once and one
command's events are never interleaved with another reconcile's.

Race outcomes depend on who takes the theatre lock first, so race tests assert the multiset of
events (or the exact list of every allowed ordering), never "at least". Hand edits in race tests
are saved the way editors save (write a temporary file, rename it over the target), so a reader
never sees a half-written file. Out of contract (C-003) and not tested: a hand edit to the same
file during a ``set``'s locked section, several ``watch`` processes, two concurrent ``set``s.
The number in each test's comment is the US3 acceptance scenario it covers.
"""

import os
import re
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from itertools import pairwise
from pathlib import Path

from conftest import (
    CliResult,
    MakeTheatre,
    WatchProcess,
    all_files,
    core,
    history_events,
    recorded_within,
    run_cli,
    snapshot,
)

type Files = dict[str, str | bytes]
type Event = dict[str, object]

ROOT = (
    "model:\n"
    "  name: gpt\n"
    "  temperature: 0.2  # creativity\n"
    "tools: [a, b]\n"
    "agents:\n"
    "  coder: file:agents/coder.yaml\n"
    "prompt: file:sys.md\n"
)
CODER = "name: Ada\nlevel: 3\n"
FIXTURE: Files = {"troupe.yml": ROOT, "agents/coder.yaml": CODER, "sys.md": "Be kind.\n"}
IMPORTED = 7  # leaves in FIXTURE, so the first non-import event has seq 8
QUIET = 2.5  # seconds: longer than the 2 s contract, so "nothing happened" means nothing will


def _event(seq: int, op: str, path: str, old: object, new: object) -> Event:
    return {"seq": seq, "op": op, "path": path, "old": old, "new": new}


def _change(op: str, path: str, old: object, new: object) -> tuple[object, ...]:
    return (op, path, old, new)


def _changes(events: list[Event]) -> Counter[tuple[object, ...]]:
    """The multiset of events with ``seq`` left out (the order depends on who won the lock)."""
    return Counter((e["op"], e["path"], e["old"], e["new"]) for e in events)


def _set(theatre: Path, path: str, value: str) -> float:
    """Run ``set`` to completion, check it succeeded silently; return the time it finished."""
    result = run_cli("config", "set", path, value, "--theatre", str(theatre))
    assert (result.code, result.out, result.err) == (0, "", "")
    return time.monotonic()


def _get(theatre: Path, path: str) -> CliResult:
    return run_cli("config", "get", path, "--theatre", str(theatre))


def _save(theatre: Path, rel: str, text: str) -> float:
    """Hand-edit ``.troupe/<rel>`` as an editor does (temp file + rename); return the time."""
    target = theatre / ".troupe" / rel
    temporary = target.with_name(f".{target.name}.swp")
    temporary.write_bytes(text.encode("utf-8"))
    os.replace(temporary, target)
    return time.monotonic()


def _edit_root(theatre: Path, pattern: str, replacement: str) -> float:
    """Substitute one line of the root file as it is now (a ``set`` may have rewritten it)."""
    text = (theatre / ".troupe" / "troupe.yml").read_text(encoding="utf-8")
    edited, count = re.subn(pattern, replacement, text, flags=re.MULTILINE)
    assert count == 1, text
    return _save(theatre, "troupe.yml", edited)


def _watch(theatre: Path) -> WatchProcess:
    return WatchProcess("--theatre", str(theatre))


def _assert_well_formed(events: list[Event]) -> None:
    """``seq`` is 1..N with no gap or duplicate, and every ``old`` is the replayed value."""
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    leaves: dict[object, object] = {}
    for event in events:
        path = event["path"]
        if event["op"] != "import":
            assert event["old"] == leaves.get(path), f"recorded twice or stale: {event}"
        if event["op"] == "remove":
            del leaves[path]
        else:
            leaves[path] = event["new"]


# --- User Story 3: a set during watch records exactly its own events (FR-015) -----------------


def test_set_during_watch_records_exactly_its_own_event(make_theatre: MakeTheatre) -> None:  # 1
    theatre = make_theatre(FIXTURE)
    with _watch(theatre) as w:
        w.wait_ready()
        before = history_events(theatre)
        set_at = _set(theatre, "model.temperature", "0.5")
        written = snapshot(theatre)
        events = recorded_within(theatre, set_at)
        stopped = w.stop()

    assert len(before) == IMPORTED
    assert core(events) == [*core(before), _event(8, "set", "model.temperature", 0.2, 0.5)]
    assert written[".troupe/troupe.yml"] == ROOT.replace("0.2  #", "0.5  #").encode()
    assert snapshot(theatre) == written  # watch wrote nothing
    assert stopped == (0, "", "")
    # No lock file and no temporary file is left behind: only the configuration and history.
    leftovers = all_files(theatre) - {f".troupe/{rel}" for rel in FIXTURE}
    assert ".troupe/history.sqlite" in leftovers
    assert leftovers <= {f".troupe/history.sqlite{suffix}" for suffix in ("", "-wal", "-shm")}


def test_list_replacement_during_watch_records_set_and_remove_once(
    make_theatre: MakeTheatre,
) -> None:  # 2
    theatre = make_theatre(FIXTURE)
    with _watch(theatre) as w:
        w.wait_ready()
        before = history_events(theatre)
        events = recorded_within(theatre, _set(theatre, "tools", "[c]"))
        stopped = w.stop()

    assert core(events) == [
        *core(before),
        _event(8, "set", "tools.0", "a", "c"),
        _event(9, "remove", "tools.1", "b", None),
    ]
    assert stopped == (0, "", "")


def test_no_op_set_during_watch_records_nothing(make_theatre: MakeTheatre) -> None:  # 3
    theatre = make_theatre(FIXTURE)
    with _watch(theatre) as w:
        w.wait_ready()
        before = history_events(theatre)
        files = snapshot(theatre)
        events = recorded_within(theatre, _set(theatre, "model.temperature", "0.20"), QUIET)
        stopped = w.stop()

    assert len(before) == IMPORTED
    assert events == before
    assert snapshot(theatre) == files
    assert stopped == (0, "", "")


def test_set_inside_include_and_text_include_during_watch_records_once(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre(FIXTURE)
    with _watch(theatre) as w:
        w.wait_ready()
        before = history_events(theatre)
        after_yaml = recorded_within(theatre, _set(theatre, "agents.coder.level", "4"))
        after_text = recorded_within(theatre, _set(theatre, "prompt", "Be brave."))
        stopped = w.stop()

    level = _event(8, "set", "agents.coder.level", 3, 4)
    assert core(after_yaml) == [*core(before), level]
    assert core(after_text) == [
        *core(before),
        level,
        _event(9, "set", "prompt", "Be kind.\n", "Be brave."),
    ]
    assert snapshot(theatre)[".troupe/sys.md"] == b"Be brave."
    assert stopped == (0, "", "")


def test_ten_sets_in_a_row_during_watch_record_exactly_ten_events(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre(FIXTURE)
    with _watch(theatre) as w:
        w.wait_ready()
        before = history_events(theatre)
        for value in range(1, 11):
            last_set = _set(theatre, "model.temperature", str(value))
        events = recorded_within(theatre, last_set)
        stopped = w.stop()

    olds: list[object] = [0.2, *range(1, 10)]
    assert core(events) == [
        *core(before),
        *(
            _event(IMPORTED + n, "set", "model.temperature", old, n)
            for n, old in zip(range(1, 11), olds, strict=True)
        ),
    ]
    assert stopped == (0, "", "")


def test_set_without_watch_then_get_records_nothing_more(make_theatre: MakeTheatre) -> None:  # 5
    theatre = make_theatre(FIXTURE)
    before = history_events(theatre)

    _set(theatre, "model.temperature", "0.5")
    shown = _get(theatre, "model.temperature")

    assert (shown.code, shown.out, shown.err) == (0, "0.5\n", "")
    assert core(history_events(theatre)) == [
        *core(before),
        _event(8, "set", "model.temperature", 0.2, 0.5),
    ]


# --- FR-016: each difference recorded once, never interleaved (US3 scenario 4) ----------------


def test_hand_edit_just_before_set_is_recorded_once(make_theatre: MakeTheatre) -> None:  # 4
    theatre = make_theatre(FIXTURE)
    name, temperature = "gpt", 0.2
    with _watch(theatre) as w:
        w.wait_ready()
        events = history_events(theatre)
        for i in range(5):
            new_name, new_temperature = f"hand{i}", 0.91 + i / 100
            _edit_root(theatre, r"^  name: .*$", f"  name: {new_name}")
            settled = recorded_within(  # no wait between the edit and the set
                theatre, _set(theatre, "model.temperature", str(new_temperature))
            )

            assert settled[: len(events)] == events
            assert _changes(settled[len(events) :]) == Counter(
                [
                    _change("set", "model.name", name, new_name),
                    _change("set", "model.temperature", temperature, new_temperature),
                ]
            ), f"iteration {i}"
            events, name, temperature = settled, new_name, new_temperature
        stopped = w.stop()

    assert len(events) == IMPORTED + 10
    _assert_well_formed(events)
    assert stopped == (0, "", "")


def test_hand_edit_with_concurrent_get_and_watch_is_recorded_once(
    make_theatre: MakeTheatre,
) -> None:
    # What this checks: commands that run after ``watch`` has recorded a hand edit do not record
    # it again. It is NOT the race that detects a missing theatre lock: ``watch`` polls every
    # 0.25 s and usually reconciles before the ``get`` processes have even started, so they
    # rarely reconcile concurrently. That race is covered without ``watch`` by
    # ``test_concurrent_commands_record_a_hand_edit_exactly_once_so_reconciles_are_serialised``.
    theatre = make_theatre(FIXTURE)
    names = ["Ada", *(f"Grace{i}" for i in range(5))]
    with _watch(theatre) as w:
        w.wait_ready()
        before = history_events(theatre)
        for name in names[1:]:
            edited_at = _save(theatre, "agents/coder.yaml", f"name: {name}\nlevel: 3\n")
            with ThreadPoolExecutor(max_workers=3) as pool:
                shown = list(pool.map(lambda _: _get(theatre, "agents.coder.name"), range(3)))
            # Each get reconciles before printing (or finds watch already did), so it prints
            # the new value; the history check below proves nobody recorded the edit twice.
            assert [(s.code, s.out, s.err) for s in shown] == [(0, f"{name}\n", "")] * 3
        events = recorded_within(theatre, edited_at)
        stopped = w.stop()

    assert core(events) == [
        *core(before),
        *(
            _event(IMPORTED + n, "set", "agents.coder.name", old, new)
            for n, (old, new) in enumerate(pairwise(names), start=1)
        ),
    ]
    assert stopped == (0, "", "")


LOCK_ROUNDS = 30  # each unserialised round fails about 20 % of the time: 0.8**30 is about 0.1 %
RACERS = 3


def _start_get(theatre: Path, path: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "-m", "troupe", "config", "get", path, "--theatre", str(theatre)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={k: v for k, v in os.environ.items() if k != "TROUPE_THEATRE"},
    )


def test_concurrent_commands_record_a_hand_edit_exactly_once_so_reconciles_are_serialised(
    make_theatre: MakeTheatre,
) -> None:
    """FR-016 / NFR-003 without ``watch``: the race that fails if reconciles are not serialised.

    Each round makes one hand edit, then starts three ``get`` processes at once, so all three
    find the same unrecorded difference and reconcile at about the same time. With the theatre
    lock each difference is recorded exactly once. Without it (no lock in the session, or a lock
    that does not exclude other processes) a round fails about 20 % of the time: a command
    crashes on a duplicate ``seq`` or the edit is recorded twice. 30 rounds therefore detect a
    missing lock with probability about 99.9 %.
    """
    theatre = make_theatre(FIXTURE)
    events = history_events(theatre)
    assert len(events) == IMPORTED
    name = "gpt"
    for r in range(1, LOCK_ROUNDS + 1):
        new_name = f"m{r}"
        _edit_root(theatre, r"^  name: .*$", f"  name: {new_name}")
        racers = [_start_get(theatre, "model.name") for _ in range(RACERS)]
        try:
            outputs = [p.communicate(timeout=30) for p in racers]
        finally:
            for p in racers:
                if p.poll() is None:
                    p.kill()
                p.wait(timeout=10)
        results = [(p.returncode, out, err) for p, (out, err) in zip(racers, outputs, strict=True)]
        assert results == [(0, f"{new_name}\n".encode(), b"")] * RACERS, f"round {r}"

        settled = history_events(theatre)  # history does not reconcile: shows what they recorded
        assert core(settled) == [
            *core(events),
            _event(len(events) + 1, "set", "model.name", name, new_name),
        ], f"round {r}"
        events, name = settled, new_name

    assert len(events) == IMPORTED + LOCK_ROUNDS
    _assert_well_formed(events)


def test_events_of_one_command_are_contiguous(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)
    with _watch(theatre) as w:
        w.wait_ready()
        before = history_events(theatre)
        command = ["config", "set", "tools", "[x, y, z]", "--theatre", str(theatre)]
        set_process = subprocess.Popen(
            [sys.executable, "-m", "troupe", *command],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        _save(theatre, "agents/coder.yaml", "name: Ada\nlevel: 4\n")  # another file, same time
        out, err = set_process.communicate(timeout=30)
        events = recorded_within(theatre, time.monotonic())
        stopped = w.stop()

    own = [
        ("set", "tools.0", "a", "x"),
        ("set", "tools.1", "b", "y"),
        ("set", "tools.2", None, "z"),
    ]
    hand = [("set", "agents.coder.level", 3, 4)]
    new = [(e["op"], e["path"], e["old"], e["new"]) for e in events[len(before) :]]
    assert (set_process.returncode, out, err) == (0, b"", b"")
    assert new in (hand + own, own + hand)  # the set's events form one contiguous run
    _assert_well_formed(events)
    assert stopped == (0, "", "")


def test_history_has_no_gaps_or_duplicate_seq_after_races(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)
    expected = Counter(
        _change("import", path, None, value)
        for path, value in (
            ("model.name", "gpt"),
            ("model.temperature", 0.2),
            ("tools.0", "a"),
            ("tools.1", "b"),
            ("agents.coder.name", "Ada"),
            ("agents.coder.level", 3),
            ("prompt", "Be kind.\n"),
        )
    )
    level, temperature, name = 3, 0.2, "gpt"
    with _watch(theatre) as w:
        w.wait_ready()
        for i in range(5):
            # A hand edit to another file while a set and two gets race with watch...
            _save(theatre, "agents/coder.yaml", f"name: Ada\nlevel: {10 + i}\n")
            with ThreadPoolExecutor(max_workers=3) as pool:
                gets = [pool.submit(_get, theatre, p) for p in ("model.name", "tools.0")]
                pool.submit(_set, theatre, "model.temperature", str(i)).result()
                assert [(f.result().code, f.result().err) for f in gets] == [(0, "")] * 2
            # ...then a hand edit to the file the set has just written.
            _edit_root(theatre, r"^  name: .*$", f"  name: race{i}")
            expected += Counter(
                [
                    _change("set", "agents.coder.level", level, 10 + i),
                    _change("set", "model.temperature", temperature, i),
                    _change("set", "model.name", name, f"race{i}"),
                ]
            )
            level, temperature, name = 10 + i, i, f"race{i}"
        events = recorded_within(theatre, time.monotonic())
        stopped = w.stop()

    _assert_well_formed(events)  # seq is exactly 1..N
    assert _changes(events) == expected  # each difference recorded exactly once
    assert stopped == (0, "", "")
