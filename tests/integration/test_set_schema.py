"""``set`` with the schema, ``--include`` and ``!literal`` tags (US5-3, S-9, S-11 to S-13).

Real CLI, real files, the real event store and the ``remote`` test server (spec C-006). Refusals
assert exit 3 (or 2 for a bad option), empty stdout, the one stderr line, every theatre file
unchanged and no event recorded (NFR-002). Successful writes compare the whole root file byte for
byte (NFR-003) and read the value back with ``get``.

The tag tests cover each way an existing scalar is replaced (plain, quoted, block, flow and the
kind-changing fallback) against the rule in research R-8: an untagged scalar gets ``!literal``
for a literal VALUE, a tagged one keeps it for any string and loses it for a number or an
``--include`` include.
"""

import json
from pathlib import Path

import pytest

from conftest import MakeTheatre, history_events, run_cli, snapshot
from remote_server import RemoteServer

SCHEMA_FILE = "troupe.schema.json"


def _set(theatre: Path, *args: str) -> tuple[int, str, str]:
    result = run_cli("config", "set", *args, "--theatre", str(theatre))
    return result.code, result.out, result.err


def _get(theatre: Path, path: str) -> str:
    result = run_cli("config", "get", path, "--theatre", str(theatre))
    assert (result.code, result.err) == (0, ""), result.err
    return result.out


def _root(theatre: Path) -> Path:
    return theatre / ".troupe" / "troupe.yml"


def _schema(properties: dict[str, object]) -> str:
    return json.dumps({"type": "object", "properties": properties})


def _refused(theatre: Path, *args: str) -> str:
    """Run ``set *args``; assert exit 3 changing nothing and recording nothing; return stderr."""
    events = history_events(theatre)
    before = snapshot(theatre)

    code, out, err = _set(theatre, *args)

    assert (code, out) == (3, "")
    assert err.startswith("troupe: ") and err.count("\n") == 1
    assert snapshot(theatre) == before
    assert history_events(theatre) == events
    return err


# --- The schema (US5-3, S-9) ---------------------------------------------------------------------


def test_set_that_would_violate_the_schema_exits_3_naming_path_and_schema(
    make_theatre: MakeTheatre,
) -> None:  # US5-3
    theatre = make_theatre(
        {"troupe.yml": "model: opus\n", SCHEMA_FILE: _schema({"model": {"type": "string"}})}
    )
    schema = (theatre / ".troupe" / SCHEMA_FILE).resolve()

    err = _refused(theatre, "model", "5")

    assert err == (
        f"troupe: model: the change would not match schema {schema} at model:"
        " 5 is not of type 'string'; no file changed\n"
    )


def test_set_that_matches_the_schema_is_written(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(
        {"troupe.yml": "model: opus\n", SCHEMA_FILE: _schema({"model": {"type": "string"}})}
    )

    assert _set(theatre, "model", "sonnet") == (0, "", "")

    assert _root(theatre).read_text(encoding="utf-8") == "model: sonnet\n"


def test_set_whose_new_include_cannot_be_fetched_exits_3_naming_the_url(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # S-12, US6-6
    missing = remote.url("/missing.yaml")  # not served: 404
    theatre = make_theatre({"troupe.yml": "a: 1\n"})
    root = _root(theatre).resolve()

    err = _refused(theatre, "--include", "team", missing)

    assert err == (
        f"troupe: team: cannot fetch {missing} (included from {root}, at team):"
        " HTTP 404 Not Found; no file changed\n"
    )


def test_set_with_include_on_a_uri_path_exits_3(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # S-12, US6-3
    url = remote.serve("/n.yaml", "a: 1\n")
    theatre = make_theatre(
        {"troupe.yml": "a: 1\n", SCHEMA_FILE: _schema({"webhook": {"format": "uri"}})}
    )
    schema = (theatre / ".troupe" / SCHEMA_FILE).resolve()

    err = _refused(theatre, "--include", "webhook", url)

    assert err == (
        f"troupe: webhook: schema {schema} marks webhook as format uri, so it cannot be an"
        " include; no file changed\n"
    )
    assert remote.requests() == []


def test_uri_path_without_include_is_written_untagged_and_not_fetched(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # S-11 with the schema's mark
    url = remote.serve("/n", "x")
    theatre = make_theatre(
        {"troupe.yml": "a: 1\n", SCHEMA_FILE: _schema({"webhook": {"format": "uri"}})}
    )

    assert _set(theatre, "webhook", url) == (0, "", "")

    assert _root(theatre).read_text(encoding="utf-8") == f"a: 1\nwebhook: {url}\n"
    assert _get(theatre, "webhook") == f"{url}\n"
    assert remote.requests() == []


@pytest.mark.parametrize("command", ["get", "show", "history", "watch"])
def test_include_flag_on_other_subcommands_exits_2(
    make_theatre: MakeTheatre, command: str
) -> None:  # S-12, US6-7
    theatre = make_theatre({"troupe.yml": "a: 1\n"})
    before = snapshot(theatre)
    args = ["a"] if command == "get" else []

    result = run_cli("config", command, *args, "--include", "--theatre", str(theatre))

    assert (result.code, result.out) == (2, "")
    assert "unrecognized arguments: --include" in result.err
    assert snapshot(theatre) == before


def test_set_on_unrelated_path_reuses_one_fetch_per_url(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # R-10: the command's load and its verification reload share one fetch
    team = remote.serve("/team.yaml", "model: opus\n")
    coder = remote.serve("/coder.yaml", "temperature: 0.7\n")
    prompt = remote.serve("/sys.md", "be terse\n")
    theatre = make_theatre(
        {
            "troupe.yml": (
                f"team: {team}\ncoder:\n  $ref: {coder}\n  temperature: 0.3\n"
                f"prompt: {prompt}\nother: 1\n"
            )
        }
    )

    assert _set(theatre, "other", "2") == (0, "", "")

    paths = sorted(request.path for request in remote.requests())
    assert paths == ["/coder.yaml", "/sys.md", "/team.yaml"]
    assert {request.method for request in remote.requests()} == {"GET"}


def test_include_flag_fetches_only_the_new_url_once_more(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # R-10, S-12
    team = remote.serve("/team.yaml", "model: opus\n")
    extra = remote.serve("/x.yaml", "k: 1\n")
    theatre = make_theatre({"troupe.yml": f"team: {team}\n"})

    assert _set(theatre, "--include", "extra", extra) == (0, "", "")

    assert _root(theatre).read_text(encoding="utf-8") == f"team: {team}\nextra: {extra}\n"
    assert sorted(request.path for request in remote.requests()) == ["/team.yaml", "/x.yaml"]
    assert _get(theatre, "extra.k") == "1\n"


# --- Literal mechanics: tags on replaced scalars (S-11, S-12, R-8, R-9) --------------------------


@pytest.mark.parametrize(
    ("text", "args", "expected"),
    [
        # untagged + literal VALUE: the tag is inserted before the content
        # (the comment keeps its column, or gets one space once the value reaches it: FR-020)
        ("d: x  # c\n", ("d", "https://x.example/y"), "d: !literal https://x.example/y # c\n"),
        ("d: x" + " " * 30 + "# c\n", ("d", "file:a"), "d: !literal file:a" + " " * 16 + "# c\n"),
        ('d: "x"\n', ("d", "file:p.md"), 'd: !literal "file:p.md"\n'),
        ("f: [a, b]\n", ("f.0", "https://h.example"), "f: [!literal https://h.example, b]\n"),
        # tagged + string: the tag is kept (S-11)
        (
            "docs: !literal https://old.example  # c\n",
            ("docs", "plain-text"),
            "docs: !literal plain-text           # c\n",
        ),
        ("d: !literal 'x'\n", ("d", "https://y"), "d: !literal 'https://y'\n"),
        ("k: !literal |\n  a\n  b\n", ("k", '"c\\nd\\n"'), "k: !literal |\n  c\n  d\n"),
        # tagged + non-string: the tag is removed, an anchor after it stays
        ("d: !literal https://old  # c\n", ("d", "5"), "d: 5" + " " * 21 + "# c\n"),
        ("k: !literal &a x\nz: *a\n", ("k", "5"), "k: &a 5\nz: *a\n"),
        ("f: [!literal a, b]\n", ("f.0", "7"), "f: [7, b]\n"),
        ("k: !literal |\n  a\n", ("k", "true"), "k: true\n"),
        # tagged + --include: the tag is removed (S-12)
        ("b: !literal file:p.md\n", ("--include", "b", "file:p.md"), "b: file:p.md\n"),
    ],
    ids=[
        "plain-gets-tag",
        "plain-gets-tag-comment-column",
        "double-quoted-gets-tag",
        "flow-gets-tag",
        "plain-keeps-tag",
        "single-quoted-keeps-tag",
        "block-keeps-tag",
        "number-drops-tag",
        "number-drops-tag-keeps-anchor",
        "flow-number-drops-tag",
        "block-to-bool-drops-tag",
        "include-flag-drops-tag",
    ],
)
def test_replacing_a_scalar_adds_keeps_or_drops_the_literal_tag(
    make_theatre: MakeTheatre, text: str, args: tuple[str, ...], expected: str
) -> None:
    theatre = make_theatre({"troupe.yml": text, "p.md": "hello\n"})

    assert _set(theatre, *args) == (0, "", "")

    assert _root(theatre).read_text(encoding="utf-8") == expected


def test_replacing_a_tagged_value_with_a_number_drops_the_tag(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "n: !literal file:x.md\nz: 1\n"})

    assert _set(theatre, "n", "5") == (0, "", "")

    assert _root(theatre).read_text(encoding="utf-8") == "n: 5\nz: 1\n"
    assert _get(theatre, "n") == "5\n"
    assert [event["new"] for event in history_events(theatre)][-1] == 5


def test_literal_value_replacing_an_untagged_block_scalar_gets_the_tag_before_the_indicator(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre({"troupe.yml": "z: 1\nkey: |\n  a\n  b\n"})

    assert _set(theatre, "key", '"file:x\\ny\\n"') == (0, "", "")

    assert _root(theatre).read_text(encoding="utf-8") == "z: 1\nkey: !literal |\n  file:x\n  y\n"
    assert _get(theatre, "key") == "file:x\ny\n"


def test_string_replacing_an_empty_tagged_value_keeps_the_tag(make_theatre: MakeTheatre) -> None:
    # The kind-changing fallback (an empty value) keeps the tag for a string (S-11).
    theatre = make_theatre({"troupe.yml": "u: !literal\nz: 1\n"})

    assert _set(theatre, "u", "hello") == (0, "", "")

    assert _root(theatre).read_text(encoding="utf-8") == "u: !literal hello\nz: 1\n"
    assert _get(theatre, "u") == "hello\n"


def test_string_a_tagged_block_cannot_hold_keeps_the_tag(make_theatre: MakeTheatre) -> None:
    # The kind-changing fallback (a control character, so no block scalar) keeps the tag (S-11).
    theatre = make_theatre({"troupe.yml": "k: !literal |\n  a\nz: 1\n"})

    assert _set(theatre, "k", '"x\\x01y"') == (0, "", "")

    assert _root(theatre).read_text(encoding="utf-8") == 'k: !literal "x\\x01y"\nz: 1\n'
    assert _get(theatre, "k") == "x\x01y\n"


def test_literal_value_replacing_a_collection_is_tagged(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "k:\n  a: 1\nz: 1\n"})

    assert _set(theatre, "k", "https://h.example") == (0, "", "")

    assert _root(theatre).read_text(encoding="utf-8") == "k: !literal https://h.example\nz: 1\n"
    assert _get(theatre, "k") == "https://h.example\n"


def test_setting_a_tagged_value_to_its_own_text_is_a_no_op(make_theatre: MakeTheatre) -> None:
    # R-9: a literal VALUE matches the literal scalar holding the same text.
    theatre = make_theatre({"troupe.yml": "docs: !literal https://x.example/y\n"})
    events = history_events(theatre)
    before = snapshot(theatre)

    assert _set(theatre, "docs", "https://x.example/y") == (0, "", "")

    assert snapshot(theatre) == before
    assert history_events(theatre) == events


def test_include_flag_on_a_literal_with_the_same_text_writes_the_include(
    make_theatre: MakeTheatre,
) -> None:  # R-9, S-12
    theatre = make_theatre({"troupe.yml": "b: !literal file:p.md\n", "p.md": "hello\n"})

    assert _set(theatre, "--include", "b", "file:p.md") == (0, "", "")

    assert _root(theatre).read_text(encoding="utf-8") == "b: file:p.md\n"
    assert _get(theatre, "b") == "hello\n"


def test_text_include_content_is_written_untagged(make_theatre: MakeTheatre) -> None:
    # S-11, US6-8: a text include's target gets file text, never a tag.
    theatre = make_theatre({"troupe.yml": "prompt: file:sys.md\n", "sys.md": "old\n"})

    assert _set(theatre, "prompt", "https://x") == (0, "", "")

    assert _root(theatre).read_text(encoding="utf-8") == "prompt: file:sys.md\n"
    assert (theatre / ".troupe" / "sys.md").read_text(encoding="utf-8") == "https://x"
