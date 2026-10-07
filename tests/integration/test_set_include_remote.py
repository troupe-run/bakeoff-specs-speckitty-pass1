"""``set --include`` with remote targets (S-12, S-9, S-4), through the real CLI.

Remote content is served by the ``remote`` test server on 127.0.0.1 (spec C-006). Successes
compare every theatre file byte for byte (NFR-003) and read the new values back with ``get``;
refusals assert exit 3, empty stdout, one ``troupe: `` stderr line, every file unchanged, no event
recorded and only ``GET`` requests at the server (NFR-001, NFR-002).
"""

import json
from pathlib import Path

from conftest import CliResult, MakeTheatre, core, history_events, run_cli, snapshot
from remote_server import RemoteServer

DASH = "—"
SCHEMA_FILE = "troupe.schema.json"
TEAM = "model: opus\ntools: [read, write]\n"


def _set(theatre: Path, *args: str) -> CliResult:
    return run_cli("config", "set", *args, "--theatre", str(theatre))


def _get(theatre: Path, path: str) -> str:
    result = run_cli("config", "get", path, "--theatre", str(theatre))
    assert (result.code, result.err) == (0, ""), result.err
    return result.out


def _root(theatre: Path) -> Path:
    return theatre / ".troupe" / "troupe.yml"


def _set_ok(theatre: Path, *args: str) -> None:
    result = _set(theatre, *args)
    assert (result.code, result.out, result.err) == (0, "", "")


def _set_fails(theatre: Path, remote: RemoteServer, *args: str) -> str:
    """Run ``set *args``; assert exit 3 changing and recording nothing; return stderr."""
    events = history_events(theatre)  # imports the theatre first: the refusal records nothing
    before = snapshot(theatre)
    remote.clear_log()

    result = _set(theatre, *args)

    assert (result.code, result.out) == (3, "")
    assert result.err.startswith("troupe: ") and result.err.count("\n") == 1
    assert snapshot(theatre) == before
    assert history_events(theatre) == events
    assert {request.method for request in remote.requests()} <= {"GET"}
    return result.err


def test_include_of_a_remote_yaml_url_adds_a_remote_include(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:
    url = remote.serve("/team.yaml", TEAM)
    theatre = make_theatre({"troupe.yml": "a: 1\n"})

    _set_ok(theatre, "--include", "team", url)

    assert snapshot(theatre) == {".troupe/troupe.yml": f"a: 1\nteam: {url}\n".encode()}
    assert _get(theatre, "team.model") == "opus\n"
    assert _get(theatre, "team.tools.1") == "write\n"
    assert [event for event in core(history_events(theatre)) if event["op"] == "set"] == [
        {"seq": 2, "op": "set", "path": "team.model", "old": None, "new": "opus"},
        {"seq": 3, "op": "set", "path": "team.tools.0", "old": None, "new": "read"},
        {"seq": 4, "op": "set", "path": "team.tools.1", "old": None, "new": "write"},
    ]


def test_include_of_a_remote_text_url_reads_its_body(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # a URL path not ending .yml/.yaml is a text include (FR-001)
    url = remote.serve("/sys.md", "be terse\n")
    theatre = make_theatre({"troupe.yml": "a: 1\n"})

    _set_ok(theatre, "--include", "prompt", url)

    assert snapshot(theatre) == {".troupe/troupe.yml": f"a: 1\nprompt: {url}\n".encode()}
    assert _get(theatre, "prompt") == "be terse\n"
    assert [event for event in core(history_events(theatre)) if event["op"] == "set"] == [
        {"seq": 2, "op": "set", "path": "prompt", "old": None, "new": "be terse\n"}
    ]


def test_new_remote_include_is_fetched_once_during_the_set(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # R-10: the check of the new include and the verification reload share one fetch
    url = remote.serve("/team.yaml", TEAM)
    theatre = make_theatre({"troupe.yml": "a: 1\n"})

    _set_ok(theatre, "--include", "team", url)

    assert [(request.method, request.path) for request in remote.requests()] == [
        ("GET", "/team.yaml")
    ]


def test_include_of_a_url_whose_content_fails_the_schema_exits_3(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # S-9 via S-12
    url = remote.serve("/team.yaml", "model: 5\n")
    schema_text = json.dumps(
        {
            "type": "object",
            "properties": {"team": {"type": "object", "properties": {"model": {"type": "string"}}}},
        }
    )
    theatre = make_theatre({"troupe.yml": "a: 1\n", SCHEMA_FILE: schema_text})
    schema = (theatre / ".troupe" / SCHEMA_FILE).resolve()

    err = _set_fails(theatre, remote, "--include", "team", url)

    assert err == (
        f"troupe: team: the change would not match schema {schema} at team.model:"
        " 5 is not of type 'string'; no file changed\n"
    )


def test_after_adding_a_remote_include_its_values_are_read_only(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # S-4
    url = remote.serve("/team.yaml", TEAM)
    theatre = make_theatre({"troupe.yml": "a: 1\n"})
    _set_ok(theatre, "--include", "team", url)

    err = _set_fails(theatre, remote, "team.model", "x")

    assert err == (
        f"troupe: team.model: value comes from remote include {url}"
        f" ({_root(theatre).resolve()} line 2); troupe does not change remote content"
        f" {DASH} change that include line instead; no file changed\n"
    )
    assert _get(theatre, "team.model") == "opus\n"
