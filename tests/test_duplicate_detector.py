"""Duplicate groups come from hashed contents, not from file names."""

import hashlib
from pathlib import Path

from modules.file_manager.duplicate_detector import find_duplicate_groups, hash_file
from modules.file_manager.scanner import scan_directory


def test_hash_file_reads_in_chunks(tmp_path: Path) -> None:
    target = tmp_path / "payload.bin"
    content = b"abcdefghijklmnopqrstuvwxyz"
    target.write_bytes(content)
    expected = hashlib.sha256(content).hexdigest()

    assert hash_file(target, chunk_size=1) == expected
    assert hash_file(target, chunk_size=7) == expected
    assert target.read_bytes() == content


def test_identical_files_form_one_group_and_stay_on_disk(tmp_path: Path) -> None:
    root = tmp_path / "Downloads"
    root.mkdir()
    (root / "one.txt").write_text("hello", encoding="utf-8")
    (root / "two.txt").write_text("hello", encoding="utf-8")
    files = scan_directory(root, recursive=True, max_depth=1, max_files=10).files

    report = find_duplicate_groups(files, chunk_size=4)

    assert len(report.groups) == 1
    assert report.groups[0].sha256 == hashlib.sha256(b"hello").hexdigest()
    assert {item.file_name for item in report.groups[0].files} == {"one.txt", "two.txt"}
    assert (root / "one.txt").read_text(encoding="utf-8") == "hello"
    assert (root / "two.txt").read_text(encoding="utf-8") == "hello"


def test_same_name_and_size_with_different_contents_are_not_duplicates(tmp_path: Path) -> None:
    root = tmp_path / "Downloads"
    (root / "left").mkdir(parents=True)
    (root / "right").mkdir()
    (root / "left" / "a.txt").write_text("aaa", encoding="utf-8")
    (root / "right" / "a.txt").write_text("bbb", encoding="utf-8")
    files = scan_directory(root, recursive=True, max_depth=2, max_files=10).files

    report = find_duplicate_groups(files, chunk_size=2)

    assert report.groups == ()
    assert len(report.hashes) == 2
    assert (root / "left" / "a.txt").read_text(encoding="utf-8") == "aaa"
    assert (root / "right" / "a.txt").read_text(encoding="utf-8") == "bbb"


def test_unique_sizes_are_not_hashed(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "Downloads"
    root.mkdir()
    (root / "small.txt").write_text("a", encoding="utf-8")
    (root / "medium.txt").write_text("bb", encoding="utf-8")
    (root / "pair-a.txt").write_text("cccc", encoding="utf-8")
    (root / "pair-b.txt").write_text("dddd", encoding="utf-8")
    files = scan_directory(root, recursive=True, max_depth=1, max_files=10).files
    calls: list[str] = []
    real_hash = hash_file

    def wrapped(path, chunk_size=1024 * 1024):
        calls.append(Path(path).name)
        return real_hash(path, chunk_size)

    monkeypatch.setattr("modules.file_manager.duplicate_detector.hash_file", wrapped)
    report = find_duplicate_groups(files, chunk_size=2)

    assert sorted(calls) == ["pair-a.txt", "pair-b.txt"]
    assert report.groups == ()


def test_missing_candidate_is_reported_without_removing_the_other(tmp_path: Path) -> None:
    root = tmp_path / "Downloads"
    root.mkdir()
    keep = root / "keep.txt"
    gone = root / "gone.txt"
    keep.write_text("same", encoding="utf-8")
    gone.write_text("same", encoding="utf-8")
    files = scan_directory(root, recursive=True, max_depth=1, max_files=10).files
    gone.unlink()

    report = find_duplicate_groups(files, chunk_size=2)

    assert report.groups == ()
    assert any(error.path.endswith("gone.txt") for error in report.errors)
    assert keep.read_text(encoding="utf-8") == "same"
