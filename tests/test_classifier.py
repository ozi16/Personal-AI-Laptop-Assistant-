"""Extension rules. Classification does not open or change a file."""

from pathlib import Path

import pytest

from modules.file_manager.classifier import OTHERS, classify_file


@pytest.mark.parametrize(
    ("name", "category"),
    [
        ("report.pdf", "Documents"),
        ("REPORT.PDF", "Documents"),
        ("notes.txt", "Documents"),
        ("photo.JPG", "Images"),
        ("clip.mp4", "Videos"),
        ("song.mp3", "Audio"),
        ("archive.zip", "Archives"),
        ("archive.tar.gz", "Archives"),
        ("setup.exe", "Installers"),
        ("sheet.xlsx", "Spreadsheets"),
        ("data.csv", "Spreadsheets"),
        ("main.py", "Development"),
        ("README", OTHERS),
        (".gitignore", OTHERS),
        ("file.unknownext", OTHERS),
    ],
)
def test_classify_file_uses_the_extension(tmp_path: Path, name: str, category: str) -> None:
    path = tmp_path / name
    path.write_bytes(b"not inspected")
    before = path.read_bytes()

    assert classify_file(path) == category
    assert path.name == name
    assert path.read_bytes() == before


def test_missing_file_is_classified_from_its_name(tmp_path: Path) -> None:
    ghost = tmp_path / "ghost.pdf"
    assert classify_file(ghost) == "Documents"
    assert not ghost.exists()
