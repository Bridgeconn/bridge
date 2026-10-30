"""Adding books to an existing project from Project Home.

project.inspectAddBooks is read-only: the books the chosen files or folders
hold, each flagged `exists` when the project already has it. project.addBooks.start
writes new siblings as lazy placeholders (the shape a multi-book import leaves),
turns a single book into a collection, replaces only the books the reviewer
named, and rewrites `.bridge/collection.json` on every sibling. It is an import
job, polled through project.import.status.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from bridge_service import BridgeEngine
from tc_ai_bridge.project_import import collection_projects
from tc_ai_bridge.secret_store import AppSettings

from tests.support.projects import call
from tests.support.waits import job_timeout

TITUS = "\\id TIT\n\\h Titus\n\\c 1\n\\p\n\\v 1 Paul, a servant of God.\n\\c 2\n\\v 1 But speak.\n"
TITUS_V2 = "\\id TIT\n\\h Titus\n\\c 1\n\\p\n\\v 1 Paul, a slave of God.\n"
PHILEMON = "\\id PHM\n\\h Philemon\n\\c 1\n\\v 1 Paul, a prisoner of Christ Jesus.\n"
JUDE = "\\id JUD\n\\h Jude\n\\c 1\n\\v 1 Jude, a servant of Jesus Christ.\n"
METADATA = {
    "languageId": "eng", "languageName": "English", "languageDirection": "ltr",
    "projectName": "NT review", "bibleName": "Test Bible",
}


def _engine(tmp_path: Path) -> BridgeEngine:
    return BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json"))


def _import_single(engine: BridgeEngine, tmp_path: Path) -> dict:
    source = tmp_path / "src"
    source.mkdir(exist_ok=True)
    (source / "57TIT.SFM").write_text(TITUS, encoding="utf-8")
    opened = call(engine, "project.import", {"path": str(source / "57TIT.SFM"), "metadata": METADATA})
    assert opened["success"] is True, opened
    return opened["result"]


def _wait(engine: BridgeEngine, job_id: str) -> dict:
    deadline = time.monotonic() + job_timeout(10.0)
    while time.monotonic() < deadline:
        snapshot = call(engine, "project.import.status", {"jobId": job_id})["result"]
        if snapshot["state"] in {"succeeded", "failed", "cancelled"}:
            return snapshot
        time.sleep(0.01)
    raise AssertionError("add-books job did not finish")


def _listed(engine: BridgeEngine) -> list[dict]:
    return call(engine, "project.list")["result"]["projects"]


def test_inspect_flags_the_books_the_project_already_has(tmp_path):
    engine = _engine(tmp_path)
    opened = _import_single(engine, tmp_path)
    folder = tmp_path / "more"
    folder.mkdir()
    (folder / "57TIT.SFM").write_text(TITUS_V2, encoding="utf-8")
    (folder / "58PHM.SFM").write_text(PHILEMON, encoding="utf-8")
    response = call(engine, "project.inspectAddBooks", {"projectId": opened["projectId"], "paths": [str(folder)]})
    assert response["success"] is True, response
    preview = response["result"]
    assert preview["existingBookIds"] == ["tit"]
    assert [(b["bookId"], b["exists"]) for b in preview["books"]] == [("tit", True), ("phm", False)]
    assert preview["books"][0]["existingPath"] == opened["path"]


def test_inspect_refuses_a_translationcore_project_and_a_book_named_twice(tmp_path):
    engine = _engine(tmp_path)
    opened = _import_single(engine, tmp_path)
    refused = call(engine, "project.inspectAddBooks", {"projectId": opened["projectId"], "paths": [opened["path"]]})
    assert refused["success"] is False
    assert "translationCore project" in refused["error"]["message"]
    a = tmp_path / "a.usfm"
    b = tmp_path / "b.usfm"
    a.write_text(PHILEMON, encoding="utf-8")
    b.write_text(PHILEMON, encoding="utf-8")
    twice = call(engine, "project.inspectAddBooks", {"projectId": opened["projectId"], "paths": [str(a), str(b)]})
    assert twice["success"] is False
    assert "PHM" in twice["error"]["message"]


def test_adding_files_turns_a_single_book_into_a_collection_in_canonical_order(tmp_path):
    engine = _engine(tmp_path)
    opened = _import_single(engine, tmp_path)
    jude = tmp_path / "jude.usfm"
    phm = tmp_path / "phm.usfm"
    jude.write_text(JUDE, encoding="utf-8")
    phm.write_text(PHILEMON, encoding="utf-8")
    started = call(engine, "project.addBooks.start", {"projectId": opened["projectId"], "paths": [str(jude), str(phm)]})
    assert started["success"] is True, started
    snapshot = _wait(engine, started["result"]["jobId"])
    assert snapshot["state"] == "succeeded", snapshot
    result = snapshot["result"]
    assert [b["bookId"] for b in result["added"]] == ["phm", "jud"]
    assert result["replaced"] == [] and result["skipped"] == []
    assert [b["bookId"] for b in result["projects"]] == ["tit", "phm", "jud"]

    # Every sibling carries the same collection record, and the new books are
    # lazy placeholders beside the original, the way an import leaves them.
    siblings = collection_projects(opened["path"])
    assert [(s["bookId"], s["lazy"]) for s in siblings] == [("tit", False), ("phm", True), ("jud", True)]
    for sibling in siblings:
        record = json.loads((Path(sibling["path"]) / ".bridge" / "collection.json").read_text(encoding="utf-8"))
        assert record["collectionId"] == result["collectionId"]
        assert [p["bookId"] for p in record["projects"]] == ["tit", "phm", "jud"]
        assert Path(sibling["path"]).parent == Path(opened["path"]).parent
    descriptor = json.loads((Path(siblings[1]["path"]) / ".bridge" / "lazy-import.json").read_text(encoding="utf-8"))
    assert descriptor["metadata"]["languageId"] == "eng"
    assert descriptor["metadata"]["bibleName"] == "Test Bible"

    # The registry now lists one 3-book collection, and the original keeps its id.
    rows = _listed(engine)
    assert len(rows) == 1 and rows[0]["bookCount"] == 3
    assert rows[0]["collectionId"] == result["collectionId"]
    ids = {b["bookId"]: b["projectId"] for b in result["projects"]}
    assert ids["tit"] == opened["projectId"]

    # A new sibling opens: it is prepared from its copied source.
    reopened = call(engine, "project.open", {"path": siblings[2]["path"], "awaitSemantic": True})
    assert reopened["success"] is True, reopened
    assert reopened["result"]["bookId"] == "jud"
    assert [p["bookId"] for p in reopened["result"]["importedProjects"]] == ["tit", "phm", "jud"]


def test_an_existing_book_is_skipped_unless_named_to_be_replaced(tmp_path):
    engine = _engine(tmp_path)
    opened = _import_single(engine, tmp_path)
    folder = tmp_path / "more"
    folder.mkdir()
    (folder / "57TIT.SFM").write_text(TITUS_V2, encoding="utf-8")
    (folder / "58PHM.SFM").write_text(PHILEMON, encoding="utf-8")

    started = call(engine, "project.addBooks.start", {"projectId": opened["projectId"], "paths": [str(folder)]})
    snapshot = _wait(engine, started["result"]["jobId"])
    assert snapshot["state"] == "succeeded", snapshot
    assert snapshot["result"]["skipped"] == ["tit"]
    assert [b["bookId"] for b in snapshot["result"]["added"]] == ["phm"]
    # Titus is untouched: still materialised, still the original wording.
    chapter = json.loads((Path(opened["path"]) / "tit" / "1.json").read_text(encoding="utf-8"))
    assert chapter["1"].startswith("Paul, a servant")

    # Only Titus is marked for replacement; Philemon is now skipped.
    started = call(engine, "project.addBooks.start", {
        "projectId": opened["projectId"], "paths": [str(folder)], "replaceBookIds": ["tit"],
    })
    snapshot = _wait(engine, started["result"]["jobId"])
    assert snapshot["state"] == "succeeded", snapshot
    assert [b["bookId"] for b in snapshot["result"]["replaced"]] == ["tit"]
    assert snapshot["result"]["skipped"] == ["phm"]
    titus = Path(opened["path"])
    assert (titus / ".bridge" / "lazy-import.json").is_file()
    assert not (titus / "tit" / "1.json").exists()
    siblings = collection_projects(str(titus))
    assert [(s["bookId"], s["lazy"]) for s in siblings] == [("tit", True), ("phm", True)]
    # The same folder, the same id: the registry still knows it as one collection.
    rows = _listed(engine)
    assert len(rows) == 1 and rows[0]["bookCount"] == 2
    ids = {b["bookId"]: b["projectId"] for b in snapshot["result"]["projects"]}
    assert ids["tit"] == opened["projectId"]
    # Opening the replaced book prepares it from the new source.
    reopened = call(engine, "project.open", {"path": str(titus), "awaitSemantic": True})
    assert reopened["success"] is True, reopened
    chapter = json.loads((titus / "tit" / "1.json").read_text(encoding="utf-8"))
    assert chapter["1"].startswith("Paul, a slave")


def test_nothing_to_add_is_refused_before_anything_is_written(tmp_path):
    engine = _engine(tmp_path)
    opened = _import_single(engine, tmp_path)
    same = tmp_path / "tit-again.usfm"
    same.write_text(TITUS_V2, encoding="utf-8")
    started = call(engine, "project.addBooks.start", {"projectId": opened["projectId"], "paths": [str(same)]})
    assert started["success"] is True, started
    snapshot = _wait(engine, started["result"]["jobId"])
    assert snapshot["state"] == "failed"
    assert "already in the project" in snapshot["error"]
    assert sorted(p.name for p in Path(opened["path"]).parent.iterdir()) == [Path(opened["path"]).name]


def test_a_reporter_may_inspect_but_not_add(tmp_path):
    engine = _engine(tmp_path)
    opened = _import_single(engine, tmp_path)
    jude = tmp_path / "jude.usfm"
    jude.write_text(JUDE, encoding="utf-8")
    user = engine.local_user()
    engine.workspace.set_user_role(user["userId"], "reporter")
    engine.refresh_local_user()
    inspected = call(engine, "project.inspectAddBooks", {"projectId": opened["projectId"], "paths": [str(jude)]})
    assert inspected["success"] is True, inspected
    refused = call(engine, "project.addBooks.start", {"projectId": opened["projectId"], "paths": [str(jude)]})
    assert refused["success"] is False
    assert "reporter" in refused["error"]["message"]
