"""Rendering ``!literal`` (spec S-10, S-11, S-13; FR-011; research R-4, R-8).

New string values are rendered by ``scalars.render_scalar`` and ``blocks.render_new_multiline``;
both write ``!literal `` before an ``includes.LiteralStr``. Every rendered text is read back with
``yamlcore.compose(..., allow_anchors=True)`` (file mode) to show it carries the tag and the
exact value. Whole-file edits are re-loaded through ``troupe.loader.load``.
"""

from pathlib import Path

import pytest

from conftest import MakeTheatre
from troupe import yamlcore
from troupe.includes import IncludeStr, LiteralStr
from troupe.leaves import flatten
from troupe.loader import load
from troupe.paths import parse_path, walk
from troupe.tree import AliasNode, MappingNode, Node, ScalarNode, SequenceNode, YamlInclude
from troupe.writeback import apply_edits
from troupe.writeback.aliases import expand_edits
from troupe.writeback.blocks import render_new_multiline
from troupe.writeback.collections import (
    Value,
    convert_include_edits,
    flow_append_edits,
    new_item_edits,
    new_key_edits,
    render_flow_value,
    replace_value_edits,
)
from troupe.writeback.placement import concrete_parent
from troupe.writeback.scalars import (
    LITERAL_PREFIX,
    Context,
    QuoteStyle,
    render_scalar,
    render_string,
)
from troupe.yamlcore import RawMapping, RawNode, RawScalar, RawSequence

VIRTUAL = Path("/virtual/troupe.yml")


def _compose(text: str) -> RawNode:
    root = yamlcore.compose(text, "<test>", allow_anchors=True)
    assert root is not None
    return root


def _read_back(rendered: str, context: Context) -> RawScalar:
    """Compose ``rendered`` as a mapping value (block) or a list item (flow)."""
    root = _compose(f"k: {rendered}\n" if context == "block" else f"[{rendered}]\n")
    if isinstance(root, RawMapping):
        node = root.pairs[0][1]
    else:
        assert isinstance(root, RawSequence)
        node = root.items[0]
    assert isinstance(node, RawScalar)
    return node


def _load(text: str) -> MappingNode:
    root = load(VIRTUAL, overrides={VIRTUAL: text})
    assert isinstance(root, MappingNode)
    return root


def _at(node: Node, *keys: str | int) -> Node:
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


def _literal_scalar(node: Node) -> ScalarNode:
    assert isinstance(node, ScalarNode)
    assert node.literal is not None
    return node


# --- T030: render_scalar ------------------------------------------------------------------------

_LITERALS = ["https://x", "file:p.md", "file: x", "https://a b", "http://h/a#b", "it's"]


@pytest.mark.parametrize("context", ["block", "flow"])
@pytest.mark.parametrize("value", _LITERALS)
def test_render_scalar_prefixes_literal_strings_in_block_and_flow(
    value: str, context: Context
) -> None:
    rendered = render_scalar(LiteralStr(value), None, context)
    assert rendered == LITERAL_PREFIX + render_scalar(value, None, context)
    raw = _read_back(rendered, context)
    assert raw.tag is not None
    assert raw.text == value


def test_render_scalar_keeps_the_preferred_style_for_literal_strings() -> None:
    assert render_scalar(LiteralStr("https://x"), "double", "block") == '!literal "https://x"'
    assert render_scalar(LiteralStr("https://x"), "single", "flow") == "!literal 'https://x'"
    assert render_scalar(LiteralStr("file: x"), None, "block") == "!literal 'file: x'"


@pytest.mark.parametrize("context", ["block", "flow"])
@pytest.mark.parametrize(
    "value", ["https://x", IncludeStr("https://x"), IncludeStr("file:a.md"), 1, 0.5, True, None]
)
def test_render_scalar_leaves_plain_strings_and_non_strings_untagged(
    value: str | int | float | bool | None, context: Context
) -> None:
    rendered = render_scalar(value, None, context)
    assert "!literal" not in rendered
    assert _read_back(rendered, context).tag is None


@pytest.mark.parametrize("style", ["plain", "single", "double"])
def test_render_string_never_prefixes_even_for_literal_str(style: QuoteStyle) -> None:
    rendered = render_string(LiteralStr("https://x"), style)
    assert not rendered.startswith("!")
    assert rendered in ("https://x", "'https://x'", '"https://x"')


# --- T031: render_new_multiline -----------------------------------------------------------------


@pytest.mark.parametrize("value", ["https://x\nline two\n", "file:a\nb", "  lead\nx\n\n"])
def test_new_multiline_literal_string_gets_tag_before_block_indicator(value: str) -> None:
    header, body = render_new_multiline(LiteralStr(value), "block", 2)
    plain_header, plain_body = render_new_multiline(value, "block", 2)
    assert header == LITERAL_PREFIX + plain_header
    assert body == plain_body
    root = _compose("k: " + header + "\n" + "".join(line + "\n" for line in body))
    assert isinstance(root, RawMapping)
    raw = root.pairs[0][1]
    assert isinstance(raw, RawScalar)
    assert raw.tag is not None and raw.style == "literal" and raw.text == value


def test_new_multiline_literal_string_as_double_quoted_in_flow() -> None:
    value = "https://x\nline two"
    rendered, body = render_new_multiline(LiteralStr(value), "flow", 0)
    assert body == []
    assert rendered == '!literal "https://x\\nline two"'
    raw = _read_back(rendered, "flow")
    assert raw.tag is not None and raw.style == "double" and raw.text == value


def test_new_multiline_plain_string_is_untagged() -> None:
    header, _body = render_new_multiline("https://x\ny", "block", 2)
    assert header == "|-"
    assert render_new_multiline("https://x\ny", "flow", 0)[0] == '"https://x\\ny"'


# --- T032: new values through collections -------------------------------------------------------


def test_new_key_with_literal_value_is_written_tagged() -> None:
    before = "team:\n  lead: ann  # c\n"
    root = _load(before)
    mapping = _at(root, "team")
    assert isinstance(mapping, MappingNode)
    value: Value = {"url": LiteralStr("https://x"), "notes": LiteralStr("file:a\nb\n")}
    edits = new_key_edits(
        root.origin.file, mapping, ["site", "cfg"], value, 2, path="team.site.cfg"
    )
    after = apply_edits(before, edits)
    assert after == (
        "team:\n"
        "  lead: ann  # c\n"
        "  site:\n"
        "    cfg:\n"
        "      url: !literal https://x\n"
        "      notes: !literal |\n"
        "        file:a\n"
        "        b\n"
    )
    reloaded = _load(after)
    assert _literal_scalar(_at(reloaded, "team", "site", "cfg", "url")).value == "https://x"
    assert _literal_scalar(_at(reloaded, "team", "site", "cfg", "notes")).value == "file:a\nb\n"


def test_new_key_literal_copies_sibling_style_after_the_tag() -> None:
    before = 'a: "x"\n'
    root = _load(before)
    edits = new_key_edits(root.origin.file, root, ["b"], LiteralStr("file:p.md"), 2, path="b")
    after = apply_edits(before, edits)
    assert after == 'a: "x"\nb: !literal "file:p.md"\n'
    assert _literal_scalar(_at(_load(after), "b")).value == "file:p.md"


def test_new_block_item_with_literal_value_is_tagged() -> None:
    before = "l:\n  - a\n"
    root = _load(before)
    seq = _at(root, "l")
    assert isinstance(seq, SequenceNode)
    edits = new_item_edits(root.origin.file, seq, LiteralStr("https://x"), 2, path="l.1")
    after = apply_edits(before, edits)
    assert after == "l:\n  - a\n  - !literal https://x\n"
    assert _literal_scalar(_at(_load(after), "l", 1)).value == "https://x"


@pytest.mark.parametrize(
    ("before", "key", "value", "after"),
    [
        ("f: {a: 1}\n", "b", LiteralStr("https://x"), "f: {a: 1, b: !literal https://x}\n"),
        ("f: [a]  # c\n", None, LiteralStr("file:p.md"), "f: [a, !literal file:p.md] # c\n"),
        (
            "f: {a: 1}\n",
            "b",
            {"u": LiteralStr("https://x"), "m": LiteralStr("a\nb")},
            'f: {a: 1, b: {u: !literal https://x, m: !literal "a\\nb"}}\n',
        ),
        ("f: []\n", None, [LiteralStr("file:x")], "f: [[!literal file:x]]\n"),
    ],
    ids=["mapping", "sequence", "nested-mapping", "nested-list"],
)
def test_flow_append_of_literal_value_is_tagged(
    before: str, key: str | None, value: Value, after: str
) -> None:
    root = _load(before)
    flow = _at(root, "f")
    assert isinstance(flow, MappingNode | SequenceNode)
    text = apply_edits(before, flow_append_edits(root.origin.file, flow, key, value))
    assert text == after
    _load(text)  # reads back: every tag sits on a scalar


def test_render_flow_value_tags_literal_scalars_but_not_keys() -> None:
    rendered = render_flow_value({"file:k": LiteralStr("file:v")})
    assert rendered == "{file:k: !literal file:v}"


def test_override_line_from_include_conversion_is_tagged(make_theatre: MakeTheatre) -> None:
    before = "coder: file:agents/coder.yaml  # c\n"
    theatre = make_theatre({"troupe.yml": before, "agents/coder.yaml": "model: m\n"})
    root = load(theatre / ".troupe" / "troupe.yml")
    assert isinstance(root, MappingNode)
    include = _at(root, "coder")
    assert isinstance(include, YamlInclude)
    edits = convert_include_edits(
        include.origin.file,
        root,
        "coder",
        include.origin,
        ["docs"],
        LiteralStr("https://x"),
        2,
        path="coder.docs",
    )
    after = apply_edits(before, edits)
    assert after == "coder:  # c\n  $ref: file:agents/coder.yaml\n  docs: !literal https://x\n"
    raw = _compose(after)
    assert isinstance(raw, RawMapping)
    coder = raw.pairs[0][1]
    assert isinstance(coder, RawMapping)
    docs = coder.pairs[1][1]
    assert isinstance(docs, RawScalar) and docs.tag is not None and docs.text == "https://x"


def test_flow_include_conversion_override_is_tagged(make_theatre: MakeTheatre) -> None:
    before = "agents: [file:agents/coder.yaml]\n"
    theatre = make_theatre({"troupe.yml": before, "agents/coder.yaml": "model: m\n"})
    root = load(theatre / ".troupe" / "troupe.yml")
    assert isinstance(root, MappingNode)
    seq = _at(root, "agents")
    assert isinstance(seq, SequenceNode)
    include = seq.items[0]
    edits = convert_include_edits(
        include.origin.file,
        seq,
        0,
        include.origin,
        ["docs"],
        LiteralStr("file:p.md"),
        2,
        path="agents.0.docs",
    )
    after = apply_edits(before, edits)
    assert after == "agents: [{$ref: file:agents/coder.yaml, docs: !literal file:p.md}]\n"


# --- T032: kind-changing replacement drops the tag ----------------------------------------------


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("u: !literal https://x\n", "u:\n  k: 1\n"),
        ("u: !literal https://x  # c\nz: 0\n", "u:                     # c\n  k: 1\nz: 0\n"),
        ("u: &a !literal https://x\nz: *a\n", "u: &a\n  k: 1\nz: *a\n"),
        ("u: !literal &a https://x\nz: *a\n", "u: &a\n  k: 1\nz: *a\n"),
        (
            "u: !literal  &a  https://x  # c\nz: *a\n",
            "u: &a                       # c\n  k: 1\nz: *a\n",
        ),
        (
            "u: &a  !literal  https://x # c\nz: *a\n",
            "u: &a                      # c\n  k: 1\nz: *a\n",
        ),
        ("u: !literal\n  https://x\n", "u:\n  k: 1\n"),
        ("u: !literal  # c\n  https://x\n", "u:           # c\n  k: 1\n"),
        ("u: !literal &a\n  https://x\nz: *a\n", "u: &a\n  k: 1\nz: *a\n"),
        ("u:\n  !literal https://x\n", "u:\n  k: 1\n"),
        ("u:\n  !literal\n  https://x\n", "u:\n  k: 1\n"),
        ("u:\n  !literal  # c\n  https://x\n", "u:\n            # c\n  k: 1\n"),
        ("u: !literal |\n  https://x\n", "u:\n  k: 1\n"),
        ("u: !literal\nz: 0\n", "u:\n  k: 1\nz: 0\n"),
        ("u: !literal &a\nz: *a\n", "u: &a\n  k: 1\nz: *a\n"),
    ],
    ids=[
        "plain",
        "comment",
        "anchor-then-tag",
        "tag-then-anchor",
        "tag-then-anchor-comment",
        "anchor-then-tag-comment",
        "value-next-line",
        "value-next-line-comment",
        "tag-anchor-value-next-line",
        "tag-with-value-next-line",
        "tag-own-line",
        "tag-own-line-comment",
        "block-scalar",
        "empty",
        "empty-anchored",
    ],
)
def test_replacing_tagged_scalar_by_mapping_removes_only_the_tag(before: str, after: str) -> None:
    root = _load(before)
    old = _literal_scalar(_at(root, "u"))
    edits = replace_value_edits(root.origin.file, root, "u", old, {"k": 1}, 2, path="u")
    text = apply_edits(before, edits)
    assert text == after
    reloaded = _load(text)
    assert isinstance(_at(reloaded, "u"), MappingNode)


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("l:\n  - !literal https://x\n", "l:\n  -\n    - a\n"),
        ("l:\n  - !literal &a https://x\nz: *a\n", "l:\n  - &a\n    - a\nz: *a\n"),
        (
            "l:\n  - &a !literal https://x  # c\nz: *a\n",
            "l:\n  - &a                     # c\n    - a\nz: *a\n",
        ),
    ],
    ids=["plain", "tag-then-anchor", "anchor-then-tag-comment"],
)
def test_replacing_tagged_item_by_list_removes_the_tag(before: str, after: str) -> None:
    root = _load(before)
    seq = _at(root, "l")
    assert isinstance(seq, SequenceNode)
    old = _literal_scalar(seq.items[0])
    text = apply_edits(
        before, replace_value_edits(root.origin.file, seq, 0, old, ["a"], 2, path="l.0")
    )
    assert text == after
    _load(text)


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("f: {u: !literal https://x, b: 2}\n", "f: {u: {k: 1}, b: 2}\n"),
        ("f: {u: &a !literal https://x}\nz: *a\n", "f: {u: &a {k: 1}}\nz: *a\n"),
        ("f: {u: !literal &a https://x}\nz: *a\n", "f: {u: &a {k: 1}}\nz: *a\n"),
        ("f: {u: !literal , b: 2}\n", "f: {u: {k: 1} , b: 2}\n"),
    ],
    ids=["plain", "anchor-then-tag", "tag-then-anchor", "empty"],
)
def test_replacing_tagged_flow_value_by_mapping_removes_the_tag(before: str, after: str) -> None:
    root = _load(before)
    flow = _at(root, "f")
    assert isinstance(flow, MappingNode)
    old = _literal_scalar(_at(flow, "u"))
    text = apply_edits(
        before, replace_value_edits(root.origin.file, flow, "u", old, {"k": 1}, 2, path="f.u")
    )
    assert text == after
    _load(text)


# --- T032: alias copies keep the tag ------------------------------------------------------------


def _expand(tmp_path: Path, text: str, path: str) -> str:
    config = tmp_path / "troupe.yml"
    config.write_bytes(text.encode("utf-8"))
    root = load(config)
    found = walk(root, parse_path(path))
    alias = next(n for n in found.nodes if isinstance(n, AliasNode) and not n.merge)
    located = concrete_parent(root, alias)
    assert located is not None
    parent, slot = located
    after = apply_edits(text, expand_edits(alias.origin.file, alias, parent, slot, 2, path=path))
    config.write_bytes(after.encode("utf-8"))
    assert flatten(load(config)) == flatten(root)  # the copy reads as the same values
    return after


def test_alias_copy_keeps_literal_tag_on_copied_scalars(tmp_path: Path) -> None:
    text = (
        "d: &d\n"
        "  url: !literal https://x\n"
        "  q: !literal 'file:p.md'\n"
        "  notes: !literal |\n"
        "    https://a\n"
        "    b\n"
        "  e: !literal\n"
        "  plain: https-free\n"
        "c:\n"
        "  s: *d\n"
    )
    assert _expand(tmp_path, text, "c.s.url") == text.replace(
        "  s: *d\n",
        "  s:  # expanded from *d by troupe\n"
        "    url: !literal https://x\n"
        "    q: !literal 'file:p.md'\n"
        "    notes: !literal |\n"
        "      https://a\n"
        "      b\n"
        "    e: !literal\n"
        "    plain: https-free\n",
    )


def test_alias_copy_of_tagged_scalar_and_folded_block(tmp_path: Path) -> None:
    text = "u: &u !literal https://x\nf: &f !literal >\n  a\n  b\nl:\n  - *u\n  - *f\n"
    first = _expand(tmp_path, text, "l.0")
    assert first == text.replace(
        "  - *u\n", "  - !literal https://x  # expanded from *u by troupe\n"
    )
    second = _expand(tmp_path, first, "l.1")
    assert second.endswith("  - !literal |  # expanded from *f by troupe\n    a b\n")


def test_alias_copy_of_anchored_tagged_scalar_drops_anchor_keeps_tag(tmp_path: Path) -> None:
    text = "u: !literal &u https://x\nv: *u\n"
    after = _expand(tmp_path, text, "v")
    assert (
        after == "u: !literal &u https://x\nv: !literal https://x  # expanded from *u by troupe\n"
    )
