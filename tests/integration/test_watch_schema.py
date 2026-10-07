"""``watch`` with a schema and remote includes (spec S-6, FR-006; research R-11), real processes.

The schema file is in ``watch``'s baseline, because it decides what is a literal and what is
valid: editing it triggers a reconcile like any watched file. URLs are not in the baseline:
``watch`` never polls them, and fetches remote content again only when a reconcile runs. Waits
follow ``test_watch.py``: ``recorded_within`` (2 s, FR-011) and ``QUIET`` (nothing happens).
"""

import json
import time
from pathlib import Path

import pytest

from conftest import MakeTheatre, WatchProcess, core, history_events, recorded_within
from remote_server import RemoteServer

type Event = dict[str, object]

QUIET = 2.5  # seconds: longer than the 2 s contract, so "nothing happened" means nothing will
URI_MARK = {"properties": {"webhook": {"format": "uri"}}}
SERVED = "served text\n"


def _write(theatre: Path, rel: str, text: str) -> float:
    """Hand-edit ``.troupe/<rel>`` and return ``time.monotonic()`` right after the write."""
    (theatre / ".troupe" / rel).write_bytes(text.encode("utf-8"))
    return time.monotonic()


def _set(seq: int, path: str, old: object, new: object) -> Event:
    return {"seq": seq, "op": "set", "path": path, "old": old, "new": new}


def _watch(theatre: Path) -> WatchProcess:
    return WatchProcess("--theatre", str(theatre))


@pytest.mark.parametrize("change", ["mark-added", "mark-removed", "schema-deleted"])
def test_editing_the_schema_triggers_a_reconcile(
    make_theatre: MakeTheatre, remote: RemoteServer, change: str
) -> None:
    url = remote.serve("/notify", SERVED)
    marked = change != "mark-added"
    files: dict[str, str | bytes] = {"troupe.yml": f"a: 1\nwebhook: {url}\n"}
    files["troupe.schema.json"] = json.dumps(URI_MARK if marked else {"type": "object"})
    theatre = make_theatre(files)
    imported = history_events(theatre)
    before, after = (url, SERVED) if marked else (SERVED, url)

    with _watch(theatre) as w:
        w.wait_ready()
        if change == "schema-deleted":
            (theatre / ".troupe" / "troupe.schema.json").unlink()
            edited_at = time.monotonic()
        else:
            edited_at = _write(
                theatre, "troupe.schema.json", json.dumps(URI_MARK if not marked else {})
            )
        events = recorded_within(theatre, edited_at)
        stopped = w.stop()

    assert core(imported)[1] == {
        "seq": 2,
        "op": "import",
        "path": "webhook",
        "old": None,
        "new": before,
    }
    assert core(events) == [*core(imported), _set(3, "webhook", before, after)]
    assert stopped == (0, "", "")


def test_watch_does_not_poll_remote_urls(make_theatre: MakeTheatre, remote: RemoteServer) -> None:
    url = remote.serve("/team.yaml", "model: opus\n")
    theatre = make_theatre({"troupe.yml": f"a: 1\nteam: {url}\n"})
    history_events(theatre)

    with _watch(theatre) as w:
        w.wait_ready()
        remote.clear_log()
        remote.serve("/team.yaml", "model: sonnet\n")
        time.sleep(QUIET)
        while_idle = remote.requests()
        unchanged = history_events(theatre)
        stopped = w.stop()

    assert while_idle == []
    assert [event["path"] for event in core(unchanged)] == ["a", "team.model"]
    assert stopped == (0, "", "")


def test_remote_change_is_picked_up_when_a_local_edit_triggers_a_reconcile(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:
    url = remote.serve("/team.yaml", "model: opus\n")
    theatre = make_theatre({"troupe.yml": f"a: 1\nteam: {url}\n"})
    imported = history_events(theatre)

    with _watch(theatre) as w:
        w.wait_ready()
        remote.serve("/team.yaml", "model: sonnet\n")
        events = recorded_within(theatre, _write(theatre, "troupe.yml", f"a: 2\nteam: {url}\n"))
        stopped = w.stop()

    assert core(events) == [
        *core(imported),
        _set(3, "a", 1, 2),
        _set(4, "team.model", "opus", "sonnet"),
    ]
    assert stopped == (0, "", "")


def test_invalid_schema_while_watching_is_reported_and_watch_keeps_running(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre({"troupe.yml": "a: 1\n", "troupe.schema.json": "{}"})
    schema_file = theatre.resolve() / ".troupe" / "troupe.schema.json"
    imported = history_events(theatre)

    with _watch(theatre) as w:
        w.wait_ready()
        _write(theatre, "troupe.schema.json", "{not json")
        reported = w.wait_stderr(1)
        _write(theatre, "troupe.yml", "a: 2\n")  # not recordable while the schema is broken
        time.sleep(QUIET)
        still_one = w.stderr_lines()
        fixed_at = _write(theatre, "troupe.schema.json", '{"type": "object"}')
        events = recorded_within(theatre, fixed_at)
        code, rest, err = w.stop()

    message = (
        f"troupe: cannot load schema {schema_file}: not valid JSON: "
        "Expecting property name enclosed in double quotes at line 1 column 2\n"
    )
    assert reported == still_one == [message]
    assert core(events) == [*core(imported), _set(2, "a", 1, 2)]
    assert (code, rest, err) == (0, "", message)


def test_configuration_made_invalid_by_a_schema_edit_is_reported_and_recovers(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre({"troupe.yml": "model: 5\n", "troupe.schema.json": "{}"})
    schema_file = theatre.resolve() / ".troupe" / "troupe.schema.json"
    imported = history_events(theatre)

    with _watch(theatre) as w:
        w.wait_ready()
        _write(
            theatre, "troupe.schema.json", json.dumps({"properties": {"model": {"type": "string"}}})
        )
        reported = w.wait_stderr(1)
        fixed_at = _write(theatre, "troupe.yml", "model: '5'\n")
        events = recorded_within(theatre, fixed_at)
        code, rest, err = w.stop()

    message = (
        f"troupe: configuration does not match schema {schema_file} at model: "
        "5 is not of type 'string'\n"
    )
    assert reported == [message]
    assert core(events) == [*core(imported), _set(2, "model", 5, "5")]
    assert (code, rest, err) == (0, "", message)
