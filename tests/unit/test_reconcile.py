"""Reconcile and watched files against real files, the real loader and a real HistoryStore."""

import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from conftest import LOCAL_NO_PROXY
from remote_server import RemoteServer
from troupe.history import HistoryRecord, HistoryStore
from troupe.leaves import flatten
from troupe.lineage import UNKNOWN_ACTOR, import_lineage
from troupe.loader import load
from troupe.reconcile import reconcile, watched_files
from troupe.tree import Node

type Files = dict[str, str | bytes]
type Write = Callable[[Files], Node]


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    directory = tmp_path / ".troupe"
    directory.mkdir()
    return directory


@pytest.fixture
def write(state_dir: Path) -> Write:
    """Write files under ``.troupe/`` (verbatim bytes) and return the loaded root tree."""

    def build(files: Files) -> Node:
        for rel, content in files.items():
            target = state_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
        return load(state_dir / "troupe.yml")

    return build


@pytest.fixture
def store(state_dir: Path) -> Iterator[HistoryStore]:
    opened = HistoryStore(state_dir)
    yield opened
    opened.close()


def _changes(records: list[HistoryRecord]) -> list[tuple[str, str, object, object]]:
    return [(r.op, r.path, r.old, r.new) for r in records if r.op != "import"]


def _imported(store: HistoryStore, write: Write, files: Files) -> None:
    store.import_leaves(flatten(write(files)), import_lineage())


def test_reconcile_records_nothing_when_files_equal_recorded_configuration(
    store: HistoryStore, write: Write
) -> None:
    files: Files = {"troupe.yml": "a: 1\nb: [x, y]\n"}
    _imported(store, write, files)
    before = store.records()

    assert reconcile(store, write(files)) == []
    assert store.records() == before


def test_reconcile_records_changed_value_as_set_with_old_and_new(
    store: HistoryStore, write: Write
) -> None:
    _imported(store, write, {"troupe.yml": "a: 1\nb: 2\n"})

    changes = reconcile(store, write({"troupe.yml": "a: 1\nb: 3\n"}))

    assert [(c.op, c.path, c.old, c.new) for c in changes] == [("set", "b", 2, 3)]
    assert _changes(store.records()) == [("set", "b", 2, 3)]
    assert store.records()[-1].seq == 3


def test_reconcile_orders_sets_in_document_order_then_removes_in_recorded_order(
    store: HistoryStore, write: Write
) -> None:
    _imported(store, write, {"troupe.yml": "a: 1\nb: 2\nc: 3\nd: 4\n"})

    reconcile(store, write({"troupe.yml": "d: changed\na: changed\ne: new\n"}))

    assert _changes(store.records()) == [
        ("set", "d", 4, "changed"),
        ("set", "a", 1, "changed"),
        ("set", "e", None, "new"),
        ("remove", "b", 2, None),
        ("remove", "c", 3, None),
    ]


@pytest.mark.parametrize(
    ("before", "after"),
    [
        pytest.param({"troupe.yml": "m:\n  a: 1\n"}, {"troupe.yml": "m:\n    a: 1\n"}, id="indent"),
        pytest.param({"troupe.yml": "a: 1\n"}, {"troupe.yml": "a: 1  # note\n"}, id="comment"),
        pytest.param({"troupe.yml": "a: 0.2\n"}, {"troupe.yml": "a: 0.20\n"}, id="spelling"),
        pytest.param({"troupe.yml": "a: 'a'\n"}, {"troupe.yml": "a: a\n"}, id="single-plain"),
        pytest.param({"troupe.yml": "a: a\n"}, {"troupe.yml": 'a: "a"\n'}, id="plain-double"),
        pytest.param(
            {"troupe.yml": "l:\n  - x\n  - 2\n"},
            {"troupe.yml": "l: [x, 2]\n"},
            id="block-flow-list",
        ),
        pytest.param(
            {"troupe.yml": "l: [x, 2]\n"},
            {"troupe.yml": "l:\n  - x\n  - 2\n"},
            id="flow-block-list",
        ),
        pytest.param(
            {"troupe.yml": "m:\n  a: 1\n  b: x\n"},
            {"troupe.yml": "m: {a: 1, b: x}\n"},
            id="block-flow-map",
        ),
        pytest.param(
            {"troupe.yml": "m: {a: 1, b: x}\n"},
            {"troupe.yml": "m:\n  a: 1\n  b: x\n"},
            id="flow-block-map",
        ),
        pytest.param(
            {"troupe.yml": "a: 1\nb: 2\n"}, {"troupe.yml": "\na: 1\n\n\nb: 2\n\n"}, id="blank-lines"
        ),
        pytest.param(
            {"troupe.yml": "m: file:x.yaml\n", "x.yaml": "a: 1\nb: [x]\n"},
            {"troupe.yml": "m:\n  a: 1\n  b: [x]\n"},
            id="include-inlined",
        ),
    ],
)
def test_formatting_and_comment_only_edits_record_nothing(
    store: HistoryStore, write: Write, before: Files, after: Files
) -> None:
    _imported(store, write, before)
    imported = store.records()

    assert reconcile(store, write(after)) == []
    assert store.records() == imported


@pytest.mark.parametrize(
    ("before", "after", "old", "new"),
    [
        pytest.param('a: "1"\n', "a: 1\n", "1", 1, id="str-to-int"),
        pytest.param("a: 1\n", "a: 1.0\n", 1, 1.0, id="int-to-float"),
        pytest.param("a: true\n", 'a: "true"\n', True, "true", id="bool-to-str"),
    ],
)
def test_type_change_with_same_text_is_recorded(
    store: HistoryStore, write: Write, before: str, after: str, old: object, new: object
) -> None:
    _imported(store, write, {"troupe.yml": before})

    reconcile(store, write({"troupe.yml": after}))

    [record] = [r for r in store.records() if r.op != "import"]
    assert (record.op, record.path) == ("set", "a")
    assert type(record.old) is type(old) and record.old == old
    assert type(record.new) is type(new) and record.new == new


def test_value_set_to_null_is_a_set_not_a_remove(store: HistoryStore, write: Write) -> None:
    _imported(store, write, {"troupe.yml": "a: 1\nb: 2\n"})

    reconcile(store, write({"troupe.yml": "a: null\nb: 2\n"}))
    reconcile(store, write({"troupe.yml": "b: 2\n"}))

    assert _changes(store.records()) == [("set", "a", 1, None), ("remove", "a", None, None)]


def test_reconcile_never_writes_files(store: HistoryStore, write: Write, state_dir: Path) -> None:
    _imported(store, write, {"troupe.yml": "a: 1\np: file:p.md\n", "p.md": "old\n"})
    tree = write({"troupe.yml": "a: 2\np: file:p.md\n", "p.md": "new\n"})
    config = [state_dir / "troupe.yml", state_dir / "p.md"]
    before = {path: (path.read_bytes(), os.stat(path).st_mtime_ns) for path in config}

    changes = reconcile(store, tree)

    assert len(changes) == 2
    assert {path: (path.read_bytes(), os.stat(path).st_mtime_ns) for path in config} == before


def test_reconcile_records_its_changes_as_one_file_change_with_unknown_actor(
    store: HistoryStore, write: Write
) -> None:
    _imported(store, write, {"troupe.yml": "a: 1\nb: 2\nc: 3\n"})
    imported_change = store.records()[0].lineage.change

    reconcile(store, write({"troupe.yml": "a: 10\nc: 3\nd: new\n"}))

    reconciled = store.records()[3:]
    assert len(reconciled) == 3
    [lineage] = {r.lineage for r in reconciled}
    assert (lineage.actor, lineage.via, lineage.reason) == (UNKNOWN_ACTOR, "file", None)
    assert lineage.change != imported_change


def test_each_reconcile_is_its_own_change(store: HistoryStore, write: Write) -> None:
    _imported(store, write, {"troupe.yml": "a: 1\nb: 1\n"})

    reconcile(store, write({"troupe.yml": "a: 2\nb: 2\n"}))
    reconcile(store, write({"troupe.yml": "a: 3\nb: 3\n"}))

    first, second = store.records()[2:4], store.records()[4:6]
    assert len({r.lineage.change for r in first}) == 1
    assert len({r.lineage.change for r in second}) == 1
    assert first[0].lineage.change != second[0].lineage.change


def test_watched_files_cover_root_yaml_includes_and_text_includes_at_any_depth(
    write: Write, state_dir: Path
) -> None:
    tree = write(
        {
            "troupe.yml": "a: file:a.yaml\nlist:\n  - x\n",
            "a.yaml": b"b: file:sub/b.yml\r\n",
            "sub/b.yml": b"\xef\xbb\xbfitems:\n  - t: file:../t.md\n",
            "t.md": b"text\r\nwith CRLF\r\n",
        }
    )

    watched = watched_files(tree)

    expected = [
        state_dir / "troupe.yml",
        state_dir / "a.yaml",
        state_dir / "sub" / "b.yml",
        state_dir / "t.md",
    ]
    assert set(watched) == {path.resolve() for path in expected}
    assert all(data == path.read_bytes() for path, data in watched.items())


def test_watched_files_of_empty_root_contain_the_root(write: Write, state_dir: Path) -> None:
    tree = write({"troupe.yml": ""})

    assert watched_files(tree) == {(state_dir / "troupe.yml").resolve(): b""}


def test_watched_files_exclude_remote_content(
    write: Write, state_dir: Path, remote: RemoteServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NO_PROXY", LOCAL_NO_PROXY)
    monkeypatch.setenv("no_proxy", LOCAL_NO_PROXY)
    remote.serve("/sys.md", "be brief\n")
    team = remote.serve("/team.yaml", "prompt: file:sys.md\nmore: file:more.yaml\n")
    remote.serve("/more.yaml", "x: 1\n")
    tree = write(
        {
            "troupe.yml": f"team: {team}\nlocal: file:local.yaml\nref:\n  $ref: {team}\n  y: 2\n",
            "local.yaml": "a: 1\n",
        }
    )

    watched = watched_files(tree)

    assert watched == {
        (state_dir / "troupe.yml").resolve(): (state_dir / "troupe.yml").read_bytes(),
        (state_dir / "local.yaml").resolve(): b"a: 1\n",
    }
