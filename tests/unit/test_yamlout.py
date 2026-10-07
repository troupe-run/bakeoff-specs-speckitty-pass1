"""yamlout: block YAML rendering of a loaded tree with per-line sources (FR-005, FR-007 to FR-011).

Trees are loaded from real files; every rendering is also parsed back with ruamel safe-load and
compared with the tree's resolved data (research D-8).
"""

import math
import warnings
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from conftest import LOCAL_NO_PROXY, MakeTheatre
from remote_server import RemoteServer
from troupe.loader import load
from troupe.location import Url
from troupe.paths import unwrap
from troupe.theatre import locate
from troupe.tree import MappingNode, Node, ScalarNode, SequenceNode, TextInclude
from troupe.yamlout import (
    INDENT_STEP,
    SOURCE_COMMENT_PREFIX,
    Line,
    render,
    source_label,
    to_text,
)

ROOT = "troupe.yml"
type YamlVersion = tuple[int, int]
YAML_VERSIONS: list[YamlVersion] = [(1, 2), (1, 1)]


def _load(make_theatre: MakeTheatre, files: dict[str, str | bytes]) -> tuple[Node, Path]:
    """Write ``files`` under ``.troupe/`` and load the configuration; also return the theatre."""
    theatre = locate(make_theatre(files))
    return load(theatre.config_file), theatre.directory


def _root(make_theatre: MakeTheatre, files: dict[str, str | bytes]) -> Node:
    return _load(make_theatre, files)[0]


def _value(make_theatre: MakeTheatre, text: str, key: str = "k") -> Node:
    """Load ``troupe.yml`` = ``text`` and return the value of root key ``key``."""
    root = unwrap(_root(make_theatre, {ROOT: text}))
    assert isinstance(root, MappingNode)
    entry = root.get(key)
    assert entry is not None
    return entry.value


def _data(node: Node) -> object:
    """The resolved plain data of ``node``; a YAML include is transparent."""
    node = unwrap(node)
    if isinstance(node, ScalarNode):
        return node.value
    if isinstance(node, TextInclude):
        return node.target.text
    if isinstance(node, SequenceNode):
        return [_data(item) for item in node.items]
    assert isinstance(node, MappingNode)
    return {entry.key: _data(entry.value) for entry in node.entries}


def _parse(text: str, version: YamlVersion = (1, 2)) -> object:
    """Load ``text`` with ruamel safe-load as a YAML ``version`` reader (1.2 by default)."""
    reader = YAML(typ="safe", pure=True)
    reader.version = version
    return reader.load(text)


def _text(node: Node) -> str:
    return to_text(render(node), None)


# --- T001: Line, to_text, source_label -------------------------------------------------------


def test_source_label_inside_theatre_is_relative_posix_path(tmp_path: Path) -> None:
    assert source_label(tmp_path / ".troupe" / "troupe.yml", tmp_path) == ".troupe/troupe.yml"


def test_source_label_outside_theatre_uses_dotdot(tmp_path: Path) -> None:
    theatre = tmp_path / "theatre"

    assert source_label(tmp_path / "shared" / "x.yml", theatre) == "../shared/x.yml"


def test_source_label_of_remote_content_is_the_url_verbatim(tmp_path: Path) -> None:
    url = "https://Cfg.example.com/a/../team.yaml?v=2#frag"

    assert source_label(Url(url), tmp_path) == url


def test_sources_of_remote_scalars_name_the_resolved_url(
    make_theatre: MakeTheatre, remote: RemoteServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NO_PROXY", LOCAL_NO_PROXY)
    monkeypatch.setenv("no_proxy", LOCAL_NO_PROXY)
    team = remote.serve("/a/team.yaml", "model: opus\nprompt: file:sys.md\n")
    remote.serve("/a/sys.md", "be brief")
    root, theatre = _load(make_theatre, {ROOT: f"team: {team}\nlocal: 1\n"})

    assert to_text(render(root), theatre) == (
        "team:\n"
        f"  model: opus # from {team}\n"
        f"  prompt: |- # from {remote.url('/a/sys.md')}\n"
        "    be brief\n"
        "local: 1 # from .troupe/troupe.yml\n"
    )


def test_to_text_without_root_never_adds_comments(tmp_path: Path) -> None:
    lines = [Line("a: 1", tmp_path / "f.yml"), Line("b:")]

    assert to_text(lines, None) == "a: 1\nb:\n"


def test_to_text_with_sources_appends_relative_posix_path(tmp_path: Path) -> None:
    lines = [
        Line("a:"),
        Line("  b: 1", tmp_path / ".troupe" / "troupe.yml"),
        Line("c: |", tmp_path / ".troupe" / "p" / "sys.md"),
        Line("  text"),
    ]

    assert to_text(lines, tmp_path) == (
        "a:\n  b: 1 # from .troupe/troupe.yml\nc: | # from .troupe/p/sys.md\n  text\n"
    )


def test_layout_constants_are_two_space_step_and_from_comment() -> None:
    assert (INDENT_STEP, SOURCE_COMMENT_PREFIX) == (2, " # from ")


# --- T002: scalars and keys -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("yaml_value", "rendered"),
    [
        ("''", "''"),
        ("'123'", "'123'"),
        ("'true'", "'true'"),
        ("'null'", "'null'"),
        ("'0.2'", "'0.2'"),
        ("'a: b'", "'a: b'"),
        ("' lead'", "' lead'"),
        ("it's", "it's"),
        ("plain text", "plain text"),
        ('"tab\\there"', "'tab\there'"),
        ('"bell\\a"', '"bell\\a"'),
    ],
)
def test_render_strings_that_look_like_other_types_are_quoted(
    make_theatre: MakeTheatre, yaml_value: str, rendered: str
) -> None:
    node = _value(make_theatre, f"k: {yaml_value}\n")

    assert _text(node) == rendered + "\n"
    assert _parse(_text(node)) == _data(node)


@pytest.mark.parametrize(
    ("yaml_value", "rendered"),
    [
        ("null", "null"),
        ("~", "null"),
        ("True", "true"),
        ("false", "false"),
        ("0x1F", "31"),
        ("0o17", "15"),
        ("-7", "-7"),
        ("0.2", "0.2"),
        ("1e3", "1000.0"),
    ],
)
def test_render_non_strings_in_canonical_plain_form(
    make_theatre: MakeTheatre, yaml_value: str, rendered: str
) -> None:
    node = _value(make_theatre, f"k: {yaml_value}\n")

    assert _text(node) == rendered + "\n"
    assert _parse(_text(node)) == _data(node)


@pytest.mark.parametrize(
    ("yaml_value", "rendered", "value"),
    [
        ("1e+20", "1.0e+20", 1e20),
        ("1e-5", "1.0e-05", 1e-05),
        ("5e-324", "5.0e-324", 5e-324),
        ("-1E20", "-1.0e+20", -1e20),
        ("1.5e300", "1.5e+300", 1.5e300),
        ("0.1", "0.1", 0.1),
        ("1e3", "1000.0", 1000.0),
    ],
)
@pytest.mark.parametrize("version", YAML_VERSIONS, ids=["yaml1.2", "yaml1.1"])
def test_render_exponent_float_has_dot_and_reads_back_without_warning(
    make_theatre: MakeTheatre,
    capsys: pytest.CaptureFixture[str],
    yaml_value: str,
    rendered: str,
    value: float,
    version: YamlVersion,
) -> None:
    node = _value(make_theatre, f"k: {yaml_value}\n")
    text = _text(node)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        data = _parse(f"k: {text}", version)

    assert text == rendered + "\n"
    assert data == {"k": value}
    assert isinstance(data, dict) and type(data["k"]) is float
    assert [str(w.message) for w in caught] == []
    assert capsys.readouterr() == ("", "")


def test_render_float_specials_read_back_as_floats(make_theatre: MakeTheatre) -> None:
    root = _root(make_theatre, {ROOT: "a: .inf\nb: -.Inf\nc: .NaN\n"})

    text = _text(root)
    data = _parse(text)

    assert text == "a: .inf\nb: -.inf\nc: .nan\n"
    assert isinstance(data, dict)
    assert data["a"] == math.inf
    assert data["b"] == -math.inf
    assert isinstance(data["c"], float) and math.isnan(data["c"])


# Plain under the YAML 1.2 core schema, but read as something else (or refused) by ruamel
# safe-load under YAML 1.2 and/or 1.1: dates, underscores, signed hex/octal, binary, 1.1 booleans,
# sexagesimals, the value key ``=`` (research D-10).
READER_DIVERGENT = [
    "2001-12-14",
    "1_000",
    "-1_0",
    "0x1_0",
    "-0x10",
    "+0x10",
    "-0o7",
    "0b101",
    "yes",
    "no",
    "on",
    "off",
    "y",
    "n",
    "1:20",
    "=",
]


@pytest.mark.parametrize("version", YAML_VERSIONS, ids=["yaml1.2", "yaml1.1"])
@pytest.mark.parametrize("s", READER_DIVERGENT)
def test_render_value_other_yaml_readers_misread_is_single_quoted(
    make_theatre: MakeTheatre, s: str, version: YamlVersion
) -> None:
    node = _value(make_theatre, f"k: '{s}'\n")

    assert _text(node) == f"'{s}'\n"
    assert _parse(f"k: {_text(node)}", version) == {"k": s}


# ``=`` misreads only as a value; ``<<`` only matters as a key (merge key).
@pytest.mark.parametrize("version", YAML_VERSIONS, ids=["yaml1.2", "yaml1.1"])
@pytest.mark.parametrize("s", [*(s for s in READER_DIVERGENT if s != "="), "<<"])
def test_render_key_other_yaml_readers_misread_is_single_quoted(
    make_theatre: MakeTheatre, s: str, version: YamlVersion
) -> None:
    root = _root(make_theatre, {ROOT: f"'{s}': x\n"})

    assert _text(root) == f"'{s}': x\n"
    assert _parse(_text(root), version) == {s: "x"}


@pytest.mark.parametrize("version", YAML_VERSIONS, ids=["yaml1.2", "yaml1.1"])
def test_render_key_every_reader_reads_back_stays_plain(
    make_theatre: MakeTheatre, version: YamlVersion
) -> None:
    root = _root(make_theatre, {ROOT: "=: x\n"})

    assert _text(root) == "=: x\n"
    assert _parse(_text(root), version) == {"=": "x"}


@pytest.mark.parametrize(
    ("yaml_key", "rendered"),
    [
        ("'true'", "'true'"),
        ("''", "''"),
        ("a b", "a b"),
        ("'1'", "'1'"),
        ("'a: b'", "'a: b'"),
        ("'- x'", "'- x'"),
        ('"line\\nbreak"', '"line\\nbreak"'),
        ("'#c'", "'#c'"),
    ],
)
def test_render_keys_needing_quotes_are_quoted(
    make_theatre: MakeTheatre, yaml_key: str, rendered: str
) -> None:
    root = _root(make_theatre, {ROOT: f"{yaml_key}: v\n"})

    assert _text(root) == f"{rendered}: v\n"
    assert _parse(_text(root)) == _data(root)


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("a\n", "k: |\n  a\n"),
        ("a", "k: |-\n  a\n"),
        ("a\n\n", "k: |+\n  a\n\n"),
        ("", "k: |-\n"),
        (" a\nb\n", "k: |2\n   a\n  b\n"),
        ("Be brief.\n", "k: |\n  Be brief.\n"),
        ("a\n\nb\n", "k: |\n  a\n\n  b\n"),
        ("\n", "k: |+\n\n"),
    ],
)
def test_render_text_include_as_literal_block_with_exact_chomping(
    make_theatre: MakeTheatre, content: str, expected: str
) -> None:
    root = _root(make_theatre, {ROOT: "k: file:p.txt\n", "p.txt": content})

    assert _text(root) == expected
    assert _parse(_text(root)) == {"k": content}


def test_render_text_include_at_root_of_path_is_block_with_body_at_column_two(
    make_theatre: MakeTheatre,
) -> None:
    root = unwrap(_root(make_theatre, {ROOT: "k: file:p.txt\n", "p.txt": " x\ny"}))
    assert isinstance(root, MappingNode)
    node = root.entries[0].value

    assert _text(node) == "|2-\n   x\n  y\n"
    assert _parse(_text(node)) == " x\ny"


def test_render_multiline_string_in_file_as_literal_block(make_theatre: MakeTheatre) -> None:
    root = _root(make_theatre, {ROOT: 'k: "one\\ntwo\\n"\nm:\n  j: "x\\ny"\n'})

    assert _text(root) == "k: |\n  one\n  two\nm:\n  j: |-\n    x\n    y\n"
    assert _parse(_text(root)) == _data(root)


def test_render_crlf_text_include_is_double_quoted(make_theatre: MakeTheatre) -> None:
    root = _root(make_theatre, {ROOT: "k: file:p.txt\n", "p.txt": b"a\r\nb\r\n"})

    assert _text(root) == 'k: "a\\r\\nb\\r\\n"\n'
    assert _parse(_text(root)) == {"k": "a\r\nb\r\n"}


def test_render_multiline_string_with_control_char_is_double_quoted(
    make_theatre: MakeTheatre,
) -> None:
    root = _root(make_theatre, {ROOT: 'k: "a\\x01\\nb"\n'})

    assert _text(root) == 'k: "a\\x01\\nb"\n'
    assert _parse(_text(root)) == {"k": "a\x01\nb"}


# --- T003: collection layout ------------------------------------------------------------------


def test_render_nested_mapping_uses_two_space_indent(make_theatre: MakeTheatre) -> None:
    root = _root(make_theatre, {ROOT: "a:\n    b:\n        c: 1\n    d: x\ne: true\n"})

    assert _text(root) == "a:\n  b:\n    c: 1\n  d: x\ne: true\n"


def test_render_list_under_key_is_indented_block_sequence(make_theatre: MakeTheatre) -> None:
    root = _root(make_theatre, {ROOT: "tools: [a, b]\n"})

    assert _text(root) == "tools:\n  - a\n  - b\n"


def test_render_list_of_mappings_is_compact(make_theatre: MakeTheatre) -> None:
    root = _root(
        make_theatre,
        {ROOT: "l:\n- name: x\n  count: 1\n- {name: z, sub: {p: q}}\n"},
    )

    assert _text(root) == "l:\n  - name: x\n    count: 1\n  - name: z\n    sub:\n      p: q\n"
    assert _parse(_text(root)) == _data(root)


def test_render_list_of_lists_is_compact(make_theatre: MakeTheatre) -> None:
    root = _root(make_theatre, {ROOT: "- [[a, b], c]\n- [d]\n- [{k: v, j: w}]\n"})

    assert _text(root) == ("- - - a\n    - b\n  - c\n- - d\n- - k: v\n    j: w\n")
    assert _parse(_text(root)) == _data(root)


def test_render_entries_and_items_keep_file_order(make_theatre: MakeTheatre) -> None:
    root = _root(make_theatre, {ROOT: "z: 1\na: 2\nm: [3, 1, 2]\n"})

    assert _text(root) == "z: 1\na: 2\nm:\n  - 3\n  - 1\n  - 2\n"


def test_render_empty_collections_inline(make_theatre: MakeTheatre) -> None:
    root = _root(
        make_theatre,
        {
            ROOT: "m: {}\nl: []\ninc: file:empty.yml\nitems:\n  - {}\n  - []\n  - - []\n",
            "empty.yml": "",
        },
    )

    assert _text(root) == "m: {}\nl: []\ninc: {}\nitems:\n  - {}\n  - []\n  - - []\n"
    assert _parse(_text(root)) == _data(root)


def test_render_empty_root_is_empty_mapping(make_theatre: MakeTheatre) -> None:
    root = _root(make_theatre, {ROOT: ""})

    assert _text(root) == "{}\n"
    assert _parse(_text(root)) == {}


def test_render_root_list_and_root_scalar(make_theatre: MakeTheatre) -> None:
    root = unwrap(_root(make_theatre, {ROOT: "l: [x, [], {}]\ns: 'true'\n"}))
    assert isinstance(root, MappingNode)
    items, scalar = (entry.value for entry in root.entries)

    assert _text(items) == "- x\n- []\n- {}\n"
    assert _text(scalar) == "'true'\n"
    assert _text(SequenceNode(origin=root.origin, flow=False, items=[])) == "[]\n"


def test_render_literal_block_in_list_item_and_compact_mapping_reads_back(
    make_theatre: MakeTheatre,
) -> None:
    root = _root(
        make_theatre,
        {
            ROOT: ("l:\n  - file:a.txt\n  - k: file:b.txt\n    j: file:a.txt\n  - - file:b.txt\n"),
            "a.txt": " lead\nx\n",
            "b.txt": "p\n\n",
        },
    )

    assert _text(root) == (
        "l:\n"
        "  - |2\n"
        "     lead\n"
        "    x\n"
        "  - k: |+\n"
        "      p\n"
        "\n"
        "    j: |2\n"
        "       lead\n"
        "      x\n"
        "  - - |+\n"
        "      p\n"
        "\n"
    )
    assert _parse(_text(root)) == _data(root)


def test_render_yaml_include_is_transparent_at_every_level(make_theatre: MakeTheatre) -> None:
    root = _root(
        make_theatre,
        {
            ROOT: "server: file:server.yml\nl:\n  - file:item.yml\n  - file:scalar.yml\n",
            "server.yml": "port: 8080\nhosts: file:hosts.yml\n",
            "hosts.yml": "[a, b]\n",
            "item.yml": "i: 1\nm: 2\n",
            "scalar.yml": "hello\n",
        },
    )

    assert _text(root) == (
        "server:\n  port: 8080\n  hosts:\n    - a\n    - b\nl:\n  - i: 1\n    m: 2\n  - hello\n"
    )
    assert _parse(_text(root)) == _data(root)


# --- T004: sources ----------------------------------------------------------------------------


def test_sources_mark_scalar_lines_and_block_headers_only(make_theatre: MakeTheatre) -> None:
    root, theatre = _load(
        make_theatre,
        {
            ROOT: (
                "name: demo\n"
                "server:\n"
                "  port: 8080\n"
                "empty: {}\n"
                "l:\n"
                "  - a\n"
                "  - k: v\n"
                "    sub:\n"
                "      - x\n"
                "prompt: file:p.md\n"
            ),
            "p.md": "line one\nline two\n",
        },
    )
    main = theatre / ".troupe" / ROOT
    prompt = theatre / ".troupe" / "p.md"

    lines = render(root)

    assert [line.text for line in lines] == [
        "name: demo",
        "server:",
        "  port: 8080",
        "empty: {}",
        "l:",
        "  - a",
        "  - k: v",
        "    sub:",
        "      - x",
        "prompt: |",
        "  line one",
        "  line two",
    ]
    assert [line.source for line in lines] == [
        main,
        None,
        main,
        None,
        None,
        main,
        main,
        None,
        main,
        prompt,
        None,
        None,
    ]


def test_sources_never_comment_block_body_lines(make_theatre: MakeTheatre) -> None:
    root, theatre = _load(make_theatre, {ROOT: "k: file:p.md\n", "p.md": "a\nb\n"})

    assert to_text(render(root), theatre) == "k: | # from .troupe/p.md\n  a\n  b\n"


def test_sources_inside_yaml_include_name_included_file(make_theatre: MakeTheatre) -> None:
    root, theatre = _load(
        make_theatre,
        {
            ROOT: "name: demo\nserver: file:server.yml\nl:\n  - file:s.yml\n",
            "server.yml": "port: 8080\nopts: {}\n",
            "s.yml": "only\n",
        },
    )

    assert to_text(render(root), theatre) == (
        "name: demo # from .troupe/troupe.yml\n"
        "server:\n"
        "  port: 8080 # from .troupe/server.yml\n"
        "  opts: {}\n"
        "l:\n"
        "  - only # from .troupe/s.yml\n"
    )


def test_text_include_source_is_included_file(make_theatre: MakeTheatre) -> None:
    root, theatre = _load(
        make_theatre,
        {ROOT: "a: file:t/one.md\nb: file:t/crlf.txt\n", "t/one.md": "x", "t/crlf.txt": b"y\r\n"},
    )

    assert [line.source for line in render(root)] == [
        theatre / ".troupe" / "t" / "one.md",
        None,
        theatre / ".troupe" / "t" / "crlf.txt",
    ]


def test_sources_for_file_outside_theatre_use_dotdot(
    make_theatre: MakeTheatre, tmp_path: Path
) -> None:
    (tmp_path / "shared").mkdir()
    (tmp_path / "shared" / "x.yml").write_text("v: 1\n", encoding="utf-8")
    root, theatre = _load(make_theatre, {ROOT: "s: file:../../shared/x.yml\n"})

    assert to_text(render(root), theatre) == "s:\n  v: 1 # from ../shared/x.yml\n"


def test_contract_example_with_sources(make_theatre: MakeTheatre) -> None:
    root, theatre = _load(
        make_theatre,
        {
            ROOT: (
                "name: demo\nserver: file:server.yml\ntools: [a, b]\nprompt: file:prompts/sys.md\n"
            ),
            "server.yml": "port: 8080\n",
            "prompts/sys.md": "Be brief.\n",
        },
    )

    assert to_text(render(root), theatre) == (
        "name: demo # from .troupe/troupe.yml\n"
        "server:\n"
        "  port: 8080 # from .troupe/server.yml\n"
        "tools:\n"
        "  - a # from .troupe/troupe.yml\n"
        "  - b # from .troupe/troupe.yml\n"
        "prompt: | # from .troupe/prompts/sys.md\n"
        "  Be brief.\n"
    )


def test_output_with_and_without_sources_parse_to_same_data(make_theatre: MakeTheatre) -> None:
    root, theatre = _load(
        make_theatre,
        {
            ROOT: "a: '# not a comment'\nb: file:p.md\nc: [x, {d: 1}]\n",
            "p.md": "text # with hash\n",
        },
    )
    lines = render(root)

    plain = to_text(lines, None)
    tagged = to_text(lines, theatre)

    assert tagged != plain
    assert _parse(tagged) == _parse(plain) == _data(root)


# --- T005: parse-back property ----------------------------------------------------------------

FIXTURES: dict[str, dict[str, str | bytes]] = {
    "flat-scalars": {
        ROOT: "s: hi\ni: 3\nf: 0.5\nb: false\nn: null\ninf: -.inf\nbig: 1e+20\nsmall: 1e-05\n"
    },
    "lookalike-strings": {ROOT: "a: ''\nb: '123'\nc: 'a: b'\nd: ' lead'\ne: it's\nf: 'yes'\n"},
    "quoted-keys": {ROOT: "'true': 1\n'': 2\na b: 3\n'1': 4\n'x: y': 5\n'- z': 6\n"},
    "nested": {ROOT: "a:\n  b:\n    c: [1, [2, [3, {}]], []]\n  d: {e: {f: g}}\n"},
    "list-of-mappings": {ROOT: "- a: 1\n  b: [x, y]\n- c: {d: e}\n- []\n- {}\n"},
    "text-includes": {
        ROOT: "a: file:1.txt\nb: file:2.txt\nc: file:3.txt\nd: file:4.txt\ne: file:5.txt\n",
        "1.txt": "Be brief.\n",
        "2.txt": "no newline",
        "3.txt": "keep\n\n\n",
        "4.txt": "",
        "5.txt": "  indented\n\tlines\n",
    },
    "crlf-and-control": {
        ROOT: 'a: file:crlf.txt\nb: "x\\x07y"\nc: "u\\u2028v"\n',
        "crlf.txt": b"one\r\ntwo\r\n",
    },
    "blocks-in-items": {
        ROOT: "l:\n  - file:m.txt\n  - k: file:m.txt\n    j: [file:m.txt]\n",
        "m.txt": " first\nsecond\n\n",
    },
    "yaml-includes": {
        ROOT: "inc: file:a.yml\nl: [file:b.yml, file:c.yml]\n",
        "a.yml": "x: file:t.md\ny: [1, 2]\n",
        "b.yml": "",
        "c.yml": "'just text'\n",
        "t.md": "doc\n",
    },
    "multiline-strings-in-file": {ROOT: 'a: "1\\n2"\nb:\n  - "x\\n\\ny\\n"\n  - |+\n    z\n\n'},
    "unicode": {ROOT: "名前: 日本😀\n'é: x': 'ü #'\n"},
    "reader-divergent-strings": {
        ROOT: "".join(f"'{s}': '{s}'\n" for s in READER_DIVERGENT)
        + "'<<': [yes, 'no', '2001-12-14']\n"
    },
    "scalar-root": {ROOT: "42\n"},
    "list-root": {ROOT: "- a\n- - b\n  - c\n"},
    "empty-root": {ROOT: ""},
}


@pytest.mark.parametrize("version", YAML_VERSIONS, ids=["yaml1.2", "yaml1.1"])
@pytest.mark.parametrize("files", FIXTURES.values(), ids=FIXTURES.keys())
def test_rendering_reads_back_as_tree_data_with_and_without_sources(
    make_theatre: MakeTheatre, files: dict[str, str | bytes], version: YamlVersion
) -> None:
    root, theatre = _load(make_theatre, files)
    lines = render(root)

    assert _parse(to_text(lines, None), version) == _data(root)
    assert _parse(to_text(lines, theatre), version) == _data(root)
