"""User Story 4: lineage survives restarts and a pre-lineage history stays readable and untouched.

The pre-lineage store (tests/fixtures/pre_lineage, written by the step-3 code) is always copied
into a temporary theatre first; the fixture itself is never opened. Stored rows are read with
``sqlite3`` directly, not with troupe code, and compared as raw bytes (NFR-004, C-005).
"""

import json
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

from test_history import _valid_record

from conftest import MakeTheatre, run_cli

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "pre_lineage"
ORACLE = (FIXTURE_DIR / "expected_history.jsonl").read_text("utf-8")
ORACLE_LINES = ORACLE.splitlines(keepends=True)

type Row = tuple[str, int, str, bytes]


def _pre_lineage_theatre(make_theatre: MakeTheatre) -> Path:
    """Copy the fixture's ``troupe.yml`` and ``history.sqlite`` into a fresh theatre."""
    return make_theatre(
        {
            "troupe.yml": (FIXTURE_DIR / "troupe.yml").read_bytes(),
            "history.sqlite": (FIXTURE_DIR / "history.sqlite").read_bytes(),
        }
    )


def _rows(theatre: Path) -> list[Row]:
    """Return every raw ``stored_events`` row of the theatre's store, read with ``sqlite3``."""
    database = theatre / ".troupe" / "history.sqlite"
    with closing(sqlite3.connect(database)) as connection:
        rows: list[Row] = connection.execute(
            "SELECT originator_id, originator_version, topic, state FROM stored_events "
            "ORDER BY originator_id, originator_version"
        ).fetchall()
    return rows


def _history_text(theatre: Path) -> str:
    result = run_cli("config", "history", "--theatre", str(theatre))
    assert (result.code, result.err) == (0, ""), result.err
    return result.out


def _records(text: str) -> list[dict[str, Any]]:
    return [_valid_record(line) for line in text.splitlines()]


def test_pre_lineage_history_prints_known_fields_and_marks_the_rest_unknown(
    make_theatre: MakeTheatre,
) -> None:  # US4-2, FR-013
    theatre = _pre_lineage_theatre(make_theatre)

    text = _history_text(theatre)

    assert _records(text) == [json.loads(line) for line in ORACLE_LINES]
    assert text == ORACLE


def test_reading_pre_lineage_history_does_not_modify_stored_rows(
    make_theatre: MakeTheatre,
) -> None:  # NFR-004, C-005
    theatre = _pre_lineage_theatre(make_theatre)
    before = _rows(theatre)
    assert len(before) >= len(ORACLE_LINES)

    _history_text(theatre)
    _history_text(theatre)

    assert _rows(theatre) == before


def test_new_set_on_pre_lineage_history_has_full_lineage_and_a_fresh_change(
    make_theatre: MakeTheatre,
) -> None:  # US4-3, NFR-004
    theatre = _pre_lineage_theatre(make_theatre)
    rows_before = _rows(theatre)

    result = run_cli(
        "config",
        "set",
        "model.temperature",
        "0.9",
        "--theatre",
        str(theatre),
        env={"TROUPE_ACTOR": "human:alice"},
    )

    assert (result.code, result.out, result.err) == (0, "", "")
    lines = _history_text(theatre).splitlines(keepends=True)
    assert lines[: len(ORACLE_LINES)] == ORACLE_LINES
    [new] = _records("".join(lines[len(ORACLE_LINES) :]))
    assert (new["seq"], new["op"], new["path"], new["old"], new["new"]) == (
        len(ORACLE_LINES) + 1,
        "set",
        "model.temperature",
        0.5,
        0.9,
    )
    assert (new["actor"], new["via"], new["reason"]) == (
        {"kind": "human", "id": "alice"},
        "cli",
        None,
    )
    assert str(uuid.UUID(new["change"])) == new["change"]
    assert new["change"] not in {json.loads(line)["change"] for line in ORACLE_LINES}
    rows_after = _rows(theatre)
    assert set(rows_before) <= set(rows_after)  # every old row is still there, byte for byte
    assert len(rows_after) > len(rows_before)


def test_history_survives_restart_byte_identical(make_theatre: MakeTheatre) -> None:
    # US4-1, SC-004, FR-012
    theatre = _pre_lineage_theatre(make_theatre)
    root = theatre / ".troupe" / "troupe.yml"
    set_reason = run_cli(
        "config",
        "set",
        "tools",
        "[search, fetch, read]",
        "--reason",
        "add read",
        "--theatre",
        str(theatre),
        env={"TROUPE_ACTOR": "agent:planner"},
    )
    assert (set_reason.code, set_reason.err) == (0, "")
    root.write_text(root.read_text("utf-8").replace("name: claude", "name: o1"), "utf-8")
    assert run_cli("config", "get", "model.name", "--theatre", str(theatre)).out == "o1\n"

    first = _history_text(theatre)
    second = _history_text(theatre)

    assert first == second
    records = _records(first)
    assert first.startswith(ORACLE)
    assert [r["via"] for r in records[len(ORACLE_LINES) :]] == ["cli", "file"]
