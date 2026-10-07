"""The read-only rule for remote content at both checkpoints (spec S-4, S-5; research R-7).

Checkpoint 1 is ``placement.place`` (an existing value from remote content, before the alias
rule); checkpoint 2 is ``apply.apply_set`` (a plan that would write a remote source). Trees are
loaded with ``troupe.loader.load`` from real files, with remote documents served by the
``remote`` fixture; the server's request log shows that nothing but ``GET`` is ever sent.
"""

from pathlib import Path

import pytest

from conftest import LOCAL_NO_PROXY
from remote_server import RemoteServer
from troupe.errors import WriteRefused
from troupe.loader import load
from troupe.paths import parse_path
from troupe.tree import Node
from troupe.values import parse_value
from troupe.writeback.apply import apply_set
from troupe.writeback.placement import (
    AddKeys,
    ConvertInclude,
    ReplaceScalar,
    place,
)

DASH = "—"


@pytest.fixture(autouse=True)
def _bypass_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    # The test server is local; a proxy configured in the environment must not intercept it.
    monkeypatch.setenv("NO_PROXY", LOCAL_NO_PROXY)
    monkeypatch.setenv("no_proxy", LOCAL_NO_PROXY)


def _config(tmp_path: Path, text: str) -> Path:
    config = tmp_path / "troupe.yml"
    config.write_text(text, encoding="utf-8")
    return config


def _refusal(config: Path, written: str, line: int, dotted: str) -> str:
    return (
        f"{dotted}: value comes from remote include {written} ({config.resolve()} line {line});"
        f" troupe does not change remote content {DASH} change that include line instead;"
        " no file changed"
    )


def _place_refused(root: Node, dotted: str, *, expand_alias: bool = False) -> str:
    with pytest.raises(WriteRefused) as caught:
        place(root, parse_path(dotted), dotted, expand_alias=expand_alias)
    assert caught.value.exit_code == 3
    return caught.value.message


def _set_refused(
    root: Node, dotted: str, value: str, *, in_include: bool = False, expand_alias: bool = False
) -> str:
    with pytest.raises(WriteRefused) as caught:
        apply_set(
            root,
            parse_path(dotted),
            dotted,
            parse_value(value),
            value,
            in_include=in_include,
            expand_alias=expand_alias,
        )
    assert caught.value.exit_code == 3
    return caught.value.message


def _methods(remote: RemoteServer) -> set[str]:
    return {request.method for request in remote.requests()}


# --- Checkpoint 1: existing values (place) -------------------------------------------------------


def test_existing_remote_scalar_is_refused_quoting_the_include_its_file_and_line(
    tmp_path: Path, remote: RemoteServer
) -> None:
    url = remote.serve("/team.yaml", "model: opus\n")
    config = _config(tmp_path, f"a: 1\nteam: {url}  # shared\n")

    message = _place_refused(load(config), "team.model")

    assert message == _refusal(config, url, 2, "team.model")
    assert _methods(remote) == {"GET"}


def test_quoted_include_string_is_quoted_exactly_as_written(
    tmp_path: Path, remote: RemoteServer
) -> None:
    url = remote.serve("/team.yaml", "model: opus\n")
    config = _config(tmp_path, f'team: "{url}"\n')

    message = _place_refused(load(config), "team.model")

    assert message == _refusal(config, f'"{url}"', 1, "team.model")


def test_value_from_a_remote_ref_is_refused_naming_the_ref_value(
    tmp_path: Path, remote: RemoteServer
) -> None:
    url = remote.serve("/coder.yaml", "temperature: 0.7\nmodel: gpt\n")
    config = _config(tmp_path, f"coder:\n  $ref: '{url}'\n  temperature: 0.3\n")

    message = _place_refused(load(config), "coder.model")

    assert message == _refusal(config, f"'{url}'", 2, "coder.model")


def test_local_override_of_a_remote_ref_is_replaced_in_the_local_file(
    tmp_path: Path, remote: RemoteServer
) -> None:  # US2-5: a value from a local override is local
    url = remote.serve("/coder.yaml", "temperature: 0.7\nmodel: gpt\n")
    config = _config(tmp_path, f"coder:\n  $ref: {url}\n  temperature: 0.3\n")

    placement = place(load(config), ["coder", "temperature"], "coder.temperature")

    assert isinstance(placement, ReplaceScalar)
    assert placement.node.value == 0.3
    assert placement.node.origin.file.path == config.resolve()


@pytest.mark.parametrize(
    ("text", "dotted", "line"),
    [
        ("team: {yaml}\n", "team", 1),  # a whole scalar-form remote YAML include
        ("a: 1\nprompt: {text}\n", "prompt", 2),  # a remote text include
        ("coder:\n  $ref: {yaml}\n  temperature: 0.3\n", "coder", 2),  # merged view, remote ref
        ("coder:\n  $ref: {yaml}\n", "coder", 2),  # mapping form without overrides
    ],
    ids=["scalar-form-include", "text-include", "merged-view", "ref-only"],
)
def test_whole_remote_include_or_merged_view_with_a_remote_ref_is_refused(
    tmp_path: Path, remote: RemoteServer, text: str, dotted: str, line: int
) -> None:
    yaml_url = remote.serve("/team.yaml", "model: opus\ntemperature: 0.7\n")
    text_url = remote.serve("/sys.md", "be terse\n")
    config = _config(tmp_path, text.format(yaml=yaml_url, text=text_url))
    written = text_url if dotted == "prompt" else yaml_url

    message = _place_refused(load(config), dotted)

    assert message == _refusal(config, written, line, dotted)


def test_value_from_a_nested_remote_include_names_the_outermost_include(
    tmp_path: Path, remote: RemoteServer
) -> None:
    inner = remote.serve("/inner.yaml", "deep: 1\n")
    outer = remote.serve("/outer.yaml", f"nested: {inner}\n")
    config = _config(tmp_path, f"team: {outer}\n")

    message = _place_refused(load(config), "team.nested.deep")

    assert message == _refusal(config, outer, 1, "team.nested.deep")
    assert inner not in message


def test_remote_content_reached_through_a_local_include_names_the_remote_include_line(
    tmp_path: Path, remote: RemoteServer
) -> None:
    url = remote.serve("/team.yaml", "model: opus\n")
    local = tmp_path / "agents.yaml"
    local.write_text(f"# shared team\nteam: {url}\n", encoding="utf-8")
    config = _config(tmp_path, "agents: file:agents.yaml\n")

    message = _place_refused(load(config), "agents.team.model")

    assert message == _refusal(local, url, 2, "agents.team.model")


@pytest.mark.parametrize("expand_alias", [False, True], ids=["plain", "expand-alias"])
def test_alias_inside_remote_content_gets_the_remote_refusal_before_the_alias_rule(
    tmp_path: Path, remote: RemoteServer, expand_alias: bool
) -> None:
    url = remote.serve("/team.yaml", "base: &b {model: opus}\ncoder: *b\n")
    config = _config(tmp_path, f"team: {url}\n")
    root = load(config)

    for dotted in ("team.coder.model", "team.coder"):
        message = _place_refused(root, dotted, expand_alias=expand_alias)
        assert message == _refusal(config, url, 1, dotted)
        assert "--expand-alias" not in message


def test_new_key_under_a_scalar_form_remote_include_converts_it_in_the_local_file(
    tmp_path: Path, remote: RemoteServer
) -> None:  # S-5: not refused at checkpoint 1
    url = remote.serve("/team.yaml", "model: opus\n")
    config = _config(tmp_path, f"team: {url}\n")

    placement = place(load(config), ["team", "temperature"], "team.temperature")

    assert isinstance(placement, ConvertInclude)
    assert placement.include.origin.file.path == config.resolve()
    assert placement.keys == ["temperature"]


def test_new_key_under_a_mapping_form_remote_include_goes_into_the_local_holder(
    tmp_path: Path, remote: RemoteServer
) -> None:  # S-5
    url = remote.serve("/coder.yaml", "temperature: 0.7\n")
    config = _config(tmp_path, f"coder:\n  $ref: {url}\n  temperature: 0.3\n")

    placement = place(load(config), ["coder", "top_p"], "coder.top_p")

    assert isinstance(placement, AddKeys)
    assert placement.mapping.origin.file.path == config.resolve()
    assert placement.keys == ["top_p"]


# --- Checkpoint 2: the files a plan would write (apply_set) --------------------------------------


@pytest.mark.parametrize(
    ("dotted", "value", "flags"),
    [
        ("team.tools.2", "grep", {}),  # a list append in remote content
        ("team.agents.0.extra", "1", {}),  # a new key inside an item of a remote list
        ("team.newkey", "1", {"in_include": True}),  # --in-include into remote content
        ("team.coder.extra", "1", {"expand_alias": True}),  # an --expand-alias copy
    ],
    ids=["list-append", "key-in-list-item", "in-include", "expand-alias-copy"],
)
def test_plan_that_would_write_remote_content_is_refused_quoting_the_include(
    tmp_path: Path, remote: RemoteServer, dotted: str, value: str, flags: dict[str, bool]
) -> None:
    url = remote.serve(
        "/team.yaml",
        "tools: [read, write]\nagents:\n  - name: a\nbase: &b {model: opus}\ncoder: *b\n",
    )
    config = _config(tmp_path, f"team: {url}\n")
    before = config.read_bytes()

    message = _set_refused(
        load(config),
        dotted,
        value,
        in_include=flags.get("in_include", False),
        expand_alias=flags.get("expand_alias", False),
    )

    assert message == _refusal(config, url, 1, dotted)
    assert config.read_bytes() == before
    assert _methods(remote) == {"GET"}


def test_new_key_below_an_alias_in_remote_content_is_refused_by_the_alias_rule(
    tmp_path: Path, remote: RemoteServer
) -> None:  # S-5: the step-6 alias rule applies to new keys under remote content
    url = remote.serve("/team.yaml", "base: &b {model: opus}\ncoder: *b\n")
    config = _config(tmp_path, f"team: {url}\n")

    message = _set_refused(load(config), "team.coder.extra", "1")

    assert message.startswith("team.coder.extra: team.coder is the alias *b in ")
    assert "--expand-alias" in message
