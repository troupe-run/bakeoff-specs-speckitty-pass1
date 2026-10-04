"""Regenerate the pre-lineage fixture from the step-3 code (commit ``a589041``).

Run by a developer, never by pytest::

    uv run python tests/fixtures/pre_lineage/make_fixture.py

The old code is checked out in a temporary detached git worktree (always removed) and run with
the current interpreter and ``PYTHONPATH=<old>/src``. It records an import, a CLI ``set`` and a
hand edit reconciled by ``get``. The resulting ``history.sqlite`` and ``troupe.yml`` are copied
here, and ``expected_history.jsonl`` is computed from the raw ``stored_events`` rows with
``sqlite3`` and ``json`` only, independently of troupe (research D-9).
"""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

OLD_COMMIT: Final = "a589041"
FIXTURE_DIR: Final = Path(__file__).resolve().parent
TOPIC_PREFIX: Final = "troupe.history:ConfigHistory."
OPS: Final = {"LeafImported": "import", "LeafSet": "set", "LeafRemoved": "remove"}
STEP_PAUSE: Final = 0.01  # seconds; keeps the stored timestamps of the steps apart

INITIAL_YAML: Final = """\
model:
  name: gpt
  temperature: 0.2
tools:
  - search
  - fetch
retries: 3
"""


def _git(*args: str, cwd: Path) -> str:
    completed = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return completed.stdout.strip()


def _old_env(old_src: Path) -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"TROUPE_THEATRE", "TROUPE_ACTOR", "PYTHONPATH"}
    }
    env["PYTHONPATH"] = str(old_src)
    return env


def _run_old(env: dict[str, str], theatre: Path, *args: str) -> str:
    """Run ``python -m troupe config *args`` from the old checkout; return stdout."""
    completed = subprocess.run(
        [sys.executable, "-m", "troupe", "config", *args, "--theatre", str(theatre)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"old CLI {args!r} exited {completed.returncode}: {completed.stderr.strip()}"
        )
    return completed.stdout


def _assert_old_code_runs(env: dict[str, str], old_src: Path) -> None:
    """Fail unless ``import troupe`` in the child resolves into the temporary old checkout."""
    completed = subprocess.run(
        [sys.executable, "-c", "import troupe; print(troupe.__file__)"],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    imported = Path(completed.stdout.strip()).resolve()
    if not imported.is_relative_to(old_src.resolve()):
        raise RuntimeError(f"troupe imported from {imported}, not from {old_src}")


def _record_history(env: dict[str, str], theatre: Path) -> None:
    config = theatre / ".troupe" / "troupe.yml"
    config.parent.mkdir(parents=True)
    config.write_text(INITIAL_YAML, encoding="utf-8")

    listed = _run_old(env, theatre, "history")  # imports six leaves: seq 1-6
    for line in listed.splitlines():
        keys = set(json.loads(line))
        if keys != {"seq", "op", "path", "old", "new"}:
            raise RuntimeError(f"history printed {sorted(keys)}: not the step-3 code")
    time.sleep(STEP_PAUSE)

    _run_old(env, theatre, "set", "model.temperature", "0.5")  # seq 7
    time.sleep(STEP_PAUSE)

    text = config.read_text(encoding="utf-8")
    edited = text.replace("retries: 3\n", "").replace("name: gpt", "name: claude")
    if edited == text or "retries" in edited or "name: claude" not in edited:
        raise RuntimeError(f"hand edit did not apply to:\n{text}")
    config.write_text(edited, encoding="utf-8")
    time.sleep(STEP_PAUSE)

    if _run_old(env, theatre, "get", "model.name") != "claude\n":  # reconcile: seq 8-9
        raise RuntimeError("get model.name did not print claude")


def _checkpoint(db: Path) -> None:
    connection = sqlite3.connect(db)
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()
    wal = db.with_name(db.name + "-wal")
    if wal.exists() and wal.stat().st_size != 0:
        raise RuntimeError(f"{wal} still holds {wal.stat().st_size} bytes after checkpoint")


def _decode_timestamp(value: object) -> datetime:
    """Decode the ``JSONTranscoder`` datetime encoding found in the stored state."""
    if not (isinstance(value, dict) and value.get("_type_") == "datetime_iso"):
        raise ValueError(f"unexpected timestamp encoding: {value!r}")
    data = value["_data_"]
    if not isinstance(data, str):
        raise ValueError(f"unexpected timestamp data: {data!r}")
    return datetime.fromisoformat(data)


def expected_history(db: Path) -> list[dict[str, object]]:
    """Compute what ``troupe config history`` must print for ``db`` (contracts/cli.md)."""
    # ``immutable=1``: read without locks, so no ``-wal``/``-shm`` appears beside the fixture.
    connection = sqlite3.connect(f"{db.as_uri()}?immutable=1", uri=True)
    try:
        rows: list[tuple[int, str, bytes]] = connection.execute(
            "SELECT originator_version, topic, state FROM stored_events"
            " WHERE originator_version > 1 ORDER BY originator_version"
        ).fetchall()
    finally:
        connection.close()
    lines: list[dict[str, object]] = []
    for version, topic, state_bytes in rows:
        if not topic.startswith(TOPIC_PREFIX):
            raise ValueError(f"unexpected topic {topic!r}")
        op = OPS[topic.removeprefix(TOPIC_PREFIX)]
        state = json.loads(state_bytes)
        seq = version - 1
        at = _decode_timestamp(state["timestamp"]).astimezone(UTC)
        lines.append(
            {
                "seq": seq,
                "op": op,
                "path": state["path"],
                "old": None if op == "import" else state["old"],
                "new": None if op == "remove" else state["new"],
                "actor": {"kind": "unknown", "id": None},
                "via": "import" if op == "import" else None,
                "at": at.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                "reason": None,
                "change": f"pre-lineage-{seq}",
            }
        )
    return lines


def main() -> None:
    repo = Path(_git("rev-parse", "--show-toplevel", cwd=FIXTURE_DIR))
    with tempfile.TemporaryDirectory(prefix="pre-lineage-") as tmp_name:
        tmp = Path(tmp_name)
        old = tmp / "old"
        _git("worktree", "add", "--detach", str(old), OLD_COMMIT, cwd=repo)
        try:
            env = _old_env(old / "src")
            _assert_old_code_runs(env, old / "src")
            theatre = tmp / "theatre"
            _record_history(env, theatre)
            state_dir = theatre / ".troupe"
            db = state_dir / "history.sqlite"
            _checkpoint(db)
            shutil.copyfile(db, FIXTURE_DIR / "history.sqlite")
            shutil.copyfile(state_dir / "troupe.yml", FIXTURE_DIR / "troupe.yml")
        finally:
            _git("worktree", "remove", "--force", str(old), cwd=repo)

    lines = expected_history(FIXTURE_DIR / "history.sqlite")
    for leftover in ("history.sqlite-wal", "history.sqlite-shm"):
        if (FIXTURE_DIR / leftover).exists():
            raise RuntimeError(f"{leftover} appeared in {FIXTURE_DIR}")
    with (FIXTURE_DIR / "expected_history.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for line in lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    print(f"recorded {len(lines)} events with {OLD_COMMIT} into {FIXTURE_DIR}")
    for line in lines:
        print(f"  {line['seq']}: {line['op']} {line['path']} {line['old']!r} -> {line['new']!r}")


if __name__ == "__main__":
    main()
