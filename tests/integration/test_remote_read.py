"""User Story 1: read configuration that includes shared settings from a URL (real CLI, real HTTP).

Remote content is served by the ``remote`` test server on 127.0.0.1 (spec C-006); its request
log shows what each command fetched. Every test asserts the exit code, stdout exactly and
stderr (empty, or the single ``troupe: ...`` line). The number in a test's comment is the US1
acceptance scenario it covers.
"""

import socket
from pathlib import Path

import pytest

from conftest import (
    HISTORY_PREFIX,
    MakeTheatre,
    WatchProcess,
    all_files,
    core,
    history_events,
    run_cli,
    snapshot,
)
from remote_server import RemoteServer, Route


def _cli(theatre: Path, *args: str) -> tuple[int, str, str]:
    result = run_cli("config", *args, "--theatre", str(theatre))
    return result.code, result.out, result.err


def _root(theatre: Path) -> Path:
    return (theatre / ".troupe" / "troupe.yml").resolve()


def _paths(remote: RemoteServer) -> list[str]:
    return [request.path for request in remote.requests()]


def _closed_port_url() -> str:
    """An http URL on 127.0.0.1 whose port was just released, so nothing listens there."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"http://127.0.0.1:{port}/team.yaml"


def test_get_reads_a_value_from_a_remote_yaml_include(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # 1
    url = remote.serve("/team.yaml", "model: opus\n")
    theatre = make_theatre({"troupe.yml": f"team: {url}\n"})

    assert _cli(theatre, "get", "team.model") == (0, "opus\n", "")
    assert [(r.method, r.path) for r in remote.requests()] == [("GET", "/team.yaml")]


def test_get_of_a_remote_text_include_prints_the_body_exactly(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # 2
    body = "You are terse.\r\nmodel: not yaml\n"
    url = remote.serve("/sys.md", body) + "?v=2"
    theatre = make_theatre({"troupe.yml": f"prompt: {url}\n"})

    assert _cli(theatre, "get", "prompt") == (0, body, "")
    assert _paths(remote) == ["/sys.md?v=2"]


def test_query_naming_yaml_does_not_make_a_text_url_yaml(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # 2 (the path decides, not the query)
    url = remote.serve("/sys.md", "a: 1\n") + "?as=x.yaml"
    theatre = make_theatre({"troupe.yml": f"prompt: {url}\n"})

    assert _cli(theatre, "get", "prompt") == (0, "a: 1\n", "")
    assert _cli(theatre, "get", "prompt.a") == (5, "", "troupe: prompt.a: prompt is a scalar\n")


def test_ref_form_overrides_win_and_sources_name_url_and_local_file(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # 3
    url = remote.serve("/coder.yaml", "temperature: 0.7\nmodel: gpt\n")
    theatre = make_theatre({"troupe.yml": f"coder:\n  $ref: {url}\n  temperature: 0.3\n"})

    assert _cli(theatre, "get", "coder.temperature") == (0, "0.3\n", "")
    assert _cli(theatre, "get", "coder.model") == (0, "gpt\n", "")
    assert _cli(theatre, "show", "coder", "--sources") == (
        0,
        f"temperature: 0.3 # from .troupe/troupe.yml\nmodel: gpt # from {url}\n",
        "",
    )


def test_file_include_inside_remote_yaml_is_fetched_from_the_same_server(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # 4
    extra = remote.serve("/x.yaml", "k: v\n")
    url = remote.serve("/team.yaml", f"prompt: file:prompts/sys.md\nextra: {extra}\n")
    remote.serve("/prompts/sys.md", "Be brief.\n")
    theatre = make_theatre({"troupe.yml": f"team: {url}\n"})

    assert _cli(theatre, "get", "team.prompt") == (0, "Be brief.\n", "")
    assert _cli(theatre, "get", "team.extra.k") == (0, "v\n", "")
    assert sorted(_paths(remote)) == sorted(["/team.yaml", "/prompts/sys.md", "/x.yaml"] * 2)
    assert {r.method for r in remote.requests()} == {"GET"}


FAILURES = {
    "http-404": (Route(status=404, body=b"gone\n"), "HTTP 404 Not Found"),
    "non-utf8-body": (Route(body=b"model: \xff\n"), "not valid UTF-8 at byte 7"),
    "redirect-to-ftp": (
        Route(status=302, headers={"Location": "ftp://127.0.0.1/team.yaml"}),
        "redirect to ftp://127.0.0.1/team.yaml refused (only http and https)",
    ),
    "body-over-1-MiB": (  # S-14
        Route(body=b"#" * (1024 * 1024 + 1)),
        "larger than 1 MiB, the limit for a remote include",
    ),
}


@pytest.mark.parametrize(("route", "reason"), FAILURES.values(), ids=FAILURES.keys())
def test_failed_fetch_exits_4_naming_url_and_local_file(
    make_theatre: MakeTheatre, remote: RemoteServer, route: Route, reason: str
) -> None:  # 5
    url = remote.route("/team.yaml", route)
    theatre = make_theatre({"troupe.yml": f"name: demo\nteam: {url}\n"})

    assert _cli(theatre, "get", "name") == (
        4,
        "",
        f"troupe: cannot fetch {url} (included from {_root(theatre)}, at team): {reason}\n",
    )


def test_fetch_from_a_closed_port_exits_4_naming_url_and_local_file(
    make_theatre: MakeTheatre,
) -> None:  # 5
    url = _closed_port_url()
    theatre = make_theatre({"troupe.yml": f"name: demo\nteam: {url}\n"})

    code, out, err = _cli(theatre, "get", "name")

    prefix = f"troupe: cannot fetch {url} (included from {_root(theatre)}, at team): "
    assert (code, out) == (4, "")
    assert err.startswith(prefix) and err.endswith("\n") and err.count("\n") == 1
    assert "refused" in err[len(prefix) :].lower()


def test_fetch_that_never_answers_exits_4_after_the_10_s_deadline(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # 5 (the one slow CLI deadline test)
    url = remote.route("/team.yaml", Route(behaviour="hang"))
    theatre = make_theatre({"troupe.yml": f"team: {url}\n"})

    assert _cli(theatre, "get", "team") == (
        4,
        "",
        f"troupe: cannot fetch {url} (included from {_root(theatre)}, at team): "
        "timed out after 10 s\n",
    )


def test_url_cycle_exits_4(make_theatre: MakeTheatre, remote: RemoteServer) -> None:  # 5
    a, b = remote.url("/a.yaml"), remote.url("/b.yaml")
    remote.serve("/a.yaml", f"b: {b}\n")
    remote.serve("/b.yaml", f"a: {a}\n")
    theatre = make_theatre({"troupe.yml": f"top: {a}\n"})

    assert _cli(theatre, "show") == (
        4,
        "",
        f"troupe: include cycle at top.b.a: {a} -> {b} -> {a}\n",
    )


def test_upstream_change_is_recorded_as_a_file_lineage_set_event(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # 6
    url = remote.serve("/team.yaml", "model: opus\nsize: 3\n")
    theatre = make_theatre({"troupe.yml": f"team: {url}\n"})
    imported = history_events(theatre)
    remote.serve("/team.yaml", "model: sonnet\nsize: 3\n")

    assert _cli(theatre, "get", "team.size") == (0, "3\n", "")

    events = history_events(theatre)
    assert core(events) == [
        {"seq": 1, "op": "import", "path": "team.model", "old": None, "new": "opus"},
        {"seq": 2, "op": "import", "path": "team.size", "old": None, "new": 3},
        {"seq": 3, "op": "set", "path": "team.model", "old": "opus", "new": "sonnet"},
    ]
    assert events[:2] == imported
    assert (events[2]["actor"], events[2]["via"], events[2]["reason"]) == (
        {"kind": "unknown", "id": None},
        "file",
        None,
    )


def test_history_does_not_record_an_upstream_change(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # 6 ("a command other than history")
    url = remote.serve("/team.yaml", "model: opus\n")
    theatre = make_theatre({"troupe.yml": f"team: {url}\n"})
    imported = history_events(theatre)
    remote.serve("/team.yaml", "model: sonnet\n")

    assert history_events(theatre) == imported


LOADING_COMMANDS = {
    "get": ("get", "name"),
    "show": ("show",),
    "show-sources": ("show", "name", "--sources"),
    "set": ("set", "name", "other"),
    "history": ("history",),
}


@pytest.mark.parametrize("imported", [False, True], ids=["new-theatre", "imported-theatre"])
@pytest.mark.parametrize("command", LOADING_COMMANDS.values(), ids=LOADING_COMMANDS.keys())
def test_every_command_that_loads_fails_with_exit_4_when_a_fetch_fails(
    make_theatre: MakeTheatre, remote: RemoteServer, command: tuple[str, ...], imported: bool
) -> None:  # 5, FR-003, FR-009
    url = remote.serve("/team.yaml", "model: opus\n")
    theatre = make_theatre({"troupe.yml": f"name: demo\nteam: {url}\n"})
    if imported:
        history_events(theatre)
    before, files_before = snapshot(theatre), all_files(theatre)
    events_before = history_events(theatre) if imported else []
    remote.serve("/team.yaml", "gone\n", status=404)

    assert _cli(theatre, *command) == (
        4,
        "",
        f"troupe: cannot fetch {url} (included from {_root(theatre)}, at team): "
        "HTTP 404 Not Found\n",
    )
    assert snapshot(theatre) == before
    assert all_files(theatre) == files_before
    if imported:
        remote.serve("/team.yaml", "model: opus\n")
        assert history_events(theatre) == events_before
    else:
        assert not any(rel.startswith(HISTORY_PREFIX) for rel in all_files(theatre))


def test_watch_exits_4_at_startup_when_a_fetch_fails_and_never_prints_watching(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # 5, FR-003
    url = remote.serve("/team.yaml", "gone\n", status=404)
    theatre = make_theatre({"troupe.yml": f"team: {url}\n"})

    with WatchProcess("--theatre", str(theatre)) as w:
        result = w.wait_exit()

    assert result == (
        4,
        "",
        f"troupe: cannot fetch {url} (included from {_root(theatre)}, at team): "
        "HTTP 404 Not Found\n",
    )
    assert not any(rel.startswith(HISTORY_PREFIX) for rel in all_files(theatre))


def test_each_url_is_fetched_once_per_command(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # edge case "the same URL included twice", S-2
    shared = remote.serve("/shared.yaml", "k: v\n")
    team = remote.serve("/team.yaml", f"one: {shared}\ntwo: {shared}\n")
    theatre = make_theatre(
        {"troupe.yml": f"team: {team}\nagain: {team}\nalso: {shared}\nref:\n  $ref: {shared}\n"}
    )

    code, out, err = _cli(theatre, "show")

    assert (code, err) == (0, "")
    assert out == (
        "team:\n  one:\n    k: v\n  two:\n    k: v\n"
        "again:\n  one:\n    k: v\n  two:\n    k: v\n"
        "also:\n  k: v\n"
        "ref:\n  k: v\n"
    )
    assert sorted(_paths(remote)) == ["/shared.yaml", "/team.yaml"]
    assert {r.method for r in remote.requests()} == {"GET"}


def test_https_include_with_an_untrusted_certificate_exits_4(
    make_theatre: MakeTheatre, https_remote: RemoteServer
) -> None:  # 5, S-2 (TLS certificates are verified)
    url = https_remote.serve("/team.yaml", "model: opus\n")
    theatre = make_theatre({"troupe.yml": f"team: {url}\n"})

    code, out, err = _cli(theatre, "get", "team.model")

    prefix = f"troupe: cannot fetch {url} (included from {_root(theatre)}, at team): "
    assert (code, out) == (4, "")
    assert err.startswith(prefix) and err.endswith("\n") and err.count("\n") == 1
    assert "CERTIFICATE_VERIFY_FAILED" in err
