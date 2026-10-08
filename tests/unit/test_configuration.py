"""``troupe.configuration``: the one "loaded and valid" entry point (research R-10, spec S-8).

Each test writes a real theatre under ``tmp_path`` (configuration, include files and, where
needed, ``troupe.schema.json``) and loads it with ``load_configuration``. Remote includes come
from the ``remote`` test server, whose request log shows what was fetched.
"""

import json
import math
import warnings
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from conftest import LOCAL_NO_PROXY
from remote_server import RemoteServer
from troupe import yamlout
from troupe.configuration import Loaded, load_configuration, to_data, violation
from troupe.errors import LoadError
from troupe.location import Url
from troupe.schema import load_schema
from troupe.theatre import Theatre, locate


@pytest.fixture(autouse=True)
def _bypass_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_PROXY", LOCAL_NO_PROXY)
    monkeypatch.setenv("no_proxy", LOCAL_NO_PROXY)


def _theatre(tmp_path: Path, files: dict[str, str], schema: object = None) -> Theatre:
    """Write ``.troupe/<rel>`` for every file (and the schema, if given); locate the theatre."""
    state_dir = tmp_path / ".troupe"
    for rel, content in files.items():
        target = state_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8"))
    if schema is not None:
        (state_dir / "troupe.schema.json").write_text(json.dumps(schema), encoding="utf-8")
    return locate(tmp_path)


def _shown(loaded: Loaded) -> object:
    """What ``show`` prints for the whole configuration, read back by a YAML 1.2 reader."""
    reader = YAML(typ="safe", pure=True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return reader.load(yamlout.to_text(yamlout.render(loaded.tree), None))


# --- to_data: the instance validated is what every read sees ------------------------------------

READ_VIEWS = {
    "merged-override": (
        {
            "troupe.yml": "coder:\n  $ref: file:coder.yaml\n  temperature: 0.3\n",
            "coder.yaml": "model: gpt\ntemperature: 0.7\n",
        },
        {"coder": {"model": "gpt", "temperature": 0.3}},
    ),
    "aliases-and-merge-key": (
        {
            "troupe.yml": (
                "base: &b\n  model: gpt\n  n: 1\n"
                "coder:\n  <<: *b\n  n: 2\n"
                "copy: *b\n"
                "tools: &t [a, b]\n"
                "more: *t\n"
            )
        },
        {
            "base": {"model": "gpt", "n": 1},
            "coder": {"model": "gpt", "n": 2},
            "copy": {"model": "gpt", "n": 1},
            "tools": ["a", "b"],
            "more": ["a", "b"],
        },
    ),
    "text-and-yaml-includes": (
        {
            "troupe.yml": "prompt: file:sys.md\nserver: file:server.yml\n",
            "sys.md": "Be brief.\r\nNo more.\n",
            "server.yml": "port: 8080\nhosts: [x, y]\n",
        },
        {"prompt": "Be brief.\r\nNo more.\n", "server": {"port": 8080, "hosts": ["x", "y"]}},
    ),
    "literals": (
        {
            "troupe.yml": (
                "note: !literal file:readme.md\n"
                "docs: !literal https://x.example/y\n"
                "n: !literal 5\n"
                "plain: 5\n"
            )
        },
        {"note": "file:readme.md", "docs": "https://x.example/y", "n": "5", "plain": 5},
    ),
}


@pytest.mark.parametrize(("files", "expected"), READ_VIEWS.values(), ids=READ_VIEWS.keys())
def test_to_data_is_the_resolved_configuration_that_show_prints(
    tmp_path: Path, files: dict[str, str], expected: object
) -> None:
    loaded = load_configuration(_theatre(tmp_path, files))

    data = to_data(loaded.tree)

    assert data == expected
    assert data == _shown(loaded)


def test_to_data_passes_non_finite_floats_through(tmp_path: Path) -> None:
    loaded = load_configuration(_theatre(tmp_path, {"troupe.yml": "a: .inf\nb: .nan\n"}))

    data = to_data(loaded.tree)

    assert isinstance(data, dict)
    assert data["a"] == math.inf
    assert isinstance(data["b"], float) and math.isnan(data["b"])


def test_to_data_reads_remote_includes_as_fetched(tmp_path: Path, remote: RemoteServer) -> None:
    url = remote.serve("/team.yaml", "model: opus\nprompt: file:sys.md\n")
    remote.serve("/sys.md", "Hi.\n")

    loaded = load_configuration(_theatre(tmp_path, {"troupe.yml": f"team: {url}\n"}))

    assert to_data(loaded.tree) == {"team": {"model": "opus", "prompt": "Hi.\n"}}


# --- validation ---------------------------------------------------------------------------------


def test_without_schema_file_nothing_is_validated(tmp_path: Path) -> None:
    # Every value of every type loads: there is nothing to validate against.
    theatre = _theatre(tmp_path, {"troupe.yml": "model: 5\nlist: [1, a, null]\n"})

    loaded = load_configuration(theatre)

    assert loaded.schema is None
    assert to_data(loaded.tree) == {"model": 5, "list": [1, "a", None]}


def test_matching_configuration_loads_with_its_schema(tmp_path: Path) -> None:
    schema = {"properties": {"model": {"type": "string"}}}
    theatre = _theatre(tmp_path, {"troupe.yml": "model: gpt\n"}, schema)

    loaded = load_configuration(theatre)

    assert loaded.schema is not None
    assert loaded.schema.path == theatre.state_dir / "troupe.schema.json"
    assert loaded.schema.document == schema


def test_violation_raises_load_error_naming_schema_file_and_path(tmp_path: Path) -> None:
    schema = {"properties": {"agents": {"additionalProperties": {"type": "string"}}}}
    theatre = _theatre(tmp_path, {"troupe.yml": "agents:\n  coder: ok\n  tester: 5\n"}, schema)

    with pytest.raises(LoadError) as caught:
        load_configuration(theatre)

    schema_file = theatre.state_dir / "troupe.schema.json"
    assert caught.value.exit_code == 4
    assert caught.value.message == (
        f"configuration does not match schema {schema_file} at agents.tester: "
        "5 is not of type 'string'"
    )


def test_violation_returns_the_first_failure_or_none(tmp_path: Path) -> None:
    theatre = _theatre(tmp_path, {"troupe.yml": "a: 1\nb: x\n"})
    tree = load_configuration(theatre).tree
    (theatre.state_dir / "troupe.schema.json").write_text(
        json.dumps({"properties": {"a": {"type": "string"}, "b": {"type": "integer"}}})
    )
    strict = load_schema(theatre.state_dir)
    (theatre.state_dir / "troupe.schema.json").write_text(json.dumps({"type": "object"}))
    loose = load_schema(theatre.state_dir)
    assert strict is not None and loose is not None

    found = violation(tree, strict)

    assert found is not None
    assert (found.path, found.message) == ("a", "1 is not of type 'string'")
    assert violation(tree, loose) is None


def test_validation_sees_literal_strings_and_text_includes_as_strings(tmp_path: Path) -> None:
    schema = {"additionalProperties": {"type": "string", "minLength": 2}}
    files = {"troupe.yml": "n: !literal 55\nprompt: file:p.md\n", "p.md": "hello\n"}

    loaded = load_configuration(_theatre(tmp_path, files, schema))

    assert to_data(loaded.tree) == {"n": "55", "prompt": "hello\n"}


def test_invalid_schema_is_refused_before_the_configuration_is_read(tmp_path: Path) -> None:
    # The configuration itself cannot load either; the schema error proves the schema came first.
    theatre = _theatre(tmp_path, {"troupe.yml": "a: file:missing.md\n"})
    (theatre.state_dir / "troupe.schema.json").write_text("{not json")

    with pytest.raises(LoadError) as caught:
        load_configuration(theatre)

    assert caught.value.message.startswith(
        f"cannot load schema {theatre.state_dir / 'troupe.schema.json'}: not valid JSON"
    )


def test_schema_decides_literals_so_a_uri_string_is_not_fetched(
    tmp_path: Path, remote: RemoteServer
) -> None:
    url = remote.serve("/hook", "never fetched\n")
    schema = {"properties": {"webhook": {"format": "uri"}}}

    loaded = load_configuration(_theatre(tmp_path, {"troupe.yml": f"webhook: {url}\n"}, schema))

    assert to_data(loaded.tree) == {"webhook": url}
    assert remote.requests() == []


def test_overrides_replace_file_texts(tmp_path: Path) -> None:
    theatre = _theatre(tmp_path, {"troupe.yml": "a: 1\n"})

    loaded = load_configuration(theatre, {theatre.config_file.resolve(): "a: 2\n"})

    assert to_data(loaded.tree) == {"a": 2}


# --- fetched: one snapshot of the remote content per command ------------------------------------


def test_fetched_is_filled_and_returned_as_the_same_dict(
    tmp_path: Path, remote: RemoteServer
) -> None:
    url = remote.serve("/team.yaml", "model: opus\n")
    theatre = _theatre(tmp_path, {"troupe.yml": f"team: {url}\nsame: {url}\n"})
    fetched: dict[Url, str] = {}

    loaded = load_configuration(theatre, fetched=fetched)

    assert loaded.fetched is fetched
    assert fetched == {Url(url): "model: opus\n"}
    assert [r.path for r in remote.requests()] == ["/team.yaml"]


def test_fetched_is_reused_by_a_later_load_without_fetching_again(
    tmp_path: Path, remote: RemoteServer
) -> None:
    url = remote.serve("/team.yaml", "model: opus\n")
    theatre = _theatre(tmp_path, {"troupe.yml": f"team: {url}\n"})
    first = load_configuration(theatre)
    remote.serve("/team.yaml", "model: changed\n")

    again = load_configuration(theatre, fetched=first.fetched)

    assert to_data(again.tree) == {"team": {"model": "opus"}}
    assert again.fetched is first.fetched
    assert len(remote.requests()) == 1


def test_fetched_defaults_to_a_new_dict_per_call(tmp_path: Path, remote: RemoteServer) -> None:
    url = remote.serve("/team.yaml", "model: opus\n")
    theatre = _theatre(tmp_path, {"troupe.yml": f"team: {url}\n"})

    first, second = load_configuration(theatre), load_configuration(theatre)

    assert first.fetched is not second.fetched
    assert first.fetched == second.fetched == {Url(url): "model: opus\n"}
    assert len(remote.requests()) == 2


def test_failed_fetch_is_a_load_error_naming_the_url(tmp_path: Path, remote: RemoteServer) -> None:
    url = remote.url("/missing.yaml")
    theatre = _theatre(tmp_path, {"troupe.yml": f"team: {url}\n"})

    with pytest.raises(LoadError) as caught:
        load_configuration(theatre)

    assert caught.value.exit_code == 4
    assert caught.value.message == (
        f"cannot fetch {url} (included from {theatre.config_file}, at team): HTTP 404 Not Found"
    )
