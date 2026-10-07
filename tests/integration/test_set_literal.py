"""User Story 6: ``set`` writes include-looking strings safely (S-11, S-12, S-13), real CLI.

Every success compares the bytes of every theatre file (history store excluded) with the whole
expected text, reads the value back with ``get`` and, where the write is the story, checks the
one recorded ``set`` event. Every refusal asserts its exit code, empty stdout, exactly one
``troupe: `` stderr line, every file unchanged and no event recorded (NFR-002). The comment
number is the US6 acceptance scenario covered.
"""

import json
from pathlib import Path

import pytest

from conftest import CliResult, MakeTheatre, core, history_events, run_cli, snapshot
from remote_server import RemoteServer

type Files = dict[str, str | bytes]

SCHEMA_FILE = "troupe.schema.json"


def _set(theatre: Path, *args: str) -> CliResult:
    return run_cli("config", "set", *args, "--theatre", str(theatre))


def _get(theatre: Path, path: str) -> str:
    result = run_cli("config", "get", path, "--theatre", str(theatre))
    assert (result.code, result.err) == (0, ""), result.err
    return result.out


def _bytes(files: Files) -> dict[str, bytes]:
    return {
        f".troupe/{rel}": content.encode("utf-8") if isinstance(content, str) else content
        for rel, content in files.items()
    }


def _set_ok(theatre: Path, args: tuple[str, ...], expected: Files, path: str, shown: str) -> None:
    """Run ``set *args``; assert success, the whole theatre's bytes, and ``get path``."""
    result = _set(theatre, *args)
    assert (result.code, result.out, result.err) == (0, "", "")
    assert snapshot(theatre) == _bytes(expected)
    assert _get(theatre, path) == shown


def _set_fails(theatre: Path, args: tuple[str, ...], code: int) -> str:
    """Run ``set *args``; assert ``code``, empty stdout, one stderr line, nothing changed."""
    events = history_events(theatre)  # imports the theatre first: the refusal records nothing
    before = snapshot(theatre)

    result = _set(theatre, *args)

    assert (result.code, result.out) == (code, "")
    assert result.err.startswith("troupe: ") and result.err.count("\n") == 1
    assert snapshot(theatre) == before
    assert history_events(theatre) == events
    return result.err


def _last_set_events(theatre: Path) -> list[dict[str, object]]:
    return [event for event in core(history_events(theatre)) if event["op"] == "set"]


def _uri_schema(prop: str) -> str:
    return json.dumps({"type": "object", "properties": {prop: {"format": "uri"}}})


# --- US6-1: a URL VALUE is a literal by default (S-13) -------------------------------------------


def test_url_value_without_schema_is_written_as_literal(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # US6-1
    url = remote.serve("/y", "served body\n")  # would be fetched if it became an include
    theatre = make_theatre({"troupe.yml": "a: 1\n"})

    _set_ok(
        theatre, ("docs", url), {"troupe.yml": f"a: 1\ndocs: !literal {url}\n"}, "docs", f"{url}\n"
    )

    assert remote.requests() == []
    assert _last_set_events(theatre) == [
        {"seq": 2, "op": "set", "path": "docs", "old": None, "new": url}
    ]


# --- US6-2: file: VALUE literal by default, include with --include (S-13, S-12) ------------------


def test_file_value_is_written_as_literal_and_with_include_becomes_an_include(
    make_theatre: MakeTheatre, tmp_path: Path
) -> None:  # US6-2
    theatre = make_theatre({"troupe.yml": "a: 1\n", "p.md": "hello\n"})

    _set_ok(
        theatre,
        ("b", "file:p.md"),
        {"troupe.yml": "a: 1\nb: !literal file:p.md\n", "p.md": "hello\n"},
        "b",
        "file:p.md\n",
    )
    assert _last_set_events(theatre) == [
        {"seq": 2, "op": "set", "path": "b", "old": None, "new": "file:p.md"}
    ]

    # A separate, fresh theatre: the same VALUE with --include is the step-1 include.
    other = tmp_path / "other"
    (other / ".troupe").mkdir(parents=True)
    (other / ".troupe" / "troupe.yml").write_text("a: 1\n", encoding="utf-8")
    (other / ".troupe" / "p.md").write_text("hello\n", encoding="utf-8")

    _set_ok(
        other,
        ("--include", "b", "file:p.md"),
        {"troupe.yml": "a: 1\nb: file:p.md\n", "p.md": "hello\n"},
        "b",
        "hello\n",
    )
    assert _last_set_events(other) == [
        {"seq": 2, "op": "set", "path": "b", "old": None, "new": "hello\n"}
    ]


# --- US6-3: the schema's format: uri mark (S-12) -------------------------------------------------


def test_uri_path_is_written_untagged(make_theatre: MakeTheatre, remote: RemoteServer) -> None:
    # US6-3: the schema already makes the string a literal, so no tag is needed.
    url = remote.serve("/n", "served\n")
    theatre = make_theatre({"troupe.yml": "a: 1\n", SCHEMA_FILE: _uri_schema("webhook")})

    _set_ok(
        theatre,
        ("webhook", url),
        {"troupe.yml": f"a: 1\nwebhook: {url}\n", SCHEMA_FILE: _uri_schema("webhook")},
        "webhook",
        f"{url}\n",
    )
    assert remote.requests() == []


def test_include_on_uri_path_exits_3(make_theatre: MakeTheatre, remote: RemoteServer) -> None:
    # US6-3: --include cannot make a string the schema marks as a uri into an include.
    url = remote.serve("/n", "served\n")
    theatre = make_theatre({"troupe.yml": "a: 1\n", SCHEMA_FILE: _uri_schema("webhook")})
    schema = (theatre / ".troupe" / SCHEMA_FILE).resolve()

    err = _set_fails(theatre, ("--include", "webhook", url), 3)

    assert err == (
        f"troupe: webhook: schema {schema} marks webhook as format uri, so it cannot be an"
        " include; no file changed\n"
    )
    assert remote.requests() == []


# --- US6-4: strings nested in a mapping VALUE, each judged at its own path (S-11) ----------------

AGENTS_VALUE = "{coder: {docs: https://x.example/y, n: 1}}"


@pytest.mark.parametrize(
    ("before", "path", "after"),
    [
        (
            "x: 1\n",
            "agents",
            "x: 1\nagents:\n  coder:\n    docs: !literal https://x.example/y\n    n: 1\n",
        ),
        (
            "m: {x: 1}\n",
            "m.agents",
            "m: {x: 1, agents: {coder: {docs: !literal https://x.example/y, n: 1}}}\n",
        ),
    ],
    ids=["block-parent", "flow-parent"],
)
def test_only_include_looking_strings_in_a_mapping_value_are_tagged(
    make_theatre: MakeTheatre, before: str, path: str, after: str
) -> None:  # US6-4
    theatre = make_theatre({"troupe.yml": before})

    _set_ok(
        theatre,
        (path, AGENTS_VALUE),
        {"troupe.yml": after},
        f"{path}.coder.docs",
        "https://x.example/y\n",
    )

    assert _get(theatre, f"{path}.coder.n") == "1\n"
    assert _last_set_events(theatre) == [
        {
            "seq": 2,
            "op": "set",
            "path": f"{path}.coder.docs",
            "old": None,
            "new": "https://x.example/y",
        },
        {"seq": 3, "op": "set", "path": f"{path}.coder.n", "old": None, "new": 1},
    ]


# --- US6-5: an existing tag is kept for a plain string (S-11) ------------------------------------


def test_existing_literal_tag_is_kept_for_a_plain_string(make_theatre: MakeTheatre) -> None:
    # US6-5
    theatre = make_theatre({"troupe.yml": "docs: !literal https://old.example\nz: 1\n"})

    _set_ok(
        theatre,
        ("docs", "plain-text"),
        {"troupe.yml": "docs: !literal plain-text\nz: 1\n"},
        "docs",
        "plain-text\n",
    )
    assert _last_set_events(theatre) == [
        {"seq": 3, "op": "set", "path": "docs", "old": "https://old.example", "new": "plain-text"}
    ]


# --- US6-6: --include of a URL that cannot be fetched (S-12) -------------------------------------


def test_include_of_a_missing_url_exits_3_and_changes_nothing(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # US6-6
    missing = remote.url("/missing.yaml")  # not served: 404
    theatre = make_theatre({"troupe.yml": "a: 1\n"})
    root = (theatre / ".troupe" / "troupe.yml").resolve()

    err = _set_fails(theatre, ("--include", "team", missing), 3)

    assert err == (
        f"troupe: team: cannot fetch {missing} (included from {root}, at team):"
        " HTTP 404 Not Found; no file changed\n"
    )
    assert {request.method for request in remote.requests()} == {"GET"}


# --- US6-7: --include belongs to set only (S-12) -------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        ("get", "a", "--include"),
        ("get", "--include", "a"),
        ("show", "--include"),
        ("history", "--include"),
        ("watch", "--include"),
    ],
    ids=["get", "get-option-first", "show", "history", "watch"],
)
def test_include_flag_on_other_subcommands_exits_2(
    make_theatre: MakeTheatre, args: tuple[str, ...]
) -> None:  # US6-7
    theatre = make_theatre({"troupe.yml": "a: 1\n"})
    before = snapshot(theatre)

    result = run_cli("config", *args, "--theatre", str(theatre))

    assert (result.code, result.out) == (2, "")
    assert "--include" in result.err
    assert snapshot(theatre) == before


# --- US6-8: text-include content is file text, never tagged (S-11) -------------------------------


def test_text_include_content_is_never_tagged(make_theatre: MakeTheatre) -> None:  # US6-8
    theatre = make_theatre({"troupe.yml": "prompt: file:sys.md\n", "sys.md": "old\n"})

    _set_ok(
        theatre,
        ("prompt", "https://x"),
        {"troupe.yml": "prompt: file:sys.md\n", "sys.md": "https://x"},
        "prompt",
        "https://x\n",
    )


# --- Further S-11 / S-12 / C-003 cases ----------------------------------------------------------


def test_setting_a_text_include_to_its_own_string_keeps_the_step1_rule(
    make_theatre: MakeTheatre,
) -> None:
    # S-11, C-003: the string goes into the text include's file, as on step 6; nothing is tagged.
    theatre = make_theatre({"troupe.yml": "b: file:p.md\n", "p.md": "hello\n"})

    _set_ok(
        theatre,
        ("b", "file:p.md"),
        {"troupe.yml": "b: file:p.md\n", "p.md": "file:p.md"},
        "b",
        "file:p.md\n",
    )


def test_setting_a_yaml_include_to_its_own_string_is_refused_as_a_whole_replacement(
    make_theatre: MakeTheatre,
) -> None:
    # C-003: replacing a whole YAML include stays refused (step 1), whatever the VALUE.
    theatre = make_theatre({"troupe.yml": "b: file:t.yaml\n", "t.yaml": "k: 1\n"})

    target = (theatre / ".troupe" / "t.yaml").resolve()

    err = _set_fails(theatre, ("b", "file:t.yaml"), 3)

    assert err == (
        f"troupe: b: value comes from include {target}; refusing to replace it"
        " (change a path inside it instead); no file changed\n"
    )


def test_literal_replaced_by_include_drops_the_tag(make_theatre: MakeTheatre) -> None:
    # S-12: --include removes an existing !literal tag.
    theatre = make_theatre({"troupe.yml": "b: !literal file:p.md\n", "p.md": "hello\n"})

    _set_ok(
        theatre,
        ("--include", "b", "file:p.md"),
        {"troupe.yml": "b: file:p.md\n", "p.md": "hello\n"},
        "b",
        "hello\n",
    )


def test_literal_tag_is_written_in_flow_collections_and_list_appends(
    make_theatre: MakeTheatre,
) -> None:  # S-11
    theatre = make_theatre({"troupe.yml": "m: {a: 1}\ntools:\n  - read\n"})

    _set_ok(
        theatre,
        ("m.docs", "https://x.example/y"),
        {"troupe.yml": "m: {a: 1, docs: !literal https://x.example/y}\ntools:\n  - read\n"},
        "m.docs",
        "https://x.example/y\n",
    )
    _set_ok(
        theatre,
        ("tools.1", "file:p.md"),
        {
            "troupe.yml": (
                "m: {a: 1, docs: !literal https://x.example/y}\n"
                "tools:\n  - read\n  - !literal file:p.md\n"
            )
        },
        "tools.1",
        "file:p.md\n",
    )


@pytest.mark.parametrize(
    ("value", "line", "shown"),
    [
        # a space alone needs no quoting in step 1, so none is added after the tag
        ("'file:my notes.md'", "notes: !literal file:my notes.md\n", "file:my notes.md\n"),
        # " #" would start a comment: step 1 single-quotes it, and so does the tagged form
        (
            "'file:my notes #1.md'",
            "notes: !literal 'file:my notes #1.md'\n",
            "file:my notes #1.md\n",
        ),
        # ": " would start a mapping
        ("'file:a: b'", "notes: !literal 'file:a: b'\n", "file:a: b\n"),
    ],
    ids=["space-stays-plain", "hash-needs-quotes", "colon-needs-quotes"],
)
def test_quoted_include_looking_value_keeps_its_needed_quoting_after_the_tag(
    make_theatre: MakeTheatre, value: str, line: str, shown: str
) -> None:  # S-11: "!literal " followed by the string exactly as step 1 would write it
    theatre = make_theatre({"troupe.yml": "a: 1\n"})

    _set_ok(theatre, ("notes", value), {"troupe.yml": f"a: 1\n{line}"}, "notes", shown)
