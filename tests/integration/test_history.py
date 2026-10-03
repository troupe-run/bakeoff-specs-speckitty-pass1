"""``troupe config history [PATH]`` through the real CLI: import, output format, confinement."""

import json
from pathlib import Path
from typing import Any

from conftest import HISTORY_PREFIX, MakeTheatre, all_files, run_cli, snapshot

FIXTURE: dict[str, str | bytes] = {
    "troupe.yml": (
        "model:\n"
        "  name: gpt\n"
        "  temperature: 0.2\n"
        "tools:\n"
        "  - search\n"
        "  - true\n"
        "agents:\n"
        "  coder: file:agents/coder.yaml\n"
        "prompt: file:prompt.md\n"
        "retries: null\n"
    ),
    "agents/coder.yaml": "name: Cody\nlevel: 3\n",
    "prompt.md": "Be kind.\n",
}

FIXTURE_IMPORT = [
    {"seq": 1, "op": "import", "path": "model.name", "old": None, "new": "gpt"},
    {"seq": 2, "op": "import", "path": "model.temperature", "old": None, "new": 0.2},
    {"seq": 3, "op": "import", "path": "tools.0", "old": None, "new": "search"},
    {"seq": 4, "op": "import", "path": "tools.1", "old": None, "new": True},
    {"seq": 5, "op": "import", "path": "agents.coder.name", "old": None, "new": "Cody"},
    {"seq": 6, "op": "import", "path": "agents.coder.level", "old": None, "new": 3},
    {"seq": 7, "op": "import", "path": "prompt", "old": None, "new": "Be kind.\n"},
    {"seq": 8, "op": "import", "path": "retries", "old": None, "new": None},
]

KEYS = ["seq", "op", "path", "old", "new"]
JSON_SCALARS = (str, int, float, bool, type(None))


def _history(theatre: Path, *path: str) -> list[dict[str, Any]]:
    result = run_cli("config", "history", *path, "--theatre", str(theatre))
    assert (result.code, result.err) == (0, "")
    return [_valid_record(line) for line in result.out.splitlines()]


def _valid_record(line: str) -> dict[str, Any]:
    """Parse one line and check it against contracts/history-event.schema.json."""
    record: dict[str, Any] = json.loads(line)
    assert list(record) == KEYS
    assert type(record["seq"]) is int and record["seq"] >= 1
    assert record["op"] in ("import", "set", "remove")
    assert isinstance(record["path"], str)
    assert isinstance(record["old"], JSON_SCALARS)
    assert isinstance(record["new"], JSON_SCALARS)
    if record["op"] == "import":
        assert record["old"] is None
    if record["op"] == "remove":
        assert record["new"] is None
    return record


def test_history_on_fresh_theatre_imports_every_leaf_in_document_order(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre(FIXTURE)

    result = run_cli("config", "history", "--theatre", str(theatre))

    assert (result.code, result.err) == (0, "")
    assert result.out == "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in FIXTURE_IMPORT)
    assert [_valid_record(line) for line in result.out.splitlines()] == FIXTURE_IMPORT


def test_history_output_keeps_non_ascii_text_unescaped(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "name: Zoë\n"})

    result = run_cli("config", "history", "--theatre", str(theatre))

    assert result.out == '{"seq": 1, "op": "import", "path": "name", "old": null, "new": "Zoë"}\n'


def test_second_history_run_does_not_reimport(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)
    first = _history(theatre)

    second = _history(theatre)

    assert second == first == FIXTURE_IMPORT


def test_history_does_not_reconcile_a_hand_edit(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "a: 1\nb: 2\n"})
    imported = _history(theatre)

    (theatre / ".troupe" / "troupe.yml").write_text("a: 100\nc: 3\n", encoding="utf-8")

    assert _history(theatre) == imported
    assert [r["path"] for r in imported] == ["a", "b"]

    shown = run_cli("config", "get", "a", "--theatre", str(theatre))

    assert (shown.code, shown.out, shown.err) == (0, "100\n", "")
    assert _history(theatre) == [
        *imported,
        {"seq": 3, "op": "set", "path": "a", "old": 1, "new": 100},
        {"seq": 4, "op": "set", "path": "c", "old": None, "new": 3},
        {"seq": 5, "op": "remove", "path": "b", "old": 2, "new": None},
    ]


def test_history_of_empty_configuration_prints_nothing(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": ""})

    result = run_cli("config", "history", "--theatre", str(theatre))

    assert (result.code, result.out, result.err) == (0, "", "")
    assert (theatre / HISTORY_PREFIX).is_file()


def test_history_path_filter_matches_exact_and_dotted_prefix_only(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre(
        {"troupe.yml": "model: m\nmodels:\n  a: 1\nmodel_x: 2\nmodel2:\n  model: 3\n"}
    )

    assert [r["path"] for r in _history(theatre, "model")] == ["model"]
    assert [r["path"] for r in _history(theatre, "models")] == ["models.a"]
    assert [r["path"] for r in _history(theatre, "models.a")] == ["models.a"]


def test_history_path_filter_keeps_original_seq(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    filtered = _history(theatre, "agents.coder")

    assert filtered == FIXTURE_IMPORT[4:6]


def test_history_path_filter_matching_nothing_prints_nothing_and_exits_0(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre(FIXTURE)

    result = run_cli("config", "history", "nope.nothing", "--theatre", str(theatre))

    assert (result.code, result.out, result.err) == (0, "", "")


def test_history_path_with_empty_segment_exits_2_and_creates_nothing(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre(FIXTURE)
    before = all_files(theatre)

    result = run_cli("config", "history", "model..name", "--theatre", str(theatre))

    assert (result.code, result.out) == (2, "")
    assert "model..name" in result.err
    assert all_files(theatre) == before


def test_history_creates_only_history_files_under_dot_troupe(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)
    files_before = all_files(theatre)
    bytes_before = snapshot(theatre)

    _history(theatre)

    created = all_files(theatre) - files_before
    assert HISTORY_PREFIX in created
    assert all(rel.startswith(HISTORY_PREFIX) for rel in created)
    assert snapshot(theatre) == bytes_before


def test_load_failure_creates_no_history_file(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "a: file:missing.yaml\n"})
    files_before = all_files(theatre)

    result = run_cli("config", "history", "--theatre", str(theatre))

    assert (result.code, result.out) == (4, "")
    assert "missing.yaml" in result.err
    assert all_files(theatre) == files_before
    assert not any(rel.startswith(HISTORY_PREFIX) for rel in all_files(theatre))


def test_load_failure_after_import_appends_nothing(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "a: 1\n"})
    imported = _history(theatre)
    config = theatre / ".troupe" / "troupe.yml"

    config.write_text("a: [unclosed\n", encoding="utf-8")
    failed = run_cli("config", "history", "--theatre", str(theatre))
    config.write_text("a: 1\n", encoding="utf-8")

    assert failed.code == 4
    assert _history(theatre) == imported
