"""HistoryStore against the real eventsourcing library and a real SQLite file."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from troupe.history import HISTORY_DB_NAME, HistoryRecord, HistoryStore
from troupe.leaves import Change, JsonScalar


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    directory = tmp_path / ".troupe"
    directory.mkdir()
    return directory


@pytest.fixture
def store(state_dir: Path) -> Iterator[HistoryStore]:
    opened = HistoryStore(state_dir)
    yield opened
    opened.close()


def _reopened(state_dir: Path) -> list[HistoryRecord]:
    fresh = HistoryStore(state_dir)
    try:
        return fresh.records()
    finally:
        fresh.close()


def test_new_store_is_not_imported_and_has_no_records(store: HistoryStore) -> None:
    assert not store.is_imported()
    assert store.records() == []


def test_store_persists_in_history_sqlite_in_the_state_dir(
    store: HistoryStore, state_dir: Path
) -> None:
    store.import_leaves({"a": 1})

    assert (state_dir / HISTORY_DB_NAME).is_file()
    assert {p.name for p in state_dir.iterdir()} <= {
        HISTORY_DB_NAME,
        f"{HISTORY_DB_NAME}-wal",
        f"{HISTORY_DB_NAME}-shm",
        f"{HISTORY_DB_NAME}-journal",
    }


def test_import_is_read_back_by_a_new_store_instance_with_seq_from_one(
    store: HistoryStore, state_dir: Path
) -> None:
    store.import_leaves({"model.name": "gpt", "tools.0": "search", "retries": 3})
    store.close()

    assert _reopened(state_dir) == [
        HistoryRecord(1, "import", "model.name", None, "gpt"),
        HistoryRecord(2, "import", "tools.0", None, "search"),
        HistoryRecord(3, "import", "retries", None, 3),
    ]


def test_import_of_no_leaves_still_marks_theatre_imported(
    store: HistoryStore, state_dir: Path
) -> None:
    store.import_leaves({})
    store.close()

    reopened = HistoryStore(state_dir)
    try:
        assert reopened.is_imported()
        assert reopened.records() == []
    finally:
        reopened.close()


def test_record_appends_after_import_with_continuing_seq(
    store: HistoryStore, state_dir: Path
) -> None:
    store.import_leaves({"a": 1, "b": 2})
    store.record([Change("set", "a", 1, 5), Change("remove", "b", 2, None)])
    store.record([Change("set", "c", None, "new")])
    store.close()

    assert _reopened(state_dir) == [
        HistoryRecord(1, "import", "a", None, 1),
        HistoryRecord(2, "import", "b", None, 2),
        HistoryRecord(3, "set", "a", 1, 5),
        HistoryRecord(4, "remove", "b", 2, None),
        HistoryRecord(5, "set", "c", None, "new"),
    ]


def test_record_of_no_changes_appends_nothing(store: HistoryStore) -> None:
    store.import_leaves({"a": 1})
    store.record([])

    assert store.records() == [HistoryRecord(1, "import", "a", None, 1)]


def test_values_keep_their_json_types_through_the_store(
    store: HistoryStore, state_dir: Path
) -> None:
    values: dict[str, JsonScalar] = {
        "bool": True,
        "false": False,
        "float": 1.0,
        "int": 1,
        "null": None,
        "str": "1",
    }
    store.import_leaves(values)
    store.record([Change("set", "bool", True, 0.5)])
    store.close()

    records = _reopened(state_dir)

    read_back = {r.path: r.new for r in records if r.op == "import"}
    assert [(type(v), v) for v in read_back.values()] == [(type(v), v) for v in values.values()]
    assert (type(records[-1].old), type(records[-1].new)) == (bool, float)


def test_environment_variables_cannot_redirect_the_store(
    state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PERSISTENCE_MODULE", "eventsourcing.popo")
    monkeypatch.setenv("SQLITE_DBNAME", str(state_dir / "elsewhere.sqlite"))
    monkeypatch.setenv("_HISTORYAPPLICATION_SQLITE_DBNAME", str(state_dir / "other.sqlite"))

    opened = HistoryStore(state_dir)
    try:
        opened.import_leaves({"a": 1})
    finally:
        opened.close()

    assert {p.name for p in state_dir.iterdir() if not p.name.endswith(("-wal", "-shm"))} == {
        HISTORY_DB_NAME
    }
