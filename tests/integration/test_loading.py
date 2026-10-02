"""Loading real theatre files into the SourceTree: values, spans, includes, errors (FR-007/008)."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from conftest import MakeTheatre
from troupe.errors import LoadError
from troupe.loader import load, read_source
from troupe.paths import lookup, unwrap
from troupe.theatre import locate
from troupe.tree import (
    MappingNode,
    Node,
    Origin,
    ScalarNode,
    SequenceNode,
    TextInclude,
    YamlInclude,
)


def _load(make_theatre: MakeTheatre, files: dict[str, str | bytes]) -> Node:
    return load(locate(make_theatre(files)).config_file)


def _at(root: Node, dotted: str) -> Node:
    return unwrap(lookup(root, dotted.split("."), dotted))


def _scalar(root: Node, dotted: str) -> ScalarNode:
    node = _at(root, dotted)
    assert isinstance(node, ScalarNode)
    return node


def _origins(node: Node) -> Iterator[Origin]:
    """Every key and scalar/include origin in document order, following YAML includes."""
    if isinstance(node, MappingNode):
        for entry in node.entries:
            yield entry.key_origin
            yield from _origins(entry.value)
    elif isinstance(node, SequenceNode):
        for item in node.items:
            yield from _origins(item)
    elif isinstance(node, YamlInclude):
        yield node.origin
        yield from _origins(node.root)
    else:
        yield node.origin


def _sources(root: Node) -> list[tuple[str, str]]:
    return [(o.file.path.name, o.file.text[o.start : o.end]) for o in _origins(root)]


NESTED = (
    "# troupe\n"
    "model:\n"
    '  name: "gpt"   # quoted\n'
    "  temperature: 0.2\n"
    "  stop: ~\n"
    "  enabled: yes\n"
    "tools:\n"
    "  - grep\n"
    "  - {name: sed, args: ['-n', 1]}\n"
    "notes: |\n"
    "  line one\n"
    "  line two\n"
    "'quoted key': 0x1F\n"
)


def test_nested_mappings_and_lists_load_with_values_and_styles(make_theatre: MakeTheatre) -> None:
    root = _load(make_theatre, {"troupe.yml": NESTED})

    found = [
        (dotted, _scalar(root, dotted).value, _scalar(root, dotted).style)
        for dotted in (
            "model.name",
            "model.temperature",
            "model.stop",
            "model.enabled",
            "tools.0",
            "tools.1.name",
            "tools.1.args.0",
            "tools.1.args.1",
            "notes",
            "quoted key",
        )
    ]

    assert found == [
        ("model.name", "gpt", "double"),
        ("model.temperature", 0.2, "plain"),
        ("model.stop", None, "plain"),
        ("model.enabled", "yes", "plain"),
        ("tools.0", "grep", "plain"),
        ("tools.1.name", "sed", "plain"),
        ("tools.1.args.0", "-n", "single"),
        ("tools.1.args.1", 1, "plain"),
        ("notes", "line one\nline two\n", "literal"),
        ("quoted key", 31, "plain"),
    ]
    flow = _at(root, "tools.1")
    assert isinstance(flow, MappingNode)
    assert flow.flow
    assert isinstance(root, MappingNode)
    assert root.get("quoted key") is not None
    assert root.entries[-1].key_style == "single"


def test_every_origin_slice_reproduces_its_source_text(make_theatre: MakeTheatre) -> None:
    root = _load(make_theatre, {"troupe.yml": NESTED})

    assert _sources(root) == [
        ("troupe.yml", text)
        for text in [
            "model", "name", '"gpt"', "temperature", "0.2", "stop", "~", "enabled", "yes",
            "tools", "grep", "name", "sed", "args", "'-n'", "1",
            "notes", "|\n  line one\n  line two\n",
            "'quoted key'", "0x1F",
        ]
    ]  # fmt: skip


def test_bom_and_crlf_are_kept_in_text_and_spans_align(make_theatre: MakeTheatre) -> None:
    raw = "\ufeffa: 'one'\r\nb:\r\n  - two\r\n".encode()
    theatre = make_theatre({"troupe.yaml": raw})

    root = load(theatre / ".troupe" / "troupe.yaml")

    assert isinstance(root, MappingNode)
    assert root.origin.file.text.encode("utf-8") == raw
    assert _sources(root) == [
        ("troupe.yaml", "a"),
        ("troupe.yaml", "'one'"),
        ("troupe.yaml", "b"),
        ("troupe.yaml", "two"),
    ]


def test_source_file_path_is_absolute_and_resolved(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "a: 1\n"})

    root = load(theatre / ".troupe" / ".." / ".troupe" / "troupe.yml")

    assert isinstance(root, MappingNode)
    assert root.origin.file.path == (theatre / ".troupe" / "troupe.yml").resolve()


@pytest.mark.parametrize("text", ["", "# nothing yet\n"])
def test_empty_document_is_empty_block_mapping_at_start(
    make_theatre: MakeTheatre, text: str
) -> None:
    root = _load(make_theatre, {"troupe.yml": text})

    assert isinstance(root, MappingNode)
    assert (root.entries, root.flow, root.origin.start, root.origin.end) == ([], False, 0, 0)


def test_empty_document_with_bom_starts_after_bom(make_theatre: MakeTheatre) -> None:
    root = _load(make_theatre, {"troupe.yml": "\ufeff"})

    assert isinstance(root, MappingNode)
    assert (root.origin.start, root.origin.end) == (1, 1)


def test_yaml_include_embeds_target_whose_nodes_belong_to_target_file(
    make_theatre: MakeTheatre,
) -> None:
    root = _load(
        make_theatre,
        {"troupe.yml": "agents: file:agents.yaml  # team\n", "agents.yaml": "lead: ada\n"},
    )

    include = lookup(root, ["agents"], "agents")
    assert isinstance(include, YamlInclude)
    assert include.origin.file.text[include.origin.start : include.origin.end] == (
        "file:agents.yaml"
    )
    assert include.target.path.name == "agents.yaml"
    lead = _scalar(root, "agents.lead")
    assert lead.value == "ada"
    assert lead.origin.file is include.target
    assert _sources(root) == [
        ("troupe.yml", "agents"),
        ("troupe.yml", "file:agents.yaml"),
        ("agents.yaml", "lead"),
        ("agents.yaml", "ada"),
    ]


@pytest.mark.parametrize("written", ["'file:a.yml'", '"file:a.yml"', "file:a.yml"])
def test_include_is_recognised_in_any_quoting_style(
    make_theatre: MakeTheatre, written: str
) -> None:
    root = _load(make_theatre, {"troupe.yml": f"x: {written}\n", "a.yml": "k: v\n"})

    assert isinstance(lookup(root, ["x"], "x"), YamlInclude)


def test_nested_include_is_relative_to_including_files_directory(
    make_theatre: MakeTheatre,
) -> None:
    root = _load(
        make_theatre,
        {
            "troupe.yml": "team: file:teams/core.yaml\n",
            "teams/core.yaml": "members:\n  - file:members/ada.yml\n",
            "teams/members/ada.yml": "role: lead\n",
            "members/ada.yml": "role: WRONG\n",
        },
    )

    role = _scalar(root, "team.members.0.role")

    assert role.value == "lead"
    assert role.origin.file.path.parts[-3:] == ("teams", "members", "ada.yml")


def test_yaml_include_of_empty_file_is_empty_mapping(make_theatre: MakeTheatre) -> None:
    root = _load(make_theatre, {"troupe.yml": "extra: file:empty.yaml\n", "empty.yaml": ""})

    extra = _at(root, "extra")

    assert isinstance(extra, MappingNode)
    assert extra.entries == []


def test_same_file_included_twice_shares_one_source_file(make_theatre: MakeTheatre) -> None:
    root = _load(
        make_theatre,
        {"troupe.yml": "a: file:common.yml\nb: file:./common.yml\n", "common.yml": "k: v\n"},
    )

    first, second = lookup(root, ["a"], "a"), lookup(root, ["b"], "b")

    assert isinstance(first, YamlInclude)
    assert isinstance(second, YamlInclude)
    assert first.target is second.target
    assert _scalar(root, "a.k").origin.file is _scalar(root, "b.k").origin.file


def test_text_include_is_exact_text_with_crlf_and_no_trailing_newline(
    make_theatre: MakeTheatre,
) -> None:
    root = _load(
        make_theatre,
        {"troupe.yml": "prompt: file:prompt.md\n", "prompt.md": b"line 1\r\nline 2"},
    )

    prompt = lookup(root, ["prompt"], "prompt")

    assert isinstance(prompt, TextInclude)
    assert prompt.target.text == "line 1\r\nline 2"
    assert prompt.target.path.name == "prompt.md"


def test_include_suffix_match_is_case_sensitive(make_theatre: MakeTheatre) -> None:
    root = _load(make_theatre, {"troupe.yml": "x: file:a.YAML\n", "a.YAML": "k: v\n"})

    include = lookup(root, ["x"], "x")

    assert isinstance(include, TextInclude)
    assert include.target.text == "k: v\n"


def test_missing_include_target_names_target_includer_and_path(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre({"troupe.yml": "team:\n  lead: file:people/ada.yaml\n"})
    state = (theatre / ".troupe").resolve()

    with pytest.raises(LoadError) as caught:
        load(state / "troupe.yml")

    assert caught.value.message == (
        f"include target not found: {state / 'people' / 'ada.yaml'}"
        f" (included from {state / 'troupe.yml'}, at team.lead)"
    )
    assert caught.value.exit_code == 4


def test_missing_text_include_target_is_load_error(make_theatre: MakeTheatre) -> None:
    with pytest.raises(LoadError, match=r"include target not found: .*prompt\.txt"):
        _load(make_theatre, {"troupe.yml": "p: file:prompt.txt\n"})


def test_two_file_include_cycle_is_load_error_naming_chain(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "a: file:a.yaml\n", "a.yaml": "b: file:b.yaml\n",
                            "b.yaml": "back: file:a.yaml\n"})  # fmt: skip
    state = (theatre / ".troupe").resolve()

    with pytest.raises(LoadError) as caught:
        load(state / "troupe.yml")

    assert caught.value.message == (
        f"include cycle at a.b.back: {state / 'a.yaml'} -> {state / 'b.yaml'} -> {state / 'a.yaml'}"
    )


def test_self_include_is_load_error(make_theatre: MakeTheatre) -> None:
    with pytest.raises(LoadError, match=r"include cycle at me: .*troupe\.yml -> .*troupe\.yml$"):
        _load(make_theatre, {"troupe.yml": "me: file:troupe.yml\n"})


def test_include_through_symlink_to_including_file_is_cycle(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "a: file:a.yaml\n", "a.yaml": "x: file:link.yaml\n"})
    (theatre / ".troupe" / "link.yaml").symlink_to(theatre / ".troupe" / "a.yaml")

    with pytest.raises(LoadError, match=r"include cycle at a\.x"):
        load(theatre / ".troupe" / "troupe.yml")


def test_same_file_in_sibling_branches_is_not_a_cycle(make_theatre: MakeTheatre) -> None:
    root = _load(
        make_theatre,
        {"troupe.yml": "a: file:x.yaml\nb: file:y.yaml\n", "x.yaml": "c: file:y.yaml\n",
         "y.yaml": "v: 1\n"},
    )  # fmt: skip

    assert (_scalar(root, "a.c.v").value, _scalar(root, "b.v").value) == (1, 1)


def test_invalid_yaml_in_root_is_load_error_naming_file(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "a: [1,\n"})

    with pytest.raises(LoadError) as caught:
        load(theatre / ".troupe" / "troupe.yml")

    assert caught.value.message.startswith(
        f"cannot parse {(theatre / '.troupe' / 'troupe.yml').resolve()}: "
    )


def test_invalid_yaml_in_include_is_load_error_naming_include(make_theatre: MakeTheatre) -> None:
    with pytest.raises(LoadError, match=r"cannot parse \S*broken\.yaml: .* at line 2"):
        _load(
            make_theatre, {"troupe.yml": "a: file:broken.yaml\n", "broken.yaml": "k: v\n  x: y\n"}
        )


@pytest.mark.parametrize("target", ["troupe.yml", "prompt.txt"])
def test_invalid_utf8_is_load_error_naming_file(make_theatre: MakeTheatre, target: str) -> None:
    files: dict[str, str | bytes] = {"troupe.yml": "p: file:prompt.txt\n"}
    files[target] = b"p: file:prompt.txt\n\xff\n" if target == "troupe.yml" else b"\xc3("

    with pytest.raises(LoadError, match=rf"cannot read \S*{target}: not valid UTF-8"):
        _load(make_theatre, files)


def test_text_include_of_directory_is_load_error(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "p: file:prompts\n"})
    (theatre / ".troupe" / "prompts").mkdir()

    with pytest.raises(LoadError, match=r"include target is a directory: \S*prompts .* at p\)"):
        load(theatre / ".troupe" / "troupe.yml")


def test_duplicate_key_is_load_error_naming_file_and_path(make_theatre: MakeTheatre) -> None:
    with pytest.raises(LoadError, match=r"troupe\.yml: duplicate key model\.name at line 3"):
        _load(make_theatre, {"troupe.yml": "model:\n  name: a\n  name: b\n"})


def test_non_scalar_key_is_load_error_naming_file(make_theatre: MakeTheatre) -> None:
    with pytest.raises(LoadError, match=r"troupe\.yml: mapping key at line 1 under \(root\)"):
        _load(make_theatre, {"troupe.yml": "[a, b]: 1\n"})


def test_overrides_replace_disk_text_without_touching_files(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "a: 1\nb: file:b.yaml\n", "b.yaml": "c: 2\n"})
    state = theatre / ".troupe"

    root = load(state / "troupe.yml", overrides={(state / "b.yaml").resolve(): "c: 3\n"})

    assert _scalar(root, "a").value == 1
    assert _scalar(root, "b.c").value == 3
    assert _scalar(root, "b.c").origin.file.text == "c: 3\n"
    assert (state / "b.yaml").read_text(encoding="utf-8") == "c: 2\n"


def test_override_of_root_can_add_includes(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "a: 1\n", "p.txt": "hi"})
    config = (theatre / ".troupe" / "troupe.yml").resolve()

    root = load(config, overrides={config: "a: 1\np: file:p.txt\n"})

    prompt = lookup(root, ["p"], "p")
    assert isinstance(prompt, TextInclude)
    assert prompt.target.text == "hi"


def test_each_load_reads_current_disk_contents(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "a: 1\n"})
    config = theatre / ".troupe" / "troupe.yml"
    assert _scalar(load(config), "a").value == 1

    config.write_bytes(b"a: edited\n")

    assert _scalar(load(config), "a").value == "edited"


def test_read_source_keeps_bytes_exactly(tmp_path: Path) -> None:
    raw = "\ufeffa: 'é'\r\n\rb: 1".encode()
    (tmp_path / "f.yml").write_bytes(raw)

    source = read_source(tmp_path / "f.yml")

    assert source.text.encode("utf-8") == raw
    assert source.path == (tmp_path / "f.yml").resolve()


def test_read_source_of_missing_file_is_load_error_naming_it(tmp_path: Path) -> None:
    with pytest.raises(LoadError, match=r"cannot read \S*nope\.yml"):
        read_source(tmp_path / "nope.yml")
