"""CLI invocation discipline: usage errors, root-file discovery and output channels."""

import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import MakeTheatre, all_files, run_cli

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_no_subcommand_is_usage_error_with_empty_stdout() -> None:
    result = run_cli()

    assert (result.code, result.out) == (2, "")
    assert result.err.startswith("troupe: ")


def test_config_without_subcommand_is_usage_error_with_empty_stdout() -> None:
    result = run_cli("config")

    assert (result.code, result.out) == (2, "")
    assert result.err.startswith("troupe: ")


def test_unknown_subcommand_is_usage_error() -> None:
    result = run_cli("config", "frobnicate", "a.b")

    assert (result.code, result.out) == (2, "")
    assert "frobnicate" in result.err


def test_set_without_value_is_usage_error() -> None:
    result = run_cli("config", "set", "a.b")

    assert (result.code, result.out) == (2, "")
    assert "VALUE" in result.err


def test_usage_error_is_a_single_troupe_prefixed_stderr_line() -> None:
    result = run_cli("config", "show")

    assert result.code == 2
    assert result.err.startswith("troupe: ")
    assert result.err.endswith("\n")
    assert result.err.count("\n") == 1


def test_config_help_exits_0_and_lists_subcommands() -> None:
    result = run_cli("config", "--help")

    assert result.code == 0
    assert all(name in result.out for name in ("show", "set", "history"))


def test_missing_config_file_exits_4_and_names_file(tmp_path: Path) -> None:
    result = run_cli("config", "show", "a.b", "--theatre", str(tmp_path))

    assert (result.code, result.out) == (4, "")
    assert str(tmp_path.resolve() / ".troupe" / "troupe.yml") in result.err


def test_missing_root_file_with_existing_state_dir_exits_4(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"other.yml": "a: 1\n"})

    result = run_cli("config", "show", "a", "--theatre", str(theatre))

    assert (result.code, result.out) == (4, "")
    assert str(theatre.resolve() / ".troupe" / "troupe.yml") in result.err


def test_both_yml_and_yaml_exit_4_and_name_both_files(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "a: 1\n", "troupe.yaml": "a: 2\n"})

    result = run_cli("config", "show", "a", "--theatre", str(theatre))

    assert (result.code, result.out) == (4, "")
    state_dir = theatre.resolve() / ".troupe"
    assert str(state_dir / "troupe.yml") in result.err
    assert str(state_dir / "troupe.yaml") in result.err


def test_nonexistent_theatre_directory_exits_4_and_names_it(tmp_path: Path) -> None:
    missing = tmp_path / "no-such-theatre"

    result = run_cli("config", "history", "--theatre", str(missing))

    assert (result.code, result.out) == (4, "")
    assert str(missing.resolve()) in result.err


def test_theatre_defaults_to_current_directory(tmp_path: Path) -> None:
    result = run_cli("config", "show", "a.b", cwd=tmp_path)

    assert (result.code, result.out) == (4, "")
    assert str(tmp_path.resolve() / ".troupe" / "troupe.yml") in result.err


def test_theatre_env_var_is_default_and_option_wins(tmp_path: Path) -> None:
    from_env = tmp_path / "from-env"
    from_option = tmp_path / "from-option"
    from_env.mkdir()
    from_option.mkdir()
    env = {"TROUPE_THEATRE": str(from_env)}

    by_env = run_cli("config", "show", "a.b", cwd=tmp_path, env=env)
    by_option = run_cli(
        "config", "show", "a.b", "--theatre", str(from_option), cwd=tmp_path, env=env
    )
    by_empty = run_cli("config", "show", "a.b", cwd=tmp_path, env={"TROUPE_THEATRE": ""})

    assert str(from_env.resolve() / ".troupe" / "troupe.yml") in by_env.err
    assert str(from_option.resolve() / ".troupe" / "troupe.yml") in by_option.err
    assert str(tmp_path.resolve() / ".troupe" / "troupe.yml") in by_empty.err


@pytest.mark.parametrize(
    "argv_before_theatre, argv_after_theatre",
    [
        (["config", "--theatre"], ["show", "a.b"]),
        (["config", "show", "--theatre"], ["a.b"]),
        (["config", "set", "a.b", "1", "--theatre"], []),
    ],
    ids=["on-config", "before-positional", "after-positionals"],
)
def test_theatre_option_is_honoured_in_any_position(
    tmp_path: Path, argv_before_theatre: list[str], argv_after_theatre: list[str]
) -> None:
    theatre = tmp_path / "elsewhere"
    theatre.mkdir()

    result = run_cli(*argv_before_theatre, str(theatre), *argv_after_theatre, cwd=tmp_path)

    assert result.code == 4
    assert str(theatre.resolve() / ".troupe" / "troupe.yml") in result.err


@pytest.mark.parametrize("value", ["-5", "-0.5"])
def test_negative_number_value_is_accepted_as_positional(tmp_path: Path, value: str) -> None:
    # Exit 4 (no root file) rather than 2 proves argparse accepted VALUE as a positional.
    result = run_cli("config", "set", "a.b", value, "--theatre", str(tmp_path))

    assert result.code == 4


def test_missing_root_creates_no_files(tmp_path: Path) -> None:
    (tmp_path / "keep.txt").write_bytes(b"x")
    before = all_files(tmp_path)
    assert before == {"keep.txt"}

    result = run_cli("config", "set", "a.b", "1", "--theatre", str(tmp_path))

    assert result.code == 4
    assert all_files(tmp_path) == before
    assert not (tmp_path / ".troupe").exists()


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not on PATH")
def test_uv_run_troupe_from_repo_root(tmp_path: Path) -> None:
    completed = subprocess.run(
        ["uv", "run", "troupe", "config", "show", "x", "--theatre", str(tmp_path)],
        capture_output=True,
        cwd=REPO_ROOT,
        check=False,
    )

    assert completed.returncode == 4
    assert completed.stdout == b""
    assert str(tmp_path.resolve() / ".troupe" / "troupe.yml").encode() in completed.stderr
