"""Sanity checks of the pre-lineage fixture, reading it with ``sqlite3`` and ``json`` only.

No troupe code is imported: the fixture is the step-3 on-disk format, and the oracle must stay
independent of the code it checks (research D-9).
"""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

FIXTURE: Final = Path(__file__).resolve().parent.parent / "fixtures" / "pre_lineage"
PREFIX: Final = "troupe.history:ConfigHistory."
OPS: Final = {"LeafImported": "import", "LeafSet": "set", "LeafRemoved": "remove"}

type Row = tuple[int, str, dict[str, object]]


def _rows() -> list[Row]:
    """Return ``(originator_version, topic, decoded state)`` for every row, in version order."""
    # ``immutable=1``: no writes and no locks, so no ``-wal``/``-shm`` appears beside the fixture.
    db = FIXTURE / "history.sqlite"
    connection = sqlite3.connect(f"{db.as_uri()}?immutable=1", uri=True)
    try:
        raw: list[tuple[int, str, bytes]] = connection.execute(
            "SELECT originator_version, topic, state FROM stored_events ORDER BY originator_version"
        ).fetchall()
    finally:
        connection.close()
    return [(version, topic, json.loads(state)) for version, topic, state in raw]


def _at(encoded: object) -> str:
    assert isinstance(encoded, dict) and encoded["_type_"] == "datetime_iso", encoded
    data = encoded["_data_"]
    assert isinstance(data, str)
    return datetime.fromisoformat(data).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _oracle_line(version: int, topic: str, state: dict[str, object]) -> dict[str, object]:
    op = OPS[topic.removeprefix(PREFIX)]
    seq = version - 1
    return {
        "seq": seq,
        "op": op,
        "path": state["path"],
        "old": None if op == "import" else state["old"],
        "new": None if op == "remove" else state["new"],
        "actor": {"kind": "unknown", "id": None},
        "via": "import" if op == "import" else None,
        "at": _at(state["timestamp"]),
        "reason": None,
        "change": f"pre-lineage-{seq}",
    }


def test_fixture_rows_are_version_1_events_with_the_step_3_topics() -> None:
    rows = _rows()

    assert [version for version, _, _ in rows] == list(range(1, len(rows) + 1))
    assert rows[0][1] == PREFIX + "Created"
    leaf_rows = rows[1:]
    assert [topic.removeprefix(PREFIX) for _, topic, _ in leaf_rows] == [
        *["LeafImported"] * 5,
        "LeafSet",
        "LeafSet",
        "LeafRemoved",
    ]
    for _, topic, state in leaf_rows:
        assert topic.startswith(PREFIX)
        assert "class_version" not in state, state


def test_expected_history_matches_the_fixture_rows() -> None:
    expected_text = (FIXTURE / "expected_history.jsonl").read_text(encoding="utf-8")

    recomputed = [_oracle_line(*row) for row in _rows()[1:]]

    assert expected_text == "".join(
        json.dumps(line, ensure_ascii=False) + "\n" for line in recomputed
    )


def test_fixture_database_has_no_wal_dependency() -> None:
    assert not (FIXTURE / "history.sqlite-wal").exists()
    assert not (FIXTURE / "history.sqlite-shm").exists()
