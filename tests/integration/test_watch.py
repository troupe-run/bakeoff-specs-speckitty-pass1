"""``troupe config watch`` (User Story 2, FR-008..FR-014, NFR-001/002/004/005), via real processes.

Every test runs the real CLI as a child process (``WatchProcess``), which is always killed on the
way out. Waits are deadlines, except the two the contract itself defines: ``recorded_within``
(an edit is recorded within 2 s, FR-011) and ``QUIET`` (nothing is recorded or reported for a
while). The number in each test's comment is the US2 acceptance scenario it covers.
"""

import os
import signal
import time
from itertools import pairwise
from pathlib import Path

import pytest

from conftest import (
    MakeTheatre,
    WatchProcess,
    core,
    history_events,
    recorded_within,
    run_cli,
    snapshot,
)

type Files = dict[str, str | bytes]
type Event = dict[str, object]

ROOT = "a: 1\nmodel:\n  name: gpt\nagents:\n  coder: file:agents/coder.yaml\nprompt: file:sys.md\n"
FIXTURE: Files = {
    "troupe.yml": ROOT,
    "agents/coder.yaml": "name: Ada\nlevel: 3\n",
    "sys.md": "Be kind.\n",
}
IMPORTED = 5  # leaves in FIXTURE, so the first event after the import has seq 6
QUIET = 2.5  # seconds: longer than the 2 s contract, so "nothing happened" means nothing will


def _write(theatre: Path, rel: str, text: str) -> float:
    """Hand-edit ``.troupe/<rel>`` and return ``time.monotonic()`` right after the write."""
    target = theatre / ".troupe" / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.encode("utf-8"))
    return time.monotonic()


def _set(seq: int, path: str, old: object, new: object) -> Event:
    return {"seq": seq, "op": "set", "path": path, "old": old, "new": new}


def _recorded(events: list[Event]) -> dict[object, object]:
    """Replay the history into the recorded configuration, checking each event's ``old``."""
    leaves: dict[object, object] = {}
    for event in events:
        path = event["path"]
        if event["op"] != "import":
            assert event["old"] == leaves.get(path), f"stale old value in {event}"
        if event["op"] == "remove":
            del leaves[path]
        else:
            leaves[path] = event["new"]
    return leaves


def _watch(theatre: Path) -> WatchProcess:
    return WatchProcess("--theatre", str(theatre))


def test_watch_prints_exactly_watching_dir_and_nothing_else(make_theatre: MakeTheatre) -> None:  # 1
    theatre = make_theatre(FIXTURE)
    with _watch(theatre) as w:
        line = w.wait_ready()
        edited_at = _write(theatre, "troupe.yml", ROOT.replace("a: 1", "a: 2"))
        assert len(recorded_within(theatre, edited_at)) == IMPORTED + 1
        code, rest, err = w.stop()

    assert (line, code, rest, err) == (f"watching {theatre}\n", 0, "", "")


def test_watching_line_echoes_theatre_argument_verbatim(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)
    for args, cwd, shown in (
        (("--theatre", theatre.name), theatre.parent, theatre.name),
        (("--theatre", f"{theatre}/"), None, f"{theatre}/"),
        (("--theatre", f"{theatre}/.troupe/.."), None, f"{theatre}/.troupe/.."),
    ):
        with WatchProcess(*args, cwd=cwd) as w:
            assert w.wait_ready() == f"watching {shown}\n"
            assert w.stop()[0] == 0


def test_watching_line_uses_env_var_then_cwd_when_no_option(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)
    with WatchProcess(cwd=theatre.parent, env={"TROUPE_THEATRE": theatre.name}) as w:
        assert w.wait_ready() == f"watching {theatre.name}\n"
        assert w.stop()[0] == 0
    with WatchProcess(cwd=theatre) as w:  # os.getcwd() is the physical path of the cwd
        assert w.wait_ready() == f"watching {theatre.resolve()}\n"
        assert w.stop()[0] == 0


def test_root_file_edit_is_recorded_within_two_seconds(make_theatre: MakeTheatre) -> None:  # 2
    theatre = make_theatre(FIXTURE)
    with _watch(theatre) as w:
        w.wait_ready()
        edited_at = _write(theatre, "troupe.yml", ROOT.replace("a: 1", "a: 2"))

        events = recorded_within(theatre, edited_at)

    assert core(events[IMPORTED:]) == [_set(6, "a", 1, 2)]


def test_edit_immediately_after_watching_line_is_not_missed(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)
    with _watch(theatre) as w:
        w.wait_ready()
        edited_at = _write(theatre, "troupe.yml", ROOT.replace("a: 1", "a: 2"))  # same size

        events = recorded_within(theatre, edited_at)

    assert _recorded(events)["a"] == 2


def test_yaml_include_and_text_include_edits_are_recorded(make_theatre: MakeTheatre) -> None:  # 3
    theatre = make_theatre(FIXTURE)
    with _watch(theatre) as w:
        w.wait_ready()
        yaml_edited_at = _write(theatre, "agents/coder.yaml", "name: Ada\nlevel: 4\n")
        after_yaml = recorded_within(theatre, yaml_edited_at)
        text_edited_at = _write(theatre, "sys.md", "Be brave.\n")
        after_text = recorded_within(theatre, text_edited_at)

    assert core(after_yaml[IMPORTED:]) == [_set(6, "agents.coder.level", 3, 4)]
    assert core(after_text[IMPORTED:]) == [
        _set(6, "agents.coder.level", 3, 4),
        _set(7, "prompt", "Be kind.\n", "Be brave.\n"),
    ]


def test_comment_only_and_formatting_only_edits_record_nothing(
    make_theatre: MakeTheatre,
) -> None:  # 4
    theatre = make_theatre(FIXTURE)
    with _watch(theatre) as w:
        w.wait_ready()
        before = history_events(theatre)
        _write(theatre, "troupe.yml", "# tuned by hand\n" + ROOT.replace("a: 1", "a:    1  # one"))
        _write(theatre, "agents/coder.yaml", "{name: Ada,   level: 3}\n")
        time.sleep(QUIET)
        quiet = history_events(theatre)
        # Still watching: a real change after the cosmetic ones is recorded.
        edited_at = _write(theatre, "agents/coder.yaml", "{name: Ada,   level: 9}\n")
        after = recorded_within(theatre, edited_at)

    assert len(before) == IMPORTED
    assert quiet == before
    assert core(after[IMPORTED:]) == [_set(6, "agents.coder.level", 3, 9)]


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM], ids=["SIGINT", "SIGTERM"])
def test_sigint_and_sigterm_exit_zero_within_two_seconds(
    make_theatre: MakeTheatre, sig: signal.Signals
) -> None:  # 5
    theatre = make_theatre(FIXTURE)
    with _watch(theatre) as w:
        w.wait_ready()
        sent_at = time.monotonic()

        code, rest, err = w.stop(sig)

    assert time.monotonic() - sent_at < 2.0
    assert (code, rest, err) == (0, "", "")


def test_watch_imports_a_never_imported_theatre_before_the_line(
    make_theatre: MakeTheatre,
) -> None:  # 6
    theatre = make_theatre(FIXTURE)
    history_file = theatre / ".troupe" / "history.sqlite"
    assert not history_file.exists()
    with _watch(theatre) as w:
        w.wait_ready()
        imported_when_ready = history_file.exists()
        events = history_events(theatre)

    assert imported_when_ready
    assert [(e["op"], e["path"]) for e in events] == [
        ("import", "a"),
        ("import", "model.name"),
        ("import", "agents.coder.name"),
        ("import", "agents.coder.level"),
        ("import", "prompt"),
    ]


@pytest.mark.parametrize(
    ("files", "named"),
    [
        ({}, "troupe.yml"),
        ({"troupe.yml": "a: 1\n", "troupe.yaml": "a: 1\n"}, "troupe.yaml"),
        ({"troupe.yml": "a: [\n"}, "troupe.yml"),
        ({"troupe.yml": "x: file:gone.yaml\n"}, "gone.yaml"),
        ({"troupe.yml": "x: file:a.yaml\n", "a.yaml": "back: file:troupe.yml\n"}, "a.yaml"),
    ],
    ids=["no-root-file", "both-root-files", "bad-yaml", "missing-include", "include-cycle"],
)
def test_watch_on_unloadable_configuration_exits_4_without_the_line(
    make_theatre: MakeTheatre, files: Files, named: str
) -> None:  # 7
    theatre = make_theatre(files)
    with _watch(theatre) as w:
        code, out, err = w.wait_exit()

    assert (code, out) == (4, "")
    assert err.startswith("troupe: ") and err.count("\n") == 1 and err.endswith("\n")
    assert str(theatre.resolve() / ".troupe" / named) in err
    assert not (theatre / ".troupe" / "history.sqlite").exists()


def test_unloadable_edit_reports_once_keeps_watching_then_recovers(
    make_theatre: MakeTheatre,
) -> None:  # 8
    theatre = make_theatre(FIXTURE)
    root = theatre.resolve() / ".troupe" / "troupe.yml"
    with _watch(theatre) as w:
        w.wait_ready()

        _write(theatre, "troupe.yml", "a: 1\na: 1\n")
        first = w.wait_stderr(1)

        _write(theatre, "troupe.yml", "a: 1\na: 2\n")  # different file, same message
        time.sleep(QUIET)
        same_message = w.stderr_lines()

        _write(theatre, "troupe.yml", "b: 1\nb: 1\n")  # a different message
        second = w.wait_stderr(2)

        fixed_at = _write(theatre, "troupe.yml", ROOT.replace("a: 1", "a: 7"))
        recovered = recorded_within(theatre, fixed_at)
        code, rest, err = w.stop()

    assert first == [f"troupe: cannot load {root}: duplicate key a at line 2\n"]
    assert same_message == first
    assert second == [*first, f"troupe: cannot load {root}: duplicate key b at line 2\n"]
    # ``history`` cannot load the broken files either, so it is read after the fix: only the
    # fix itself was recorded, nothing for any unloadable state in between.
    assert core(recovered[IMPORTED:]) == [_set(6, "a", 1, 7)]
    assert (code, rest) == (0, "")
    assert err == "".join(second)


def test_missing_include_target_created_later_is_recorded(make_theatre: MakeTheatre) -> None:
    # User Story 4, scenario 3: the target is in no baseline, so only the retry can see it.
    theatre = make_theatre(FIXTURE)
    target = theatre.resolve() / ".troupe" / "extra.yaml"
    with _watch(theatre) as w:
        w.wait_ready()
        _write(theatre, "troupe.yml", ROOT + "extra: file:extra.yaml\n")
        reported = w.wait_stderr(1)
        created_at = _write(theatre, "extra.yaml", "k: v\nn: 2\n")

        events = recorded_within(theatre, created_at)

    assert len(reported) == 1 and f"include target not found: {target}" in reported[0]
    assert core(events[IMPORTED:]) == [_set(6, "extra.k", None, "v"), _set(7, "extra.n", None, 2)]


def test_rapid_successive_saves_settle_without_duplicates(make_theatre: MakeTheatre) -> None:  # 9
    theatre = make_theatre(FIXTURE)
    with _watch(theatre) as w:
        w.wait_ready()
        for value in (9, 8, 7, 6, 5):
            last_save = _write(theatre, "troupe.yml", ROOT.replace("a: 1", f"a: {value}"))
            time.sleep(0.05)

        events = recorded_within(theatre, last_save)

    assert _recorded(events) == {  # also checks every event's old value: nothing recorded twice
        "a": 5,
        "model.name": "gpt",
        "agents.coder.name": "Ada",
        "agents.coder.level": 3,
        "prompt": "Be kind.\n",
    }
    changes = [(e["path"], e["old"], e["new"]) for e in events[IMPORTED:]]
    assert all(earlier != later for earlier, later in pairwise(changes))


def test_atomic_rename_save_is_detected(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)
    state = theatre / ".troupe"
    with _watch(theatre) as w:
        w.wait_ready()
        (state / "troupe.yml.tmp").write_text(ROOT.replace("a: 1", "a: 3"), encoding="utf-8")
        os.replace(state / "troupe.yml.tmp", state / "troupe.yml")
        saved_at = time.monotonic()

        events = recorded_within(theatre, saved_at)

    assert core(events[IMPORTED:]) == [_set(6, "a", 1, 3)]


def test_root_file_renamed_to_other_candidate_is_followed(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)
    state = theatre / ".troupe"
    with _watch(theatre) as w:
        w.wait_ready()
        os.rename(state / "troupe.yml", state / "troupe.yaml")
        renamed_at = time.monotonic()
        unchanged = recorded_within(theatre, renamed_at)
        edited_at = _write(theatre, "troupe.yaml", ROOT.replace("a: 1", "a: 4"))

        events = recorded_within(theatre, edited_at)
        code, _, err = w.stop()

    assert len(unchanged) == IMPORTED
    assert core(events[IMPORTED:]) == [_set(6, "a", 1, 4)]
    assert (code, err) == (0, "")


def test_watch_with_extra_argument_exits_2(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    result = run_cli("config", "watch", "x", "--theatre", str(theatre))

    assert (result.code, result.out) == (2, "")
    assert result.err.startswith("troupe: ")


def test_watch_never_changes_configuration_files(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)
    with _watch(theatre) as w:
        w.wait_ready()
        _write(theatre, "troupe.yml", ROOT.replace("a: 1", "a:   2   # by hand"))
        edited_at = _write(theatre, "agents/coder.yaml", "name: Ada\r\nlevel: 4\r\n")
        edited = snapshot(theatre)
        events = recorded_within(theatre, edited_at)
        assert w.stop()[0] == 0

    assert len(events) == IMPORTED + 2
    assert snapshot(theatre) == edited
