"""The loader on files with anchors, aliases and merge keys (spec A-0, C1-C3, C13; R-3 to R-5).

Each test writes real files under ``tmp_path`` and loads them with ``troupe.loader.load``; no CLI.
"""

from pathlib import Path

import pytest

from troupe.errors import LoadError
from troupe.leaves import flatten
from troupe.loader import load
from troupe.merge import MERGE_KEY
from troupe.paths import unwrap
from troupe.reconcile import watched_files
from troupe.tree import (
    AliasNode,
    MappingNode,
    MergeKeyMapping,
    Node,
    ScalarNode,
    SequenceNode,
    TextInclude,
)
from troupe.yamlout import Line, render

REPORTER = "defaults: &d\n  model: opus\ncoder:\n  settings: *d\nreviewer:\n  settings: *d\n"


def _load(tmp_path: Path, text: str, files: dict[str, str] | None = None) -> MappingNode:
    for rel, content in (files or {}).items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    config = tmp_path / "troupe.yml"
    config.write_text(text, encoding="utf-8")
    root = load(config)
    assert isinstance(root, MappingNode)
    return root


def _at(node: Node, *keys: str) -> Node:
    """The value at ``keys`` as found (the last step is not unwrapped)."""
    for key in keys:
        mapping = unwrap(node)
        assert isinstance(mapping, MappingNode)
        entry = mapping.get(key)
        assert entry is not None, key
        node = entry.value
    return node


def _scalar(node: Node, *keys: str) -> object:
    value = unwrap(_at(node, *keys))
    assert isinstance(value, ScalarNode)
    return value.value


def _refused(tmp_path: Path, text: str, files: dict[str, str] | None = None) -> str:
    with pytest.raises(LoadError) as refused:
        _load(tmp_path, text, files)
    return refused.value.message


# --- Aliases share the anchored node (R-3) ---------------------------------------------------


def test_alias_is_an_alias_node_sharing_the_anchored_node(tmp_path: Path) -> None:
    root = _load(tmp_path, REPORTER)
    defaults = _at(root, "defaults")
    coder = _at(root, "coder", "settings")
    reviewer = _at(root, "reviewer", "settings")

    assert isinstance(coder, AliasNode) and isinstance(reviewer, AliasNode)
    assert coder.target is defaults and coder.anchored is defaults
    assert reviewer.target is defaults
    assert (coder.name, coder.merge, coder.written) == ("d", False, None)
    assert coder.origin.source == "*d"
    assert _scalar(root, "coder", "settings", "model") == "opus"


def test_anchored_node_records_anchor_name_span_and_path(tmp_path: Path) -> None:
    root = _load(tmp_path, "agents:\n  base: &b\n    model: opus\n  m: &m 3\n")
    base = _at(root, "agents", "base")
    scalar = _at(root, "agents", "m")

    assert isinstance(base, MappingNode) and base.anchor is not None
    assert (base.anchor.name, base.anchor.origin.source, base.anchor.path) == (
        "b",
        "&b",
        ("agents", "base"),
    )
    assert base.origin.source.startswith("model: opus")  # content start, not the anchor
    assert isinstance(scalar, ScalarNode) and scalar.anchor is not None
    assert (scalar.anchor.name, scalar.anchor.path, scalar.origin.source) == (
        "m",
        ("agents", "m"),
        "3",
    )
    agents = _at(root, "agents")
    assert isinstance(agents, MappingNode) and agents.anchor is None


def test_scalar_and_list_aliases_resolve(tmp_path: Path) -> None:
    root = _load(tmp_path, "m: &m opus\nl: &l [a, b]\nx: *m\ny: *l\n")
    y = _at(root, "y")

    assert _scalar(root, "x") == "opus"
    assert isinstance(y, AliasNode) and isinstance(y.target, SequenceNode)
    assert y.target is _at(root, "l")


# --- Merge keys (A-0, R-4) -------------------------------------------------------------------


def test_merge_key_view_lists_written_keys_and_merged_keys_at_the_merge_position(
    tmp_path: Path,
) -> None:
    root = _load(tmp_path, "b: &b {model: opus, t: 1}\ncoder:\n  first: 0\n  <<: *b\n  last: 9\n")
    coder = _at(root, "coder")

    assert isinstance(coder, MergeKeyMapping)
    assert [entry.key for entry in coder.entries] == ["first", "model", "t", "last"]
    assert [_scalar(coder, key) for key in ("first", "model", "t", "last")] == [0, "opus", 1, 9]


def test_written_key_wins_over_merged_key(tmp_path: Path) -> None:
    root = _load(tmp_path, "b: &b {model: opus, t: 1}\ncoder: {<<: *b, t: 2}\n")
    coder = _at(root, "coder")

    assert isinstance(coder, MergeKeyMapping)
    assert [entry.key for entry in coder.entries] == ["model", "t"]
    assert (_scalar(root, "coder", "t"), _scalar(root, "coder", "model")) == (2, "opus")
    assert isinstance(_at(root, "coder", "t"), ScalarNode)  # written, not merge-derived


def test_earlier_merge_source_wins(tmp_path: Path) -> None:
    root = _load(tmp_path, "a: &a {model: A, x: 1}\nb: &b {model: B, y: 2}\nc: {<<: [*a, *b]}\n")
    c = _at(root, "c")

    assert isinstance(c, MergeKeyMapping)
    assert [entry.key for entry in c.entries] == ["model", "x", "y"]
    assert [_scalar(c, key) for key in ("model", "x", "y")] == ["A", 1, 2]


def test_merged_values_are_merge_derived_alias_nodes(tmp_path: Path) -> None:
    root = _load(tmp_path, "b: &b {model: opus}\ncoder: {<<: *b}\ninline: {<<: {t: 1}}\n")
    model = _at(root, "coder", "model")
    written_alias = _at(root, "coder")
    assert isinstance(written_alias, MergeKeyMapping)
    in_merge = written_alias.written.get(MERGE_KEY)
    assert in_merge is not None and isinstance(in_merge.value, AliasNode)

    assert isinstance(model, AliasNode)
    assert (model.merge, model.name, model.written) == (True, "b", in_merge.value)
    assert model.anchored is _at(root, "b")
    assert model.target is _at(root, "b", "model")
    assert model.origin.source == "*b"
    t = _at(root, "inline", "t")
    assert isinstance(t, AliasNode)
    assert (t.merge, t.name, t.anchored, t.written, t.origin.source) == (
        True,
        None,
        None,
        None,
        "<<",
    )


def test_merge_view_keeps_the_written_mapping_with_its_merge_entry(tmp_path: Path) -> None:
    root = _load(tmp_path, "b: &b {model: opus}\ncoder:\n  <<: *b\n  t: 2\n")
    coder = _at(root, "coder")

    assert isinstance(coder, MergeKeyMapping)
    assert [entry.key for entry in coder.written.entries] == [MERGE_KEY, "t"]
    assert coder.origin is coder.written.origin and coder.flow is coder.written.flow
    assert coder.written.entries[1] is coder.entries[1]  # written entries are reused


def test_quoted_merge_key_is_an_ordinary_key(tmp_path: Path) -> None:
    root = _load(tmp_path, "b: &b {model: opus}\ncoder: {'<<': *b}\n")
    coder = _at(root, "coder")

    assert type(coder) is MappingNode
    assert [entry.key for entry in coder.entries] == [MERGE_KEY]
    assert _scalar(root, "coder", MERGE_KEY, "model") == "opus"


def test_nested_merge_key_mapping_contributes_its_view(tmp_path: Path) -> None:
    root = _load(tmp_path, "a: &a {model: A, x: 1}\nb: &b {<<: *a, x: 2}\nc: {<<: *b, y: 3}\n")
    c = _at(root, "c")

    assert isinstance(c, MergeKeyMapping)
    assert [entry.key for entry in c.entries] == ["model", "x", "y"]
    assert [_scalar(c, key) for key in ("model", "x", "y")] == ["A", 2, 3]


def test_merge_sources_may_be_inline_and_block_lists(tmp_path: Path) -> None:
    root = _load(tmp_path, "a: &a {x: 1}\nc:\n  <<:\n    - *a\n    - {y: 2}\n")

    assert [_scalar(root, "c", key) for key in ("x", "y")] == [1, 2]


# --- Load errors (C2, C3, C13, A-0) ----------------------------------------------------------

REFUSALS = {
    "anchored-include-string": (
        "coder: &c file:x.yaml\n",
        "anchor &c at line 1 is on an include reference",
    ),
    "anchored-ref-mapping": (
        "coder: &c\n  $ref: file:x.yaml\n",
        "anchor &c at line 1 is on an include reference",
    ),
    "anchored-ref-value": (
        "coder:\n  $ref: &c file:x.yaml\n",
        "anchor &c at line 2 is on an include reference",
    ),
    "anchored-mapping-containing-include": (
        "d: &d\n  x:\n    - file:x.yaml\n",
        "anchor &d at line 1 is on an include reference (or a value containing one)",
    ),
    "anchored-key": ("a: 1\n&k b: 2\n", "mapping key at line 2 under (root) has an anchor"),
    "alias-key": ("a: &k b\nc:\n  *k : 2\n", "mapping key at line 3 under c has an anchor or is"),
    "merge-scalar": ("c:\n  <<: 5\n", "c.<<: merge value must be a mapping, an alias of one"),
    "merge-list-with-scalar": (
        "a: &a {x: 1}\nc:\n  <<: [*a, 3]\n",
        "c.<<: merge value must be a mapping, an alias of one, or a list of those (line 3)",
    ),
    "merge-alias-of-scalar": (
        "a: &a 1\nc: {<<: *a}\n",
        "c.<<: merge value must be a mapping, an alias of one, or a list of those (line 2)",
    ),
    "merge-beside-ref": (
        "d: &d {x: 1}\ncoder: {$ref: file:x.yaml, <<: *d}\n",
        "coder: a merge key '<<' cannot be combined with '$ref' (line 2)",
    ),
    "tag": ("a: !t 1\n", "tags are not supported at line 1"),
    "undefined-alias": ("a: *nope\n", "undefined alias *nope at line 1"),
}


@pytest.mark.parametrize(("text", "expected"), REFUSALS.values(), ids=REFUSALS.keys())
def test_unsupported_anchor_uses_are_load_errors(tmp_path: Path, text: str, expected: str) -> None:
    message = _refused(tmp_path, text, {"x.yaml": "model: gpt\n"})

    assert str(tmp_path / "troupe.yml") in message
    assert expected in message


def test_anchor_inside_an_include_free_value_is_fine_beside_includes(tmp_path: Path) -> None:
    root = _load(tmp_path, "coder: file:x.yaml\nd: &d {m: 1}\ne: *d\n", {"x.yaml": "model: gpt\n"})

    assert _scalar(root, "coder", "model") == "gpt"
    assert _scalar(root, "e", "m") == 1


# --- Includes: anchors are per file ----------------------------------------------------------


def test_aliases_in_an_included_file_resolve_within_that_file(tmp_path: Path) -> None:
    included = "base: &b {model: opus}\nagent: {<<: *b, t: 1}\nother: *b\n"
    root = _load(
        tmp_path, "d: &b {model: root}\ncoder: file:x.yaml\nmine: *b\n", {"x.yaml": included}
    )

    assert _scalar(root, "coder", "agent", "model") == "opus"
    assert _scalar(root, "coder", "other", "model") == "opus"
    assert _scalar(root, "mine", "model") == "root"
    other = _at(root, "coder", "other")
    assert isinstance(other, AliasNode)
    assert other.target is _at(root, "coder", "base")
    assert other.origin.file.path == (tmp_path / "x.yaml").resolve()


def test_an_included_file_cannot_use_the_including_files_anchor(tmp_path: Path) -> None:
    message = _refused(tmp_path, "d: &d {m: 1}\ncoder: file:x.yaml\n", {"x.yaml": "a: *d\n"})

    assert str((tmp_path / "x.yaml").resolve()) in message
    assert "undefined alias *d" in message


# --- Readers (R-3 dispatch table): leaves, watched files, show --------------------------------


def test_leaves_resolve_aliases_and_merge_views_once(tmp_path: Path) -> None:
    root = _load(tmp_path, REPORTER + "m: {<<: *d, t: 1}\nl: [*d]\n")

    assert flatten(root) == {
        "defaults.model": "opus",
        "coder.settings.model": "opus",
        "reviewer.settings.model": "opus",
        "m.model": "opus",
        "m.t": 1,
        "l.0.model": "opus",
    }


def test_watched_files_follow_the_written_merge_value_not_aliases(tmp_path: Path) -> None:
    files = {"p.md": "Be brief.\n", "x.yaml": "model: gpt\n"}
    root = _load(tmp_path, "d: &d {m: 1}\nc: {<<: [*d, {p: file:p.md}], x: file:x.yaml}\n", files)

    watched = watched_files(root)

    assert sorted(path.name for path in watched) == ["p.md", "troupe.yml", "x.yaml"]
    p = _at(root, "c", "p")
    assert isinstance(p, AliasNode) and p.merge
    assert isinstance(unwrap(p), TextInclude)


def test_show_renders_aliases_as_list_items_and_values(tmp_path: Path) -> None:
    root = _load(tmp_path, "d: &d {m: 1}\ns: &s x\nl: [*d, *s]\nv: *s\n")

    text = "".join(line.text + "\n" for line in render(root))

    assert text == "d:\n  m: 1\ns: x\nl:\n  - m: 1\n  - x\nv: x\n"
    assert render(_at(root, "v")) == [Line("x", (tmp_path / "troupe.yml").resolve())]
