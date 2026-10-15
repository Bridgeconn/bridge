"""#210: opening a lazy sibling prepares it on a worker, not on the dispatcher.

On a 66-book Bible, opening a book that had never been opened materialised it
inline for about a minute while a check ran, and every checks.status poll
behind it timed out. With `prepareInBackground` (what the desktop client
sends) project.open answers `preparing` at once, the normalisation runs as an
import job, and the dispatcher keeps answering; the client opens again when
the job has succeeded. Without the flag the open still materialises inline,
so scripts and the older tests are unchanged.
"""
from __future__ import annotations

import threading
from pathlib import Path

import tc_ai_bridge.project_import as project_import
from bridge_service import BridgeEngine
from tc_ai_bridge.secret_store import AppSettings

from tests.support.projects import call
from tests.support.waits import job_timeout

TITUS = "\\id TIT\n\\h Titus\n\\c 1\n\\p\n\\v 1 Paul, a servant of God.\n\\c 2\n\\v 1 But speak.\n"
PHILEMON = "\\id PHM\n\\h Philemon\n\\c 1\n\\v 1 Paul, a prisoner of Christ Jesus.\n"
METADATA = {
    "languageId": "eng", "languageName": "English", "languageDirection": "ltr",
    "projectName": "NT review", "bibleName": "Test Bible",
}


def _import_collection(tmp_path: Path):
    source = tmp_path / "ParatextProject"
    source.mkdir()
    (source / "57TIT.SFM").write_text(TITUS, encoding="utf-8")
    (source / "58PHM.SFM").write_text(PHILEMON, encoding="utf-8")
    engine = BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json"))
    imported = call(engine, "project.import", {"path": str(source), "metadata": METADATA})
    assert imported["success"] is True, imported
    lazy = next(book for book in imported["result"]["importedProjects"] if book["lazy"])
    return engine, Path(lazy["path"])


def _wait(engine, job_id, timeout=10.0):
    import time
    deadline = time.monotonic() + job_timeout(timeout)
    while time.monotonic() < deadline:
        snapshot = call(engine, "project.import.status", {"jobId": job_id})["result"]
        if snapshot["state"] in {"succeeded", "failed", "cancelled"}:
            return snapshot
        time.sleep(0.01)
    raise AssertionError("prepare job did not finish")


def test_a_lazy_sibling_is_prepared_on_a_worker_and_the_dispatcher_keeps_answering(tmp_path, monkeypatch):
    engine, lazy_path = _import_collection(tmp_path)
    started = threading.Event()
    release = threading.Event()
    original = project_import._write_imported_book

    def gated_write(*args, **kwargs):
        started.set()
        assert release.wait(job_timeout(10.0)), "the test never released the write"
        return original(*args, **kwargs)

    monkeypatch.setattr(project_import, "_write_imported_book", gated_write)

    opened = call(engine, "project.open", {"path": str(lazy_path), "prepareInBackground": True})
    assert opened["success"] is True, opened
    result = opened["result"]
    assert result["state"] == "preparing" and result["path"] == str(lazy_path)
    assert result["job"]["jobId"] == result["jobId"]
    assert started.wait(job_timeout(5.0))

    # The request thread is free: the primary book is still open and answers.
    assert call(engine, "ping")["success"] is True
    assert call(engine, "verse.get", {"chapter": "1", "verse": "1"})["success"] is True
    status = call(engine, "project.import.status", {"jobId": result["jobId"]})["result"]
    assert status["state"] == "running" and status["phase"] == "normalize" and status["currentBook"] == "phm"
    # A second open of the same lazy book while it is being prepared is refused, not queued.
    again = call(engine, "project.open", {"path": str(lazy_path), "prepareInBackground": True})
    assert again["success"] is False and "already running" in again["error"]["message"]

    release.set()
    finished = _wait(engine, result["jobId"])
    assert finished["state"] == "succeeded", finished
    assert finished["result"] == {"path": str(lazy_path), "prepared": True}
    assert not (lazy_path / ".bridge" / "lazy-import.json").exists()

    # Now the open is the ordinary fast path and returns the project info.
    opened = call(engine, "project.open", {"path": str(lazy_path), "prepareInBackground": True})
    assert opened["success"] is True, opened
    assert opened["result"]["bookId"] == "phm" and opened["result"]["chapters"] == ["1"]


def test_cancel_leaves_the_descriptor_so_the_next_open_starts_over(tmp_path, monkeypatch):
    engine, lazy_path = _import_collection(tmp_path)
    started = threading.Event()
    release = threading.Event()
    original = project_import._write_imported_book

    def gated_write(*args, **kwargs):
        started.set()
        assert release.wait(job_timeout(10.0))
        return original(*args, **kwargs)

    monkeypatch.setattr(project_import, "_write_imported_book", gated_write)
    job_id = call(engine, "project.open", {"path": str(lazy_path), "prepareInBackground": True})["result"]["jobId"]
    assert started.wait(job_timeout(5.0))
    call(engine, "project.import.cancel", {"jobId": job_id})
    release.set()
    assert _wait(engine, job_id)["state"] == "cancelled"
    assert (lazy_path / ".bridge" / "lazy-import.json").is_file()

    monkeypatch.setattr(project_import, "_write_imported_book", original)
    second = call(engine, "project.open", {"path": str(lazy_path), "prepareInBackground": True})["result"]
    assert second["state"] == "preparing"
    assert _wait(engine, second["jobId"])["state"] == "succeeded"
    assert call(engine, "project.open", {"path": str(lazy_path)})["result"]["bookId"] == "phm"


def test_without_the_flag_the_open_materialises_inline_as_before(tmp_path):
    engine, lazy_path = _import_collection(tmp_path)
    opened = call(engine, "project.open", {"path": str(lazy_path)})
    assert opened["success"] is True, opened
    assert opened["result"]["bookId"] == "phm"
    assert not (lazy_path / ".bridge" / "lazy-import.json").exists()
    # A prepared book never goes through the job, flag or not.
    assert call(engine, "project.open", {"path": str(lazy_path), "prepareInBackground": True})["result"]["bookId"] == "phm"
