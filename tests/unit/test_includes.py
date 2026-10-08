"""The include rule in ``troupe.includes`` (spec S-1, S-2, S-3, S-7, S-10..S-13; research R-3,
R-8): include kind, target resolution, YAML-or-text, the literal rule, PATH step kinds and the
VALUE marking that ``set`` uses.

Trees for ``path_steps`` are real files loaded through ``loader.load``; schemas are real files
loaded through ``load_schema``.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from troupe import loader
from troupe.errors import LoadError, PathError, WriteRefused
from troupe.includes import (
    IncludeStr,
    LiteralStr,
    include_kind,
    is_yaml_target,
    mark_literals,
    path_steps,
    reads_as_include,
    resolve_target,
)
from troupe.location import Url
from troupe.schema import SCHEMA_FILE_NAME, Schema, load_schema
from troupe.tree import Node
from troupe.values import Value

TEAM = Url("https://h/a/team.yaml")


def _tree(tmp_path: Path, text: str) -> Node:
    config = tmp_path / "troupe.yml"
    config.write_text(text, encoding="utf-8")
    return loader.load(config)


def _schema(tmp_path: Path, document: object) -> Schema:
    state_dir = tmp_path / ".troupe"
    state_dir.mkdir(exist_ok=True)
    (state_dir / SCHEMA_FILE_NAME).write_text(json.dumps(document), encoding="utf-8")
    schema = load_schema(state_dir)
    assert schema is not None
    return schema


# --- include_kind ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("file:x", "file"),
        ("https://x", "remote"),
        ("http://x", "remote"),
        ("HTTPS://x", None),
        ("ftp://x", None),
        ("files:x", None),
        ("", None),
        (" file:x", None),
    ],
)
def test_include_kind_is_a_case_sensitive_prefix_test(text: str, kind: str | None) -> None:
    assert include_kind(text) == kind


# --- resolve_target --------------------------------------------------------------------------


def test_resolve_target_file_in_local_file_is_relative_to_its_directory_unresolved() -> None:
    containing = Path("/theatre/.troupe/troupe.yml")
    assert resolve_target("file:../prompts/sys.md", containing) == Path(
        "/theatre/.troupe/../prompts/sys.md"
    )


@pytest.mark.parametrize("containing", [Path("/t/troupe.yml"), TEAM])
def test_resolve_target_remote_string_is_the_url_as_written(containing: Path | Url) -> None:
    assert resolve_target("https://Other.example/X.yaml?v=1", containing) == Url(
        "https://Other.example/X.yaml?v=1"
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("file:prompts/sys.md", "https://h/a/prompts/sys.md"),
        ("file:../x.yaml", "https://h/x.yaml"),
        ("file:/root.yaml", "https://h/root.yaml"),
        ("file:sys.md?v=1", "https://h/a/sys.md?v=1"),
    ],
)
def test_resolve_target_file_in_remote_content_joins_against_the_url(
    text: str, expected: str
) -> None:
    assert resolve_target(text, TEAM) == Url(expected)


def test_resolve_target_file_in_remote_content_to_non_http_url_raises_naming_include() -> None:
    with pytest.raises(LoadError) as caught:
        resolve_target("file:file:///etc/passwd", TEAM)
    assert caught.value.message == (
        "include 'file:file:///etc/passwd' in https://h/a/team.yaml"
        " does not resolve to an http(s) URL"
    )
    assert caught.value.exit_code == 4


# --- is_yaml_target --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("target", "yaml"),
    [
        (Path("/t/a.yml"), True),
        (Path("/t/a.yaml"), True),
        (Path("/t/a.YAML"), False),
        (Path("/t/a.md"), False),
        (Url("https://h/team.yaml?v=2"), True),
        (Url("https://h/team.yml#top"), True),
        (Url("https://h/team.yaml.txt"), False),
        (Url("https://h/"), False),
        (Url("https://h/team.YAML"), False),
        (Url("https://h/sys.md?f=x.yaml"), False),
    ],
)
def test_is_yaml_target_uses_the_path_suffix_case_sensitively(
    target: Path | Url, yaml: bool
) -> None:
    assert is_yaml_target(target) is yaml


# --- reads_as_include ------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["file:p.md", "https://x", "plain"])
@pytest.mark.parametrize("tagged", [False, True])
@pytest.mark.parametrize("uri", [False, True])
def test_reads_as_include_only_when_include_looking_untagged_and_not_uri(
    text: str, tagged: bool, uri: bool
) -> None:
    expected = text != "plain" and not tagged and not uri
    assert reads_as_include(text, tagged=tagged, uri=uri) is expected


# --- path_steps ------------------------------------------------------------------------------


def test_path_steps_through_mappings_are_keys(tmp_path: Path) -> None:
    root = _tree(tmp_path, "a:\n  b: 1\n")
    assert path_steps(root, ["a", "b"]) == [("key", "a"), ("key", "b")]


def test_path_steps_through_a_list_gives_an_index_step(tmp_path: Path) -> None:
    root = _tree(tmp_path, "a:\n  - x: 1\n  - x: 2\n")
    assert path_steps(root, ["a", "1", "x"]) == [("key", "a"), ("index", 1), ("key", "x")]


def test_path_steps_append_index_and_new_keys_below_it(tmp_path: Path) -> None:
    root = _tree(tmp_path, "a:\n  - 1\n")
    assert path_steps(root, ["a", "1", "b", "c"]) == [
        ("key", "a"),
        ("index", 1),
        ("key", "b"),
        ("key", "c"),
    ]


def test_path_steps_new_segments_under_a_mapping_are_keys(tmp_path: Path) -> None:
    root = _tree(tmp_path, "a: {}\n")
    assert path_steps(root, ["a", "b", "0"]) == [("key", "a"), ("key", "b"), ("key", "0")]


def test_path_steps_digit_named_mapping_key_is_a_key(tmp_path: Path) -> None:
    root = _tree(tmp_path, "a:\n  '0': x\n")
    assert path_steps(root, ["a", "0"]) == [("key", "a"), ("key", "0")]


def test_path_steps_through_a_yaml_include_reads_its_content(tmp_path: Path) -> None:
    (tmp_path / "list.yaml").write_text("- p\n- q\n", encoding="utf-8")
    root = _tree(tmp_path, "a: file:list.yaml\n")
    assert path_steps(root, ["a", "0"]) == [("key", "a"), ("index", 0)]


def test_path_steps_propagates_walk_path_error(tmp_path: Path) -> None:
    root = _tree(tmp_path, "a: 1\n")
    with pytest.raises(PathError):
        path_steps(root, ["a", "b"])


# --- mark_literals ---------------------------------------------------------------------------


def test_mark_literals_marks_an_include_looking_string_literal() -> None:
    marked = mark_literals(
        "https://x.example/y", [("key", "docs")], None, include=False, dotted="docs"
    )
    assert isinstance(marked, LiteralStr)
    assert marked == "https://x.example/y"
    assert hash(marked) == hash("https://x.example/y")


def test_mark_literals_leaves_a_non_include_string_a_plain_str() -> None:
    marked = mark_literals("plain", [("key", "a")], None, include=False, dotted="a")
    assert type(marked) is str


@pytest.mark.parametrize("value", [5, 1.5, True, None])
def test_mark_literals_leaves_non_strings_unchanged(value: Value) -> None:
    assert mark_literals(value, [("key", "a")], None, include=False, dotted="a") is value


def test_mark_literals_leaves_a_uri_path_string_plain(tmp_path: Path) -> None:
    schema = _schema(tmp_path, {"properties": {"webhook": {"format": "uri"}}})
    marked = mark_literals(
        "https://h.example/n", [("key", "webhook")], schema, include=False, dotted="webhook"
    )
    assert type(marked) is str


def test_mark_literals_judges_each_nested_string_at_its_own_path(tmp_path: Path) -> None:
    schema = _schema(
        tmp_path,
        {
            "properties": {
                "agents": {
                    "additionalProperties": {"properties": {"urls": {"items": {"format": "uri"}}}}
                }
            }
        },
    )
    value: Value = {
        "coder": {
            "docs": "https://x.example/y",
            "n": 1,
            "name": "c",
            "urls": ["https://u.example", "plain"],
            "prompts": ["file:p.md"],
        }
    }
    marked = mark_literals(value, [("key", "agents")], schema, include=False, dotted="agents")
    assert marked == value
    assert isinstance(marked, dict)
    coder = marked["coder"]
    assert isinstance(coder, dict)
    assert list(coder) == ["docs", "n", "name", "urls", "prompts"]
    assert isinstance(coder["docs"], LiteralStr)
    assert coder["n"] == 1
    assert type(coder["name"]) is str
    urls = coder["urls"]
    assert isinstance(urls, list)
    assert [type(url) for url in urls] == [str, str]
    prompts = coder["prompts"]
    assert isinstance(prompts, list)
    assert isinstance(prompts[0], LiteralStr)


def test_mark_literals_s11_example_marks_only_the_include_looking_string() -> None:
    value: Value = {"coder": {"docs": "https://x.example/y", "n": 1}}
    marked = mark_literals(value, [("key", "agents")], None, include=False, dotted="agents")
    assert isinstance(marked, dict)
    coder = marked["coder"]
    assert isinstance(coder, dict)
    assert isinstance(coder["docs"], LiteralStr)
    assert coder["n"] == 1


def test_mark_literals_with_include_marks_includes_and_does_not_mutate_input() -> None:
    value: Value = {"a": ["file:p.md", "plain"], "b": "https://x.example/y.yaml"}
    snapshot = json.dumps(value)
    marked = mark_literals(value, [("key", "t")], None, include=True, dotted="t")
    assert json.dumps(value) == snapshot
    assert isinstance(value, dict)
    assert type(value["b"]) is str
    assert isinstance(marked, dict)
    items = marked["a"]
    assert isinstance(items, list)
    assert isinstance(items[0], IncludeStr)
    assert not isinstance(items[0], LiteralStr)
    assert type(items[1]) is str
    assert isinstance(marked["b"], IncludeStr)
    assert marked is not value
    assert items is not value["a"]


def test_mark_literals_without_include_does_not_mutate_input() -> None:
    inner: list[Value] = ["file:p.md"]
    value: Value = {"a": inner}
    marked = mark_literals(value, [("key", "t")], None, include=False, dotted="t")
    assert type(inner[0]) is str
    assert isinstance(marked, dict)
    assert marked["a"] is not inner


def test_mark_literals_include_on_a_uri_path_is_refused_naming_the_nested_path(
    tmp_path: Path,
) -> None:
    schema = _schema(
        tmp_path,
        {"properties": {"team": {"properties": {"hooks": {"items": {"format": "uri"}}}}}},
    )
    value: Value = {"hooks": ["plain", "https://h.example/n"]}
    with pytest.raises(WriteRefused) as caught:
        mark_literals(value, [("key", "team")], schema, include=True, dotted="team")
    assert caught.value.exit_code == 3
    assert caught.value.message == (
        f"team: schema {schema.path} marks team.hooks.1 as format uri,"
        " so it cannot be an include; no file changed"
    )


def test_mark_literals_include_on_a_uri_path_with_non_include_string_is_accepted(
    tmp_path: Path,
) -> None:
    schema = _schema(tmp_path, {"properties": {"webhook": {"format": "uri"}}})
    marked = mark_literals("plain", [("key", "webhook")], schema, include=True, dotted="webhook")
    assert type(marked) is str


def test_mark_literals_without_schema_marks_every_include_looking_string() -> None:
    value: Value = ["file:a.md", "http://b", "https://c", "c"]
    marked = mark_literals(value, [("key", "l")], None, include=False, dotted="l")
    assert isinstance(marked, list)
    assert [type(item) for item in marked] == [LiteralStr, LiteralStr, LiteralStr, str]


# --- import graph ----------------------------------------------------------------------------


def test_loader_and_includes_import_without_a_cycle() -> None:
    for order in ("troupe.loader, troupe.includes", "troupe.includes, troupe.loader"):
        result = subprocess.run(
            [sys.executable, "-c", f"import {order}"], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr
