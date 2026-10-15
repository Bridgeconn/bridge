"""#238: the projects list's columns and management.

project.list carries, per project or collection, the cached progress summed
over the collection's books, the latest open across them and who did it;
project.rename sets a display name in the registry only, project.archive and
project.unarchive set and clear an archive stamp on the whole collection.
Nothing touches the folder, the manifest or the collection file.
"""
from __future__ import annotations

import json
from pathlib import Path

from bridge_service import BridgeEngine
from tc_ai_bridge.secret_store import AppSettings

from tests.support.projects import call, wait_for_job

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
    return engine, imported["result"]


def _row(engine):
    rows = call(engine, "project.list")["result"]["projects"]
    assert len(rows) == 1, rows
    return rows[0]


def test_the_list_carries_summed_progress_and_the_latest_open_with_its_user(tmp_path):
    engine, opened = _import_collection(tmp_path)
    row = _row(engine)
    assert row["bookCount"] == 2
    assert row["progress"] is None, "no book has a rollup yet"
    assert row["lastOpenedAt"] and row["lastOpenedBy"] == engine.current_actor_id()
    assert row["lastOpenedByName"] == engine.local_user()["displayName"]

    started = call(engine, "checks.start", {"scope": "chapter", "chapters": ["1"], "checks": ["local"]})
    assert started["success"] is True, started
    assert wait_for_job(engine, started["result"]["jobId"])["state"] == "succeeded"
    row = _row(engine)
    assert row["progress"]["booksWithProgress"] == 1
    assert row["progress"]["chapterCount"] == 2 and row["progress"]["checkedChapterCount"] == 1
    assert row["progress"]["verseCount"] == 2  # TIT: 1:1 and 2:1
    assert "alignedKnownVerseCount" in row["progress"] and "languageQaCheckedVerseCount" in row["progress"]

    # Opening the sibling makes the collection's latest open its open.
    sibling = next(book for book in opened["importedProjects"] if book["bookId"] == "phm")
    first_open = row["lastOpenedAt"]
    assert call(engine, "project.open", {"path": sibling["path"], "awaitSemantic": True})["success"] is True
    row = _row(engine)
    assert row["lastOpenedAt"] >= first_open
    assert row["lastOpenedBy"] == engine.current_actor_id()


def test_rename_is_a_display_name_on_every_book_and_the_folder_is_untouched(tmp_path):
    engine, opened = _import_collection(tmp_path)
    row = _row(engine)
    primary = Path(opened["path"])
    manifest_before = (primary / "manifest.json").read_bytes()
    collection_before = (primary / ".bridge" / "collection.json").read_bytes()

    renamed = call(engine, "project.rename", {"projectId": row["projectId"], "name": "  Titus and Philemon  "})
    assert renamed["success"] is True, renamed
    assert renamed["result"] == {"projectId": row["projectId"], "displayName": "Titus and Philemon", "books": 2}
    row = _row(engine)
    assert row["displayName"] == "Titus and Philemon" and row["projectName"] == "NT review"
    assert all(e["displayName"] == "Titus and Philemon" for e in engine.project_registry.group_entries(row["projectId"]))
    assert primary.name == Path(opened["path"]).name
    assert (primary / "manifest.json").read_bytes() == manifest_before
    assert (primary / ".bridge" / "collection.json").read_bytes() == collection_before

    # Reopening re-registers the entry; the display name survives the metadata refresh.
    assert call(engine, "project.open", {"path": str(primary), "awaitSemantic": True})["success"] is True
    assert _row(engine)["displayName"] == "Titus and Philemon"

    # An empty name clears it.
    assert call(engine, "project.rename", {"projectId": row["projectId"], "name": ""})["success"] is True
    assert "displayName" not in _row(engine)
    missing = call(engine, "project.rename", {"projectId": "nope", "name": "x"})
    assert missing["success"] is False and "not found" in missing["error"]["message"].lower()


def test_archive_and_unarchive_stamp_the_whole_collection_and_survive_a_restart(tmp_path):
    engine, opened = _import_collection(tmp_path)
    row = _row(engine)
    archived = call(engine, "project.archive", {"projectId": row["projectId"]})
    assert archived["success"] is True and archived["result"] == {"projectId": row["projectId"], "archived": True, "books": 2}
    row = _row(engine)
    assert row["archivedAt"]
    assert all(e.get("archivedAt") for e in engine.project_registry.group_entries(row["projectId"]))

    # The stamp is in the workspace database, lifted to its own column, and a
    # fresh engine on the same workspace still sees it.
    settings_path = tmp_path / "settings.json"
    again = BridgeEngine(settings=AppSettings(path=settings_path))
    assert _row(again)["archivedAt"] == row["archivedAt"]
    with again.workspace._connect() as conn:
        lifted = conn.execute("SELECT archived_at, last_opened_by FROM projects").fetchall()
    assert all(r["archived_at"] == row["archivedAt"] for r in lifted)
    # Only the book that was opened carries an opener; the lazy sibling never was.
    assert [r["last_opened_by"] for r in lifted if r["last_opened_by"]] == [again.current_actor_id()]

    assert call(again, "project.unarchive", {"projectId": row["projectId"]})["success"] is True
    assert "archivedAt" not in _row(again)
    # Still on disk, still registered: archive never deletes.
    assert Path(opened["path"]).is_dir()
    assert json.loads((Path(opened["path"]) / ".bridge" / "project.json").read_text(encoding="utf-8"))["projectId"]
