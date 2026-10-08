"""User Stories 2 and 3: remote content is read-only; new keys become local overrides (real CLI).

Remote content is served by the ``remote`` test server on 127.0.0.1 (spec C-006). Refusals
assert exit 3, empty stdout, exactly one stderr line naming PATH and containing the include
string exactly as written in the local file, every theatre file unchanged, no event recorded and
only ``GET`` requests at the server (NFR-001, NFR-002). Successful writes compare the whole root
file byte for byte (NFR-003). The comment number is the acceptance scenario covered.
"""

from pathlib import Path

from conftest import MakeTheatre, history_events, run_cli, snapshot
from remote_server import RemoteServer

DASH = "—"

TEAM = "model: opus\ntools: [read, write]\nbase: &b {model: opus}\ncoder: *b\n"


def _set(theatre: Path, *args: str) -> tuple[int, str, str]:
    result = run_cli("config", "set", *args, "--theatre", str(theatre))
    return result.code, result.out, result.err


def _get(theatre: Path, path: str) -> str:
    result = run_cli("config", "get", path, "--theatre", str(theatre))
    assert (result.code, result.err) == (0, ""), result.err
    return result.out


def _root(theatre: Path) -> Path:
    return theatre / ".troupe" / "troupe.yml"


def _refusal(theatre: Path, dotted: str, written: str, line: int) -> str:
    return (
        f"troupe: {dotted}: value comes from remote include {written}"
        f" ({_root(theatre).resolve()} line {line}); troupe does not change remote content"
        f" {DASH} change that include line instead; no file changed\n"
    )


def _assert_refused(
    theatre: Path, remote: RemoteServer, args: tuple[str, ...], dotted: str, written: str, line: int
) -> None:
    """Run ``set *args``; assert the remote refusal and that nothing changed anywhere."""
    events = history_events(theatre)  # imports the theatre first: the refusal records nothing
    before = snapshot(theatre)
    remote.clear_log()

    assert _set(theatre, *args) == (3, "", _refusal(theatre, dotted, written, line))

    assert snapshot(theatre) == before
    assert history_events(theatre) == events
    assert {request.method for request in remote.requests()} == {"GET"}


def test_changing_a_remote_value_exits_3_quoting_the_include_line(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # US2-1
    url = remote.serve("/team.yaml", TEAM)
    theatre = make_theatre({"troupe.yml": f"# shared settings\nteam: {url}\n"})

    _assert_refused(theatre, remote, ("team.model", "sonnet"), "team.model", url, 2)


def test_setting_a_remote_text_include_exits_3(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # US2-2
    url = remote.serve("/sys.md", "be terse\n")
    theatre = make_theatre({"troupe.yml": f"prompt: {url}\n"})

    _assert_refused(theatre, remote, ("prompt", "x"), "prompt", url, 1)


def test_list_append_in_remote_content_exits_3(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # US2-3
    url = remote.serve("/team.yaml", TEAM)
    theatre = make_theatre({"troupe.yml": f"team: {url}\n"})

    _assert_refused(theatre, remote, ("team.tools.2", "x"), "team.tools.2", url, 1)


def test_in_include_into_remote_content_exits_3(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # US2-3
    url = remote.serve("/team.yaml", TEAM)
    theatre = make_theatre({"troupe.yml": f"team: {url}\n"})

    _assert_refused(theatre, remote, ("--in-include", "team.newkey", "1"), "team.newkey", url, 1)


def test_replacing_a_whole_remote_include_exits_3(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # US2-3
    url = remote.serve("/team.yaml", TEAM)
    theatre = make_theatre({"troupe.yml": f"team: '{url}'\n"})

    _assert_refused(theatre, remote, ("team", "{a: 1}"), "team", f"'{url}'", 1)


def test_value_from_nested_remote_include_names_the_outermost_include(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # US2-4
    inner = remote.serve("/inner.yaml", "deep: 1\n")
    outer = remote.serve("/outer.yaml", f"nested: {inner}\n")
    theatre = make_theatre({"troupe.yml": f"team: {outer}\n"})

    _assert_refused(theatre, remote, ("team.nested.deep", "2"), "team.nested.deep", outer, 1)


def test_local_override_of_remote_include_changes_only_that_line(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # US2-5
    url = remote.serve("/coder.yaml", "temperature: 0.7\nmodel: gpt\n")
    text = f"coder:\n  $ref: {url}\n  temperature: 0.3  # local\nother: 1\n"
    theatre = make_theatre({"troupe.yml": text})
    remote.clear_log()

    assert _set(theatre, "coder.temperature", "0.5") == (0, "", "")

    expected = f"coder:\n  $ref: {url}\n  temperature: 0.5  # local\nother: 1\n"
    assert _root(theatre).read_text(encoding="utf-8") == expected
    assert _get(theatre, "coder.temperature") == "0.5\n"
    assert _get(theatre, "coder.model") == "gpt\n"
    assert {request.method for request in remote.requests()} == {"GET"}


def test_new_key_under_scalar_remote_include_becomes_a_local_override(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # US3-1
    url = remote.serve("/team.yaml", "model: opus\n")
    theatre = make_theatre({"troupe.yml": f"team: {url}  # shared\n"})

    assert _set(theatre, "team.temperature", "0.3") == (0, "", "")

    expected = f"team:  # shared\n  $ref: {url}\n  temperature: 0.3\n"
    assert _root(theatre).read_text(encoding="utf-8") == expected
    assert _get(theatre, "team.temperature") == "0.3\n"
    assert _get(theatre, "team.model") == "opus\n"


def test_new_key_under_mapping_form_remote_include_is_added_beside_overrides(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # US3-2
    url = remote.serve("/coder.yaml", "temperature: 0.7\nmodel: gpt\n")
    theatre = make_theatre({"troupe.yml": f"coder:\n  $ref: {url}\n  temperature: 0.3\nother: 1\n"})

    assert _set(theatre, "coder.top_p", "0.9") == (0, "", "")

    expected = f"coder:\n  $ref: {url}\n  temperature: 0.3\n  top_p: 0.9\nother: 1\n"
    assert _root(theatre).read_text(encoding="utf-8") == expected
    assert _get(theatre, "coder.top_p") == "0.9\n"


def test_expand_alias_in_remote_content_exits_3_quoting_the_include(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # S-4
    url = remote.serve("/team.yaml", TEAM)
    theatre = make_theatre({"troupe.yml": f"team: {url}\n"})

    _assert_refused(
        theatre,
        remote,
        ("--expand-alias", "team.coder.model", "gpt"),
        "team.coder.model",
        url,
        1,
    )
    _assert_refused(
        theatre, remote, ("--expand-alias", "team.coder.extra", "1"), "team.coder.extra", url, 1
    )


def test_new_key_under_alias_in_remote_content_is_refused_mentioning_expand_alias(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # S-5
    url = remote.serve("/team.yaml", TEAM)
    theatre = make_theatre({"troupe.yml": f"team: {url}\n"})
    events = history_events(theatre)
    before = snapshot(theatre)

    code, out, err = _set(theatre, "team.coder.extra", "1")

    assert (code, out) == (3, "")
    assert err.startswith("troupe: team.coder.extra: team.coder is the alias *b in ")
    assert "--expand-alias" in err and err.count("\n") == 1
    assert snapshot(theatre) == before
    assert history_events(theatre) == events


def test_in_include_into_remote_file_ending_inside_a_block_scalar_gets_the_remote_refusal(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # review regression (WP08 cycle 1, case a): checked before the renderer refuses
    url = remote.serve("/t2.yaml", "tools:\n  - a\nitems:\n  - n: 1\nnote: |\n  text")
    theatre = make_theatre({"troupe.yml": f"t: {url}\n"})

    _assert_refused(theatre, remote, ("--in-include", "t.newk", "2"), "t.newk", url, 1)


def test_new_key_under_a_multi_line_nested_remote_include_gets_the_remote_refusal(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # review regression (WP08 cycle 1, case b): the converter would refuse first
    inner = remote.serve("/inner.yaml", "k: 1\n")
    outer = remote.serve("/t3.yaml", f"x: >-\n  {inner}\n")
    theatre = make_theatre({"troupe.yml": f"u: {outer}\n"})

    _assert_refused(theatre, remote, ("u.x.newk", "1"), "u.x.newk", outer, 1)
