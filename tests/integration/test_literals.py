"""User Story 4: URL settings stay strings (real CLI, real HTTP; spec S-7, S-10, S-3).

A string is a literal when tagged ``!literal`` or when the schema, walked through
``properties``, ``additionalProperties`` and ``items`` only, marks its path ``"format": "uri"``.
Include-looking strings point at the ``remote`` test server, whose request log proves that a
literal is never fetched, and that a string the walk does not reach is an include. The number
in a test's comment is the US4 acceptance scenario it covers.
"""

import json
from pathlib import Path

import pytest

from conftest import MakeTheatre, run_cli
from remote_server import RemoteServer


def _cli(theatre: Path, *args: str) -> tuple[int, str, str]:
    result = run_cli("config", *args, "--theatre", str(theatre))
    return result.code, result.out, result.err


def _schema(document: object) -> str:
    return json.dumps(document, indent=2) + "\n"


def test_schema_uri_setting_is_a_literal_and_is_not_fetched(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # 1
    url = remote.serve("/notify", "a body nobody should read\n")
    theatre = make_theatre(
        {
            "troupe.yml": f"webhook: {url}\n",
            "troupe.schema.json": _schema({"properties": {"webhook": {"format": "uri"}}}),
        }
    )

    assert _cli(theatre, "get", "webhook") == (0, f"{url}\n", "")
    assert _cli(theatre, "show") == (0, f"webhook: {url}\n", "")
    assert remote.requests() == []


def test_uri_through_additional_properties_and_items_is_literal(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # 2
    first, second = remote.url("/a.yaml"), remote.url("/b.md")
    schema = {
        "properties": {
            "agents": {
                "additionalProperties": {
                    "properties": {"urls": {"items": {"format": "uri"}}},
                }
            }
        }
    }
    theatre = make_theatre(
        {
            "troupe.yml": f"agents:\n  coder:\n    urls:\n      - {first}\n      - {second}\n",
            "troupe.schema.json": _schema(schema),
        }
    )

    assert _cli(theatre, "get", "agents.coder.urls.0") == (0, f"{first}\n", "")
    assert _cli(theatre, "get", "agents.coder.urls.1") == (0, f"{second}\n", "")
    assert remote.requests() == []


NOT_FOLLOWED = {
    "ref": {
        "properties": {"webhook": {"$ref": "#/$defs/uri"}},
        "$defs": {"uri": {"format": "uri"}},
    },
    "allOf": {"properties": {"webhook": {"allOf": [{"format": "uri"}]}}},
    "patternProperties": {"patternProperties": {"^web": {"format": "uri"}}},
}


@pytest.mark.parametrize("schema", NOT_FOLLOWED.values(), ids=NOT_FOLLOWED.keys())
def test_uri_only_through_ref_allof_or_pattern_properties_is_an_include(
    make_theatre: MakeTheatre, remote: RemoteServer, schema: object
) -> None:  # 3
    url = remote.serve("/notify", "served text\n")
    theatre = make_theatre(
        {"troupe.yml": f"webhook: {url}\n", "troupe.schema.json": _schema(schema)}
    )

    assert _cli(theatre, "get", "webhook") == (0, "served text\n", "")
    assert [r.path for r in remote.requests()] == ["/notify"]


def test_literal_tagged_strings_show_without_the_tag(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # 4
    url = remote.url("/team.yaml")
    theatre = make_theatre(
        {
            "troupe.yml": (
                "note: !literal file:readme.md\n"
                "docs: !literal https://x.example/y\n"
                f"team: !literal {url}\n"
                "count: !literal 5\n"
            )
        }
    )

    assert _cli(theatre, "show") == (
        0,
        f"note: file:readme.md\ndocs: https://x.example/y\nteam: {url}\ncount: '5'\n",
        "",
    )
    assert _cli(theatre, "get", "note") == (0, "file:readme.md\n", "")
    assert _cli(theatre, "get", "count") == (0, "5\n", "")
    assert remote.requests() == []


def test_literal_string_is_validated_as_a_string(make_theatre: MakeTheatre) -> None:  # 4, S-8
    theatre = make_theatre(
        {
            "troupe.yml": "n: !literal 5\n",
            "troupe.schema.json": _schema({"properties": {"n": {"type": "string"}}}),
        }
    )

    assert _cli(theatre, "get", "n") == (0, "5\n", "")


BAD_TAGS = {
    "literal-on-mapping": (
        "a: 1\nm: !literal\n  k: v\n",
        "cannot parse {file}: !literal applies only to scalars at line 2",
    ),
    "literal-on-flow-list": (
        "a: 1\nl: !literal [x, y]\n",
        "cannot parse {file}: !literal applies only to scalars at line 2",
    ),
    "other-tag": (
        "a: 1\nb: !str file:x.md\n",
        "cannot parse {file}: tags are not supported at line 2",
    ),
    "literal-on-ref-value": (
        "a: 1\ncoder:\n  $ref: !literal file:coder.yaml\n",
        "cannot load {file}: coder.$ref must be an include string, not !literal (line 3)",
    ),
}


@pytest.mark.parametrize(("text", "message"), BAD_TAGS.values(), ids=BAD_TAGS.keys())
@pytest.mark.parametrize("command", [("get", "a"), ("show",), ("history",)])
def test_literal_on_a_mapping_list_or_ref_and_other_tags_exit_4_naming_the_file(
    make_theatre: MakeTheatre, text: str, message: str, command: tuple[str, ...]
) -> None:  # 5
    theatre = make_theatre({"troupe.yml": text, "coder.yaml": "model: gpt\n"})
    file = (theatre / ".troupe" / "troupe.yml").resolve()

    assert _cli(theatre, *command) == (4, "", f"troupe: {message.format(file=file)}\n")


def test_anchored_literal_is_literal_through_its_aliases(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # edge case: S-7, the anchored node decides
    hook, tagged = remote.url("/hook"), remote.url("/tagged.yaml")
    theatre = make_theatre(
        {
            "troupe.yml": (
                f"hooks:\n  main: &h {hook}\n"
                f"elsewhere: *h\n"
                f"list: [*h]\n"
                f"keep: &t !literal {tagged}\n"
                f"copy: *t\n"
            ),
            "troupe.schema.json": _schema(
                {"properties": {"hooks": {"properties": {"main": {"format": "uri"}}}}}
            ),
        }
    )

    assert _cli(theatre, "get", "elsewhere") == (0, f"{hook}\n", "")
    assert _cli(theatre, "get", "list.0") == (0, f"{hook}\n", "")
    assert _cli(theatre, "get", "copy") == (0, f"{tagged}\n", "")
    assert remote.requests() == []
