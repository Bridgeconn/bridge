"""project.import.start / .status / .cancel (#231): the import as a job.

The job runs BridgeEngine's inspect / write / register sequence on a worker
thread; these tests drive it through the dispatcher the way the import screen
does. The one that matters most is the cancel: nothing may be left in the
destination root, and the sync project.import must be refused while a job
holds the import lock.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

import tc_ai_bridge.project_import as project_import
from bridge_service import BridgeEngine
from tc_ai_bridge.secret_store import AppSettings

from tests.support.projects import call
from tests.support.waits import job_timeout

TITUS = """\\id TIT
\\h Titus
\\c 1
\\p
\\v 1 Paul, a servant of God.
\\v 2 in hope of eternal life.
\\c 2
\\v 1 But speak the things that fit sound doctrine.
"""
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


def _engine(tmp_path: Path) -> BridgeEngine:
    return BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json"))


def _project_dirs(root: Path) -> list[str]:
    return sorted(child.name for child in root.iterdir()) if root.is_dir() else []


def _wait(engine, job_id, *, until=lambda s: s["state"] in {"succeeded", "failed", "cancelled"}, timeout=5.0):
    deadline = time.monotonic() + job_timeout(timeout)
    while time.monotonic() < deadline:
        snapshot = call(engine, "project.import.status", {"jobId": job_id})["result"]
        if until(snapshot):
            return snapshot
        time.sleep(0.01)
    raise AssertionError(f"import job {job_id} did not reach the expected state")


def test_import_job_reports_progress_and_registers_every_book(tmp_path):
    engine = _engine(tmp_path)
    source = _collection(tmp_path)

    started = call(engine, "project.import.start", {"path": str(source), "metadata": METADATA})
    assert started["success"] is True, started
    snapshot = started["result"]
    # The start answers with a drawable snapshot at once: the bar is on screen
    # before any work has happened.
    assert snapshot["state"] in {"queued", "running"}
    assert snapshot["percent"] == 0
    assert snapshot["phaseLabel"]

    finished = _wait(engine, snapshot["jobId"])
    assert finished["state"] == "succeeded", finished
    assert finished["percent"] == 100
    assert finished["phase"] == "register"
    assert finished["totalBooks"] == 2 and finished["completedBooks"] == 2
    result = finished["result"]
    assert {book["bookId"] for book in result["projects"]} == {"tit", "phm"}
    assert all(book["projectId"] and book["collectionId"] for book in result["projects"])
    assert Path(result["primaryProjectPath"]).is_dir()
    assert _project_dirs(tmp_path / "projects") == sorted(Path(b["path"]).name for b in result["projects"])

    # Registered from the worker thread; visible to the dispatcher's own list.
    listed = call(engine, "project.list")["result"]["projects"]
    assert [entry["bookCount"] for entry in listed] == [2]

    # The client opens the primary book itself, on the dispatcher as always.
    opened = call(engine, "project.open", {"path": result["primaryProjectPath"]})
    assert opened["success"] is True, opened
    assert opened["result"]["bookId"] == "tit"
    assert opened["result"]["chapters"] == ["1", "2"]

    # A finished job stays pollable; an unknown id is a clean error.
    assert call(engine, "project.import.status", {"jobId": snapshot["jobId"]})["result"]["state"] == "succeeded"
    missing = call(engine, "project.import.status", {"jobId": "nope"})
    assert missing["success"] is False and missing["error"]["code"] == "import_job_not_found"


def test_cancel_mid_import_leaves_nothing_on_disk_and_frees_the_lock(tmp_path, monkeypatch):
    engine = _engine(tmp_path)
    source = _collection(tmp_path)
    destination = tmp_path / "projects"
    started_writing = threading.Event()
    release = threading.Event()
    original = project_import._write_imported_book

    def blocking_write(*args, **kwargs):
        started_writing.set()
        assert release.wait(job_timeout(5.0)), "the test never released the import"
        return original(*args, **kwargs)

    monkeypatch.setattr(project_import, "_write_imported_book", blocking_write)

    started = call(engine, "project.import.start", {"path": str(source), "metadata": METADATA})
    assert started["success"] is True, started
    job_id = started["result"]["jobId"]
    assert started_writing.wait(job_timeout(5.0))

    # The dispatcher is free while the worker is inside the write: status
    # answers, and says which book it is on.
    status = call(engine, "project.import.status", {"jobId": job_id})["result"]
    assert status["state"] == "running"
    assert status["phase"] == "normalize" and status["currentBook"] == "tit"
    assert status["totalBooks"] == 2

    # The lock is shared with the sync RPC and with a second start.
    sync = call(engine, "project.import", {"path": str(source), "metadata": METADATA})
    assert sync["success"] is False and "already running" in sync["error"]["message"]
    again = call(engine, "project.import.start", {"path": str(source), "metadata": METADATA})
    assert again["success"] is False and "already running" in again["error"]["message"]

    cancelled = call(engine, "project.import.cancel", {"jobId": job_id})["result"]
    assert cancelled["state"] == "cancelling"
    release.set()
    finished = _wait(engine, job_id)
    assert finished["state"] == "cancelled", finished
    assert finished["result"] is None

    # Nothing on disk: no project folder and no staging directory.
    assert _project_dirs(destination) == []
    assert call(engine, "project.list")["result"]["projects"] == []

    # And the lock is released: the same source imports cleanly afterwards.
    release.set()
    rerun = call(engine, "project.import.start", {"path": str(source), "metadata": METADATA})
    assert rerun["success"] is True, rerun
    assert _wait(engine, rerun["result"]["jobId"])["state"] == "succeeded"
    assert len(_project_dirs(destination)) == 2


def test_a_failing_import_job_reports_the_error_and_frees_the_lock(tmp_path):
    engine = _engine(tmp_path)
    source = _collection(tmp_path)
    incomplete = {**METADATA, "projectName": ""}

    started = call(engine, "project.import.start", {"path": str(source), "metadata": incomplete})
    assert started["success"] is True, started
    finished = _wait(engine, started["result"]["jobId"])
    assert finished["state"] == "failed"
    assert "projectName" in finished["error"]
    assert _project_dirs(tmp_path / "projects") == []

    rerun = call(engine, "project.import.start", {"path": str(source), "metadata": METADATA})
    assert rerun["success"] is True, rerun
    assert _wait(engine, rerun["result"]["jobId"])["state"] == "succeeded"


@pytest.mark.parametrize("method", ["project.import.status", "project.import.cancel"])
def test_status_and_cancel_without_a_job_are_clean_errors(tmp_path, method):
    engine = _engine(tmp_path)
    response = call(engine, method, {"jobId": ""})
    assert response["success"] is False
    assert response["error"]["code"] == "import_job_not_found"


def test_selected_books_are_the_only_books_imported_registered_and_duplicate_checked(tmp_path):
    engine = _engine(tmp_path)
    source = _collection(tmp_path)
    started = call(engine, "project.import.start", {
        "path": str(source), "metadata": METADATA, "selectedBookIds": ["phm"],
    })
    assert started["success"], started
    finished = _wait(engine, started["result"]["jobId"])
    assert finished["state"] == "succeeded", finished
    assert finished["totalBooks"] == 1
    assert [book["bookId"] for book in finished["result"]["projects"]] == ["phm"]
    assert len(_project_dirs(tmp_path / "projects")) == 1
    assert (source / "57TIT.SFM").exists() and (source / "58PHM.SFM").exists()
    listed = call(engine, "project.list")["result"]["projects"]
    assert len(listed) == 1 and listed[0]["bookId"] == "phm"

    inspected = call(engine, "project.inspectImport", {
        "path": str(source), "metadata": METADATA, "selectedBookIds": ["phm"],
    })
    assert inspected["success"], inspected
    assert [book["bookId"] for book in inspected["result"]["books"]] == ["phm"]
    assert inspected["result"]["duplicates"]["classification"] == "exactDuplicate"
    assert inspected["result"]["duplicates"]["inputBookCount"] == 1
    duplicate = call(engine, "project.import.start", {
        "path": str(source), "metadata": METADATA, "selectedBookIds": ["phm"],
    })
    assert _wait(engine, duplicate["result"]["jobId"])["state"] == "failed"
    assert len(_project_dirs(tmp_path / "projects")) == 1

    other = call(engine, "project.import.start", {
        "path": str(source), "metadata": METADATA, "selectedBookIds": ["tit"],
    })
    other_finished = _wait(engine, other["result"]["jobId"])
    assert other_finished["state"] == "succeeded", other_finished
    assert [book["bookId"] for book in other_finished["result"]["projects"]] == ["tit"]


@pytest.mark.parametrize("selection", [[], ["unknown"], "tit", [3]])
def test_invalid_book_selection_cannot_write_projects(tmp_path, selection):
    engine = _engine(tmp_path)
    source = _collection(tmp_path)
    inspected = call(engine, "project.inspectImport", {
        "path": str(source), "metadata": METADATA, "selectedBookIds": selection,
    })
    assert not inspected["success"]
    started = call(engine, "project.import.start", {
        "path": str(source), "metadata": METADATA, "selectedBookIds": selection,
    })
    finished = _wait(engine, started["result"]["jobId"])
    assert finished["state"] == "failed", finished
    assert not _project_dirs(tmp_path / "projects")
