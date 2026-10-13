"""import_source's stage-then-commit shape (#231).

Every book of a collection is written under the staging directory and the
set is moved into the destination only after the last one is complete. A
cancel at any checkpoint, or a rename that fails part-way through the
commit, leaves the destination root exactly as it was.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

import tc_ai_bridge.project_import as project_import
from tc_ai_bridge.project_import import ImportCancelled, import_source

TITUS = "\\id TIT\n\\h Titus\n\\c 1\n\\p\n\\v 1 Paul, a servant of God.\n\\c 2\n\\v 1 But speak.\n"
PHILEMON = "\\id PHM\n\\h Philemon\n\\c 1\n\\v 1 Paul, a prisoner of Christ Jesus.\n"
METADATA = {
    "languageId": "eng", "languageName": "English", "languageDirection": "ltr",
    "projectName": "NT review", "bibleName": "Test Bible",
}


def _collection(tmp_path: Path) -> Path:
    source = tmp_path / "ParatextProject"
    source.mkdir()
    (source / "57TIT.SFM").write_text(TITUS, encoding="utf-8")
    (source / "58PHM.SFM").write_text(PHILEMON, encoding="utf-8")
    return source


def _entries(root: Path) -> list[str]:
    return sorted(child.name for child in root.iterdir()) if root.is_dir() else []


def test_progress_checkpoints_name_each_phase_book_and_chapter(tmp_path):
    source = _collection(tmp_path)
    events: list[dict] = []

    result = import_source(source, tmp_path / "projects", METADATA, progress=events.append)

    phases = [event["phase"] for event in events]
    assert phases[0] == "normalize" and phases[-1] == "commit"
    assert "stage" in phases
    chapters = [(e["chapter"], e["chapterCount"]) for e in events if e.get("chapter")]
    assert chapters == [(1, 2), (2, 2)]
    assert {e["bookId"] for e in events if e.get("bookId")} == {"tit", "phm"}
    assert all(e["bookCount"] == 2 for e in events if "bookCount" in e)
    assert len(result["projects"]) == 2


def test_cancel_at_any_checkpoint_leaves_the_destination_untouched(tmp_path):
    source = _collection(tmp_path)
    destination = tmp_path / "projects"
    seen: list[str] = []

    def cancel_after_first_book() -> bool:
        # True once the second book is reached: the first was fully written
        # to staging by then, and must still not reach the destination.
        return "stage" in seen

    def progress(event: dict) -> None:
        seen.append(event["phase"])

    with pytest.raises(ImportCancelled):
        import_source(source, destination, METADATA, progress=progress, cancel=cancel_after_first_book)

    assert "normalize" in seen and "commit" not in seen
    assert _entries(destination) == []


def test_a_rename_that_fails_part_way_takes_the_moved_books_back_out(tmp_path, monkeypatch):
    source = _collection(tmp_path)
    destination = tmp_path / "projects"
    real_replace = os.replace
    calls: list[str] = []

    def failing_second_replace(src, dst, *args, **kwargs):
        if Path(dst).parent == destination.resolve():
            calls.append(Path(dst).name)
            if len(calls) == 2:
                raise OSError("disk full")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(project_import.os, "replace", failing_second_replace)

    with pytest.raises(OSError, match="disk full"):
        import_source(source, destination, METADATA)

    assert len(calls) == 2
    assert _entries(destination) == []
