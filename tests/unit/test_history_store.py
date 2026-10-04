"""HistoryStore against the real eventsourcing library and a real SQLite file."""

import json
import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest

from troupe.history import HISTORY_DB_NAME, HistoryRecord, HistoryStore
from troupe.leaves import Change, JsonScalar
from troupe.lineage import (
    UNKNOWN_ACTOR,
    Actor,
    Lineage,
    cli_lineage,
    file_lineage,
    import_lineage,
)

PRE_LINEAGE: Final = Path(__file__).resolve().parent.parent / "fixtures" / "pre_lineage"

type Core = tuple[int, str, str, JsonScalar, JsonScalar]
type Row = tuple[int, str, bytes]


def _cli() -> Lineage:
    """A fresh lineage of one CLI change, for tests that only check the five original fields."""
    return cli_lineage(Actor("human", "t"), None)


def _core(records: list[HistoryRecord]) -> list[Core]:
    """Project records onto the five step-1 fields ``seq, op, path, old, new``."""
    return [(r.seq, r.op, r.path, r.old, r.new) for r in records]


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
    store.import_leaves({"a": 1}, import_lineage())

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
    store.import_leaves({"model.name": "gpt", "tools.0": "search", "retries": 3}, import_lineage())
    store.close()

    assert _core(_reopened(state_dir)) == [
        (1, "import", "model.name", None, "gpt"),
        (2, "import", "tools.0", None, "search"),
        (3, "import", "retries", None, 3),
    ]


def test_import_of_no_leaves_still_marks_theatre_imported(
    store: HistoryStore, state_dir: Path
) -> None:
    store.import_leaves({}, import_lineage())
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
    store.import_leaves({"a": 1, "b": 2}, import_lineage())
    store.record([Change("set", "a", 1, 5), Change("remove", "b", 2, None)], _cli())
    store.record([Change("set", "c", None, "new")], _cli())
    store.close()

    assert _core(_reopened(state_dir)) == [
        (1, "import", "a", None, 1),
        (2, "import", "b", None, 2),
        (3, "set", "a", 1, 5),
        (4, "remove", "b", 2, None),
        (5, "set", "c", None, "new"),
    ]


def test_record_of_no_changes_appends_nothing(store: HistoryStore) -> None:
    store.import_leaves({"a": 1}, import_lineage())
    store.record([], _cli())

    assert _core(store.records()) == [(1, "import", "a", None, 1)]


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
    store.import_leaves(values, import_lineage())
    store.record([Change("set", "bool", True, 0.5)], _cli())
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
        opened.import_leaves({"a": 1}, import_lineage())
    finally:
        opened.close()

    assert {p.name for p in state_dir.iterdir() if not p.name.endswith(("-wal", "-shm"))} == {
        HISTORY_DB_NAME
    }


def test_recorded_leaves_after_import_equal_imported_leaves_in_order(
    store: HistoryStore,
) -> None:
    imported: dict[str, JsonScalar] = {"a": 1, "b.0": "x", "c": None}
    store.import_leaves(imported, import_lineage())

    recorded = store.recorded_leaves()

    assert recorded == imported
    assert list(recorded) == list(imported)


def test_recorded_leaves_apply_set_and_remove_events(store: HistoryStore) -> None:
    store.import_leaves({"a": 1, "b": 2}, import_lineage())
    store.record(
        [
            Change("set", "a", 1, 10),
            Change("set", "n", None, "new"),
            Change("remove", "b", 2, None),
        ],
        _cli(),
    )

    recorded = store.recorded_leaves()

    assert recorded == {"a": 10, "n": "new"}
    assert list(recorded) == ["a", "n"]


def test_recorded_leaves_are_rebuilt_after_reopening_the_store(
    store: HistoryStore, state_dir: Path
) -> None:
    store.import_leaves({"a": 1, "b": 2, "c": 3}, import_lineage())
    store.record([Change("set", "b", 2, 20), Change("remove", "c", 3, None)], _cli())
    written = store.recorded_leaves()
    store.close()

    reopened = HistoryStore(state_dir)
    try:
        assert reopened.recorded_leaves() == written == {"a": 1, "b": 20}
    finally:
        reopened.close()


def test_replay_tolerates_remove_of_a_never_recorded_path(
    store: HistoryStore, state_dir: Path
) -> None:
    store.import_leaves({"a": 1}, import_lineage())
    store.record([Change("remove", "ghost", "x", None)], _cli())
    store.close()

    reopened = HistoryStore(state_dir)
    try:
        assert reopened.recorded_leaves() == {"a": 1}
        assert _core(reopened.records())[-1] == (2, "remove", "ghost", "x", None)
    finally:
        reopened.close()


def test_recorded_leaves_returns_a_copy(store: HistoryStore) -> None:
    store.import_leaves({"a": 1}, import_lineage())

    first = store.recorded_leaves()
    first["a"] = 99
    first["extra"] = "added"

    assert store.recorded_leaves() == {"a": 1}


def test_lineage_is_persisted_and_read_back_after_reopen(
    store: HistoryStore, state_dir: Path
) -> None:
    lineage = Lineage(
        Actor("agent", "planner:v2 x"),
        "cli",
        "2026-10-04T10:18:24.017202Z",
        'raise "limit"\nnaïve — 限界',
        "1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed",
    )
    store.import_leaves({"a": 1, "b": 2}, import_lineage())
    store.record([Change("set", "a", 1, 2), Change("remove", "b", 2, None)], lineage)
    store.close()

    records = _reopened(state_dir)

    assert [r.lineage for r in records[2:]] == [lineage, lineage]


def test_every_event_saved_by_one_call_shares_its_lineage(store: HistoryStore) -> None:
    lineage = cli_lineage(Actor("human", "alice"), "why")
    store.import_leaves({"a": 1, "b": 2}, import_lineage())
    store.record(
        [Change("set", "a", 1, 2), Change("set", "c", None, 3), Change("remove", "b", 2, None)],
        lineage,
    )

    assert [r.lineage for r in store.records()[2:]] == [lineage] * 3


def test_separate_calls_have_separate_changes(store: HistoryStore) -> None:
    store.import_leaves({"a": 1}, import_lineage())
    store.record([Change("set", "a", 1, 2)], _cli())
    store.record([Change("set", "a", 2, 3)], file_lineage())

    changes = [r.lineage.change for r in store.records()]

    assert len(set(changes)) == 3


def test_import_events_carry_the_import_lineage(store: HistoryStore) -> None:
    lineage = import_lineage()
    store.import_leaves({"a": 1, "b": "x", "c": None}, lineage)

    records = store.records()

    assert [r.lineage for r in records] == [lineage] * 3
    assert (lineage.actor, lineage.via, lineage.reason) == (UNKNOWN_ACTOR, "import", None)


@pytest.fixture
def pre_lineage_dir(tmp_path: Path) -> Path:
    """A state dir holding a copy of the step-3 fixture database (never opened in place)."""
    directory = tmp_path / "old" / ".troupe"
    directory.mkdir(parents=True)
    shutil.copyfile(PRE_LINEAGE / HISTORY_DB_NAME, directory / HISTORY_DB_NAME)
    return directory


def _as_history_line(record: HistoryRecord) -> dict[str, object]:
    lineage = record.lineage
    return {
        "seq": record.seq,
        "op": record.op,
        "path": record.path,
        "old": record.old,
        "new": record.new,
        "actor": {"kind": lineage.actor.kind, "id": lineage.actor.id},
        "via": lineage.via,
        "at": lineage.at,
        "reason": lineage.reason,
        "change": lineage.change,
    }


def _stored_rows(state_dir: Path) -> list[Row]:
    connection = sqlite3.connect(state_dir / HISTORY_DB_NAME)
    try:
        rows: list[Row] = connection.execute(
            "SELECT originator_version, topic, state FROM stored_events ORDER BY originator_version"
        ).fetchall()
    finally:
        connection.close()
    return rows


def test_pre_lineage_history_is_read_with_the_recorded_upcast(pre_lineage_dir: Path) -> None:
    expected = [
        json.loads(line)
        for line in (PRE_LINEAGE / "expected_history.jsonl").read_text("utf-8").splitlines()
    ]

    records = _reopened(pre_lineage_dir)

    assert [_as_history_line(r) for r in records] == expected


def test_reading_and_appending_to_a_pre_lineage_history_leaves_old_rows_byte_identical(
    pre_lineage_dir: Path,
) -> None:
    before = _stored_rows(pre_lineage_dir)
    opened = HistoryStore(pre_lineage_dir)
    try:
        opened.records()
        opened.record([Change("set", "model.name", "claude", "gpt")], file_lineage())
    finally:
        opened.close()

    after = _stored_rows(pre_lineage_dir)

    assert after[: len(before)] == before
    added = after[len(before) :]
    assert [(version, topic) for version, topic, _ in added] == [
        (len(before) + 1, "troupe.history:ConfigHistory.LeafSet")
    ]
    assert json.loads(added[0][2])["class_version"] == 2


def test_appended_events_after_pre_lineage_have_full_lineage_and_a_new_change(
    pre_lineage_dir: Path,
) -> None:
    lineage = cli_lineage(Actor("agent", "planner"), "raise limit")
    opened = HistoryStore(pre_lineage_dir)
    try:
        opened.record(
            [Change("set", "model.temperature", 0.5, 0.7), Change("set", "x", None, 1)], lineage
        )
    finally:
        opened.close()

    records = _reopened(pre_lineage_dir)

    old, new = records[:8], records[8:]
    assert [r.lineage for r in new] == [lineage, lineage]
    assert lineage.change not in {r.lineage.change for r in old}
    assert _core(new) == [(9, "set", "model.temperature", 0.5, 0.7), (10, "set", "x", None, 1)]
