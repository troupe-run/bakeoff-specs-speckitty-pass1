"""Expansion text for ``set --expand-alias`` (spec US4, FR-005, FR-006, C7-C9; research R-7).

Each test writes a real file under ``tmp_path``, loads it with ``troupe.loader.load``, finds the
first written alias on PATH and its concrete parent, calls ``aliases.expand_edits`` and compares
the WHOLE new text. The reload check proves each copy is faithful (same resolved leaves).
"""

from pathlib import Path

import pytest

from troupe.errors import WriteRefused
from troupe.leaves import flatten
from troupe.loader import load
from troupe.paths import parse_path, walk
from troupe.tree import AliasNode, Node, SourceFile
from troupe.writeback import apply_edits
from troupe.writeback.aliases import expand_edits
from troupe.writeback.collections import detect_indent
from troupe.writeback.placement import concrete_parent

WORKED = "defaults: &d\n  model: opus\ncoder:\n  settings: *d\nreviewer:\n  settings: *d\n"
WORKED_EXPANDED = (
    "defaults: &d\n"
    "  model: opus\n"
    "coder:\n"
    "  settings:  # expanded from *d by troupe\n"
    "    model: opus\n"
    "reviewer:\n"
    "  settings: *d\n"
)


def _load(tmp_path: Path, text: str) -> Node:
    config = tmp_path / "troupe.yml"
    config.write_bytes(text.encode("utf-8"))
    return load(config)


def _expand(tmp_path: Path, text: str, path: str, step: int | None = None) -> str:
    """Expand the first written alias on ``path`` and return the whole new text.

    ``step`` defaults to ``detect_indent(text)``; pass it when the step must not come from there
    (``detect_indent`` composes without anchors, so it falls back to 2 on anchored files).
    """
    root = _load(tmp_path, text)
    found = walk(root, parse_path(path))
    alias = next(n for n in found.nodes if isinstance(n, AliasNode) and not n.merge)
    located = concrete_parent(root, alias)
    assert located is not None
    parent, slot = located
    file: SourceFile = alias.origin.file
    assert file.text == text
    step = detect_indent(text) if step is None else step
    edits = expand_edits(file, alias, parent, slot, step, path=path)
    return apply_edits(text, edits)


def _refusal(tmp_path: Path, text: str, path: str) -> str:
    with pytest.raises(WriteRefused) as refused:
        _expand(tmp_path, text, path)
    assert refused.value.exit_code == 3
    return refused.value.message


# --- T018/T017: whole-text results ----------------------------------------------------------


def test_worked_example_expands_coder_settings_exactly(tmp_path: Path) -> None:
    assert _expand(tmp_path, WORKED, "coder.settings.model") == WORKED_EXPANDED


def test_flow_anchored_mapping_is_copied_in_block_style(tmp_path: Path) -> None:
    text = "defaults: &d {model: opus, t: 1}\ncoder:\n  settings: *d\n"
    assert _expand(tmp_path, text, "coder.settings.t") == (
        "defaults: &d {model: opus, t: 1}\n"
        "coder:\n"
        "  settings:  # expanded from *d by troupe\n"
        "    model: opus\n"
        "    t: 1\n"
    )


def test_scalar_alias_becomes_its_scalar_with_comment(tmp_path: Path) -> None:
    text = "m: &m 'opus x'\ncoder:\n  model: *m\n  other: *m\n"
    assert _expand(tmp_path, text, "coder.model") == (
        "m: &m 'opus x'\ncoder:\n  model: 'opus x'  # expanded from *m by troupe\n  other: *m\n"
    )


def test_scalar_list_item_alias_keeps_dash_line(tmp_path: Path) -> None:
    text = "m: &m opus\nmodels:\n  - *m\n  - haiku\n"
    assert _expand(tmp_path, text, "models.0") == (
        "m: &m opus\nmodels:\n  - opus  # expanded from *m by troupe\n  - haiku\n"
    )


def test_list_item_alias_puts_comment_on_dash_line(tmp_path: Path) -> None:
    text = "defaults: &d\n  model: opus\nagents:\n  - *d\n  - name: x\n"
    assert _expand(tmp_path, text, "agents.0.model") == (
        "defaults: &d\n"
        "  model: opus\n"
        "agents:\n"
        "  -  # expanded from *d by troupe\n"
        "    model: opus\n"
        "  - name: x\n"
    )


def test_inner_alias_stays_an_alias_in_the_copy(tmp_path: Path) -> None:
    text = (
        "limits: &l\n  max: 1\ndefaults: &d\n  model: opus\n  limits: *l\ncoder:\n  settings: *d\n"
    )
    new = _expand(tmp_path, text, "coder.settings.limits.max")
    assert new == (
        "limits: &l\n  max: 1\n"
        "defaults: &d\n  model: opus\n  limits: *l\n"
        "coder:\n"
        "  settings:  # expanded from *d by troupe\n"
        "    model: opus\n"
        "    limits: *l\n"
    )
    root = _load(tmp_path, new)
    found = walk(root, parse_path("coder.settings.limits"))
    assert not isinstance(found.nodes[2], AliasNode)
    assert isinstance(found.nodes[3], AliasNode)


def test_inner_anchor_and_comments_are_not_copied(tmp_path: Path) -> None:
    text = (
        "defaults: &d\n"
        "  # about d\n"
        "  model: &x opus  # the model\n"
        "  list: &y\n"
        "    - a  # first\n"
        "    - {k: v}\n"
        "coder:\n"
        "  settings: *d\n"
        "other: *x\n"
    )
    assert _expand(tmp_path, text, "coder.settings.model") == (
        "defaults: &d\n"
        "  # about d\n"
        "  model: &x opus  # the model\n"
        "  list: &y\n"
        "    - a  # first\n"
        "    - {k: v}\n"
        "coder:\n"
        "  settings:  # expanded from *d by troupe\n"
        "    model: opus\n"
        "    list:\n"
        "      - a\n"
        "      - k: v\n"
        "other: *x\n"
    )


def test_quoted_scalars_keep_their_written_quoting(tmp_path: Path) -> None:
    text = "defaults: &d\n  a: 'x'\n  b: \"y\\tz\"\n  'c d': plain\n  e: ~\n  f:\ncoder:\n  s: *d\n"
    assert _expand(tmp_path, text, "coder.s.a") == text.replace(
        "  s: *d\n",
        "  s:  # expanded from *d by troupe\n"
        "    a: 'x'\n"
        '    b: "y\\tz"\n'
        "    'c d': plain\n"
        "    e: ~\n"
        "    f:\n",
    )


def test_multiline_string_in_anchored_node_becomes_literal_block(tmp_path: Path) -> None:
    text = 'defaults: &d\n  text: >\n    one\n\n    two\n  q: "a\n    b"\ncoder:\n  s: *d\nend: 1\n'
    assert _expand(tmp_path, text, "coder.s.q") == text.replace(
        "  s: *d\n",
        "  s:  # expanded from *d by troupe\n    text: |\n      one\n      two\n    q: a b\n",
    )


def test_literal_scalar_alias_writes_header_on_the_key_line(tmp_path: Path) -> None:
    text = "m: &m |-\n  a\n  b\ncoder:\n  model: *m\n"
    assert _expand(tmp_path, text, "coder.model") == (
        "m: &m |-\n  a\n  b\ncoder:\n  model: |-  # expanded from *m by troupe\n    a\n    b\n"
    )


def test_four_space_file_indents_copy_by_four(tmp_path: Path) -> None:
    text = (
        "defaults: &d\n"
        "    model: opus\n"
        "    sub:\n"
        "        k: v\n"
        "    tools: [a, b]\n"
        "coder:\n"
        "    settings: *d\n"
    )
    assert _expand(tmp_path, text, "coder.settings.model", step=4) == text.replace(
        "    settings: *d\n",
        "    settings:  # expanded from *d by troupe\n"
        "        model: opus\n"
        "        sub:\n"
        "            k: v\n"
        "        tools:\n"
        "            - a\n"
        "            - b\n",
    )


def test_list_copy_under_key_follows_flush_sibling_list(tmp_path: Path) -> None:
    text = "l: &l\n- a\n- [b, c]\ncoder:\n  tools:\n  - x\n  more: *l\n"
    assert _expand(tmp_path, text, "coder.more.0") == (
        "l: &l\n- a\n- [b, c]\n"
        "coder:\n  tools:\n  - x\n"
        "  more:  # expanded from *l by troupe\n"
        "  - a\n"
        "  - - b\n"
        "    - c\n"
    )


def test_empty_anchored_collection_stays_on_the_key_line(tmp_path: Path) -> None:
    text = "e: &e {}\ncoder:\n  s: *e\n"
    assert _expand(tmp_path, text, "coder.s") == (
        "e: &e {}\ncoder:\n  s: {}  # expanded from *e by troupe\n"
    )


def test_crlf_file_keeps_crlf_in_copy(tmp_path: Path) -> None:
    text = WORKED.replace("\n", "\r\n")
    assert _expand(tmp_path, text, "coder.settings.model") == WORKED_EXPANDED.replace("\n", "\r\n")


def test_file_without_final_newline_stays_without(tmp_path: Path) -> None:
    text = "defaults: &d\n  model: opus\n  n: 1\ncoder:\n  settings: *d"
    assert _expand(tmp_path, text, "coder.settings.model") == (
        "defaults: &d\n  model: opus\n  n: 1\n"
        "coder:\n"
        "  settings:  # expanded from *d by troupe\n"
        "    model: opus\n"
        "    n: 1"
    )


def test_file_without_final_newline_keeps_break_after_literal_tail(tmp_path: Path) -> None:
    text = "defaults: &d\n  t: |\n    x\ncoder:\n  settings: *d"
    assert _expand(tmp_path, text, "coder.settings.t") == (
        "defaults: &d\n  t: |\n    x\n"
        "coder:\n"
        "  settings:  # expanded from *d by troupe\n"
        "    t: |\n"
        "      x\n"
    )


# --- T016: C9 refusals ----------------------------------------------------------------------


def test_alias_in_flow_collection_is_refused(tmp_path: Path) -> None:
    text = "defaults: &d\n  model: opus\ncoder: {settings: *d}\n"
    message = _refusal(tmp_path, text, "coder.settings.model")
    assert message.startswith("coder.settings.model: ")
    assert f"*d at {tmp_path / 'troupe.yml'} line 3" in message
    assert "flow collection" in message
    assert message.endswith("; no file changed")


def test_alias_line_with_comment_is_refused(tmp_path: Path) -> None:
    text = "defaults: &d\n  model: opus\ncoder:\n  settings: *d  # mine\n"
    message = _refusal(tmp_path, text, "coder.settings.model")
    assert message.startswith("coder.settings.model: ")
    assert "*d at" in message and "line 4" in message
    assert "already has a comment" in message
    assert message.endswith("; no file changed")


def test_alias_on_next_line_is_refused(tmp_path: Path) -> None:
    text = "defaults: &d\n  model: opus\ncoder:\n  settings:\n    *d\n"
    message = _refusal(tmp_path, text, "coder.settings.model")
    assert message.startswith("coder.settings.model: ")
    assert "*d at" in message and "line 5" in message
    assert "not on its key's line" in message
    assert message.endswith("; no file changed")


def test_list_item_alias_on_next_line_is_refused(tmp_path: Path) -> None:
    text = "defaults: &d\n  model: opus\nagents:\n  -\n    *d\n"
    message = _refusal(tmp_path, text, "agents.0.model")
    assert "not on its dash's line" in message
    assert message.endswith("; no file changed")


# --- T019: faithfulness ---------------------------------------------------------------------

FAITHFUL = [
    (WORKED, "coder.settings.model"),
    ("defaults: &d {model: opus, t: 1}\ncoder:\n  settings: *d\n", "coder.settings.t"),
    ("m: &m 'opus x'\ncoder:\n  model: *m\n  other: *m\n", "coder.model"),
    ("defaults: &d\n  model: opus\nagents:\n  - *d\n  - name: x\n", "agents.0.model"),
    (
        "limits: &l\n  max: 1\ndefaults: &d\n  model: opus\n  limits: *l\ncoder:\n  settings: *d\n",
        "coder.settings.limits.max",
    ),
    (
        "defaults: &d\n  model: &x opus  # c\n  list: &y\n    - a\n    - {k: v}\n"
        "coder:\n  settings: *d\nother: *x\n",
        "coder.settings.model",
    ),
    ("defaults: &d\n  text: >\n    one\n\n    two\ncoder:\n  s: *d\nend: 1\n", "coder.s.text"),
    ("m: &m |-\n  a\n  b\ncoder:\n  model: *m\n", "coder.model"),
    ("l: &l\n- a\n- [b, c]\ncoder:\n  tools:\n  - x\n  more: *l\n", "coder.more.0"),
    (WORKED.replace("\n", "\r\n"), "coder.settings.model"),
    ("defaults: &d\n  model: opus\ncoder:\n  settings: *d", "coder.settings.model"),
]


@pytest.mark.parametrize(("text", "path"), FAITHFUL)
def test_expanded_text_reloads_to_the_same_resolved_values(
    tmp_path: Path, text: str, path: str
) -> None:
    old_root = _load(tmp_path, text)
    before = flatten(old_root)
    nodes = walk(old_root, parse_path(path)).nodes
    first, alias = next((i, n) for i, n in enumerate(nodes) if isinstance(n, AliasNode))
    alias_line = text.count("\n", 0, alias.origin.start)
    new = _expand(tmp_path, text, path)
    root = _load(tmp_path, new)
    assert flatten(root) == before
    assert new.count("&") == text.count("&")
    assert not isinstance(walk(root, parse_path(path)).nodes[first], AliasNode)
    # Every old line but the alias's own is still there, in order (other aliases included).
    old_lines = text.splitlines(keepends=True)
    del old_lines[alias_line]
    remaining = iter(new.splitlines(keepends=True))
    assert all(line in remaining for line in old_lines)


@pytest.mark.parametrize(
    "anchored",
    [
        "d: &d\n  <<: *b\n  y: 2\n",
        "d: &d\n  y: 2\n  deep:\n    - {<<: *b, z: 3}\n",
    ],
)
def test_copy_containing_a_merge_key_is_refused(tmp_path: Path, anchored: str) -> None:
    text = "base: &b\n  x: 1\n" + anchored + "coder:\n  s: *d\n"
    message = _refusal(tmp_path, text, "coder.s.y")
    line = text.count("\n", 0, text.index("*d\n")) + 1
    assert message == (
        f"coder.s.y: the alias *d at {tmp_path / 'troupe.yml'} line {line} refers to a value"
        " that uses the merge key '<<'; copying it would write a merge key, which troupe never"
        " does; no file changed"
    )
    assert (tmp_path / "troupe.yml").read_bytes() == text.encode("utf-8")


def test_inner_alias_to_a_merge_key_mapping_is_copied_as_an_alias(tmp_path: Path) -> None:
    text = "base: &b\n  x: 1\nm: &m\n  <<: *b\nd: &d\n  inner: *m\ncoder:\n  s: *d\n"
    assert _expand(tmp_path, text, "coder.s.inner") == text.replace(
        "  s: *d\n", "  s:  # expanded from *d by troupe\n    inner: *m\n"
    )
