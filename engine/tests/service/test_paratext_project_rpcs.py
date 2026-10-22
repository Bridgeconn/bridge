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
