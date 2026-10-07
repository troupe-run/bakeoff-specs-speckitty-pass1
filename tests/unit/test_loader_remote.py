"""The loader with remote includes, against a real local HTTP server (spec S-1 to S-3; R-3, R-10).

Each test writes real files under ``tmp_path``, serves remote documents from the ``remote``
fixture and loads with ``troupe.loader.load``; the server's request log shows what was fetched.
"""

from pathlib import Path

import pytest

from conftest import LOCAL_NO_PROXY
from remote_server import RemoteServer
from troupe import loader
from troupe.errors import LoadError
from troupe.leaves import flatten
from troupe.loader import load
from troupe.location import Url
from troupe.paths import lookup, unwrap
from troupe.tree import (
    AliasNode,
    MappingNode,
    MergedMapping,
    Node,
    ScalarNode,
    SourceFile,
    TextInclude,
    YamlInclude,
)


@pytest.fixture(autouse=True)
def _bypass_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    # The test server is local; a proxy configured in the environment must not intercept it.
    monkeypatch.setenv("NO_PROXY", LOCAL_NO_PROXY)
    monkeypatch.setenv("no_proxy", LOCAL_NO_PROXY)


def _config(tmp_path: Path, text: str, files: dict[str, str] | None = None) -> Path:
    for rel, content in (files or {}).items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    config = tmp_path / "troupe.yml"
    config.write_text(text, encoding="utf-8")
    return config


def _at(root: Node, dotted: str) -> Node:
    """The node at ``dotted`` as found (includes and aliases not unwrapped at the end)."""
    return lookup(root, dotted.split("."), dotted)


def _paths(remote: RemoteServer) -> list[str]:
    return [request.path for request in remote.requests()]


def _load_error(config: Path) -> LoadError:
    with pytest.raises(LoadError) as caught:
        load(config)
    return caught.value


def test_remote_yaml_include_embeds_its_content(tmp_path: Path, remote: RemoteServer) -> None:
    url = remote.serve("/team.yaml", "model: opus\nlimits:\n  tokens: 8\n")
    config = _config(tmp_path, f"team: {url}\n")

    root = load(config)

    include = _at(root, "team")
    assert isinstance(include, YamlInclude)
    assert include.target.path == Url(url)
    assert include.origin.source == url
    assert flatten(root) == {"team.model": "opus", "team.limits.tokens": 8}
    assert _paths(remote) == ["/team.yaml"]


def test_remote_text_include_is_its_body_exactly(tmp_path: Path, remote: RemoteServer) -> None:
    body = "\ufeffline 1\r\nline 2\n"
    url = remote.serve("/prompts/sys.md", body)

    root = load(_config(tmp_path, f"prompt: {url}\n"))

    include = _at(root, "prompt")
    assert isinstance(include, TextInclude)
    assert include.target.text == body
    assert flatten(root) == {"prompt": body}


def test_remote_text_include_with_query_is_text_or_yaml_by_url_path(
    tmp_path: Path, remote: RemoteServer
) -> None:
    yaml_url = remote.serve("/t.yaml", "k: v\n") + "?v=1"
    text_url = remote.serve("/t.md", "k: v\n") + "?x.yaml"

    root = load(_config(tmp_path, f"y: {yaml_url}\nt: {text_url}\n"))

    assert isinstance(_at(root, "y"), YamlInclude)
    assert isinstance(_at(root, "t"), TextInclude)
    assert flatten(root) == {"y.k": "v", "t": "k: v\n"}
    assert _paths(remote) == ["/t.yaml?v=1", "/t.md?x.yaml"]


def test_ref_form_with_remote_include_and_overrides_merges(
    tmp_path: Path, remote: RemoteServer
) -> None:
    url = remote.serve("/coder.yaml", "model: opus\ntemperature: 0.7\n")
    config = _config(tmp_path, f"coder:\n  $ref: {url}\n  temperature: 0.3\n")

    root = load(config)

    merged = _at(root, "coder")
    assert isinstance(merged, MergedMapping)
    assert merged.ref is not None and merged.ref.target.path == Url(url)
    assert flatten(root) == {"coder.model": "opus", "coder.temperature": 0.3}


def test_ref_form_without_overrides_is_the_remote_include_itself(
    tmp_path: Path, remote: RemoteServer
) -> None:
    url = remote.serve("/coder.yaml", "model: opus\n")

    include = _at(load(_config(tmp_path, f"coder:\n  $ref: {url}\n")), "coder")

    assert isinstance(include, YamlInclude)
    assert include.holder is not None


def test_overrides_on_a_remote_text_include_are_refused(
    tmp_path: Path, remote: RemoteServer
) -> None:
    url = remote.serve("/p.md", "text\n")
    config = _config(tmp_path, f"p:\n  $ref: {url}\n  extra: 1\n")

    assert _load_error(config).message == (
        f"cannot load {config}: p: overrides need a YAML include, but {url} is not a .yml/.yaml"
        " file"
    )


def test_file_include_inside_remote_content_resolves_against_the_url(
    tmp_path: Path, remote: RemoteServer
) -> None:
    url = remote.serve("/a/team.yaml", "prompt: file:prompts/sys.md\n")
    remote.serve("/a/prompts/sys.md", "be brief\n")

    root = load(_config(tmp_path, f"team: {url}\n"))

    prompt = _at(root, "team.prompt")
    assert isinstance(prompt, TextInclude)
    assert prompt.target.path == Url(remote.url("/a/prompts/sys.md"))
    assert flatten(root) == {"team.prompt": "be brief\n"}
    assert "/a/prompts/sys.md" in _paths(remote)


def test_nested_remote_include_from_remote_content(tmp_path: Path, remote: RemoteServer) -> None:
    inner = remote.serve("/inner.yaml", "x: 1\n")
    outer = remote.serve("/outer.yaml", f"inner: {inner}\ny: 2\n")

    root = load(_config(tmp_path, f"team: {outer}\n"))

    assert flatten(root) == {"team.inner.x": 1, "team.y": 2}
    nested = _at(root, "team.inner")
    assert isinstance(nested, YamlInclude)
    assert nested.origin.file.path == Url(outer)
    assert nested.target.remote


def test_url_cycle_is_refused_naming_the_urls(tmp_path: Path, remote: RemoteServer) -> None:
    a, b = remote.url("/a.yaml"), remote.url("/b.yaml")
    remote.serve("/a.yaml", f"b: {b}\n")
    remote.serve("/b.yaml", f"a: {a}\n")
    config = _config(tmp_path, f"top: {a}\n")

    error = _load_error(config)

    assert error.exit_code == 4
    assert error.message == f"include cycle at top.b.a: {a} -> {b} -> {a}"


def test_relative_url_cycle_is_detected_on_the_resolved_url(
    tmp_path: Path, remote: RemoteServer
) -> None:
    a = remote.serve("/d/a.yaml", "again: file:a.yaml\n")

    error = _load_error(_config(tmp_path, f"top: {a}\n"))

    assert error.message == f"include cycle at top.again: {a} -> {a}"


def test_same_url_included_twice_is_fetched_once_per_load(
    tmp_path: Path, remote: RemoteServer
) -> None:
    url = remote.serve("/team.yaml", "model: opus\n")

    root = load(_config(tmp_path, f"x: {url}\ny:\n  - {url}\n"))

    first, second = _at(root, "x"), _at(root, "y.0")
    assert isinstance(first, YamlInclude) and isinstance(second, YamlInclude)
    assert first.target is second.target  # one SourceFile per location per load
    assert _paths(remote) == ["/team.yaml"]


def test_fetched_cache_is_reused_across_loads(tmp_path: Path, remote: RemoteServer) -> None:
    url = remote.serve("/team.yaml", "model: opus\n")
    config = _config(tmp_path, f"team: {url}\n")
    fetched: dict[Url, str] = {}

    first = load(config, fetched=fetched)
    second = load(config, fetched=fetched)

    assert _paths(remote) == ["/team.yaml"]
    assert fetched == {Url(url): "model: opus\n"}
    assert flatten(first) == flatten(second) == {"team.model": "opus"}
    first_include, second_include = _at(first, "team"), _at(second, "team")
    assert isinstance(first_include, YamlInclude) and isinstance(second_include, YamlInclude)
    assert first_include.target is not second_include.target  # SourceFiles are per load


def test_without_a_fetched_map_every_load_fetches_again(
    tmp_path: Path, remote: RemoteServer
) -> None:
    url = remote.serve("/team.yaml", "model: opus\n")
    config = _config(tmp_path, f"team: {url}\n")

    load(config)
    load(config)

    assert _paths(remote) == ["/team.yaml", "/team.yaml"]


def test_url_override_replaces_the_remote_text_without_fetching(
    tmp_path: Path, remote: RemoteServer
) -> None:
    url = remote.serve("/team.yaml", "model: opus\n")

    root = load(_config(tmp_path, f"team: {url}\n"), overrides={Url(url): "model: haiku\n"})

    assert flatten(root) == {"team.model": "haiku"}
    assert _paths(remote) == []


def test_failed_fetch_names_url_including_file_and_path(
    tmp_path: Path, remote: RemoteServer
) -> None:
    url = remote.url("/missing.yaml")
    config = _config(tmp_path, f"agents:\n  team: {url}\n")

    error = _load_error(config)

    assert error.exit_code == 4
    assert error.message == (
        f"cannot fetch {url} (included from {config.resolve()}, at agents.team): HTTP 404 Not Found"
    )


def test_failed_fetch_inside_remote_content_names_the_including_url(
    tmp_path: Path, remote: RemoteServer
) -> None:
    outer = remote.serve("/outer.yaml", "items:\n  - file:gone.md\n")
    gone = remote.url("/gone.md")

    error = _load_error(_config(tmp_path, f"team: {outer}\n"))

    assert error.message == (
        f"cannot fetch {gone} (included from {outer}, at team.items.0): HTTP 404 Not Found"
    )


def test_file_include_in_remote_content_that_escapes_to_another_scheme_is_refused(
    tmp_path: Path, remote: RemoteServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = tmp_path / "secret.yaml"
    secret.write_text("stolen: true\n", encoding="utf-8")
    url = remote.serve("/team.yaml", f"x: file:file://{secret}\n")
    config = _config(tmp_path, f"team: {url}\n")
    read: list[Path] = []
    real_read_source = loader.read_source

    def spy(path: Path) -> SourceFile:
        read.append(path)
        return real_read_source(path)

    monkeypatch.setattr(loader, "read_source", spy)

    error = _load_error(config)

    assert error.exit_code == 4
    assert error.message == (
        f"include 'file:file://{secret}' in {url} does not resolve to an http(s) URL"
    )
    assert read == [config.resolve()]


def test_file_include_in_remote_content_resolving_to_a_hostless_url_never_touches_disk(
    tmp_path: Path, remote: RemoteServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ``file:https:/x`` inside http content: urljoin keeps a different scheme as written, so the
    # target is ``https:/x``, an http(s) URL with no host. It must fail as a fetch (exit 4),
    # naming it, and never be read as a local path such as ``/x``.
    url = remote.serve("/team.yaml", "x: file:https:/x\n")
    config = _config(tmp_path, f"team: {url}\n")
    read: list[Path] = []
    real_read_source = loader.read_source

    def spy(path: Path) -> SourceFile:
        read.append(path)
        return real_read_source(path)

    monkeypatch.setattr(loader, "read_source", spy)

    error = _load_error(config)

    assert error.exit_code == 4
    assert error.message.startswith(f"cannot fetch https:/x (included from {url}, at team.x): ")
    assert read == [config.resolve()]
    assert _paths(remote) == ["/team.yaml"]


def test_remote_source_files_are_remote_and_local_ones_are_not(
    tmp_path: Path, remote: RemoteServer
) -> None:
    url = remote.serve("/team.yaml", "prompt: file:sys.md\n")
    remote.serve("/sys.md", "hi\n")
    config = _config(tmp_path, f"team: {url}\nlocal: file:local.yaml\n", {"local.yaml": "a: 1\n"})

    root = load(config)

    assert isinstance(root, MappingNode)
    assert not root.origin.file.remote
    local = _at(root, "local")
    team = _at(root, "team")
    prompt = _at(root, "team.prompt")
    assert isinstance(local, YamlInclude) and not local.target.remote
    assert isinstance(team, YamlInclude) and team.target.remote
    assert isinstance(prompt, TextInclude) and prompt.target.remote
    assert prompt.origin.file is team.target


def test_anchor_on_a_remote_include_reference_is_refused(
    tmp_path: Path, remote: RemoteServer
) -> None:
    url = remote.serve("/team.yaml", "model: opus\n")
    config = _config(tmp_path, f"a: &t {url}\nb: *t\n")

    error = _load_error(config)

    assert error.message == (
        f"cannot load {config.resolve()}: anchor &t at line 1 is on an include reference (or a"
        " value containing one); anchors may not share includes"
    )
    assert _paths(remote) == []


def test_anchor_on_a_mapping_containing_a_remote_include_is_refused(
    tmp_path: Path, remote: RemoteServer
) -> None:
    url = remote.url("/team.yaml")
    config = _config(tmp_path, f"a: &t\n  inner:\n    - {url}\nb: *t\n")

    assert "anchor &t at line 1 is on an include reference" in _load_error(config).message


def test_remote_content_may_use_anchors_and_aliases_internally(
    tmp_path: Path, remote: RemoteServer
) -> None:
    body = "base: &b\n  model: opus\ncoder: *b\nreviewer:\n  <<: *b\n  temperature: 0.2\n"
    url = remote.serve("/team.yaml", body)

    root = load(_config(tmp_path, f"team: {url}\n"))

    assert flatten(root) == {
        "team.base.model": "opus",
        "team.coder.model": "opus",
        "team.reviewer.model": "opus",
        "team.reviewer.temperature": 0.2,
    }
    alias = _at(root, "team.coder")
    assert isinstance(alias, AliasNode)
    base = unwrap(_at(root, "team.base"))
    assert alias.target is base
    assert isinstance(base, MappingNode) and base.anchor is not None
    assert base.anchor.path == ("team", "base")
    model = unwrap(_at(root, "team.base.model"))
    assert isinstance(model, ScalarNode) and model.origin.file.path == Url(url)
