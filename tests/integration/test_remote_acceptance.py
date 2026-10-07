"""Cross-cutting acceptance for remote includes and a schema (step 7; WP10, T045).

These tests cover what no single user story owns: the non-functional requirements NFR-001
(remote content is never written), NFR-002 (refusals change nothing and record nothing) and
NFR-003 (byte-surgical writes), the spec's Edge Cases list, and history/lineage with remote
leaves (S-6). Everything runs through the real CLI subprocess against real files, the real
event store and a real HTTP server on 127.0.0.1 (``remote`` fixture, C-006).

"Records no event" is checked against the real history store (``stored_records``), which needs
no configuration load, so it also holds while the configuration cannot load (exit 4 cases).
"""

import json
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from conftest import (
    MakeTheatre,
    WatchProcess,
    core,
    history_events,
    recorded_within,
    run_cli,
    snapshot,
    stored_records,
)
from remote_server import RemoteServer, Route

DASH = "—"

# Remote team file: a list, and anchors, aliases and a merge key used internally (step 6).
TEAM = (
    "model: opus\n"
    "tools: [read, write]\n"
    "base: &b\n"
    "  model: opus\n"
    "coder: *b\n"
    "reviewer:\n"
    "  <<: *b\n"
    "  temperature: 0.2\n"
)


def _cli(theatre: Path, *args: str, env: dict[str, str] | None = None) -> tuple[int, str, str]:
    result = run_cli("config", *args, "--theatre", str(theatre), env=env)
    return result.code, result.out, result.err


def _root(theatre: Path) -> Path:
    return theatre / ".troupe" / "troupe.yml"


def _remote_refusal(theatre: Path, dotted: str, written: str, line: int) -> str:
    return (
        f"troupe: {dotted}: value comes from remote include {written}"
        f" ({_root(theatre).resolve()} line {line}); troupe does not change remote content"
        f" {DASH} change that include line instead; no file changed\n"
    )


def _methods(remote: RemoteServer) -> set[str]:
    return {request.method for request in remote.requests()}


# --- NFR-001: remote content is never written ------------------------------------------------

REFUSED_REMOTE_WRITES = {
    # (set arguments, PATH named in stderr, key of the include line, its line number)
    "US2-1-existing-value": (("team.model", "sonnet"), "team.model", "team", 1),
    "US2-2-text-include": (("prompt", "x"), "prompt", "prompt", 2),
    "US2-3-list-append": (("team.tools.2", "x"), "team.tools.2", "team", 1),
    "US2-3-in-include": (("--in-include", "team.newkey", "1"), "team.newkey", "team", 1),
    "US2-3-whole-replacement": (("team", "{a: 1}"), "team", "team", 1),
    "US2-4-nested-include": (("outer.nested.deep", "2"), "outer.nested.deep", "outer", 3),
    "S-4-expand-alias": (
        ("--expand-alias", "team.coder.model", "sonnet"),
        "team.coder.model",
        "team",
        1,
    ),
}


def test_nfr001_every_refused_remote_write_sends_only_gets_and_changes_nothing(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:
    """NFR-001, S-4: a scripted sequence of every refused remote write (US2 1-4, ``--in-include``,
    ``--expand-alias``) exits 3 naming the local include line; the server only ever sees ``GET``,
    and no file and no event changes across the whole sequence."""
    urls = {
        "team": remote.serve("/team.yaml", TEAM),
        "prompt": remote.serve("/sys.md", "be terse\n"),
        "outer": remote.serve("/outer.yaml", f"nested: {remote.url('/inner.yaml')}\n"),
    }
    remote.serve("/inner.yaml", "deep: 1\n")
    theatre = make_theatre(
        {"troupe.yml": f"team: {urls['team']}\nprompt: {urls['prompt']}\nouter: {urls['outer']}\n"}
    )
    events = history_events(theatre)
    before = snapshot(theatre)
    remote.clear_log()

    for args, dotted, key, line in REFUSED_REMOTE_WRITES.values():
        assert _cli(theatre, "set", *args) == (
            3,
            "",
            _remote_refusal(theatre, dotted, urls[key], line),
        ), args

    assert snapshot(theatre) == before
    assert history_events(theatre) == events
    assert remote.requests() != [] and _methods(remote) == {"GET"}


# --- NFR-002: every refusal changes no file and records no event ------------------------------

SCHEMA = json.dumps({"type": "object", "properties": {"model": {"type": "string"}}})


def _break_fetch(theatre: Path, remote: RemoteServer) -> None:
    remote.serve("/team.yaml", "gone\n", status=404)


def _break_schema(theatre: Path, remote: RemoteServer) -> None:
    (theatre / ".troupe" / "troupe.schema.json").write_text("{not json", encoding="utf-8")


type Breaker = Callable[[Path, RemoteServer], None]

REFUSALS: dict[str, tuple[tuple[str, ...], int, Breaker | None]] = {
    "2-tag-in-value": (("set", "model", "!literal x"), 2, None),
    "2-include-on-get": (("get", "--include", "model"), 2, None),
    "3-remote-write": (("set", "team.model", "sonnet"), 3, None),
    "3-schema-violation": (("set", "model", "5"), 3, None),
    "4-failed-fetch": (("set", "model", "sonnet"), 4, _break_fetch),
    "4-invalid-schema": (("set", "model", "sonnet"), 4, _break_schema),
    "5-bad-path": (("set", "tools.5", "x"), 5, None),
}


@pytest.mark.parametrize(("args", "code", "breaker"), REFUSALS.values(), ids=REFUSALS.keys())
def test_nfr002_refusal_with_each_exit_code_changes_no_file_and_records_no_event(
    make_theatre: MakeTheatre,
    remote: RemoteServer,
    args: tuple[str, ...],
    code: int,
    breaker: Breaker | None,
) -> None:
    """NFR-002: one case per exit code 2, 3, 4 and 5; stdout is empty, stderr is one
    ``troupe:`` line, the theatre's file bytes and the stored events are unchanged."""
    url = remote.serve("/team.yaml", "model: opus\n")
    theatre = make_theatre(
        {"troupe.yml": f"model: opus\ntools: [a, b]\nteam: {url}\n", "troupe.schema.json": SCHEMA}
    )
    history_events(theatre)  # import, so "no event" is measured against a real, non-empty store
    if breaker is not None:
        breaker(theatre, remote)
    before, records = snapshot(theatre), stored_records(theatre)

    got, out, err = _cli(theatre, *args)

    assert (got, out) == (code, "")
    assert err.startswith("troupe: ") and err.count("\n") == 1 and err.endswith("\n")
    assert snapshot(theatre) == before
    assert stored_records(theatre) == records


# --- NFR-003: byte-surgical successful writes --------------------------------------------------

LOCAL_FILES = {
    "agents/coder.yaml": "# coder, hand written\nname: Ada   # keep spacing\n",
    "p.md": "prompt text\n",
}


def _write_shapes(url: str) -> dict[str, tuple[str, tuple[str, ...], str]]:
    """``id -> (troupe.yml before, set arguments, troupe.yml after)``; one per new write shape."""
    head = "# team settings\nagent: file:agents/coder.yaml\n"
    return {
        "literal-new-key": (
            head,
            ("docs", "https://x.example/y"),
            head + "docs: !literal https://x.example/y\n",
        ),
        "tag-kept": (
            head + "docs: !literal https://old.example  # note\n",
            ("docs", "plain-text"),
            head + "docs: !literal plain-text           # note\n",  # comment keeps its column
        ),
        "tag-inserted": (
            head + "docs: plain  # note\n",
            ("docs", "file:p.md"),
            head + "docs: !literal file:p.md # note\n",  # value reaches it: one space
        ),
        "tag-removed": (
            head + "docs: !literal https://old.example  # note\n",
            ("--include", "docs", "file:p.md"),
            head + "docs: file:p.md                     # note\n",
        ),
        "local-override-under-remote": (
            head + f"coder:\n  $ref: {url}\n  temperature: 0.3  # local\n",
            ("coder.temperature", "0.5"),
            head + f"coder:\n  $ref: {url}\n  temperature: 0.5  # local\n",
        ),
        "include-remote": (
            head,
            ("--include", "extra", url),
            head + f"extra: {url}\n",
        ),
    }


SHAPE_IDS = list(_write_shapes("u"))


@pytest.mark.parametrize("shape", SHAPE_IDS)
def test_nfr003_each_new_write_shape_changes_only_the_bytes_it_must(
    make_theatre: MakeTheatre, remote: RemoteServer, shape: str
) -> None:
    """NFR-003, S-5, S-11, S-12, S-13: one successful ``set`` per new write shape; the root file
    is compared byte for byte and every other file (local includes, text files) is identical."""
    url = remote.serve("/coder.yaml", "temperature: 0.7\nmodel: gpt\n")
    before_text, args, after_text = _write_shapes(url)[shape]
    theatre = make_theatre({"troupe.yml": before_text, **LOCAL_FILES})
    before = snapshot(theatre)

    assert _cli(theatre, "set", *args) == (0, "", "")

    assert snapshot(theatre) == {**before, ".troupe/troupe.yml": after_text.encode("utf-8")}
    assert _methods(remote) <= {"GET"}


# --- Edge cases (spec list) -------------------------------------------------------------------


def test_edge_same_url_included_twice_is_fetched_once_per_load(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:
    """Edge case, S-2: one URL included at two places is fetched once by one ``get``."""
    url = remote.serve("/team.yaml", "model: opus\n")
    theatre = make_theatre({"troupe.yml": f"team: {url}\nagain:\n  $ref: {url}\n  x: 1\n"})

    assert _cli(theatre, "get", "again.model") == (0, "opus\n", "")

    assert [(r.method, r.path) for r in remote.requests()] == [("GET", "/team.yaml")]


def test_edge_anchor_on_a_remote_include_reference_exits_4(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:
    """Edge case (step 6 C3 for every include reference): ``&t`` on a URL include exits 4,
    naming the file, and nothing is fetched."""
    url = remote.serve("/team.yaml", "model: opus\n")
    theatre = make_theatre({"troupe.yml": f"a: &t {url}\nb: *t\n"})

    assert _cli(theatre, "get", "a.model") == (
        4,
        "",
        f"troupe: cannot load {_root(theatre).resolve()}: anchor &t at line 1 is on an include"
        " reference (or a value containing one); anchors may not share includes\n",
    )
    assert remote.requests() == []


def test_edge_remote_anchors_aliases_and_merge_keys_read_correctly_and_are_read_only(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:
    """Edge case, S-4: remote YAML using an anchor, an alias and a merge key reads as in step 6;
    writes through the alias or into the merged mapping exit 3 and change nothing."""
    url = remote.serve("/team.yaml", TEAM)
    theatre = make_theatre({"troupe.yml": f"team: {url}\n"})

    assert _cli(theatre, "show", "team") == (
        0,
        "model: opus\n"
        "tools:\n  - read\n  - write\n"
        "base:\n  model: opus\n"
        "coder:\n  model: opus\n"
        "reviewer:\n  model: opus\n  temperature: 0.2\n",
        "",
    )
    events, before = history_events(theatre), snapshot(theatre)
    for path in ("team.coder.model", "team.reviewer.model", "team.reviewer.temperature"):
        assert _cli(theatre, "set", path, "x") == (3, "", _remote_refusal(theatre, path, url, 1))
    assert snapshot(theatre) == before
    assert history_events(theatre) == events


def test_edge_aliased_string_whose_anchored_node_is_literal_by_schema_stays_literal(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:
    """Edge case, S-7: the anchored node's path decides; the alias reads the URL, unfetched."""
    url = remote.url("/notify")
    schema = {"properties": {"hooks": {"properties": {"main": {"format": "uri"}}}}}
    theatre = make_theatre(
        {
            "troupe.yml": f"hooks:\n  main: &h {url}\nbackup: *h\n",
            "troupe.schema.json": json.dumps(schema),
        }
    )

    assert _cli(theatre, "get", "backup") == (0, f"{url}\n", "")
    assert _cli(theatre, "get", "hooks.main") == (0, f"{url}\n", "")
    assert remote.requests() == []


def test_edge_redirect_to_ftp_is_a_failed_fetch_exit_4(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:
    """Edge case, S-2: a redirect to a non-http(s) scheme is refused as a failed fetch."""
    url = remote.route(
        "/team.yaml", Route(status=302, headers={"Location": "ftp://127.0.0.1/team.yaml"})
    )
    theatre = make_theatre({"troupe.yml": f"team: {url}\n"})

    assert _cli(theatre, "get", "team.model") == (
        4,
        "",
        f"troupe: cannot fetch {url} (included from {_root(theatre).resolve()}, at team): "
        "redirect to ftp://127.0.0.1/team.yaml refused (only http and https)\n",
    )


def test_edge_watch_reports_a_failed_fetch_and_keeps_running(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:
    """Edge case, S-6 (step 3 rule): a fetch failing during a reconcile is reported once on
    stderr; ``watch`` keeps running and records the pending edit once the URL answers again."""
    url = remote.serve("/team.yaml", "model: opus\n")
    theatre = make_theatre({"troupe.yml": f"a: 1\nteam: {url}\n"})
    imported = history_events(theatre)
    message = (
        f"troupe: cannot fetch {url} (included from {_root(theatre).resolve()}, at team): "
        "HTTP 404 Not Found\n"
    )

    with WatchProcess("--theatre", str(theatre)) as w:
        w.wait_ready()
        remote.serve("/team.yaml", "gone\n", status=404)
        _root(theatre).write_text(f"a: 2\nteam: {url}\n", encoding="utf-8")
        reported = w.wait_stderr(1)
        remote.serve("/team.yaml", "model: opus\n")
        events = recorded_within(theatre, time.monotonic())
        stopped = w.stop()

    assert reported == [message]
    assert core(events) == [
        *core(imported),
        {"seq": 3, "op": "set", "path": "a", "old": 1, "new": 2},
    ]
    assert stopped == (0, "", message)


def test_edge_set_on_an_unrelated_path_with_a_failing_remote_exits_4(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:
    """Edge case: the whole configuration loads before any ``set``, so a failing remote include
    fails a ``set`` of an unrelated local path with exit 4, and the local file is unchanged."""
    url = remote.serve("/team.yaml", "gone\n", status=404)
    theatre = make_theatre({"troupe.yml": f"name: demo\nteam: {url}\n"})
    before = snapshot(theatre)

    assert _cli(theatre, "set", "name", "other") == (
        4,
        "",
        f"troupe: cannot fetch {url} (included from {_root(theatre).resolve()}, at team): "
        "HTTP 404 Not Found\n",
    )
    assert snapshot(theatre) == before


# --- History and lineage with remote leaves (S-6) ---------------------------------------------


def test_set_with_reason_on_a_local_override_under_a_remote_include_records_cli_lineage(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:
    """S-4, S-6: the override is local, so its ``set`` is a CLI event with actor and reason."""
    url = remote.serve("/coder.yaml", "temperature: 0.7\nmodel: gpt\n")
    theatre = make_theatre({"troupe.yml": f"coder:\n  $ref: {url}\n  temperature: 0.3\n"})
    recorded = len(history_events(theatre))

    assert _cli(
        theatre,
        "set",
        "coder.temperature",
        "0.5",
        "--reason",
        "r",
        env={"TROUPE_ACTOR": "agent:planner"},
    ) == (0, "", "")

    [event] = history_events(theatre)[recorded:]
    assert core([event]) == [
        {"seq": recorded + 1, "op": "set", "path": "coder.temperature", "old": 0.3, "new": 0.5}
    ]
    assert (event["actor"], event["via"], event["reason"]) == (
        {"kind": "agent", "id": "planner"},
        "cli",
        "r",
    )


def test_upstream_change_is_recorded_with_file_lineage_on_the_next_command(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:
    """US1-6, S-6: the next loading command records the upstream change as a file event."""
    url = remote.serve("/team.yaml", "model: opus\n")
    theatre = make_theatre({"troupe.yml": f"team: {url}\nname: demo\n"})
    imported = history_events(theatre)
    remote.serve("/team.yaml", "model: sonnet\n")

    assert _cli(theatre, "get", "name") == (0, "demo\n", "")

    events = history_events(theatre)
    assert events[: len(imported)] == imported
    [change] = events[len(imported) :]
    assert core([change]) == [
        {"seq": 3, "op": "set", "path": "team.model", "old": "opus", "new": "sonnet"}
    ]
    assert (change["actor"], change["via"], change["reason"]) == (
        {"kind": "unknown", "id": None},
        "file",
        None,
    )


def test_history_of_a_remote_include_path_lists_its_remote_leaves(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:
    """S-6: ``history team`` lists the leaves that come from the remote include."""
    url = remote.serve("/team.yaml", "model: opus\ntools: [read]\n")
    theatre = make_theatre({"troupe.yml": f"name: demo\nteam: {url}\n"})
    history_events(theatre)

    code, out, err = _cli(theatre, "history", "team")

    assert (code, err) == (0, "")
    assert core([json.loads(line) for line in out.splitlines()]) == [
        {"seq": 2, "op": "import", "path": "team.model", "old": None, "new": "opus"},
        {"seq": 3, "op": "import", "path": "team.tools.0", "old": None, "new": "read"},
    ]


# --- S-1: includes inside remote content resolve against the URL and are remote ---------------


def test_s1_file_include_in_remote_content_is_fetched_relative_to_the_url_and_is_read_only(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:
    """S-1, S-4: ``file:prompts/sys.md`` inside ``/team/team.yaml`` is fetched as
    ``/team/prompts/sys.md``; what it brings in is remote, so a ``set`` on it exits 3 naming the
    outermost include, the one written in the local file."""
    url = remote.serve("/team/team.yaml", "prompt: file:prompts/sys.md\n")
    remote.serve("/team/prompts/sys.md", "Be brief.\n")
    theatre = make_theatre({"troupe.yml": f"team: {url}\n"})

    assert _cli(theatre, "get", "team.prompt") == (0, "Be brief.\n", "")
    assert sorted(r.path for r in remote.requests()) == ["/team/prompts/sys.md", "/team/team.yaml"]
    before = snapshot(theatre)
    assert _cli(theatre, "set", "team.prompt", "x") == (
        3,
        "",
        _remote_refusal(theatre, "team.prompt", url, 1),
    )
    assert snapshot(theatre) == before
    assert _methods(remote) == {"GET"}
