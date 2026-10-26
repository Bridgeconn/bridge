"""paratext.linkStatus / relink / refresh / bookNames (#356), over the protocol.

A synthetic Paratext folder is imported, then moved, renamed or replaced
under the open project; the project always opens and the link state says
what happened.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import paratext_session
from bridge_service import BridgeEngine
from tc_ai_bridge import paratext_link
from tc_ai_bridge.project_import import import_source
from tc_ai_bridge.secret_store import AppSettings
from tests.support.paratext_fixture import DEFAULT_GUID, build_paratext_project, write_notes_file
from tests.support.projects import call

OTHER_GUID = "0000000000000000000000000000000000000abc"


@pytest.fixture
def no_paratext_install(monkeypatch, tmp_path):
    """No real Paratext projects folder is ever searched by these tests."""
    projects = tmp_path / "pt-projects"
    projects.mkdir()
    monkeypatch.setattr(paratext_link, "paratext_projects_dir", lambda *a, **k: projects)
    return projects


def _import(tmp_path: Path, projects: Path) -> tuple[Path, dict]:
    source = build_paratext_project(
        projects, notes={"User A": [{"thread": "t1", "verse_ref": "TIT 1:1", "date": "2026-01-01T00:00:00Z",
                                     "status": "todo", "contents": "x"}]},
        book_names={"TIT": ("Ti", "Titus", "The Letter to Titus")},
    )
    (source / "Notes_AI_Suggestion.xml").write_text('<notes version="1.1"/>', encoding="utf-8")
    result = import_source(source, tmp_path / "projects", {"languageName": "Tamil"})
    return source, result


def _engine(tmp_path: Path) -> BridgeEngine:
    return BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json"))


def _open(engine: BridgeEngine, path: str) -> dict:
    response = call(engine, "project.open", {"path": path})
    assert response["success"] is True, response
    return response["result"]


def _status(engine: BridgeEngine) -> dict:
    response = call(engine, "paratext.linkStatus")
    assert response["success"] is True, response
    return response["result"]


def _links(result: dict) -> list[dict]:
    return [json.loads((Path(p["path"]) / ".bridge" / "collection.json").read_text(encoding="utf-8"))["paratext"]
            for p in result["projects"]]


def test_link_status_after_import(tmp_path, no_paratext_install):
    source, result = _import(tmp_path, no_paratext_install)
    engine = _engine(tmp_path)
    _open(engine, result["primaryProjectPath"])

    status = _status(engine)

    assert status["state"] == "linked"
    assert status["guid"] == DEFAULT_GUID
    assert status["folder"] == str(source.resolve())
    assert status["name"] == "TSTP"
    assert status["versification"] == "eng"
    assert status["encoding"] == "65001"
    assert status["booksPresent"] == ["TIT", "PHM"]
    assert status["files"]["notes"] == {"count": 1, "users": ["User A"]}
    assert status["files"]["bookNames"] is True
    assert status["files"]["termRenderings"] is False
    assert "candidate" not in status

    names = call(engine, "paratext.bookNames")
    assert names["success"] is True
    assert names["result"]["bookNames"]["TIT"]["short"] == "Titus"


def test_a_missing_folder_still_opens_and_relink_restores_every_sibling(tmp_path, no_paratext_install):
    source, result = _import(tmp_path, no_paratext_install)
    moved = tmp_path / "elsewhere" / "TSTP-moved"
    moved.parent.mkdir()
    shutil.move(str(source), str(moved))
    engine = _engine(tmp_path)

    _open(engine, result["primaryProjectPath"])                # the project still opens
    status = _status(engine)
    assert status["state"] == "folderMissing"
    assert call(engine, "paratext.bookNames")["result"] == {"bookNames": {}, "state": "folderMissing"}

    relinked = call(engine, "paratext.relink", {"folder": str(moved)})
    assert relinked["success"] is True, relinked
    assert relinked["result"]["state"] == "linked"
    assert relinked["result"]["folder"] == str(moved.resolve())
    assert [link["folder"] for link in _links(result)] == [str(moved.resolve())] * 2
    assert all(link["guid"] == DEFAULT_GUID and link["relinkedAt"] for link in _links(result))

    # The sibling opens linked too, without a relink of its own.
    _open(engine, result["projects"][1]["path"])
    assert _status(engine)["state"] == "linked"


def test_a_folder_moved_inside_the_paratext_projects_folder_is_offered(tmp_path, no_paratext_install):
    source, result = _import(tmp_path, no_paratext_install)
    renamed = no_paratext_install / "TSTP-renamed"
    source.rename(renamed)
    engine = _engine(tmp_path)
    _open(engine, result["primaryProjectPath"])

    status = _status(engine)

    assert status["state"] == "folderMoved"
    assert status["candidate"] == str(renamed)


def test_another_project_at_the_linked_path_is_a_guid_mismatch(tmp_path, no_paratext_install):
    source, result = _import(tmp_path, no_paratext_install)
    shutil.rmtree(source)
    build_paratext_project(no_paratext_install, "TSTP", guid=OTHER_GUID)
    engine = _engine(tmp_path)
    _open(engine, result["primaryProjectPath"])

    assert _status(engine)["state"] == "guidMismatch"

    refused = call(engine, "paratext.relink", {"folder": str(source)})
    assert refused["success"] is False
    assert OTHER_GUID in refused["error"]["message"]
    assert [link["folder"] for link in _links(result)] == [str(source.resolve())] * 2


def test_a_plain_usfm_project_is_not_paratext(tmp_path, no_paratext_install):
    source = tmp_path / "TIT.usfm"
    source.write_text("\\id TIT\n\\c 1\n\\v 1 Text.\n", encoding="utf-8")
    result = import_source(source, tmp_path / "projects", {
        "languageId": "tam", "languageName": "Tamil", "projectName": "P", "bibleName": "B"})
    engine = _engine(tmp_path)
    _open(engine, result["primaryProjectPath"])

    assert _status(engine)["state"] == "notParatext"
    refused = call(engine, "paratext.relink", {"folder": str(tmp_path)})
    assert refused["success"] is False


def test_without_an_open_project_link_status_is_not_paratext(tmp_path):
    assert _status(_engine(tmp_path))["state"] == "notParatext"


def test_the_session_is_kept_across_books_of_one_project_and_refresh_rereads(tmp_path, no_paratext_install):
    source, result = _import(tmp_path, no_paratext_install)
    engine = _engine(tmp_path)
    _open(engine, result["primaryProjectPath"])
    session = engine._paratext
    assert isinstance(session, paratext_session.ParatextSession)
    reader = session.reader

    _open(engine, result["projects"][1]["path"])
    assert engine._paratext is session and session.reader is reader

    write_notes_file(source, "User B", [{"thread": "t2", "verse_ref": "TIT 1:2", "date": "2026-01-02T00:00:00Z",
                                         "status": "todo", "contents": "y"}])
    refreshed = call(engine, "paratext.refresh")
    assert refreshed["success"] is True
    assert refreshed["result"]["files"]["notes"]["users"] == ["User A", "User B"]
    assert engine._paratext is session and session.reader is not reader


def test_link_rpcs_never_write_into_the_paratext_folder(tmp_path, no_paratext_install):
    import hashlib

    source, result = _import(tmp_path, no_paratext_install)

    def digest() -> dict[str, str]:
        return {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(source.rglob("*")) if p.is_file()}

    before = digest()
    engine = _engine(tmp_path)
    _open(engine, result["primaryProjectPath"])
    for method, params in [("paratext.linkStatus", {}), ("paratext.bookNames", {}), ("paratext.refresh", {}),
                           ("paratext.relink", {"folder": str(source)})]:
        assert call(engine, method, params)["success"] is True
    assert digest() == before


# --------------------------------------------------------------------------- #357 notes


NOTES = {
    "User A": [
        {"thread": "n1", "verse_ref": "TIT 1:2", "date": "2026-01-01T10:00:00+05:30", "selected_text": "word",
         "status": "todo", "contents": ["First **para**", "Second"], "tags_added": ["1"]},
        {"thread": "n2", "verse_ref": "TIT 1:3", "date": "2026-01-02T10:00:00+05:30", "status": "deleted",
         "contents": "resolved in Paratext (9.5 writes a resolve as deleted)"},
        {"thread": "n3", "verse_ref": "TIT 1:3", "date": "2026-01-03T10:00:00+05:30", "status": "todo",
         "type": "conflict", "contents": "conflict"},
        {"thread": "BT_x", "verse_ref": "TIT 1:3", "date": "2026-01-03T11:00:00+05:30", "status": "todo",
         "contents": "term"},
        {"thread": "n9", "verse_ref": "PHM 1:1", "date": "2026-01-03T11:00:00+05:30", "status": "todo",
         "contents": "other book"},
    ],
    "User B": [
        {"thread": "n1", "verse_ref": "TIT 1:2", "date": "2026-01-01T12:00:00+05:30", "status": "",
         "contents": "a reply", "reply_to_user": "User A", "assigned_user": "User A"},
        {"thread": "n4", "verse_ref": "TIT 1:2", "date": "2026-01-04T10:00:00+05:30", "status": "done",
         "contents": "resolved one"},
    ],
}


def _import_with_notes(tmp_path: Path, projects: Path, notes=NOTES) -> tuple[Path, dict]:
    source = build_paratext_project(projects, notes=notes, comment_tags={"1": "To Do"})
    result = import_source(source, tmp_path / "projects", {"languageName": "Tamil"})
    return source, result


def _ready(engine: BridgeEngine) -> None:
    assert engine._paratext.wait_for_notes_index(20) in {"ready", "stale"}


def test_notes_for_chapter_counts_and_merges_users(tmp_path, no_paratext_install):
    _, result = _import_with_notes(tmp_path, no_paratext_install)
    engine = _engine(tmp_path)
    _open(engine, result["primaryProjectPath"])                # TIT
    _ready(engine)

    chapter = call(engine, "paratext.notesForChapter", {"chapter": "1"})["result"]

    assert chapter["state"] == "ready"
    assert chapter["counts"] == {"2": {"open": 1, "resolved": 1}, "3": {"open": 1, "resolved": 1}}
    assert [t["id"] for t in chapter["verses"]["2"]] == ["n1"]   # resolved n4 hidden by default
    n1 = chapter["verses"]["2"][0]
    assert n1["users"] == ["User A", "User B"] and n1["commentCount"] == 2
    assert n1["excerpt"] == "First para" and n1["assignedUser"] == "User A"
    assert n1["tags"] == [{"id": "1", "name": "To Do"}]
    assert [t["kind"] for t in chapter["verses"]["3"]] == ["conflict"]

    everything = call(engine, "paratext.notesForChapter", {
        "chapter": "1", "includeResolved": True, "kinds": ["note", "conflict", "biblicalTerm"]})["result"]
    assert [t["id"] for t in everything["verses"]["2"]] == ["n1", "n4"]
    assert {t["id"] for t in everything["verses"]["3"]} == {"n2", "n3", "BT_x"}


def test_notes_for_verse_and_thread(tmp_path, no_paratext_install):
    _, result = _import_with_notes(tmp_path, no_paratext_install)
    engine = _engine(tmp_path)
    _open(engine, result["primaryProjectPath"])
    _ready(engine)

    verse = call(engine, "paratext.notesForVerse", {"chapter": "1", "verse": "2"})["result"]
    assert [t["id"] for t in verse["threads"]] == ["n1", "n4"]
    n1 = verse["threads"][0]
    assert [(c["user"], c["contents"]) for c in n1["comments"]] == [
        ("User A", "First para\nSecond"), ("User B", "a reply")]
    assert n1["comments"][0]["tagsAdded"] == [{"id": "1", "name": "To Do"}]

    bridged = call(engine, "paratext.notesForVerse", {"chapter": "1", "verse": "2-3"})["result"]
    assert [t["id"] for t in bridged["threads"]] == ["n1", "n4", "n2", "n3", "BT_x"]

    thread = call(engine, "paratext.noteThread", {"threadId": "n4"})["result"]
    assert thread["thread"]["resolved"] is True
    assert call(engine, "paratext.noteThread", {"threadId": "nope"})["result"]["thread"] is None


def test_notes_are_unavailable_when_the_folder_is_missing(tmp_path, no_paratext_install):
    source, result = _import_with_notes(tmp_path, no_paratext_install)
    shutil.rmtree(source)
    engine = _engine(tmp_path)
    _open(engine, result["primaryProjectPath"])

    chapter = call(engine, "paratext.notesForChapter", {"chapter": "1"})["result"]
    assert chapter == {"state": "unavailable", "book": "TIT", "chapter": "1", "verses": {}, "counts": {}}
    assert _status(engine)["notesIndex"]["state"] == "unavailable"


def test_a_changed_notes_file_is_picked_up_and_the_cache_is_reused(tmp_path, no_paratext_install):
    source, result = _import_with_notes(tmp_path, no_paratext_install)
    engine = _engine(tmp_path)
    _open(engine, result["primaryProjectPath"])
    _ready(engine)
    assert _status(engine)["notesIndex"]["source"] == "files"
    cache_files = list((tmp_path / "paratext-cache").glob("*/notes-*.jsonl.gz"))
    assert len(cache_files) == 1

    write_notes_file(source, "User B", [{"thread": "n7", "verse_ref": "TIT 1:4", "date": "2026-02-01T00:00:00Z",
                                         "status": "todo", "contents": "new in Paratext"}])
    call(engine, "paratext.refresh")
    _ready(engine)
    chapter = call(engine, "paratext.notesForChapter", {"chapter": "1"})["result"]
    assert chapter["state"] == "ready"
    assert "4" in chapter["counts"] and "n4" not in str(chapter)
    assert [p.name for p in (tmp_path / "paratext-cache").glob("*/notes-*.jsonl.gz")] != [cache_files[0].name]

    # A new engine (an app restart) loads the index from the cache.
    second = _engine(tmp_path)
    _open(second, result["primaryProjectPath"])
    _ready(second)
    status = _status(second)["notesIndex"]
    assert status["source"] == "cache" and status["state"] == "ready"
    assert call(second, "paratext.notesForChapter", {"chapter": "1"})["result"]["counts"] == chapter["counts"]


def test_the_dispatcher_answers_while_the_index_builds(tmp_path, no_paratext_install, monkeypatch):
    import threading

    _, result = _import_with_notes(tmp_path, no_paratext_install)
    gate = threading.Event()
    real = paratext_session.build_notes_index

    def slow(folder, previous=None):
        gate.wait(10)
        return real(folder, previous=previous)

    monkeypatch.setattr(paratext_session, "build_notes_index", slow)
    engine = _engine(tmp_path)
    _open(engine, result["primaryProjectPath"])

    assert call(engine, "ping")["success"] is True
    chapter = call(engine, "paratext.notesForChapter", {"chapter": "1"})["result"]
    assert chapter["state"] == "building" and chapter["counts"] == {}
    assert _status(engine)["notesIndex"]["state"] == "building"
    gate.set()
    _ready(engine)
    assert call(engine, "paratext.notesForChapter", {"chapter": "1"})["result"]["state"] == "ready"
