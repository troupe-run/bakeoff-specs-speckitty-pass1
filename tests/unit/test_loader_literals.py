"""Literal strings in the loader: ``!literal`` and schema ``format: uri`` (spec S-3, S-7, S-10).

Each test writes a real theatre state directory under ``tmp_path`` (configuration and, where
needed, ``troupe.schema.json`` read with ``schema.load_schema``) and loads it with
``troupe.loader.load``. Include-looking strings point at the ``remote`` test server, so the
request log proves that a literal is never fetched.
"""

import json
from pathlib import Path

import pytest

from conftest import LOCAL_NO_PROXY
from remote_server import RemoteServer
from troupe.errors import LoadError, WriteRefused
from troupe.leaves import flatten
from troupe.loader import load
from troupe.paths import lookup, unwrap
from troupe.schema import Schema, load_schema
from troupe.tree import (
    AliasNode,
    MappingNode,
    MergeKeyMapping,
    Node,
    ScalarNode,
    SequenceNode,
    TextInclude,
    YamlInclude,
)
from troupe.values import parse_value
from troupe.writeback.apply import apply_set


@pytest.fixture(autouse=True)
def _bypass_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_PROXY", LOCAL_NO_PROXY)
    monkeypatch.setenv("no_proxy", LOCAL_NO_PROXY)


def _theatre(
    tmp_path: Path, text: str, schema: object = None, files: dict[str, str] | None = None
) -> tuple[Path, Schema | None]:
    """Write ``.troupe/troupe.yml`` (and the schema, if given); return it and the read schema."""
    state_dir = tmp_path / ".troupe"
    state_dir.mkdir()
    for rel, content in (files or {}).items():
        (state_dir / rel).write_text(content, encoding="utf-8")
    if schema is not None:
        (state_dir / "troupe.schema.json").write_text(json.dumps(schema), encoding="utf-8")
    config = state_dir / "troupe.yml"
    config.write_text(text, encoding="utf-8")
    return config, load_schema(state_dir)


def _at(root: Node, dotted: str) -> Node:
    return lookup(root, dotted.split("."), dotted)


def _literal(root: Node, dotted: str) -> ScalarNode:
    node = unwrap(_at(root, dotted))
    assert isinstance(node, ScalarNode), node
    return node


def _load_error(config: Path, schema: Schema | None = None) -> LoadError:
    with pytest.raises(LoadError) as caught:
        load(config, schema=schema)
    return caught.value


@pytest.mark.parametrize("kind", ["file", "https", "http"])
def test_literal_tag_makes_an_include_looking_string_a_plain_string(
    tmp_path: Path, remote: RemoteServer, kind: str
) -> None:
    served = remote.serve("/team.yaml", "model: opus\n")
    value = {"file": "file:team.yaml", "https": "https://127.0.0.1:1/x.yaml", "http": served}[kind]
    config, _ = _theatre(
        tmp_path, f"note: !literal {value}\n", files={"team.yaml": "model: opus\n"}
    )

    root = load(config)

    node = _literal(root, "note")
    assert node.value == value
    assert node.literal is not None and node.literal.source == "!literal "
    assert node.origin.source == value
    assert flatten(root) == {"note": value}
    assert remote.requests() == []


@pytest.mark.parametrize(
    ("text", "value", "style"),
    [
        ("n: !literal 5\n", "5", "plain"),
        ("n: !literal true\n", "true", "plain"),
        ("n: !literal\n", "", "plain"),
        ("n: !literal ''\n", "", "single"),
        ("n: !literal |\n  file:a.md\n  b\n", "file:a.md\nb\n", "literal"),
        ("n: !literal >-\n  https://x.example/a\n  b\n", "https://x.example/a b", "folded"),
    ],
)
def test_literal_value_is_the_scalar_text_as_a_string(
    tmp_path: Path, text: str, value: str, style: str
) -> None:
    config, _ = _theatre(tmp_path, text)

    node = _literal(load(config), "n")

    assert (node.value, node.style) == (value, style)
    assert node.literal is not None and node.literal.source.startswith("!literal")


def test_untagged_scalars_have_no_literal_span(tmp_path: Path) -> None:
    config, _ = _theatre(tmp_path, "n: 5\ns: text\n")

    root = load(config)

    assert _literal(root, "n").literal is None
    assert _literal(root, "s").literal is None


URI_SCHEMA = {
    "type": "object",
    "properties": {
        "webhook": {"type": "string", "format": "uri"},
        "agents": {
            "additionalProperties": {
                "properties": {"urls": {"type": "array", "items": {"format": "uri"}}}
            }
        },
    },
}


def test_schema_format_uri_makes_strings_literal_via_properties_additional_and_items(
    tmp_path: Path, remote: RemoteServer
) -> None:
    hook, doc = remote.url("/hook"), remote.url("/doc.yaml")
    team = remote.serve("/team.yaml", "model: opus\n")
    text = f"webhook: {hook}\nagents:\n  coder:\n    urls:\n      - {doc}\nteam: {team}\n"
    config, schema = _theatre(tmp_path, text, URI_SCHEMA)

    root = load(config, schema=schema)

    assert _literal(root, "webhook").value == hook
    assert _literal(root, "webhook").literal is None
    assert _literal(root, "agents.coder.urls.0").value == doc
    assert isinstance(_at(root, "team"), YamlInclude)
    assert [request.path for request in remote.requests()] == ["/team.yaml"]


def test_same_strings_without_the_schema_mark_are_includes(
    tmp_path: Path, remote: RemoteServer
) -> None:
    hook = remote.serve("/hook", "ok\n")
    doc = remote.serve("/doc.yaml", "a: 1\n")
    config, _ = _theatre(
        tmp_path, f"webhook: {hook}\nagents:\n  coder:\n    urls:\n      - {doc}\n"
    )

    root = load(config)

    assert isinstance(_at(root, "webhook"), TextInclude)
    assert isinstance(_at(root, "agents.coder.urls.0"), YamlInclude)


def test_schema_marked_through_ref_or_pattern_properties_is_not_followed(
    tmp_path: Path, remote: RemoteServer
) -> None:
    hook = remote.serve("/hook", "ok\n")
    schema = {
        "$defs": {"uri": {"format": "uri"}},
        "properties": {"a": {"$ref": "#/$defs/uri"}},
        "patternProperties": {"^b$": {"format": "uri"}},
    }
    config, loaded = _theatre(tmp_path, f"a: {hook}\nb: {hook}\n", schema)

    root = load(config, schema=loaded)

    assert isinstance(_at(root, "a"), TextInclude)
    assert isinstance(_at(root, "b"), TextInclude)


def test_digit_named_mapping_key_is_looked_up_as_a_key_not_an_index(
    tmp_path: Path, remote: RemoteServer
) -> None:
    url = remote.serve("/x.md", "text\n")
    schema = {
        "properties": {
            "m": {"properties": {"0": {"format": "uri"}}},
            "l": {"properties": {"0": {"format": "uri"}}},
        }
    }
    config, loaded = _theatre(tmp_path, f'm:\n  "0": {url}\nl:\n  - {url}\n', schema)

    root = load(config, schema=loaded)

    assert _literal(root, "m.0").value == url
    assert isinstance(_at(root, "l.0"), TextInclude)  # an index step looks in ``items`` only


def test_anchored_literal_is_allowed_and_literal_at_every_alias(
    tmp_path: Path, remote: RemoteServer
) -> None:
    url = remote.url("/hook")
    schema = {"properties": {"webhook": {"format": "uri"}}}
    config, loaded = _theatre(tmp_path, f"webhook: &w {url}\nbackup: *w\nlist:\n  - *w\n", schema)

    root = load(config, schema=loaded)

    anchored = _literal(root, "webhook")
    assert anchored.anchor is not None and anchored.anchor.name == "w"
    for path in ("backup", "list.0"):
        alias = _at(root, path)
        assert isinstance(alias, AliasNode) and alias.target is anchored
    assert flatten(root) == {"webhook": url, "backup": url, "list.0": url}
    assert remote.requests() == []


def test_anchored_tagged_literal_is_allowed(tmp_path: Path, remote: RemoteServer) -> None:
    url = remote.url("/hook")
    config, _ = _theatre(tmp_path, f"a: &w !literal {url}\nb: *w\n")

    root = load(config)

    assert flatten(root) == {"a": url, "b": url}
    assert remote.requests() == []


def test_alias_path_marked_uri_does_not_make_an_anchored_include_a_literal(
    tmp_path: Path, remote: RemoteServer
) -> None:
    # S-7: an aliased string is judged at the path of its anchored node, here unmarked, so the
    # anchor sits on an include reference (C3) whatever the alias's path says.
    url = remote.url("/hook")
    schema = {"properties": {"b": {"format": "uri"}}}
    config, loaded = _theatre(tmp_path, f"a: &w {url}\nb: *w\n", schema)

    error = _load_error(config, loaded)

    assert "anchor &w at line 1 is on an include reference" in error.message
    assert remote.requests() == []


def test_anchor_on_a_mapping_holding_only_literals_is_allowed(
    tmp_path: Path, remote: RemoteServer
) -> None:
    url = remote.url("/hook")
    schema = {"properties": {"d": {"properties": {"hook": {"format": "uri"}}}}}
    text = f"d: &d\n  hook: {url}\n  note: !literal file:x.md\ne: *d\n"
    config, loaded = _theatre(tmp_path, text, schema)

    root = load(config, schema=loaded)

    assert flatten(root) == {
        "d.hook": url,
        "d.note": "file:x.md",
        "e.hook": url,
        "e.note": "file:x.md",
    }
    assert remote.requests() == []


def test_inline_merge_source_strings_are_judged_at_the_merged_path(
    tmp_path: Path, remote: RemoteServer
) -> None:
    url = remote.url("/hook")
    schema = {"properties": {"a": {"properties": {"hook": {"format": "uri"}}}}}
    config, loaded = _theatre(tmp_path, f"a:\n  <<:\n    - {{hook: {url}}}\n  n: 1\n", schema)

    root = load(config, schema=loaded)

    assert flatten(root) == {"a.hook": url, "a.n": 1}
    assert remote.requests() == []


@pytest.mark.parametrize(
    ("merge", "written_at"),
    [
        ("{k: {r: &a 1}}", ("m", "<<", "k", "r")),
        ("[{k: {r: &a 1}}, {j: 0}]", ("m", "<<", "0", "k", "r")),
    ],
)
def test_anchor_in_an_inline_merge_source_keeps_its_written_path_as_identity(
    tmp_path: Path, merge: str, written_at: tuple[str, ...]
) -> None:
    # Review regression (WP05 cycle 1): the schema lookup mounts a ``<<`` value at its mapping,
    # but ``Anchor.path`` (the verifier's anchor identity, R-8 rule 1) stays the written path.
    # Otherwise the merge-source ``&a`` and the written ``&a`` share ``m.k.r`` and a ``set`` of
    # ``m.k`` silently rebinds ``z`` from 2 to 1 instead of being refused.
    text = f"m:\n  <<: {merge}\n  k: {{r: &a 2}}\nz: *a\n"
    config, _ = _theatre(tmp_path, text)
    root = load(config)
    holder = _at(root, "m")
    assert isinstance(holder, MergeKeyMapping)
    source = holder.written.entries[0].value  # the ``<<`` value as written
    if isinstance(source, SequenceNode):
        source = source.items[0]
    assert isinstance(source, MappingNode)
    inner = unwrap(lookup(source, ["k", "r"], "k.r"))
    assert isinstance(inner, ScalarNode) and inner.anchor is not None
    assert inner.anchor.path == written_at
    written = _literal(root, "z")
    assert written.anchor is not None and written.anchor.path == ("m", "k", "r")

    with pytest.raises(WriteRefused) as caught:
        apply_set(root, ["m", "k"], "m.k", parse_value("{r: 3}"), "{r: 3}")

    assert caught.value.exit_code == 3
    assert caught.value.message == "m.k: cannot write this change byte-surgically; no file changed"
    assert config.read_text(encoding="utf-8") == text


def test_ref_value_tagged_literal_is_refused(tmp_path: Path) -> None:
    config, _ = _theatre(tmp_path, "coder:\n  model: x\n  $ref: !literal file:x.yaml\n")

    error = _load_error(config)

    assert error.exit_code == 4
    assert error.message == (
        f"cannot load {config.resolve()}: coder.$ref must be an include string, not !literal"
        " (line 3)"
    )


def test_ref_value_that_is_no_include_string_names_the_three_kinds(tmp_path: Path) -> None:
    config, _ = _theatre(tmp_path, "coder:\n  $ref: ftp://x/y.yaml\n")

    assert _load_error(config).message == (
        f"cannot load {config.resolve()}: coder.$ref must be an include string ('file:...',"
        " 'https://...' or 'http://...'), got ftp://x/y.yaml"
    )


def test_ref_value_is_an_include_even_where_the_schema_marks_uri(tmp_path: Path) -> None:
    schema = {"properties": {"coder": {"format": "uri"}}}
    config, loaded = _theatre(
        tmp_path, "coder:\n  $ref: file:c.yaml\n", schema, {"c.yaml": "model: opus\n"}
    )

    root = load(config, schema=loaded)

    assert isinstance(_at(root, "coder"), YamlInclude)
    assert flatten(root) == {"coder.model": "opus"}


@pytest.mark.parametrize(
    ("text", "line", "under"),
    [
        ("!literal file:k: v\n", 1, "(root)"),
        ("a:\n  b:\n    !literal k: v\n", 3, "a.b"),
        ("a: {!literal $ref: file:x.yaml}\n", 1, "a"),
    ],
)
def test_literal_tag_on_a_mapping_key_is_refused(
    tmp_path: Path, text: str, line: int, under: str
) -> None:
    config, _ = _theatre(tmp_path, text)

    error = _load_error(config)

    assert error.exit_code == 4
    assert error.message == (
        f"cannot load {config.resolve()}: mapping key at line {line} under {under} is tagged"
        " !literal; keys are never includes"
    )


def test_literal_values_read_as_strings_without_the_tag(tmp_path: Path) -> None:
    config, _ = _theatre(
        tmp_path,
        "note: !literal file:readme.md\ndocs: !literal https://x.example/y\nn: !literal 5\n",
    )

    root = load(config)

    assert isinstance(root, MappingNode)
    assert flatten(root) == {"note": "file:readme.md", "docs": "https://x.example/y", "n": "5"}
