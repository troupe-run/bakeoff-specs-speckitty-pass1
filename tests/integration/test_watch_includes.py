"""Includes added or removed by hand are followed (User Story 4, FR-012, FR-003), real processes.

A reconcile recomputes the watched files from what it loaded, so an include added by hand has its
leaves recorded as ``set`` events and its file watched from then on; an include removed by hand
has its leaves recorded as ``remove`` events and its file no longer affects the history. Each
scenario that names "a command" or "watch" is run both ways where the story allows either.
The number in each test's comment is the US4 acceptance scenario it covers (scenario 3 is in
``test_watch.py``).
"""

import time
from collections.abc import Callable
from pathlib import Path

import pytest

from conftest import (
    MakeTheatre,
    WatchProcess,
    history_events,
    recorded_within,
    run_cli,
    snapshot,
)

type Files = dict[str, str | bytes]
type Event = dict[str, object]

ROOT = "model:\n  name: m0\n"
INCLUDE = "agents:\n  coder: file:agents/coder.yaml\n"
CODER = "name: Ada\nmodel: m1\n"
NOT_INCLUDED: Files = {"troupe.yml": ROOT, "agents/coder.yaml": CODER}
INCLUDED: Files = {"troupe.yml": ROOT + INCLUDE, "agents/coder.yaml": CODER}
QUIET = 2.5  # seconds: longer than the 2 s contract, so "nothing happened" means nothing will
MODES = ["command", "watch"]


def _write(theatre: Path, rel: str, content: str | bytes) -> float:
    """Hand-edit ``.troupe/<rel>`` and return ``time.monotonic()`` right after the write."""
    target = theatre / ".troupe" / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    return time.monotonic()


def _event(seq: int, op: str, path: str, old: object, new: object) -> Event:
    return {"seq": seq, "op": op, "path": path, "old": old, "new": new}


def _imported(make_theatre: MakeTheatre, files: Files) -> tuple[Path, list[Event]]:
    """Build the theatre and import it with ``history`` (which records nothing else)."""
    theatre = make_theatre(files)
    return theatre, history_events(theatre)


def _reconciled(
    theatre: Path, mode: str, edit: Callable[[], float], seconds: float = 2.0
) -> list[Event]:
    """Apply ``edit`` and let a command (``get``) or a running ``watch`` reconcile it.

    Returns ``history`` once the reconcile is due: right after ``get`` for a command, or
    ``seconds`` after the edit for ``watch``, which must then stop cleanly.
    """
    if mode == "command":
        edit()
        shown = run_cli("config", "get", "model.name", "--theatre", str(theatre))
        assert (shown.code, shown.out, shown.err) == (0, "m0\n", "")
        return history_events(theatre)
    with WatchProcess("--theatre", str(theatre)) as w:
        w.wait_ready()
        events = recorded_within(theatre, edit(), seconds)
        assert w.stop() == (0, "", "")
    return events


def test_include_added_by_hand_is_followed_by_next_command(
    make_theatre: MakeTheatre,
) -> None:  # 1
    theatre, imported = _imported(make_theatre, NOT_INCLUDED)

    events = _reconciled(theatre, "command", lambda: _write(theatre, "troupe.yml", ROOT + INCLUDE))

    assert imported == [_event(1, "import", "model.name", None, "m0")]
    assert events == [
        *imported,
        _event(2, "set", "agents.coder.name", None, "Ada"),
        _event(3, "set", "agents.coder.model", None, "m1"),
    ]


def test_include_added_by_hand_is_followed_by_watch_and_then_watched(
    make_theatre: MakeTheatre,
) -> None:  # 2
    theatre, imported = _imported(make_theatre, NOT_INCLUDED)
    with WatchProcess("--theatre", str(theatre)) as w:
        w.wait_ready()
        included = recorded_within(theatre, _write(theatre, "troupe.yml", ROOT + INCLUDE))
        edited_at = _write(theatre, "agents/coder.yaml", "name: Grace\nmodel: m1\n")
        edited = recorded_within(theatre, edited_at)
        stopped = w.stop()

    assert included == [
        *imported,
        _event(2, "set", "agents.coder.name", None, "Ada"),
        _event(3, "set", "agents.coder.model", None, "m1"),
    ]
    assert edited == [*included, _event(4, "set", "agents.coder.name", "Ada", "Grace")]
    assert stopped == (0, "", "")


@pytest.mark.parametrize("mode", MODES)
def test_include_removed_by_hand_records_removes_and_stops_watching(
    make_theatre: MakeTheatre, mode: str
) -> None:  # 4
    theatre, imported = _imported(make_theatre, INCLUDED)
    removed = _reconciled(theatre, mode, lambda: _write(theatre, "troupe.yml", ROOT))
    expected = [
        *imported,
        _event(4, "remove", "agents.coder.name", "Ada", None),
        _event(5, "remove", "agents.coder.model", "m1", None),
    ]
    assert removed == expected

    # The file is no longer included: editing it records nothing, whoever reconciles.
    with WatchProcess("--theatre", str(theatre)) as w:
        w.wait_ready()
        _write(theatre, "agents/coder.yaml", "name: Grace\nmodel: m9\n")
        time.sleep(QUIET)
        while_watching = history_events(theatre)
        stopped = w.stop()
    shown = run_cli("config", "get", "model.name", "--theatre", str(theatre))

    assert len(imported) == 3
    assert while_watching == expected
    assert stopped == (0, "", "")
    assert (shown.code, shown.out, shown.err) == (0, "m0\n", "")
    assert history_events(theatre) == expected


@pytest.mark.parametrize("mode", MODES)
def test_include_replaced_by_equal_inline_content_records_nothing(
    make_theatre: MakeTheatre, mode: str
) -> None:  # 5
    theatre, imported = _imported(make_theatre, INCLUDED)
    inline = ROOT + "agents:\n  coder: {name: Ada, model: m1}\n"

    events = _reconciled(
        theatre, mode, lambda: _write(theatre, "troupe.yml", inline), seconds=QUIET
    )

    assert len(imported) == 3
    assert events == imported
    assert snapshot(theatre) == {  # the reconcile wrote nothing
        ".troupe/agents/coder.yaml": CODER.encode(),
        ".troupe/troupe.yml": inline.encode(),
    }


def test_nested_include_added_inside_an_included_file_is_followed(
    make_theatre: MakeTheatre,
) -> None:
    files: Files = {**INCLUDED, "agents/skills.yml": "lint: strict\nreview: 2\n"}
    theatre, imported = _imported(make_theatre, files)
    with WatchProcess("--theatre", str(theatre)) as w:
        w.wait_ready()
        nested_at = _write(theatre, "agents/coder.yaml", CODER + "skills: file:skills.yml\n")
        nested = recorded_within(theatre, nested_at)
        edited_at = _write(theatre, "agents/skills.yml", "lint: loose\nreview: 2\n")
        edited = recorded_within(theatre, edited_at)
        stopped = w.stop()

    assert len(imported) == 3
    assert nested == [
        *imported,
        _event(4, "set", "agents.coder.skills.lint", None, "strict"),
        _event(5, "set", "agents.coder.skills.review", None, 2),
    ]
    assert edited == [*nested, _event(6, "set", "agents.coder.skills.lint", "strict", "loose")]
    assert stopped == (0, "", "")


@pytest.mark.parametrize("mode", MODES)
def test_text_include_added_by_hand_records_its_text_as_one_leaf(
    make_theatre: MakeTheatre, mode: str
) -> None:
    text = "Be kind.\r\nBe brief.\r\n\r\n  -- the director\r\n"
    theatre, imported = _imported(make_theatre, {"troupe.yml": ROOT, "sys.md": text.encode()})

    events = _reconciled(
        theatre, mode, lambda: _write(theatre, "troupe.yml", ROOT + "prompt: file:sys.md\n")
    )

    assert events == [*imported, _event(2, "set", "prompt", None, text)]
