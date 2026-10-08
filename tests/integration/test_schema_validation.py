"""User Story 5, load part: the configuration matches its schema (real CLI; spec S-8, FR-009).

When ``.troupe/troupe.schema.json`` exists, every command that loads the configuration validates
the resolved configuration (remote content included) against it as JSON Schema 2020-12 and exits
4 naming the schema file and the first failing path; an unreadable or invalid schema exits 4
naming the schema file. The load happens before the history is opened, so a failure records
nothing. Scenario 3 (``set``) belongs to the ``set`` tests. The number in a test's comment is the
US5 acceptance scenario it covers.
"""

import json
from pathlib import Path

import pytest
from test_show_sources import CONTRACT_FILES, CONTRACT_OUTPUT

from conftest import HISTORY_PREFIX, MakeTheatre, all_files, core, history_events, run_cli, snapshot
from remote_server import RemoteServer

MODEL_IS_A_STRING = {"properties": {"model": {"type": "string"}}}
LOADING_COMMANDS = {
    "get": ("get", "name"),
    "show": ("show",),
    "set": ("set", "name", "other"),
    "history": ("history",),
}


def _cli(theatre: Path, *args: str) -> tuple[int, str, str]:
    result = run_cli("config", *args, "--theatre", str(theatre))
    return result.code, result.out, result.err


def _schema(document: object) -> str:
    return json.dumps(document, indent=2) + "\n"


def _schema_file(theatre: Path) -> Path:
    return (theatre / ".troupe" / "troupe.schema.json").resolve()


def _has_history(theatre: Path) -> bool:
    return any(rel.startswith(HISTORY_PREFIX) for rel in all_files(theatre))


@pytest.mark.parametrize("command", LOADING_COMMANDS.values(), ids=LOADING_COMMANDS.keys())
def test_configuration_not_matching_the_schema_exits_4_naming_schema_and_path(
    make_theatre: MakeTheatre, command: tuple[str, ...]
) -> None:  # 1 (a local value)
    theatre = make_theatre(
        {"troupe.yml": "name: demo\nmodel: 5\n", "troupe.schema.json": _schema(MODEL_IS_A_STRING)}
    )

    assert _cli(theatre, *command) == (
        4,
        "",
        f"troupe: configuration does not match schema {_schema_file(theatre)} at model: "
        "5 is not of type 'string'\n",
    )


def test_value_from_a_remote_include_not_matching_the_schema_exits_4(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # 1 (a value in a remote file)
    url = remote.serve("/team.yaml", "model: 5\n")
    schema = {"properties": {"team": {"properties": {"model": {"type": "string"}}}}}
    theatre = make_theatre({"troupe.yml": f"team: {url}\n", "troupe.schema.json": _schema(schema)})

    assert _cli(theatre, "get", "team") == (
        4,
        "",
        f"troupe: configuration does not match schema {_schema_file(theatre)} at team.model: "
        "5 is not of type 'string'\n",
    )


def test_first_failure_in_path_order_is_reported(make_theatre: MakeTheatre) -> None:  # 1
    schema = {"additionalProperties": {"type": "string"}, "required": ["zzz"]}
    theatre = make_theatre({"troupe.yml": "b: 1\na: [1]\n", "troupe.schema.json": _schema(schema)})

    assert _cli(theatre, "show") == (
        4,
        "",
        f"troupe: configuration does not match schema {_schema_file(theatre)} at (root): "
        "'zzz' is a required property\n",
    )


INVALID_SCHEMAS = {
    "not-json": (
        "{not json",
        "not valid JSON: Expecting property name enclosed in double quotes at line 1 column 2",
    ),
    "nan": ('{"maximum": NaN}', "not valid JSON: NaN/Infinity are not JSON"),
    "not-utf8": (b'{"title": "\xff"}', "not valid UTF-8 at byte 11"),
    "wrong-dialect": (
        '{"$schema": "http://json-schema.org/draft-07/schema#"}',
        "$schema must be https://json-schema.org/draft/2020-12/schema, "
        "got http://json-schema.org/draft-07/schema#",
    ),
    "meta-schema-failure": (
        '{"type": 5}',
        "not a valid JSON Schema 2020-12: 5 is not valid under any of the given schemas at /type",
    ),
    "remote-ref": (
        '{"properties": {"model": {"$ref": "https://example.com/s.json"}}}',
        "$ref https://example.com/s.json at /properties/model/$ref is not a fragment within "
        "this file (references to other documents are not fetched)",
    ),
}


@pytest.mark.parametrize("command", LOADING_COMMANDS.values(), ids=LOADING_COMMANDS.keys())
@pytest.mark.parametrize(("text", "reason"), INVALID_SCHEMAS.values(), ids=INVALID_SCHEMAS.keys())
def test_invalid_schema_files_exit_4_naming_the_schema_file(
    make_theatre: MakeTheatre, text: str | bytes, reason: str, command: tuple[str, ...]
) -> None:  # 2
    theatre = make_theatre({"troupe.yml": "name: demo\n", "troupe.schema.json": text})

    assert _cli(theatre, *command) == (
        4,
        "",
        f"troupe: cannot load schema {_schema_file(theatre)}: {reason}\n",
    )


def test_invalid_schema_is_reported_before_fetching_anything(
    make_theatre: MakeTheatre, remote: RemoteServer
) -> None:  # 2: the schema is read first, because it decides what is fetched
    url = remote.serve("/team.yaml", "model: opus\n")
    theatre = make_theatre({"troupe.yml": f"team: {url}\n", "troupe.schema.json": "[]"})

    assert _cli(theatre, "get", "team.model") == (
        4,
        "",
        f"troupe: cannot load schema {_schema_file(theatre)}: "
        "the schema must be a JSON object or boolean\n",
    )
    assert remote.requests() == []


def test_format_uri_is_not_asserted(make_theatre: MakeTheatre) -> None:  # 4
    schema = {"properties": {"webhook": {"type": "string", "format": "uri"}}}
    theatre = make_theatre(
        {"troupe.yml": "webhook: not a uri\n", "troupe.schema.json": _schema(schema)}
    )

    assert _cli(theatre, "get", "webhook") == (0, "not a uri\n", "")
    assert _cli(theatre, "show") == (0, "webhook: not a uri\n", "")


@pytest.mark.parametrize("schema", [None, True, {}], ids=["no-schema-file", "true", "empty"])
def test_without_schema_file_behaviour_is_unchanged(
    make_theatre: MakeTheatre, schema: object
) -> None:  # 5 (step-1 contract example; an accept-all schema changes nothing either)
    files = dict(CONTRACT_FILES)
    if schema is not None:
        files["troupe.schema.json"] = _schema(schema)
    theatre = make_theatre(files)

    assert _cli(theatre, "show", "--sources") == (0, CONTRACT_OUTPUT, "")
    assert _cli(theatre, "get", "prompt") == (0, "Be brief.\n", "")
    assert _cli(theatre, "get", "server.port") == (0, "8080\n", "")
    assert _cli(theatre, "show", "tools") == (0, "- a\n- b\n", "")
    assert core(history_events(theatre)) == [
        {"seq": 1, "op": "import", "path": "name", "old": None, "new": "demo"},
        {"seq": 2, "op": "import", "path": "server.port", "old": None, "new": 8080},
        {"seq": 3, "op": "import", "path": "tools.0", "old": None, "new": "a"},
        {"seq": 4, "op": "import", "path": "tools.1", "old": None, "new": "b"},
        {"seq": 5, "op": "import", "path": "prompt", "old": None, "new": "Be brief.\n"},
    ]


@pytest.mark.parametrize("command", LOADING_COMMANDS.values(), ids=LOADING_COMMANDS.keys())
def test_validation_failure_records_nothing_and_creates_no_history(
    make_theatre: MakeTheatre, command: tuple[str, ...]
) -> None:  # session order: load (and validate) before the history is opened
    theatre = make_theatre(
        {"troupe.yml": "name: demo\nmodel: 5\n", "troupe.schema.json": _schema(MODEL_IS_A_STRING)}
    )
    before = snapshot(theatre)

    assert _cli(theatre, *command) == (
        4,
        "",
        f"troupe: configuration does not match schema {_schema_file(theatre)} at model: "
        "5 is not of type 'string'\n",
    )

    assert snapshot(theatre) == before
    assert not _has_history(theatre)


def test_hand_edit_breaking_the_schema_is_not_recorded_until_fixed(
    make_theatre: MakeTheatre,
) -> None:  # session order, imported theatre
    theatre = make_theatre(
        {"troupe.yml": "model: gpt\n", "troupe.schema.json": _schema(MODEL_IS_A_STRING)}
    )
    imported = history_events(theatre)
    (theatre / ".troupe" / "troupe.yml").write_text("model: 5\n")

    assert _cli(theatre, "get", "model")[0] == 4
    (theatre / ".troupe" / "troupe.yml").write_text("model: opus\n")
    assert _cli(theatre, "get", "model") == (0, "opus\n", "")

    assert core(history_events(theatre)) == [
        *core(imported),
        {"seq": 2, "op": "set", "path": "model", "old": "gpt", "new": "opus"},
    ]
