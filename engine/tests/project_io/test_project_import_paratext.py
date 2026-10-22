"""Importing a whole Paratext 9 project folder (#355), against synthetic folders."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tc_ai_bridge.project_import import inspect_import, import_source
from tests.support.paratext_fixture import DEFAULT_GUID, build_paratext_project, simple_book


def _digest(folder: Path) -> dict[str, str]:
    return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


def _messy_project(tmp_path: Path, **kwargs) -> Path:
    """A folder that broke the old recursive scan: RegExBackups that start with
    a real \\id, .BAK copies, an INT peripheral with no \\c, and a stray
    front-matter file under shared/ptxprint."""
    folder = build_paratext_project(
        tmp_path, regex_backups=2, bak=True,
        peripherals={"INT": "\\id INT\n\\ip Introduction only.\n"}, **kwargs,
    )
    stray = folder / "shared" / "ptxprint" / "Default"
    stray.mkdir(parents=True)
    (stray / "FRTlocal.sfm").write_text("\\id FRT\n\\mt Front\n", encoding="utf-8")
    return folder


def test_inspect_lists_the_named_books_and_reports_skips(tmp_path):
    folder = _messy_project(tmp_path)

    preview = inspect_import(folder)

    assert preview["kind"] == "paratext"
    assert [book["bookId"] for book in preview["books"]] == ["tit", "phm"]
    assert {Path(book["sourceFile"]).name for book in preview["books"]} == {"57TITTSTP.SFM", "58PHMTSTP.SFM"}
    assert "Skipped RegExBackup1.sfm: Paratext find-and-replace backup (RegExBackup)." in preview["warnings"]
    assert "Skipped RegExBackup2.sfm: Paratext find-and-replace backup (RegExBackup)." in preview["warnings"]
    assert "Skipped A7INTTSTP.SFM: peripheral book INT, not Scripture text." in preview["warnings"]
    assert not any("FRTlocal" in warning for warning in preview["warnings"])
    assert preview["metadata"]["projectName"] == "TSTP"
    assert preview["metadata"]["bibleName"] == "Synthetic Test Project"
    block = preview["paratext"]
    assert block["guid"] == DEFAULT_GUID
    assert block["folder"] == str(folder.resolve())
    assert block["booksPresent"] == ["TIT", "PHM", "INT"]
    assert block["versification"] == "eng"


def test_known_language_code_leaves_the_name_to_the_iso_table(tmp_path):
    # <Language> is free text ("TestDeva" on a real test project): a known code
    # is named by the import screen from its ISO 639-3 table (#355 decision).
    folder = build_paratext_project(tmp_path, language="TestDeva", language_iso="sa:::")
    preview = inspect_import(folder)
    assert preview["metadata"]["languageId"] == "san"
    assert preview["metadata"]["languageName"] == ""
    assert preview["paratextLanguageName"] == "TestDeva"


def test_tamil_project_language(tmp_path):
    preview = inspect_import(build_paratext_project(tmp_path))
    assert preview["metadata"]["languageId"] == "tam"
    assert preview["paratextLanguageName"] == "Tamil"


@pytest.mark.parametrize(("iso", "language_id", "language_name"), [
    ("xx:::", "", "Somelang"),          # not an ISO 639-1 code: <Language> is the name
    ("xxx:Latn::", "xxx", ""),
    ("", "", "Somelang"),
])
def test_language_iso_cases_308(tmp_path, iso, language_id, language_name):
    folder = build_paratext_project(tmp_path, language="Somelang", language_iso=iso)
    preview = inspect_import(folder)
    assert preview["metadata"]["languageId"] == language_id
    assert preview["metadata"]["languageName"] == language_name


def test_a_pattern_that_names_nothing_falls_back_to_the_folder_scan(tmp_path):
    folder = build_paratext_project(tmp_path, naming="none")
    preview = inspect_import(folder)
    assert preview["kind"] == "paratext"
    assert sorted(book["bookId"] for book in preview["books"]) == ["phm", "tit"]
    assert "Every Scripture file in the folder was scanned instead." in preview["warnings"]


def test_the_fallback_scan_skips_regex_backups_and_never_enters_hg(tmp_path):
    folder = build_paratext_project(tmp_path, naming="none", regex_backups=1)
    hg = folder / ".hg" / "store"
    hg.mkdir(parents=True)
    (hg / "57TIT.SFM").write_text(simple_book("TIT"), encoding="utf-8")
    preview = inspect_import(folder)
    assert sorted(book["bookId"] for book in preview["books"]) == ["phm", "tit"]
    assert all(".hg" not in book["sourceFile"] and "RegExBackup" not in book["sourceFile"] for book in preview["books"])


def test_picking_one_book_file_keeps_the_settings_but_not_the_whole_folder(tmp_path):
    folder = build_paratext_project(tmp_path)
    preview = inspect_import(folder / "57TITTSTP.SFM")
    assert preview["kind"] == "paratext"
    assert [book["bookId"] for book in preview["books"]] == ["tit"]
    assert preview["paratext"]["guid"] == DEFAULT_GUID


def test_a_settings_file_that_is_not_paratext_is_ignored(tmp_path):
    folder = tmp_path / "Plain"
    folder.mkdir()
    (folder / "57TIT.SFM").write_text(simple_book("TIT"), encoding="utf-8")
    (folder / "Settings.xml").write_text("<Settings><Name>x</Name></Settings>", encoding="utf-8")
    preview = inspect_import(folder)
    assert preview["kind"] == "usfm"
    assert preview["paratext"] is None


def test_import_writes_the_link_to_every_sibling_and_leaves_the_source_alone(tmp_path):
    folder = _messy_project(tmp_path)
    before = _digest(folder)
    destination = tmp_path / "projects"

    result = import_source(folder, destination, {"languageName": "Tamil"})

    assert [project["bookId"] for project in result["projects"]] == ["tit", "phm"]
    blocks = []
    for project in result["projects"]:
        collection = json.loads((Path(project["path"]) / ".bridge" / "collection.json").read_text(encoding="utf-8"))
        assert collection["schemaVersion"] == 2
        blocks.append(collection["paratext"])
    assert blocks[0] == blocks[1]
    assert blocks[0]["guid"] == DEFAULT_GUID and blocks[0]["schemaVersion"] == 1
    assert _digest(folder) == before


def test_a_plain_usfm_import_records_no_link(tmp_path):
    source = tmp_path / "TIT.usfm"
    source.write_text(simple_book("TIT"), encoding="utf-8")
    result = import_source(source, tmp_path / "projects", {
        "languageId": "tam", "languageName": "Tamil", "projectName": "P", "bibleName": "B"})
    collection = json.loads((Path(result["primaryProjectPath"]) / ".bridge" / "collection.json").read_text(encoding="utf-8"))
    assert "paratext" not in collection
