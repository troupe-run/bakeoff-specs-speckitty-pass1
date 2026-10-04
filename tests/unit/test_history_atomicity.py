"""NFR-001: a change is saved with all of its events or with none, on the real eventsourcing store.

The failure is injected at encode time inside the single ``save()`` of ``HistoryStore.record``:
every event object of the batch is built (and applied to the in-memory aggregate) first, then
eventsourcing's JSON transcoder refuses the value of the last one. A value of type ``set`` is
used because building an event does not encode it; only saving does.
"""

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import cast

import pytest
from eventsourcing.persistence import TranscodingNotRegisteredError

from troupe.history import HISTORY_DB_NAME, HistoryStore
from troupe.leaves import Change, JsonScalar
from troupe.lineage import file_lineage, import_lineage


def _row_count(state_dir: Path) -> int:
    with closing(sqlite3.connect(state_dir / HISTORY_DB_NAME)) as connection:
        (count,) = connection.execute("SELECT COUNT(*) FROM stored_events").fetchone()
    return int(count)


def test_a_change_that_fails_to_save_records_none_of_its_events(tmp_path: Path) -> None:
    state_dir = tmp_path / ".troupe"
    state_dir.mkdir()
    store = HistoryStore(state_dir)
    try:
        store.import_leaves({"a": 1, "b": 2, "c": 3}, import_lineage())
        records_before = store.records()
        leaves_before = store.recorded_leaves()
        rows_before = _row_count(state_dir)
        # Deliberately not a JSON scalar: the transcoder cannot encode a ``set``.
        unencodable = cast(JsonScalar, {"x", "y"})
        batch = [
            Change("set", "a", 1, 10),
            Change("remove", "b", 2, None),
            Change("set", "c", 3, unencodable),
        ]

        with pytest.raises(TranscodingNotRegisteredError):
            store.record(batch, file_lineage())
    finally:
        store.close()

    reopened = HistoryStore(state_dir)
    try:
        assert reopened.records() == records_before
        assert reopened.recorded_leaves() == leaves_before == {"a": 1, "b": 2, "c": 3}
    finally:
        reopened.close()
    assert _row_count(state_dir) == rows_before
