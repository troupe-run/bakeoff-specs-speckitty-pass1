"""Reads, history and watch on a mapping-form include with overrides (US1, FR-004), real CLI.

Fixture from spec US1: ``coder`` includes ``agents/coder.yaml`` and overrides ``temperature``
and ``tools.web``. The number in a test's comment is the US1 acceptance scenario it covers.
"""

import time
from pathlib import Path

from conftest import (
    MakeTheatre,
    WatchProcess,
    core,
    history_events,
    recorded_within,
    run_cli,
    snapshot,
)
from troupe.loader import load
from troupe.reconcile import watched_files
from troupe.theatre import locate

type Files = dict[str, str | bytes]
type Event = dict[str, object]

ROOT = "coder:\n  $ref: file:agents/coder.yaml\n  temperature: 0.3\n  tools:\n    web: true\n"
CODER = "model: gpt\ntemperature: 0.7\ntools:\n  shell: true\nstop: [a, b]\n"
FIXTURE: Files = {"troupe.yml": ROOT, "agents/coder.yaml": CODER}
IMPORTED = 6  # merged leaves in FIXTURE, so the first event after the import has seq 7


def _cli(theatre: Path, *args: str) -> tuple[int, str, str]:
    result = run_cli("config", *args, "--theatre", str(theatre))
    return result.code, result.out, result.err


def _write(theatre: Path, rel: str, text: str) -> float:
    """Hand-edit ``.troupe/<rel>`` and return ``time.monotonic()`` right after the write."""
    (theatre / ".troupe" / rel).write_bytes(text.encode("utf-8"))
    return time.monotonic()


def _event(seq: int, op: str, path: str, old: object, new: object) -> Event:
    return {"seq": seq, "op": op, "path": path, "old": old, "new": new}


def test_get_returns_override_where_present_else_included_value(
    make_theatre: MakeTheatre,
) -> None:  # 1
    theatre = make_theatre(FIXTURE)

    assert [
        _cli(theatre, "get", "coder.temperature"),
        _cli(theatre, "get", "coder.model"),
        _cli(theatre, "get", "coder.tools.web"),
        _cli(theatre, "get", "coder.tools.shell"),
    ] == [(0, "0.3\n", ""), (0, "gpt\n", ""), (0, "true\n", ""), (0, "true\n", "")]


def test_show_prints_merged_mapping_without_ref(make_theatre: MakeTheatre) -> None:  # 2
    theatre = make_theatre(FIXTURE)

    assert _cli(theatre, "show", "coder") == (
        0,
        "model: gpt\ntemperature: 0.3\ntools:\n  shell: true\n  web: true\nstop:\n  - a\n  - b\n",
        "",
    )


def test_show_of_overridden_list_prints_only_override_items(make_theatre: MakeTheatre) -> None:
    # 3
    theatre = make_theatre({"troupe.yml": ROOT + "  stop: [c]\n", "agents/coder.yaml": CODER})

    assert _cli(theatre, "show", "coder.stop") == (0, "- c\n", "")


def test_show_sources_names_including_file_for_overrides(make_theatre: MakeTheatre) -> None:  # 4
    theatre = make_theatre(FIXTURE)

    assert _cli(theatre, "show", "coder", "--sources") == (
        0,
        "model: gpt # from .troupe/agents/coder.yaml\n"
        "temperature: 0.3 # from .troupe/troupe.yml\n"
        "tools:\n"
        "  shell: true # from .troupe/agents/coder.yaml\n"
        "  web: true # from .troupe/troupe.yml\n"
        "stop:\n"
        "  - a # from .troupe/agents/coder.yaml\n"
        "  - b # from .troupe/agents/coder.yaml\n",
        "",
    )


def test_first_command_imports_merged_leaves(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    assert core(history_events(theatre)) == [
        _event(1, "import", "coder.model", None, "gpt"),
        _event(2, "import", "coder.temperature", None, 0.3),
        _event(3, "import", "coder.tools.shell", None, True),
        _event(4, "import", "coder.tools.web", None, True),
        _event(5, "import", "coder.stop.0", None, "a"),
        _event(6, "import", "coder.stop.1", None, "b"),
    ]


def test_hand_edit_of_included_value_hidden_by_override_records_nothing(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre(FIXTURE)
    imported = history_events(theatre)
    _write(theatre, "agents/coder.yaml", CODER.replace("temperature: 0.7", "temperature: 0.9"))
    edited = snapshot(theatre)

    assert _cli(theatre, "get", "coder.temperature") == (0, "0.3\n", "")
    assert history_events(theatre) == imported
    assert snapshot(theatre) == edited


def test_hand_edit_of_override_records_one_set_event(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)
    imported = history_events(theatre)
    _write(theatre, "troupe.yml", ROOT.replace("temperature: 0.3", "temperature: 0.4"))

    assert _cli(theatre, "get", "coder.temperature") == (0, "0.4\n", "")
    assert core(history_events(theatre)) == [
        *core(imported),
        _event(IMPORTED + 1, "set", "coder.temperature", 0.3, 0.4),
    ]


def test_watch_follows_ref_target(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)
    with WatchProcess("--theatre", str(theatre)) as w:
        w.wait_ready()
        edited_at = _write(theatre, "agents/coder.yaml", CODER.replace("gpt", "claude"))

        events = recorded_within(theatre, edited_at)
        assert w.stop() == (0, "", "")

    assert core(events[IMPORTED:]) == [_event(IMPORTED + 1, "set", "coder.model", "gpt", "claude")]


def test_watched_files_include_ref_target_and_includes_hidden_by_overrides(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre(
        {
            "troupe.yml": "coder:\n  $ref: file:agents/coder.yaml\n  prompt: file:local.md\n",
            "agents/coder.yaml": "model: gpt\nprompt: file:shared.md\n",
            "agents/shared.md": "Shared.\n",
            "local.md": "Local.\n",
        }
    )

    files = watched_files(load(locate(theatre).config_file))

    state = (theatre / ".troupe").resolve()
    assert sorted(path.relative_to(state).as_posix() for path in files) == [
        "agents/coder.yaml",
        "agents/shared.md",  # hidden by the override, still read
        "local.md",
        "troupe.yml",
    ]
    assert _cli(theatre, "get", "coder.prompt") == (0, "Local.\n", "")
