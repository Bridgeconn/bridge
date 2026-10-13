"""Cross-reference targets and origins (framework item 28, #249), on the shapes
the IRV uses: book names are the books' \\toc3, a reference may be a range across
chapters, a whole chapter, or a bare chapter after the previous book."""
from __future__ import annotations

import json

from tc_ai_bridge.language_qa_xrefs import collection_names, xref_findings

NAMES = {"ஆதி": "GEN", "யாத்": "EXO", "2நாளா": "2CH", "சங்": "PSA", "மத்": "MAT"}


def xref(xt: str, origin: str = "1:3") -> str:
    return f"\\x + \\xo {origin} \\xt {xt}\\x*இயேசு சொன்னார்."


def found(raw: str, names: dict[str, str] = NAMES, verse: str = "3") -> list[tuple[str, str]]:
    return [(f["rule"], f["originalText"]) for f in xref_findings("jhn", {"1": {verse: raw}}, names)]


def test_targets_that_exist_in_some_versification_are_fine():
    assert found(xref("ஆதி 1:1; யாத் 7:8-12:13; சங் 59; 142; 2நாளா 24:20-22; மத் 19:4,6")) == []
    # PSA 151 exists in the LXX versification, MAL 4 in the English one: numbering differs, not wrong
    assert found(xref("சங் 151")) == []


def test_a_verse_or_chapter_that_does_not_exist_is_flagged():
    assert found(xref("ஆதி 1:1; ஆதி 50:40")) == [("xref.target-missing", "ஆதி 50:40")]
    assert found(xref("சங் 152")) == [("xref.target-missing", "சங் 152")]
    [finding] = xref_findings("jhn", {"1": {"3": xref("யாத் 41:2")}}, NAMES)
    assert "EXO 41" in finding["message"] and finding["suggestions"] == []


def test_an_unknown_book_name_only_counts_in_a_whole_bible():
    assert found(xref("ஆதியா 1:1")) == []
    whole = dict(NAMES, **{f"book{i}": f"B{i:02d}" for i in range(61)})
    assert found(xref("ஆதியா 1:1"), whole) == [("xref.target-missing", "ஆதியா 1:1")]


def test_text_that_is_not_a_reference_is_skipped():
    assert found(xref("1சாமு 16:1-2சாமு 2:11")) == []


def test_an_origin_that_is_not_this_verse_is_flagged_with_its_reference():
    [finding] = xref_findings("jhn", {"1": {"3": xref("ஆதி 1:1", origin="2:9")}}, NAMES)
    assert (finding["rule"], finding["originalText"], finding["suggestions"][0]["text"]) == \
        ("xref.origin-mismatch", "2:9", "1:3")
    assert found(xref("ஆதி 1:1", origin="1:1-5")) == []      # a range naming this verse
    assert found(xref("ஆதி 1:1", origin="1:4"), verse="3-4") == []  # a verse bridge


def test_the_pass_reports_a_missing_target_in_its_own_book(tmp_path):
    from tc_ai_bridge.language_qa_jobs import LanguageQaManager  # noqa: PLC0415
    from tests.support.language_qa import project_at, wait  # noqa: PLC0415
    # a single book with no name map: a reference with no book name is this book's
    project = project_at(tmp_path, verses={"3": xref("50:40")}, book="rut")
    manager = LanguageQaManager(debounce=0, yield_seconds=0)
    manager.bind(project)
    try:
        result = wait(manager)
    finally:
        manager.unbind()
    # chapter 1, verse 3: the \xo 1:3 is right, RUT 50 does not exist
    assert [(f["rule"], f["originalText"]) for f in result["findings"] if f["rule"].startswith("xref.")] == \
        [("xref.target-missing", "50:40")]
    assert not [line for line in result["limitations"] if "Cross-reference" in line]


def _book(folder, book: str, toc3: str, lazy: bool = False) -> None:
    folder.mkdir()
    usfm = f"\\id {book.upper()}\n\\h {toc3}ஆகமம்\n\\toc2 {toc3}ஆகமம்\n\\toc3 {toc3}\n\\c 1\n\\p\n\\v 1 வசனம்.\n"
    (folder / ".bridge").mkdir()
    if lazy:
        (folder / ".bridge" / "source.usfm").write_text(usfm, encoding="utf-8")
        (folder / ".bridge" / "lazy-import.json").write_text(json.dumps({"sourceCopy": ".bridge/source.usfm"}),
                                                             encoding="utf-8")
    else:
        (folder / f"{book}.usfm").write_text(usfm, encoding="utf-8")


def test_the_names_come_from_every_book_of_the_collection_lazy_ones_too(tmp_path):
    _book(tmp_path / "gen", "gen", "ஆதி")
    _book(tmp_path / "exo", "exo", "யாத்", lazy=True)
    collection = {"projects": [{"directoryName": "gen", "bookId": "gen"}, {"directoryName": "exo", "bookId": "exo"}]}
    for name in ("gen", "exo"):
        (tmp_path / name / ".bridge" / "collection.json").write_text(json.dumps(collection), encoding="utf-8")
    names = collection_names(tmp_path / "gen")
    assert names["ஆதி"] == "GEN" and names["யாத்"] == "EXO" and names["யாத்ஆகமம்"] == "EXO"
