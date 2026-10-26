"""#309: importing a project Bridge made earlier.

The copy carries the source's `.bridge/project.json`. When that id is already
registered on this device at a path that exists, the copy gets a new id and
records the source's ids in `.bridge/import.json` `importedFrom` (Benz,
2026-10-22, option b). Otherwise -- an archive from another machine -- the copy
keeps the id, and with it its history.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

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


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _bridge_made(engine: BridgeEngine, source: Path) -> Path:
    """A Bridge-made project, registered by project.list and never opened."""
    result = import_source(source, engine.project_root, METADATA)
    assert call(engine, "project.list")["success"] is True
    return Path(result["primaryProjectPath"])


def _as_import_source(project: Path, kind: str, tmp_path: Path) -> Path:
    if kind == "folder":
        return project
    archive = tmp_path / f"exported{'.zip' if kind == 'zip' else '.tcore'}"
    with zipfile.ZipFile(archive, "w") as handle:
        for path in project.rglob("*"):
            if path.is_file():
                handle.write(path, f"{project.name}/{path.relative_to(project).as_posix()}")
    return archive


def _import(engine: BridgeEngine, source: Path) -> dict:
    imported = call(engine, "project.import", {"path": str(source), "metadata": METADATA, "allowDuplicate": True})
    assert imported["success"] is True, imported
    return imported["result"]


@pytest.mark.parametrize("kind", ["folder", "zip", "tcore"])
def test_a_copy_of_a_project_registered_here_gets_a_new_id_and_records_the_source(tmp_path, kind):
    engine = BridgeEngine(settings=AppSettings(path=tmp_path / "app" / "settings.json"))
    titus = tmp_path / "TIT.usfm"
    titus.write_text(TITUS, encoding="utf-8")
    original = _bridge_made(engine, titus)
    identity = _read(original / ".bridge" / "project.json")

    result = _import(engine, _as_import_source(original, kind, tmp_path))

    copy = Path(result["path"])
    assert copy != original
    copied = _read(copy / ".bridge" / "project.json")
    assert copied["projectId"] not in {"", identity["projectId"]}
    assert result["projectId"] == copied["projectId"]
    provenance = _read(copy / ".bridge" / "import.json")["importedFrom"]
    assert provenance["projectId"] == identity["projectId"]
    assert provenance["createdAt"] == identity["createdAt"]
    assert provenance["collectionId"] == identity.get("collectionId", "")
    assert provenance["sourcePath"]
    # The source keeps its identity, and both are listed with no conflict.
    assert _read(original / ".bridge" / "project.json") == identity
    rows = call(engine, "project.list")["result"]["projects"]
    assert not [row for row in rows if row.get("conflict")]
    assert {row["projectId"] for row in rows} == {identity["projectId"], copied["projectId"]}


@pytest.mark.parametrize("kind", ["folder", "zip", "tcore"])
def test_a_copy_whose_id_is_not_registered_here_keeps_it(tmp_path, kind):
    maker = BridgeEngine(settings=AppSettings(path=tmp_path / "other-device" / "settings.json"))
    titus = tmp_path / "TIT.usfm"
    titus.write_text(TITUS, encoding="utf-8")
    original = _bridge_made(maker, titus)
    identity = _read(original / ".bridge" / "project.json")

    engine = BridgeEngine(settings=AppSettings(path=tmp_path / "this-device" / "settings.json"))
    result = _import(engine, _as_import_source(original, kind, tmp_path))

    copy = Path(result["path"])
    assert _read(copy / ".bridge" / "project.json")["projectId"] == identity["projectId"]
    assert result["projectId"] == identity["projectId"]
    assert "importedFrom" not in _read(copy / ".bridge" / "import.json")


def test_a_book_copied_from_a_collection_is_a_collection_of_its_own_folder(tmp_path):
    engine = BridgeEngine(settings=AppSettings(path=tmp_path / "app" / "settings.json"))
    source = tmp_path / "ParatextProject"
    source.mkdir()
    (source / "57TIT.SFM").write_text(TITUS, encoding="utf-8")
    (source / "58PHM.SFM").write_text(PHILEMON, encoding="utf-8")
    original = _bridge_made(engine, source)
    collection = _read(original / ".bridge" / "collection.json")
    assert collection["collectionId"] and len(collection["projects"]) == 2

    result = _import(engine, original)

    copy = Path(result["path"])
    rewritten = _read(copy / ".bridge" / "collection.json")
    assert rewritten["collectionId"] == "" and result["collectionId"] == ""
    assert [(entry["bookId"], entry["directoryName"], entry["projectId"]) for entry in rewritten["projects"]] == [
        ("tit", copy.name, result["projectId"]),
    ]
    assert _read(copy / ".bridge" / "import.json")["importedFrom"]["collectionId"] == collection["collectionId"]
    # The source collection is untouched and still one row of two books.
    assert _read(original / ".bridge" / "collection.json") == collection
    rows = call(engine, "project.list")["result"]["projects"]
    assert not [row for row in rows if row.get("conflict")]
    assert sorted(row.get("bookCount", 1) for row in rows) == [1, 2]
