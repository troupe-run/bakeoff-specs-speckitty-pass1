"""writeback.collections: new entries, new collection values, kind changes (FR-011/012/016/019).

Every edit test applies the edits to a whole file text, asserts the exact resulting text, then
re-loads it through ``troupe.loader.load`` and compares the *whole* configuration with the
expected value, so the new value is confirmed and every other value is shown unchanged.
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from conftest import MakeTheatre
from troupe import yamlcore
from troupe.errors import WriteRefused
from troupe.loader import load
from troupe.paths import unwrap
from troupe.tree import (
    MappingEntry,
    MappingNode,
    Node,
    ScalarNode,
    SequenceNode,
    TextInclude,
    YamlInclude,
)
from troupe.writeback import TextEdit, apply_edits
from troupe.writeback.collections import (
    Value,
    convert_include_edits,
    detect_indent,
    entry_column,
    flow_append_edits,
    insertion_point,
    new_item_edits,
    new_key_edits,
    render_block_value,
    render_flow_value,
    replace_value_edits,
)

VIRTUAL = Path("/virtual/troupe.yml")

type MakeEdits = Callable[[MappingNode], list[TextEdit]]


def _load(text: str) -> MappingNode:
    root = load(VIRTUAL, overrides={VIRTUAL: text})
    assert isinstance(root, MappingNode)
    return root


def _plain(node: Node) -> Value:
    if isinstance(node, ScalarNode):
        return node.value
    if isinstance(node, MappingNode):
        return {entry.key: _plain(entry.value) for entry in node.entries}
    if isinstance(node, SequenceNode):
        return [_plain(item) for item in node.items]
    if isinstance(node, YamlInclude):
        return _plain(node.root)
    assert isinstance(node, TextInclude)
    return node.target.text


def _map(node: Node | None, *keys: str | int) -> Node:
    """Walk ``keys`` from ``node`` (mapping keys or sequence indices)."""
    assert node is not None
    for key in keys:
        if isinstance(key, int):
            assert isinstance(node, SequenceNode)
            node = node.items[key]
        else:
            assert isinstance(node, MappingNode)
            entry = node.get(key)
            assert entry is not None
            node = entry.value
    return node


def _mapping(root: MappingNode, *keys: str | int) -> MappingNode:
    node = _map(root, *keys)
    assert isinstance(node, MappingNode)
    return node


def _seq(root: MappingNode, *keys: str | int) -> SequenceNode:
    node = _map(root, *keys)
    assert isinstance(node, SequenceNode)
    return node


def _check(before: str, make: MakeEdits, expected_text: str, expected_value: Value) -> None:
    """Apply ``make``'s edits to ``before``; assert the exact text and the whole re-loaded value."""
    after = apply_edits(before, make(_load(before)))
    assert after == expected_text
    assert _plain(_load(after)) == expected_value


def _new_key(*keys: str, value: Value, at: tuple[str | int, ...] = (), step: int = 2) -> MakeEdits:
    def make(root: MappingNode) -> list[TextEdit]:
        mapping = _mapping(root, *at)
        path = ".".join(str(k) for k in [*at, *keys])
        return new_key_edits(mapping.origin.file, mapping, list(keys), value, step, path=path)

    return make


def _new_item(*at: str | int, value: Value, step: int = 2) -> MakeEdits:
    def make(root: MappingNode) -> list[TextEdit]:
        seq = _seq(root, *at)
        return new_item_edits(seq.origin.file, seq, value, step, path="x")

    return make


def _replace(*at: str | int, value: Value, step: int = 2) -> MakeEdits:
    def make(root: MappingNode) -> list[TextEdit]:
        parent = _map(root, *at[:-1]) if at[:-1] else root
        assert isinstance(parent, MappingNode | SequenceNode)
        old = _map(root, *at)
        return replace_value_edits(parent.origin.file, parent, at[-1], old, value, step, path="x")

    return make


# --- T030 detect_indent ---


@pytest.mark.parametrize(
    ("text", "step"),
    [
        ("a:\n  b: 1\n", 2),
        ("a:\n    b:\n        c: 1\n", 4),
        ("a:\n  - 1\n", 2),
        ("a:\n   - 1\n", 3),
        ("a: 1\nb: 2\n", 2),
        ("", 2),
        ("# only a comment\n", 2),
    ],
)
def test_detect_indent_reads_first_nesting_step(text: str, step: int) -> None:
    assert detect_indent(text) == step


def test_detect_indent_flush_sequences_give_no_information() -> None:
    assert detect_indent("a:\n- 1\nb:\n- 2\n") == 2
    assert detect_indent("a:\n- 1\nb:\n    c: 1\n") == 4


def test_detect_indent_skips_block_scalar_bodies() -> None:
    assert detect_indent("notes: |\n      body\nb:\n   c: 1\n") == 3


def test_detect_indent_ignores_compact_sequence_item_gap() -> None:
    # "- a" puts the key two columns right of the dash; that is not the indentation step.
    assert detect_indent("- a: 1\n  b:\n     c: 1\n") == 3


def test_detect_indent_skips_flow_collections() -> None:
    assert detect_indent("a: {b: 1}\nc:\n    d: 1\n") == 4


# --- T031 entry_column / insertion_point ---


def test_entry_column_of_compact_mapping_in_sequence_is_key_column() -> None:
    text = "l:\n- a: 1\n  b: 2\n"
    root = _load(text)
    assert entry_column(text, _mapping(root, "l", 0)) == 2
    assert entry_column(text, _seq(root, "l")) == 0


def test_entry_column_of_indented_sequence() -> None:
    text = "l:\n    - a\n"
    assert entry_column(text, _seq(_load(text), "l")) == 4


@pytest.mark.parametrize(
    ("text", "marker"),
    [
        # trailing comments at or deeper than the entries belong to the collection
        ("m:\n  a: 1\n  # c1\n    # c2\nx: 1\n", "x: 1"),
        # a less-indented comment ends the collection
        ("m:\n  a: 1\n# top\n  # after top\nx: 1\n", "# top"),
        # trailing blank lines stay after the new entry
        ("m:\n  a: 1\n\n\nx: 1\n", "\n\nx: 1"),
        # blank lines between belonging comments are kept inside
        ("m:\n  a: 1\n\n  # c\n\nx: 1\n", "\nx: 1"),
        # nested content and deeper comments of the last entry
        ("m:\n  a:\n    b: 1\n      # deep\nx: 1\n", "x: 1"),
        # a flush sequence value of the last entry belongs to it
        ("m:\n  a:\n  - 1\n  - 2\nx: 1\n", "x: 1"),
        # the last entry's block scalar body belongs to it, comment-like lines included
        ("m:\n  a: |\n    # not a comment\nx: 1\n", "x: 1"),
    ],
)
def test_insertion_point_of_nested_mapping(text: str, marker: str) -> None:
    assert insertion_point(text, _mapping(_load(text), "m")) == text.index(marker)


def test_insertion_point_keeps_keep_block_scalar_blank_lines_inside() -> None:
    text = "m:\n  a: |+\n    x\n\n\nx: 1\n"
    assert insertion_point(text, _mapping(_load(text), "m")) == text.index("x: 1")


def test_insertion_point_of_empty_item_sequence() -> None:
    text = "l:\n  - a\n  -\n  # c\nx: 1\n"
    assert insertion_point(text, _seq(_load(text), "l")) == text.index("x: 1")


def test_insertion_point_of_empty_document_is_end_of_text() -> None:
    text = "# header\n"
    assert insertion_point(text, _load(text)) == len(text)


# --- T032 new block keys ---


def test_new_key_goes_at_end_of_nested_mapping() -> None:
    _check(
        "model:\n  name: claude\nother: 1\n",
        _new_key("top_p", value=0.9, at=("model",)),
        "model:\n  name: claude\n  top_p: 0.9\nother: 1\n",
        {"model": {"name": "claude", "top_p": 0.9}, "other": 1},
    )


def test_new_key_goes_below_trailing_comments_and_above_less_indented_comment() -> None:
    _check(
        "model:\n"
        "  name: claude\n"
        "  temperature: 0.2\n"
        "  # tuning notes\n"
        "  #   more notes\n"
        "# section: tools\n"
        "tools: []\n",
        _new_key("top_p", value=0.9, at=("model",)),
        "model:\n"
        "  name: claude\n"
        "  temperature: 0.2\n"
        "  # tuning notes\n"
        "  #   more notes\n"
        "  top_p: 0.9\n"
        "# section: tools\n"
        "tools: []\n",
        {"model": {"name": "claude", "temperature": 0.2, "top_p": 0.9}, "tools": []},
    )


def test_new_key_goes_before_trailing_blank_lines() -> None:
    _check(
        "a:\n  b: 1\n\n\nc: 2\n",
        _new_key("d", value=3, at=("a",)),
        "a:\n  b: 1\n  d: 3\n\n\nc: 2\n",
        {"a": {"b": 1, "d": 3}, "c": 2},
    )


def test_new_root_key_goes_below_trailing_comments_before_blank_lines() -> None:
    _check(
        "a: 1\n# end notes\n\n",
        _new_key("b", value=2),
        "a: 1\n# end notes\nb: 2\n\n",
        {"a": 1, "b": 2},
    )


def test_new_key_at_eof_without_final_newline_keeps_it_missing() -> None:
    _check(
        "a:\n  b: 1",
        _new_key("c", value=2, at=("a",)),
        "a:\n  b: 1\n  c: 2",
        {"a": {"b": 1, "c": 2}},
    )


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("", "name: x\n"),
        ("\ufeff", "\ufeffname: x\n"),
        ("# header\n", "# header\nname: x\n"),
        ("# header", "# header\nname: x"),
    ],
)
def test_new_key_into_empty_document(before: str, after: str) -> None:
    _check(before, _new_key("name", value="x"), after, {"name": "x"})


def test_new_key_after_bom_first_line() -> None:
    _check("\ufeffa: 1\n", _new_key("b", value=2), "\ufeffa: 1\nb: 2\n", {"a": 1, "b": 2})


def test_new_key_after_keep_block_scalar_keeps_its_blank_lines() -> None:
    _check(
        "a: |+\n  x\n\n\nb: 1\n",
        _new_key("c", value=1),
        "a: |+\n  x\n\n\nb: 1\nc: 1\n",
        {"a": "x\n\n\n", "b": 1, "c": 1},
    )
    _check(
        "m:\n  t: |+\n    x\n\nb: 1\n",
        _new_key("u", value=1, at=("m",)),
        "m:\n  t: |+\n    x\n\n  u: 1\nb: 1\n",
        {"m": {"t": "x\n\n", "u": 1}, "b": 1},
    )


def test_new_key_copies_sibling_key_style() -> None:
    _check(
        'm:\n  "name": x\n',
        _new_key("top_p", value=0.9, at=("m",)),
        'm:\n  "name": x\n  "top_p": 0.9\n',
        {"m": {"name": "x", "top_p": 0.9}},
    )


def test_new_key_copies_sibling_value_style() -> None:
    _check(
        "m:\n  a: 'x'\n",
        _new_key("b", value="y", at=("m",)),
        "m:\n  a: 'x'\n  b: 'y'\n",
        {"m": {"a": "x", "b": "y"}},
    )


def test_new_key_without_sibling_is_plain() -> None:
    _check("", _new_key("a b", value="c d"), "a b: c d\n", {"a b": "c d"})


def test_new_key_falls_back_when_sibling_style_cannot_represent() -> None:
    # Sibling value plain, but "true" and "x: y" need quotes: minimal quoting is single.
    _check(
        "a: plain\n",
        _new_key("b", value="x: y"),
        "a: plain\nb: 'x: y'\n",
        {"a": "plain", "b": "x: y"},
    )
    _check(
        "a: 'q'\n",
        _new_key("null", value="it's\ttab\x01"),
        "a: 'q'\n'null': \"it's\\ttab\\x01\"\n",
        {"a": "q", "null": "it's\ttab\x01"},
    )


def test_new_non_string_value_is_plain_despite_quoted_sibling() -> None:
    _check("a: 'x'\n", _new_key("b", value=True), "a: 'x'\nb: true\n", {"a": "x", "b": True})


def test_intermediate_mappings_are_created_two_levels_deep() -> None:
    _check(
        'agents:\n  "coder":\n    name: c\nx: 1\n',
        _new_key("writer", "model", "name", value="w", at=("agents",)),
        'agents:\n  "coder":\n    name: c\n  "writer":\n    model:\n      name: w\nx: 1\n',
        {"agents": {"coder": {"name": "c"}, "writer": {"model": {"name": "w"}}}, "x": 1},
    )


def test_intermediate_mappings_use_file_indentation_of_four() -> None:
    text = "a:\n    b: 1\n"
    _check(
        text,
        _new_key("c", "d", value=2, at=("a",), step=detect_indent(text)),
        "a:\n    b: 1\n    c:\n        d: 2\n",
        {"a": {"b": 1, "c": {"d": 2}}},
    )


def test_new_mapping_value_is_block_style() -> None:
    _check(
        "a: 1\n",
        _new_key("m", value={"k": "v", "n": {"x": None}}),
        "a: 1\nm:\n  k: v\n  n:\n    x: null\n",
        {"a": 1, "m": {"k": "v", "n": {"x": None}}},
    )


def test_new_list_value_is_indented_by_step_without_sibling_sequence() -> None:
    _check(
        "a: 1\n",
        _new_key("l", value=["x", {"k": 1, "j": [2]}, [3, 4]]),
        "a: 1\nl:\n  - x\n  - k: 1\n    j:\n      - 2\n  - - 3\n    - 4\n",
        {"a": 1, "l": ["x", {"k": 1, "j": [2]}, [3, 4]]},
    )


def test_new_list_value_copies_flush_sibling_sequence() -> None:
    _check(
        "a:\n- 1\nb: 2\n",
        _new_key("l", value=["x"]),
        "a:\n- 1\nb: 2\nl:\n- x\n",
        {"a": [1], "b": 2, "l": ["x"]},
    )


def test_new_empty_collections_are_written_in_flow_form() -> None:
    _check(
        "a: 1\n",
        _new_key("m", value={"e": {}, "l": []}),
        "a: 1\nm:\n  e: {}\n  l: []\n",
        {"a": 1, "m": {"e": {}, "l": []}},
    )


def test_new_multiline_string_is_literal_block() -> None:
    _check(
        "m:\n  a: 1\nx: 2",
        _new_key("notes", value="line 1\nline 2\n", at=("m",)),
        "m:\n  a: 1\n  notes: |\n    line 1\n    line 2\nx: 2",
        {"m": {"a": 1, "notes": "line 1\nline 2\n"}, "x": 2},
    )


def test_new_multiline_string_at_eof_without_newline_gets_final_break() -> None:
    _check("a: 1", _new_key("n", value="p\nq"), "a: 1\nn: |-\n  p\n  q\n", {"a": 1, "n": "p\nq"})


def test_new_keep_block_before_blank_lines_is_refused() -> None:
    before = "m:\n  a: 1\n\nx: 2\n"
    root = _load(before)
    mapping = _mapping(root, "m")
    with pytest.raises(WriteRefused, match=r"m\.notes"):
        new_key_edits(mapping.origin.file, mapping, ["notes"], "a\n\n", 2, path="m.notes")


def test_new_key_into_compact_mapping_in_sequence() -> None:
    _check(
        "l:\n- name: a\n  role: b\n- name: c\n",
        _new_key("model", value="m", at=("l", 0)),
        "l:\n- name: a\n  role: b\n  model: m\n- name: c\n",
        {"l": [{"name": "a", "role": "b", "model": "m"}, {"name": "c"}]},
    )


def test_new_key_uses_crlf_in_crlf_file() -> None:
    _check(
        "m:\r\n  a: 1\r\nx: 2\r\n",
        _new_key("b", "c", value=[1], at=("m",)),
        "m:\r\n  a: 1\r\n  b:\r\n    c:\r\n      - 1\r\nx: 2\r\n",
        {"m": {"a": 1, "b": {"c": [1]}}, "x": 2},
    )


def test_new_key_rejects_empty_key_list() -> None:
    root = _load("a: 1\n")
    with pytest.raises(ValueError, match="at least one key"):
        new_key_edits(root.origin.file, root, [], 1, 2, path="x")


# --- T032 new block list items ---


def test_append_to_indented_block_list() -> None:
    _check(
        "tools:\n  - read\n  - write\n  # more later\nx: 1\n",
        _new_item("tools", value="search"),
        "tools:\n  - read\n  - write\n  # more later\n  - search\nx: 1\n",
        {"tools": ["read", "write", "search"], "x": 1},
    )


def test_append_to_flush_block_list_column_zero_comment_belongs_to_it() -> None:
    _check(
        "tools:\n- read\n# section\nx: 1\n",
        _new_item("tools", value="write"),
        "tools:\n- read\n# section\n- write\nx: 1\n",
        {"tools": ["read", "write"], "x": 1},
    )


def test_append_copies_previous_item_quoting() -> None:
    _check(
        'l:\n  - "a"\n',
        _new_item("l", value="b"),
        'l:\n  - "a"\n  - "b"\n',
        {"l": ["a", "b"]},
    )


def test_append_mapping_item_uses_compact_form() -> None:
    _check(
        "l:\n- name: a\n  role: b\n- x",
        _new_item("l", value={"name": "c", "tools": ["t"]}),
        "l:\n- name: a\n  role: b\n- x\n- name: c\n  tools:\n    - t",
        {"l": [{"name": "a", "role": "b"}, "x", {"name": "c", "tools": ["t"]}]},
    )


def test_append_after_empty_item() -> None:
    _check(
        "l:\n  - a\n  -\nx: 1\n",
        _new_item("l", value="b"),
        "l:\n  - a\n  -\n  - b\nx: 1\n",
        {"l": ["a", None, "b"], "x": 1},
    )


def test_append_multiline_item_is_literal_block() -> None:
    _check(
        "l:\n  - a\nx: 1\n",
        _new_item("l", value="p\nq\n"),
        "l:\n  - a\n  - |\n    p\n    q\nx: 1\n",
        {"l": ["a", "p\nq\n"], "x": 1},
    )


def test_append_to_nested_compact_list() -> None:
    _check(
        "l:\n- - a\n  - b\n- c\n",
        _new_item("l", 0, value="z"),
        "l:\n- - a\n  - b\n  - z\n- c\n",
        {"l": [["a", "b", "z"], "c"]},
    )


def test_render_block_value_lines() -> None:
    assert render_block_value({"a": [1, {"b": 2}]}, 2, 2) == ["  a:", "    - 1", "    - b: 2"]
    assert render_block_value({"a": [1]}, 0, 4, seq_offset=0) == ["a:", "- 1"]
    assert render_block_value("scalar", 0, 2) == []


# --- T033 flow collections ---


def test_flow_list_append_keeps_comment_column() -> None:
    _check(
        "tools: [read, write]   # core\n",
        _new_item("tools", value="search"),
        "tools: [read, write, search] # core\n",
        {"tools": ["read", "write", "search"]},
    )


def test_flow_list_append_keeps_comment_column_when_room() -> None:
    _check(
        "tools: [a]          # core\nx: 1\n",
        _new_item("tools", value="b"),
        "tools: [a, b]       # core\nx: 1\n",
        {"tools": ["a", "b"], "x": 1},
    )


def test_flow_mapping_append_copies_separator_and_last_key_style() -> None:
    _check(
        "m: {'a': 'x',b: 'y'}\n",
        _new_key("c", value="z", at=("m",)),
        "m: {'a': 'x',b: 'y',c: 'z'}\n",
        {"m": {"a": "x", "b": "y", "c": "z"}},
    )


def test_empty_flow_collections_get_entry_without_separator() -> None:
    _check("l: []\n", _new_item("l", value="c"), "l: [c]\n", {"l": ["c"]})
    _check("m: {}\n", _new_key("b", value=2, at=("m",)), "m: {b: 2}\n", {"m": {"b": 2}})


def test_flow_parent_gets_flow_collection_and_nested_intermediate_mappings() -> None:
    _check(
        "m: {a: 1}  # c\n",
        _new_key("b", "c", value=[1, {"d": "e f"}], at=("m",)),
        "m: {a: 1, b: {c: [1, {d: e f}]}} # c\n",
        {"m": {"a": 1, "b": {"c": [1, {"d": "e f"}]}}},
    )


def test_multiline_string_in_flow_is_double_quoted() -> None:
    _check(
        "l: [a]\n",
        _new_item("l", value="x\ny"),
        'l: [a, "x\\ny"]\n',
        {"l": ["a", "x\ny"]},
    )


def test_flow_append_in_multiline_flow_list_goes_on_last_entry_line() -> None:
    _check(
        "l: [\n  a,\n  b  # last\n]\n",
        _new_item("l", value="c"),
        "l: [\n  a,\n  b, c # last\n]\n",
        {"l": ["a", "b", "c"]},
    )


def test_flow_mapping_append_after_empty_value() -> None:
    _check(
        "m: {a: }\n",
        _new_key("b", value=1, at=("m",)),
        "m: {a: , b: 1}\n",
        {"m": {"a": None, "b": 1}},
    )


def test_flow_value_quotes_flow_indicators() -> None:
    assert render_flow_value(["a,b", "c"]) == "['a,b', c]"
    assert render_flow_value("x", "double") == '"x"'
    assert render_flow_value({}) == "{}"


def test_flow_append_argument_errors() -> None:
    root = _load("m: {a: 1}\nl: [1]\n")
    mapping, seq = _mapping(root, "m"), _seq(root, "l")
    with pytest.raises(ValueError, match="needs a key"):
        flow_append_edits(root.origin.file, mapping, None, 1)
    with pytest.raises(ValueError, match="no key"):
        flow_append_edits(root.origin.file, seq, "k", 1)


# --- T034 kind-changing replacement ---


def test_scalar_to_block_mapping_keeps_key_line_through_comment() -> None:
    _check(
        "k: value  # about k\nx: 1\n",
        _replace("k", value={"m": 1, "n": [2]}),
        "k:        # about k\n  m: 1\n  n:\n    - 2\nx: 1\n",
        {"k": {"m": 1, "n": [2]}, "x": 1},
    )


def test_scalar_to_block_list_without_comment_drops_value_and_spaces() -> None:
    _check(
        "a:\n  k: 'v'\n  z: 0\n",
        _replace("a", "k", value=["p", "q"]),
        "a:\n  k:\n    - p\n    - q\n  z: 0\n",
        {"a": {"k": ["p", "q"], "z": 0}},
    )


def test_null_to_block_mapping_inserts_below_key_line() -> None:
    _check(
        "a:   # empty for now\nb: 1",
        _replace("a", value={"c": 2}),
        "a:   # empty for now\n  c: 2\nb: 1",
        {"a": {"c": 2}, "b": 1},
    )


def test_null_on_last_line_without_newline_to_mapping() -> None:
    _check("b: 1\na:", _replace("a", value={"c": 2}), "b: 1\na:\n  c: 2", {"b": 1, "a": {"c": 2}})


def test_block_list_to_scalar_keeps_comments_after_last_entry() -> None:
    _check(
        "k:   # list\n  - a\n  - b\n  # trailing\nx: 1\n",
        _replace("k", value="s"),
        "k: s # list\n  # trailing\nx: 1\n",
        {"k": "s", "x": 1},
    )


def test_block_mapping_to_scalar_at_eof_without_newline() -> None:
    _check("x: 1\nk:\n  a: 1\n  b: 2", _replace("k", value=5), "x: 1\nk: 5", {"x": 1, "k": 5})


def test_block_mapping_to_empty_list() -> None:
    _check("k:\n  a: 1\nx: 1\n", _replace("k", value=[]), "k: []\nx: 1\n", {"k": [], "x": 1})


def test_flow_list_in_block_parent_becomes_block_list() -> None:
    _check(
        "tools: [a, b]  # core\nx: 1\n",
        _replace("tools", value=["a", "b", "c"]),
        "tools:         # core\n  - a\n  - b\n  - c\nx: 1\n",
        {"tools": ["a", "b", "c"], "x": 1},
    )


def test_block_collection_to_block_collection_uses_old_entry_column() -> None:
    _check(
        "k:\n- a\n- b\nx: 1\n",
        _replace("k", value=["c"]),
        "k:\n- c\nx: 1\n",
        {"k": ["c"], "x": 1},
    )
    _check(
        "k:\n    a: 1\nx: 1\n",
        _replace("k", value=["c"]),
        "k:\n    - c\nx: 1\n",
        {"k": ["c"], "x": 1},
    )


def test_flush_list_to_mapping_is_indented_by_step() -> None:
    _check(
        "k:\n- a\nx: 1\n",
        _replace("k", value={"m": 1}),
        "k:\n  m: 1\nx: 1\n",
        {"k": {"m": 1}, "x": 1},
    )


def test_block_scalar_to_mapping_removes_header_and_body() -> None:
    _check(
        "k: |  # text\n  line\n\nx: 1\n",
        _replace("k", value={"m": 1}),
        "k:    # text\n  m: 1\n\nx: 1\n",
        {"k": {"m": 1}, "x": 1},
    )


def test_collection_to_multiline_string_is_literal_block() -> None:
    _check(
        "k:\n  a: 1\nx: 1\n",
        _replace("k", value="p\nq\n"),
        "k: |\n  p\n  q\nx: 1\n",
        {"k": "p\nq\n", "x": 1},
    )


def test_sequence_item_scalar_to_mapping() -> None:
    _check(
        "l:\n  - a  # first\n  - b\n",
        _replace("l", 0, value={"m": 1}),
        "l:\n  -    # first\n    m: 1\n  - b\n",
        {"l": [{"m": 1}, "b"]},
    )


def test_sequence_item_compact_mapping_to_list_and_scalar() -> None:
    _check(
        "l:\n- a: 1\n  b: 2\n- x\n",
        _replace("l", 0, value=[1, 2]),
        "l:\n- - 1\n  - 2\n- x\n",
        {"l": [[1, 2], "x"]},
    )
    _check(
        "l:\n- a: 1\n  b: 2\n- x\n",
        _replace("l", 0, value="s"),
        "l:\n- s\n- x\n",
        {"l": ["s", "x"]},
    )


def test_sequence_item_block_list_on_next_lines_to_scalar() -> None:
    _check(
        "l:\n  -\n    - a\n  - b\n",
        _replace("l", 0, value=1),
        "l:\n  - 1\n  - b\n",
        {"l": [1, "b"]},
    )


def test_flow_parent_replacement_is_flow() -> None:
    _check(
        "m: {a: 1, b: x}  # c\n",
        _replace("m", "b", value={"p": [1]}),
        "m: {a: 1, b: {p: [1]}} # c\n",
        {"m": {"a": 1, "b": {"p": [1]}}},
    )
    _check("m: {a: }\n", _replace("m", "a", value=[1]), "m: {a: [1] }\n", {"m": {"a": [1]}})


def test_value_on_next_line_with_comment_is_refused() -> None:
    before = "k:\n  value  # keep me\nx: 1\n"
    root = _load(before)
    with pytest.raises(WriteRefused, match=r"cannot replace k in .*drop a comment"):
        replace_value_edits(root.origin.file, root, "k", _map(root, "k"), {"a": 1}, 2, path="k")


def test_multiline_flow_value_with_inner_comment_is_refused() -> None:
    before = "k: [a,  # first\n  b]\nx: 1\n"
    root = _load(before)
    with pytest.raises(WriteRefused, match="drop a comment"):
        replace_value_edits(root.origin.file, root, "k", _map(root, "k"), {"a": 1}, 2, path="k")


def test_multiline_flow_value_without_comment_is_replaced() -> None:
    _check(
        "k: [a,\n  b]\nx: 1\n",
        _replace("k", value={"m": 1}),
        "k:\n  m: 1\nx: 1\n",
        {"k": {"m": 1}, "x": 1},
    )


def test_replacement_in_crlf_file_uses_crlf() -> None:
    _check(
        "k: v\r\nx: 1\r\n",
        _replace("k", value=["a"]),
        "k:\r\n  - a\r\nx: 1\r\n",
        {"k": ["a"], "x": 1},
    )


# --- Sweep: every collection of varied files accepts every value shape ---

_SWEEP_FILES = [
    "a:\n  b: 1\n  # c\n\nl:\n- x\n- y: 1\n  z: [1, 2]  # zz\n# end\n",
    "\ufeffroot:\r\n    k: 'v'\r\n    s:\r\n        - \"q\"\r\n    t: |\r\n        body\r\n",
    "m: {a: 1, b: [x]}   # flow\nn:\n  - - p\n    - q\n  -\n  - {r: s}\nlast: end",
    "x:\n  deep:\n    deeper:\n      leaf: 1\n      # deeper note\n    # deep note\n  # x note\n",
]
_SWEEP_VALUES: list[Value] = [
    1,
    None,
    "plain text",
    "needs: quotes",
    "multi\nline\n",
    {"k": "v", "n": [1, {"o": "p"}]},
    [1, [2, 3], {"a": "b"}],
    {},
    [],
]


def _collections(node: Node, segments: tuple[str | int, ...] = ()) -> list[tuple[str | int, ...]]:
    found: list[tuple[str | int, ...]] = []
    if isinstance(node, MappingNode):
        found.append(segments)
        for entry in node.entries:
            found += _collections(entry.value, (*segments, entry.key))
    elif isinstance(node, SequenceNode):
        found.append(segments)
        for index, item in enumerate(node.items):
            found += _collections(item, (*segments, index))
    return found


def _with(value: Value, segments: tuple[str | int, ...], new: Value) -> Value:
    """``value`` with ``new`` added at ``segments`` (a mapping gets key ``new_key``)."""
    if not segments:
        if isinstance(value, dict):
            return {**value, "new_key": new}
        assert isinstance(value, list)
        return [*value, new]
    head, rest = segments[0], segments[1:]
    if isinstance(value, dict):
        assert isinstance(head, str)
        return {k: (_with(v, rest, new) if k == head else v) for k, v in value.items()}
    assert isinstance(value, list) and isinstance(head, int)
    return [_with(v, rest, new) if i == head else v for i, v in enumerate(value)]


@pytest.mark.parametrize("text", _SWEEP_FILES)
@pytest.mark.parametrize("value", _SWEEP_VALUES)
def test_sweep_new_entry_reads_back_and_keeps_other_bytes(text: str, value: Value) -> None:
    root = _load(text)
    before = _plain(root)
    step = detect_indent(text)
    for segments in _collections(root):
        node = _map(root, *segments) if segments else root
        file = node.origin.file
        if isinstance(node, MappingNode):
            edits = new_key_edits(file, node, ["new_key"], value, step, path="p")
        else:
            assert isinstance(node, SequenceNode)
            edits = new_item_edits(file, node, value, step, path="p")
        after = apply_edits(text, edits)
        assert _plain(_load(after)) == _with(before, segments, value), (segments, after)
        (edit,) = edits
        assert after[: edit.start] == text[: edit.start]
        assert after[len(after) - (len(text) - edit.end) :] == text[edit.end :]


def _replaced(value: Value, segments: tuple[str | int, ...], new: Value) -> Value:
    head, rest = segments[0], segments[1:]
    if isinstance(value, dict):
        assert isinstance(head, str)
        return {
            k: (_replaced(v, rest, new) if rest else new) if k == head else v
            for k, v in value.items()
        }
    assert isinstance(value, list) and isinstance(head, int)
    return [
        (_replaced(v, rest, new) if rest else new) if i == head else v for i, v in enumerate(value)
    ]


def _values(node: Node, segments: tuple[str | int, ...] = ()) -> list[tuple[str | int, ...]]:
    found: list[tuple[str | int, ...]] = [segments] if segments else []
    if isinstance(node, MappingNode):
        for entry in node.entries:
            found += _values(entry.value, (*segments, entry.key))
    elif isinstance(node, SequenceNode):
        for index, item in enumerate(node.items):
            found += _values(item, (*segments, index))
    return found


@pytest.mark.parametrize("text", _SWEEP_FILES)
@pytest.mark.parametrize("value", _SWEEP_VALUES)
def test_sweep_kind_change_reads_back_or_is_refused(text: str, value: Value) -> None:
    root = _load(text)
    before = _plain(root)
    step = detect_indent(text)
    for segments in _values(root):
        old = _map(root, *segments)
        new_is_collection = isinstance(value, dict | list)
        if isinstance(old, MappingNode | SequenceNode) is new_is_collection and not (
            new_is_collection and old.origin.file.text[old.origin.start] in "[{"
        ):
            continue  # same kind: not this function's business (except flow -> block)
        parent = _map(root, *segments[:-1]) if segments[:-1] else root
        assert isinstance(parent, MappingNode | SequenceNode)
        try:
            edits = replace_value_edits(
                parent.origin.file, parent, segments[-1], old, value, step, path="p"
            )
        except WriteRefused:
            continue
        after = apply_edits(text, edits)
        assert _plain(_load(after)) == _replaced(before, segments, value), (segments, after)


# --- Review cycle 1: D1 open end after a block scalar, D2 flow ":" handling ---


def _refused(before: str, make: MakeEdits) -> None:
    with pytest.raises(WriteRefused, match="ends inside a block scalar"):
        make(_load(before))


@pytest.mark.parametrize(
    ("before", "make"),
    [
        ("a:\n  s: >\n    x", _new_key("t", value=1, at=("a",))),
        ("a:\n  s: |+\n    x", _new_key("t", value=1, at=("a",))),
        ("s: |\n  x", _new_key("t", value=1)),
        ("s: >+\n  x", _new_key("t", value=1)),
        ("l:\n  - |\n    x", _new_item("l", value="y")),
    ],
)
def test_append_after_open_block_scalar_at_eof_is_refused(before: str, make: MakeEdits) -> None:
    _refused(before, make)


def test_append_after_strip_block_scalar_at_eof_is_written() -> None:
    _check("s: |-\n  x", _new_key("t", value=1), "s: |-\n  x\nt: 1", {"s": "x", "t": 1})
    _check(
        "l:\n  - >-\n    x",
        _new_item("l", value="y"),
        "l:\n  - >-\n    x\n  - y",
        {"l": ["x", "y"]},
    )


def test_kind_change_below_anchor_at_eof_after_block_scalar_keeps_it() -> None:
    _check(
        "s: |\n  x\nk:",
        _replace("k", value={"m": 1}),
        "s: |\n  x\nk:\n  m: 1",
        {"s": "x\n", "k": {"m": 1}},
    )


def test_kind_change_below_dash_at_eof_after_block_scalar_item_keeps_it() -> None:
    before = "l:\n- |\n  x\n-"
    _check(
        before,
        _replace("l", 1, value=[1]),
        "l:\n- |\n  x\n-\n  - 1",
        {"l": ["x\n", [1]]},
    )


def test_flow_list_append_after_items_ending_in_colon_keeps_them_strings() -> None:
    _check(
        "l: [C:, D:]  # drives\n",
        _new_item("l", value="E"),
        "l: [C:, D:, E] # drives\n",
        {"l": ["C:", "D:", "E"]},
    )


def test_flow_mapping_key_ending_in_colon_is_not_renamed() -> None:
    _check(
        "m: {a:}\n",
        _new_key("c", value=1, at=("m",)),
        "m: {a:, c: 1}\n",
        {"m": {"a:": None, "c": 1}},
    )
    _check(
        "m: {x: 1, a:}\n",
        _new_key("c", value=1, at=("m",)),
        "m: {x: 1, a:, c: 1}\n",
        {"m": {"x": 1, "a:": None, "c": 1}},
    )


def test_flow_mapping_value_ending_in_colon_stays_parseable() -> None:
    _check(
        "m: {a: b:}\n",
        _new_key("c", value=1, at=("m",)),
        "m: {a: b:, c: 1}\n",
        {"m": {"a": "b:", "c": 1}},
    )


def test_flow_replace_of_empty_value_of_key_ending_in_colon_keeps_key() -> None:
    _check("m: {a:}\n", _replace("m", "a:", value=[1]), "m: {a:: [1]}\n", {"m": {"a:": [1]}})


# --- Include conversion to mapping form (include overrides FR-006, D-2 to D-5, D-11, R-7) ---

_INCLUDED = {"agents/coder.yaml": "model: m\n", "agents/a.yaml": "name: a\n"}


def _convert(
    make_theatre: MakeTheatre, before: str, *at: str | int, keys: tuple[str, ...], value: Value
) -> str:
    """Load ``before`` as a real theatre's troupe.yml, convert the include at ``at``, apply.

    ``at`` locates the include from the root (empty: the whole document is the include); the
    step is the file's own (``detect_indent``). The result must still be YAML.
    """
    theatre = make_theatre({"troupe.yml": before, **_INCLUDED})
    root = load(theatre / ".troupe" / "troupe.yml")
    parent: MappingNode | SequenceNode | None = None
    slot: str | int | None = None
    if at:
        holder = _map(root, *at[:-1])
        assert isinstance(holder, MappingNode | SequenceNode)
        parent, slot = holder, at[-1]
    include = _map(root, *at)
    assert isinstance(include, YamlInclude)
    file = include.origin.file
    assert file.text == before
    path = ".".join(str(segment) for segment in (*at, *keys))
    edits = convert_include_edits(
        file, parent, slot, include.origin, list(keys), value, detect_indent(before), path=path
    )
    after = apply_edits(before, edits)
    assert yamlcore.compose(after, "converted") is not None
    return after


def test_convert_block_include_keeps_comment_gap_on_key_line(make_theatre: MakeTheatre) -> None:
    after = _convert(
        make_theatre,
        "coder: file:agents/coder.yaml  # c\n",
        "coder",
        keys=("temperature",),
        value=0.3,
    )
    assert after == "coder:  # c\n  $ref: file:agents/coder.yaml\n  temperature: 0.3\n"


@pytest.mark.parametrize(
    ("before", "expected"),
    [
        (
            "coder: file:agents/coder.yaml\n",
            "coder:\n  $ref: file:agents/coder.yaml\n  temperature: 0.3\n",
        ),
        # trailing spaces after the value stay on the key's line, as they were
        (
            "coder: file:agents/coder.yaml   \n",
            "coder:   \n  $ref: file:agents/coder.yaml\n  temperature: 0.3\n",
        ),
        # a file without a final line break still ends without one
        (
            "coder: file:agents/coder.yaml",
            "coder:\n  $ref: file:agents/coder.yaml\n  temperature: 0.3",
        ),
    ],
)
def test_convert_block_include_without_comment(
    make_theatre: MakeTheatre, before: str, expected: str
) -> None:
    after = _convert(make_theatre, before, "coder", keys=("temperature",), value=0.3)
    assert after == expected


def test_convert_block_include_in_four_space_file_indents_four(make_theatre: MakeTheatre) -> None:
    before = "team:\n    lead: ann\nagents:\n    coder: file:agents/coder.yaml  # c\n"
    after = _convert(make_theatre, before, "agents", "coder", keys=("temperature",), value=0.3)
    assert after == (
        "team:\n    lead: ann\nagents:\n    coder:  # c\n"
        "        $ref: file:agents/coder.yaml\n        temperature: 0.3\n"
    )


def test_convert_block_include_with_value_on_next_line(make_theatre: MakeTheatre) -> None:
    before = "coder:\n  file:agents/coder.yaml  # c\nother: 1\n"
    after = _convert(make_theatre, before, "coder", keys=("temperature",), value=0.3)
    assert after == "coder:\n  $ref: file:agents/coder.yaml  # c\n  temperature: 0.3\nother: 1\n"


def test_convert_block_include_with_intermediate_keys_creates_nested_override(
    make_theatre: MakeTheatre,
) -> None:
    after = _convert(
        make_theatre,
        "coder: file:agents/coder.yaml  # c\nother: 1\n",
        "coder",
        keys=("model", "params", "temperature"),
        value=0.3,
    )
    assert after == (
        "coder:  # c\n  $ref: file:agents/coder.yaml\n"
        "  model:\n    params:\n      temperature: 0.3\nother: 1\n"
    )


@pytest.mark.parametrize(
    ("key", "value", "rendered"),
    [
        ("tools", ["read", "write"], "  tools:\n    - read\n    - write\n"),
        ("limits", {"tokens": 100, "turns": 3}, "  limits:\n    tokens: 100\n    turns: 3\n"),
        ("prompt", "Be brief.\nBe kind.\n", "  prompt: |\n    Be brief.\n    Be kind.\n"),
        ("empty", [], "  empty: []\n"),
        ("label", "a: b", "  label: 'a: b'\n"),
    ],
)
def test_convert_block_include_with_collection_and_multiline_values_uses_step1_renderers(
    make_theatre: MakeTheatre, key: str, value: Value, rendered: str
) -> None:
    before = "coder: file:agents/coder.yaml\nother: 1\n"
    after = _convert(make_theatre, before, "coder", keys=(key,), value=value)
    assert after == "coder:\n  $ref: file:agents/coder.yaml\n" + rendered + "other: 1\n"


@pytest.mark.parametrize(
    ("before", "keys", "value", "expected"),
    [
        # contract D-3 example; the longer line keeps one space before the comment (FR-020)
        (
            "agents: {coder: file:agents/coder.yaml}  # c\n",
            ("t",),
            1,
            "agents: {coder: {$ref: file:agents/coder.yaml, t: 1}} # c\n",
        ),
        # with room, the comment keeps its column (FR-020)
        (
            "agents: {coder: file:agents/coder.yaml}                # c\n",
            ("t",),
            1,
            "agents: {coder: {$ref: file:agents/coder.yaml, t: 1}}  # c\n",
        ),
        # intermediate keys are nested flow mappings
        (
            "agents: {coder: file:agents/coder.yaml, x: 1}\n",
            ("model", "t"),
            1,
            "agents: {coder: {$ref: file:agents/coder.yaml, model: {t: 1}}, x: 1}\n",
        ),
        # a multi-line string in flow context is double-quoted (step-1 rule)
        (
            "agents: {coder: file:agents/coder.yaml}\n",
            ("prompt",),
            "a\nb",
            'agents: {coder: {$ref: file:agents/coder.yaml, prompt: "a\\nb"}}\n',
        ),
    ],
)
def test_convert_include_in_flow_mapping_writes_flow_mapping_form(
    make_theatre: MakeTheatre, before: str, keys: tuple[str, ...], value: Value, expected: str
) -> None:
    after = _convert(make_theatre, before, "agents", "coder", keys=keys, value=value)
    assert after == expected


def test_convert_include_in_flow_list_writes_flow_mapping_item(make_theatre: MakeTheatre) -> None:
    after = _convert(
        make_theatre, "list: [file:agents/a.yaml, x]\n", "list", 0, keys=("k",), value=1
    )
    assert after == "list: [{$ref: file:agents/a.yaml, k: 1}, x]\n"


@pytest.mark.parametrize(
    ("before", "expected"),
    [
        (
            "list:\n  - file:agents/a.yaml  # c\n  - plain\n",
            "list:\n  - $ref: file:agents/a.yaml  # c\n    k: 1\n  - plain\n",
        ),
        ("list:\n- file:agents/a.yaml\n", "list:\n- $ref: file:agents/a.yaml\n  k: 1\n"),
        (
            "list:\n  -   file:agents/a.yaml\n",
            "list:\n  -   $ref: file:agents/a.yaml\n      k: 1\n",
        ),
    ],
)
def test_convert_block_list_item_include(
    make_theatre: MakeTheatre, before: str, expected: str
) -> None:
    assert _convert(make_theatre, before, "list", 0, keys=("k",), value=1) == expected


@pytest.mark.parametrize(
    ("before", "expected"),
    [
        ("file:agents/coder.yaml\n", "$ref: file:agents/coder.yaml\ntemperature: 0.3\n"),
        # a leading BOM is not a column: the overrides still start at column 0
        (
            "\ufefffile:agents/coder.yaml  # c\n",
            "\ufeff$ref: file:agents/coder.yaml  # c\ntemperature: 0.3\n",
        ),
    ],
)
def test_convert_document_root_include(
    make_theatre: MakeTheatre, before: str, expected: str
) -> None:
    assert _convert(make_theatre, before, keys=("temperature",), value=0.3) == expected


@pytest.mark.parametrize("written", ['"file:agents/coder.yaml"', "'file:agents/coder.yaml'"])
def test_convert_keeps_quoted_include_bytes_verbatim(
    make_theatre: MakeTheatre, written: str
) -> None:
    before = f"coder: {written}  # c\n"
    after = _convert(make_theatre, before, "coder", keys=("temperature",), value=0.3)
    assert after == f"coder:  # c\n  $ref: {written}\n  temperature: 0.3\n"


def test_convert_crlf_file_keeps_crlf(make_theatre: MakeTheatre) -> None:
    before = "name: t\r\ncoder: file:agents/coder.yaml  # c\r\nother: 1\r\n"
    after = _convert(make_theatre, before, "coder", keys=("model", "t"), value=1)
    assert after == (
        "name: t\r\ncoder:  # c\r\n  $ref: file:agents/coder.yaml\r\n"
        "  model:\r\n    t: 1\r\nother: 1\r\n"
    )


@pytest.mark.parametrize(
    "before",
    [
        # a double-quoted string wrapped with an escaped line break reads file:agents/coder.yaml
        'name: t\ncoder: "file:agents/\\\n  coder.yaml"\n',
        "name: t\ncoder: |-\n  file:agents/coder.yaml\n",
    ],
)
def test_convert_multiline_include_string_is_refused(
    make_theatre: MakeTheatre, before: str
) -> None:
    with pytest.raises(WriteRefused) as refused:
        _convert(make_theatre, before, "coder", keys=("temperature",), value=0.3)
    assert refused.value.exit_code == 3
    config = make_theatre({}) / ".troupe" / "troupe.yml"
    assert refused.value.message == (
        f"coder.temperature: the include at {config.resolve()} line 2 spans several lines;"
        " cannot convert it to mapping form without rewriting it; no file changed"
    )


def test_convert_changes_no_other_line(make_theatre: MakeTheatre) -> None:
    before = (
        "# team file\nname: t  # n\n\ncoder: file:agents/coder.yaml  # c\n"
        "# about other\nother:\n  x: 1\n"
    )
    after = _convert(make_theatre, before, "coder", keys=("temperature",), value=0.3)
    old = before.splitlines(keepends=True)
    changed = old.index("coder: file:agents/coder.yaml  # c\n")
    assert after.splitlines(keepends=True) == [
        *old[:changed],
        "coder:  # c\n",
        "  $ref: file:agents/coder.yaml\n",
        "  temperature: 0.3\n",
        *old[changed + 1 :],
    ]


# --- WP05 T022: anchors kept on kind-changing replacement (R-9, C5); indentation with anchors ---


@pytest.mark.parametrize(
    ("before", "value", "after", "resolved"),
    [
        (  # scalar -> mapping
            "model: &m opus\nx: *m\n",
            {"a": 1},
            "model: &m\n  a: 1\nx: *m\n",
            {"model": {"a": 1}, "x": {"a": 1}},
        ),
        (  # mapping -> scalar
            "d: &d\n  model: opus\nx: *d\n",
            5,
            "d: &d 5\nx: *d\n",
            {"d": 5, "x": 5},
        ),
        (  # block mapping -> empty mapping (flow form)
            "d: &d\n  model: opus\nx: *d\n",
            {},
            "d: &d {}\nx: *d\n",
            {"d": {}, "x": {}},
        ),
        (  # block mapping -> block list, comment on the key's line kept
            "d: &d  # shared\n  model: opus\nx: *d\n",
            ["a", "b"],
            "d: &d  # shared\n  - a\n  - b\nx: *d\n",
            {"d": ["a", "b"], "x": ["a", "b"]},
        ),
        (  # anchored empty value -> mapping
            "d: &d\nx: *d\n",
            {"m": 1},
            "d: &d\n  m: 1\nx: *d\n",
            {"d": {"m": 1}, "x": {"m": 1}},
        ),
    ],
    ids=["scalar-to-mapping", "mapping-to-scalar", "mapping-to-empty", "mapping-to-list", "empty"],
)
def test_kind_change_keeps_anchor_on_key_line(
    before: str, value: Value, after: str, resolved: Value
) -> None:
    root = _load(before)
    key = before.split(":", 1)[0]
    edits = replace_value_edits(root.origin.file, root, key, _map(root, key), value, 2, path=key)
    text = apply_edits(before, edits)
    assert text == after
    assert _resolved(_load(text)) == resolved


def test_kind_change_keeps_anchor_on_dash_line() -> None:
    before = "l:\n  - &a\n    k: v\nx: *a\n"
    root = _load(before)
    seq = _seq(root, "l")
    edits = replace_value_edits(root.origin.file, seq, 0, seq.items[0], 7, 2, path="l.0")
    assert apply_edits(before, edits) == "l:\n  - &a 7\nx: *a\n"


def test_flow_replacement_keeps_anchor_before_the_value() -> None:
    before = "f: {a: &a [1, 2], b: 2}\nx: *a\n"
    root = _load(before)
    flow = _mapping(root, "f")
    edits = replace_value_edits(
        root.origin.file, flow, "a", _map(root, "f", "a"), {"k": 1}, 2, path="f.a"
    )
    text = apply_edits(before, edits)
    assert text == "f: {a: &a {k: 1}, b: 2}\nx: *a\n"
    assert _resolved(_load(text)) == {"f": {"a": {"k": 1}, "b": 2}, "x": {"k": 1}}


@pytest.mark.parametrize(
    "before",
    ["model:\n  &m opus\nx: *m\n", "d:\n  &d\n  model: opus\nx: *d\n"],
    ids=["scalar", "mapping"],
)
def test_kind_change_refuses_anchor_on_its_own_line(before: str) -> None:
    root = _load(before)
    key = "model" if before.startswith("model") else "d"
    with pytest.raises(WriteRefused) as err:
        replace_value_edits(root.origin.file, root, key, _map(root, key), [1], 2, path=key)
    message = str(err.value)
    assert message.startswith(f"{key}: the anchor &")
    assert "not on its key's line" in message and "no file changed" in message


def test_detect_indent_reads_files_with_anchors() -> None:
    assert detect_indent("defaults: &d\n    model: opus\ncoder:\n    settings: *d\n") == 4
    assert detect_indent("a: *x\n") == 2  # undefined alias: unreadable, default step
    assert detect_indent("x: &x 1\nalias: *x\nb:\n   c: 1\n") == 3


def _resolved(node: Node) -> Value:
    """Like ``_plain``, following aliases."""
    return _plain(_unaliased(node))


def _unaliased(node: Node) -> Node:
    node = unwrap(node)
    if isinstance(node, MappingNode):
        entries = [
            MappingEntry(e.key, e.key_origin, e.key_style, _unaliased(e.value))
            for e in node.entries
        ]
        return MappingNode(node.origin, node.flow, entries)
    if isinstance(node, SequenceNode):
        return SequenceNode(node.origin, node.flow, [_unaliased(item) for item in node.items])
    return node


def test_open_end_check_reads_files_with_anchors() -> None:
    refused = "a: &a 1\nb: *a\ns: |\n  x"
    root = _load(refused)
    with pytest.raises(WriteRefused, match="ends inside a block scalar"):
        new_key_edits(root.origin.file, root, ["t"], 1, 2, path="t")
    written = "a: &a 1\nb: *a\ns: |-\n  x"
    root = _load(written)
    edits = new_key_edits(root.origin.file, root, ["t"], 1, 2, path="t")
    assert apply_edits(written, edits) == written + "\nt: 1"
