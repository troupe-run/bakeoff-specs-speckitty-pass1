"""writeback.fileio and apply_edits: newlines, atomic writes, splicing (R-05, R-12, NFR-002)."""

import os
import stat
from pathlib import Path

import pytest

from troupe.errors import WriteRefused
from troupe.location import Url
from troupe.tree import SourceFile
from troupe.writeback import TextEdit, apply_edits
from troupe.writeback.fileio import atomic_write, detect_newline, to_crlf, uses_crlf, write_files


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("a: 1\r\nb: 2\r\n", "\r\n"),
        ("a: 1\nb: 2\r\n", "\n"),
        ("a: 1\r\nb: 2\n", "\r\n"),
        ("a: 1", "\n"),
        ("", "\n"),
        ("\n", "\n"),
        ("\ufeffa: 1\r\n", "\r\n"),
    ],
)
def test_detect_newline_follows_the_first_line_break(text: str, expected: str) -> None:
    assert detect_newline(text) == expected


def test_uses_crlf_is_true_when_any_line_ends_with_crlf() -> None:
    assert uses_crlf("one\ntwo\r\n")
    assert not uses_crlf("one\ntwo\n")
    assert not uses_crlf("one\rtwo")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("a\nb\n", "a\r\nb\r\n"),
        ("a\r\nb\n", "a\r\nb\r\n"),
        ("a\r\n", "a\r\n"),
        ("no break", "no break"),
        ("lone\rcr", "lone\rcr"),
        ("\n\n", "\r\n\r\n"),
    ],
)
def test_to_crlf_converts_bare_lf_and_leaves_existing_crlf_alone(value: str, expected: str) -> None:
    assert to_crlf(value) == expected


def _temp_residue(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir() if p.name.endswith(".tmp"))


def test_atomic_write_writes_bom_and_crlf_bytes_exactly(tmp_path: Path) -> None:
    target = tmp_path / "troupe.yml"
    target.write_bytes(b"old\n")
    atomic_write(target, "\ufeffa: \xe9\r\nb: 2\r\n")
    assert target.read_bytes() == b"\xef\xbb\xbfa: \xc3\xa9\r\nb: 2\r\n"


def test_atomic_write_keeps_the_original_permission_bits(tmp_path: Path) -> None:
    target = tmp_path / "troupe.yml"
    target.write_bytes(b"old\n")
    target.chmod(0o640)
    atomic_write(target, "new\n")
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


def test_atomic_write_leaves_no_temp_file_on_success(tmp_path: Path) -> None:
    target = tmp_path / "troupe.yml"
    target.write_bytes(b"old\n")
    atomic_write(target, "new\n")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["troupe.yml"]


def test_atomic_write_failing_rename_removes_temp_and_keeps_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "troupe.yml"
    target.write_bytes(b"old\r\n")

    def failing_replace(src: str, dst: Path) -> None:
        assert Path(src).exists()  # the temp file was written before the rename was attempted
        raise OSError("simulated rename failure")

    monkeypatch.setattr(os, "replace", failing_replace)
    with pytest.raises(OSError, match="simulated rename failure"):
        atomic_write(target, "new\n")
    assert target.read_bytes() == b"old\r\n"
    assert _temp_residue(tmp_path) == []


def test_atomic_write_failing_fsync_removes_temp_and_keeps_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "troupe.yml"
    target.write_bytes(b"old\n")

    def failing_fsync(fd: int) -> None:
        raise OSError("simulated fsync failure")

    monkeypatch.setattr(os, "fsync", failing_fsync)
    with pytest.raises(OSError, match="simulated fsync failure"):
        atomic_write(target, "new\n")
    assert target.read_bytes() == b"old\n"
    assert _temp_residue(tmp_path) == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_atomic_write_into_read_only_directory_raises_and_changes_nothing(tmp_path: Path) -> None:
    directory = tmp_path / "locked"
    directory.mkdir()
    target = directory / "troupe.yml"
    target.write_bytes(b"old\n")
    directory.chmod(0o555)
    try:
        with pytest.raises(PermissionError):
            atomic_write(target, "new\n")
        assert sorted(p.name for p in directory.iterdir()) == ["troupe.yml"]
        assert target.read_bytes() == b"old\n"
    finally:
        directory.chmod(0o755)


def test_write_files_writes_only_files_whose_text_changed(tmp_path: Path) -> None:
    changed_path = tmp_path / "changed.yml"
    same_path = tmp_path / "same.yml"
    changed_path.write_bytes(b"a: 1\n")
    same_path.write_bytes(b"b: 2\n")
    os.utime(same_path, ns=(1_000_000_000, 1_000_000_000))
    changed = SourceFile(path=changed_path, text="a: 1\n")
    same = SourceFile(path=same_path, text="b: 2\n")

    write_files({changed: "a: 3\n", same: "b: 2\n"})

    assert changed_path.read_bytes() == b"a: 3\n"
    assert same_path.stat().st_mtime_ns == 1_000_000_000


def test_write_files_refuses_remote_content_before_writing_any_file(tmp_path: Path) -> None:
    local_path = tmp_path / "local.yml"
    local_path.write_bytes(b"a: 1\n")
    local = SourceFile(path=local_path, text="a: 1\n")
    remote = SourceFile(path=Url("https://cfg.example.com/team.yaml"), text="b: 2\n")

    with pytest.raises(WriteRefused) as caught:
        write_files({local: "a: 3\n", remote: "b: 3\n"})  # the local file comes first

    assert caught.value.exit_code == 3
    assert caught.value.message == (
        "cannot write https://cfg.example.com/team.yaml: it is remote content, which troupe never"
        " changes; no file changed"
    )
    assert local_path.read_bytes() == b"a: 1\n"
    assert _temp_residue(tmp_path) == []


def test_write_files_refuses_unchanged_remote_content_too(tmp_path: Path) -> None:
    remote = SourceFile(path=Url("https://cfg.example.com/team.yaml"), text="b: 2\n")

    with pytest.raises(WriteRefused):
        write_files({remote: "b: 2\n"})


def test_apply_edits_splices_replacements_and_insertions_given_in_any_order() -> None:
    text = "a: 1\nb: 2\n"
    edits = [TextEdit(10, 10, "c: 3\n"), TextEdit(3, 4, "100"), TextEdit(8, 9, "x")]
    assert apply_edits(text, edits) == "a: 100\nb: x\nc: 3\n"


def test_apply_edits_with_no_edits_returns_the_text_unchanged() -> None:
    assert apply_edits("a: 1\n", []) == "a: 1\n"


def test_apply_edits_keeps_the_given_order_of_insertions_at_one_index() -> None:
    assert apply_edits("ab", [TextEdit(1, 1, "1"), TextEdit(1, 1, "2")]) == "a12b"


def test_apply_edits_allows_an_insertion_adjacent_to_a_replacement() -> None:
    assert apply_edits("abc", [TextEdit(1, 2, "B"), TextEdit(2, 2, "+"), TextEdit(1, 1, "-")]) == (
        "a-B+c"
    )


@pytest.mark.parametrize(
    "edits",
    [
        [TextEdit(0, 3, "x"), TextEdit(2, 4, "y")],
        [TextEdit(0, 3, "x"), TextEdit(1, 1, "y")],
        [TextEdit(1, 2, "x"), TextEdit(1, 3, "y")],
    ],
)
def test_apply_edits_rejects_overlapping_edits(edits: list[TextEdit]) -> None:
    with pytest.raises(ValueError, match="overlapping"):
        apply_edits("abcdef", edits)


@pytest.mark.parametrize("edit", [TextEdit(-1, 0, "x"), TextEdit(2, 1, "x"), TextEdit(0, 7, "x")])
def test_apply_edits_rejects_out_of_bounds_edits(edit: TextEdit) -> None:
    with pytest.raises(ValueError, match="out of bounds"):
        apply_edits("abcdef", [edit])
