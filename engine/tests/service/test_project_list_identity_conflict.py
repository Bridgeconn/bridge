"""#309: one managed folder whose identity conflicts must not empty project.list.

A copy of a Bridge-made project carries the source's `.bridge/project.json`.
Before #309 the registry's discovery pass raised ProjectIdentityError for it and
project.list failed for every project. The other projects are listed, and the
copy comes back as one row with a `conflict` and no projectId of its own.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from bridge_service import BridgeEngine
from tc_ai_bridge.project_import import import_source
from tc_ai_bridge.secret_store import AppSettings

from tests.support.projects import call

TITUS = "\\id TIT\n\\h Titus\n\\c 1\n\\p\n\\v 1 Paul, a servant of God.\n"
PHILEMON = "\\id PHM\n\\h Philemon\n\\c 1\n\\v 1 Paul, a prisoner of Christ Jesus.\n"
METADATA = {
    "languageId": "eng", "languageName": "English", "languageDirection": "ltr",
    "projectName": "NT review", "bibleName": "Test Bible",
}


def _import(engine: BridgeEngine, source: Path) -> dict:
    """Write the books into the managed folder and let project.list register
    them. Nothing is opened, so no background work is still writing the
    folders when the test copies them."""
    result = import_source(source, engine.project_root, METADATA)
    listed = call(engine, "project.list")
    assert listed["success"] is True, listed
    return result


def _engine(tmp_path: Path) -> BridgeEngine:
    return BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json"))


def test_a_duplicated_identity_is_one_conflict_row_and_the_rest_are_listed(tmp_path):
    engine = _engine(tmp_path)
    titus = tmp_path / "TIT.usfm"
    titus.write_text(TITUS, encoding="utf-8")
    philemon = tmp_path / "PHM.usfm"
    philemon.write_text(PHILEMON, encoding="utf-8")
    source = Path(_import(engine, titus)["primaryProjectPath"])
    _import(engine, philemon)
    identity = json.loads((source / ".bridge" / "project.json").read_text(encoding="utf-8"))
    copy = source.parent / f"{source.name}-copy"
    shutil.copytree(source, copy)

    listed = call(engine, "project.list")
    assert listed["success"] is True, listed
    rows = listed["result"]["projects"]
    registered = [row for row in rows if not row.get("conflict")]
    conflicts = [row for row in rows if row.get("conflict")]
    assert sorted(row["bookId"] for row in registered) == ["phm", "tit"]
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert Path(conflict["path"]) == copy
    assert conflict["projectId"] == "" and conflict["bookId"] == "tit"
    assert conflict["conflict"]["projectId"] == identity["projectId"]
    assert Path(conflict["conflict"]["registeredPath"]) == source
    assert "two accessible paths" in conflict["conflict"]["message"]
    # Nothing was written to the copy, and it is not registered.
    assert json.loads((copy / ".bridge" / "project.json").read_text(encoding="utf-8")) == identity
    assert engine.project_registry.get(identity["projectId"])["path"] == str(source)

    # Still listed on the next call; gone once the copy is removed.
    assert len([row for row in call(engine, "project.list")["result"]["projects"] if row.get("conflict")]) == 1
    shutil.rmtree(copy)
    rows = call(engine, "project.list")["result"]["projects"]
    assert not [row for row in rows if row.get("conflict")] and len(rows) == 2


def test_a_copied_collection_is_one_conflict_row_with_its_book_count(tmp_path):
    engine = _engine(tmp_path)
    source = tmp_path / "ParatextProject"
    source.mkdir()
    (source / "57TIT.SFM").write_text(TITUS, encoding="utf-8")
    (source / "58PHM.SFM").write_text(PHILEMON, encoding="utf-8")
    result = _import(engine, source)
    copies = tmp_path / "copies"
    for book in result["projects"]:
        folder = Path(book["path"])
        shutil.copytree(folder, copies / folder.name)
    for folder in (copies).iterdir():
        shutil.move(str(folder), str(engine.project_root / f"{folder.name}-copy"))

    rows = call(engine, "project.list")["result"]["projects"]
    registered = [row for row in rows if not row.get("conflict")]
    conflicts = [row for row in rows if row.get("conflict")]
    assert len(registered) == 1 and registered[0]["bookCount"] == 2
    assert len(conflicts) == 1 and conflicts[0]["bookCount"] == 2
    assert conflicts[0]["conflict"]["collectionId"] == registered[0]["collectionId"]
