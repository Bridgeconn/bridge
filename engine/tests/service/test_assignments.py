"""#240: assign a book or chapter to a user; "My work" reads the cache.

assignments.set and .clear are a project_admin's (authorize(),
manage_projects); assignments.list is anyone's. The record is one
team_assignments row per scope in the book's workbench (chapter "" is the
whole book), riding the change_log; the workspace cache the dashboard reads
is refreshed from each write's seq and repaired on open.
"""
from __future__ import annotations

import json
from pathlib import Path

from bridge_service import BridgeEngine
from tc_ai_bridge.secret_store import AppSettings

from tests.support.projects import call

TITUS = "\\id TIT\n\\h Titus\n\\c 1\n\\p\n\\v 1 Paul, a servant of God.\n\\c 2\n\\v 1 But speak.\n"
PHILEMON = "\\id PHM\n\\h Philemon\n\\c 1\n\\v 1 Paul, a prisoner of Christ Jesus.\n"
METADATA = {
    "languageId": "eng", "languageName": "English", "languageDirection": "ltr",
    "projectName": "NT review", "bibleName": "Test Bible",
}


def _collection(tmp_path: Path):
    source = tmp_path / "ParatextProject"
    source.mkdir()
    (source / "57TIT.SFM").write_text(TITUS, encoding="utf-8")
    (source / "58PHM.SFM").write_text(PHILEMON, encoding="utf-8")
    engine = BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json"))
    imported = call(engine, "project.import", {"path": str(source), "metadata": METADATA})
    assert imported["success"] is True, imported
    return engine, imported["result"]


def _dashboard(engine) -> dict[str, dict]:
    return {b["bookId"]: b for b in call(engine, "project.listBookProgress")["result"]["books"]}


def test_an_admin_assigns_a_book_and_a_chapter_and_the_dashboard_sees_both(tmp_path):
    engine, opened = _collection(tmp_path)
    me = engine.local_user()
    rina = call(engine, "users.create", {"displayName": "Rina", "role": "editor"})["result"]

    assert call(engine, "assignments.list")["result"]["assignments"] == []
    book = call(engine, "assignments.set", {"chapter": "", "userId": rina["userId"]})
    assert book["success"] is True, book
    chapter = call(engine, "assignments.set", {"chapter": "2", "userId": me["userId"]})
    assert chapter["success"] is True, chapter
    listed = chapter["result"]["assignments"]
    assert [(a["chapter"], a["assigneeName"], a["assignedBy"]) for a in listed] == [
        ("", "Rina", me["userId"]), ("2", me["displayName"], me["userId"]),
    ]
    assert all(a["assignedAt"] for a in listed)

    # The record: one row per scope with lifted columns, on the change log.
    project = engine.project
    rows = project.workbench.rows("team_assignments", project_id=project.workbench_identity.project_id)
    assert sorted(r["chapter"] for r in rows) == ["", "2"]
    assert {r["assignee_id"] for r in rows} == {rina["userId"], me["userId"]}
    assert all(r["assigned_by"] == me["userId"] and r["assigned_at"] for r in rows)
    assert project.workbench.max_seq(project_id=project.workbench_identity.project_id, table="team_assignments") >= 2

    # The dashboard reads the cache, for every book, in one call.
    books = _dashboard(engine)
    assert [a["chapter"] for a in books["tit"]["assignments"]] == ["", "2"]
    assert books["phm"]["assignments"] == []

    # Refused: a missing chapter, an inactive or unknown user.
    assert call(engine, "assignments.set", {"chapter": "9", "userId": rina["userId"]})["success"] is False
    assert call(engine, "assignments.set", {"chapter": "1", "userId": "nope"})["success"] is False
    call(engine, "users.deactivate", {"userId": rina["userId"]})
    assert call(engine, "assignments.set", {"chapter": "1", "userId": rina["userId"]})["success"] is False

    # Clear the chapter; the book assignment stays; clearing again is a no-op.
    cleared = call(engine, "assignments.clear", {"chapter": "2"})["result"]["assignments"]
    assert [a["chapter"] for a in cleared] == [""]
    assert call(engine, "assignments.clear", {"chapter": "2"})["success"] is True
    assert [a["chapter"] for a in _dashboard(engine)["tit"]["assignments"]] == [""]


def test_the_cache_is_repaired_on_open_and_forgotten_with_the_project(tmp_path):
    engine, opened = _collection(tmp_path)
    rina = call(engine, "users.create", {"displayName": "Rina", "role": "editor"})["result"]
    assert call(engine, "assignments.set", {"chapter": "1", "userId": rina["userId"]})["success"] is True
    project = engine.project
    assert project.sync_assignments_cache() == "fresh"

    # A cache that lags (or vanished) is rebuilt from the workbench on open.
    engine.workspace.forget_assignments_cache([project.path])
    assert engine.workspace.assignments_cache_entry(project.path) is None
    assert project.sync_assignments_cache() == "repaired"
    assert [a["chapter"] for a in engine.workspace.assignments_cache_entry(project.path)["assignments"]] == ["1"]
    engine.workspace.forget_assignments_cache([project.path])
    assert call(engine, "project.open", {"path": str(project.path), "awaitSemantic": True})["success"] is True
    assert engine.workspace.assignments_cache_entry(project.path) is not None

    # Forgetting the project drops its cache entries with it.
    listed = call(engine, "project.list")["result"]["projects"][0]
    assert call(engine, "project.forget", {"projectId": listed["projectId"]})["success"] is True
    assert engine.workspace.assignments_cache_entry(project.path) is None


def test_only_a_project_admin_assigns_but_everyone_may_read(tmp_path):
    engine, opened = _collection(tmp_path)
    rina = call(engine, "users.create", {"displayName": "Rina", "role": "editor"})["result"]
    assert call(engine, "assignments.set", {"chapter": "", "userId": rina["userId"]})["success"] is True
    assert call(engine, "users.setCurrent", {"userId": rina["userId"]})["success"] is True
    refused = call(engine, "assignments.set", {"chapter": "1", "userId": rina["userId"]})
    assert refused["success"] is False and refused["error"]["code"] == "forbidden"
    assert call(engine, "assignments.clear", {"chapter": ""})["error"]["code"] == "forbidden"
    assert [a["assigneeName"] for a in call(engine, "assignments.list")["result"]["assignments"]] == ["Rina"]
    assert _dashboard(engine)["tit"]["assignments"][0]["assigneeId"] == rina["userId"]
    assert json.dumps(call(engine, "project.listBookProgress")["result"])  # serialisable end to end
