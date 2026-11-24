"""#507: showing and editing what stands outside the verses -- a section
heading, a major heading before a chapter, a psalm title before verse 1 and
the book's introduction -- through a real import and the dispatcher, and what
an export writes afterwards. Drives the RPCs, so it lives here."""
from __future__ import annotations

import json
from pathlib import Path

from bridge_service import BridgeEngine
from tc_ai_bridge.project_import import import_source
from tests.support.projects import _write_minimal_book, call

PSALMS = (
    "\\id PSA Test Psalms\n\\h Psalms\n\\toc1 The Psalms\n\\mt Psalms\n"
    "\\is Introduction\n"
    "\\ip The book of \\bk Psalms\\bk* is a hymn book.\n"
    "\\iot Outline\n"
    "\\io1 Book one \\ior 1-41\\ior*\n"
    "\\io1 Book two \\ior 42-72\\ior*\n"
    "\\ms BOOK ONE\n"
    "\\c 1\n\\q1\n\\v 1 Blessed is the man\n\\q2 who walks not\n"
    "\\c 3\n\\d A Psalm of David, when he fled.\n\\q1\n\\v 1 Lord, how\n\\q2 many are they\n\\q1\n"
    "\\v 2 Many say\n\\s The Lord answers\n\\r (Ps 4)\n\\q1\n\\v 3 But you\n"
    "\\ms BOOK TWO\n"
    "\\c 42\n\\d For the director.\n\\q1\n\\v 1 As the deer\n\\q2 pants\n"
)


def _import(tmp_path) -> tuple[BridgeEngine, Path]:
    source = tmp_path / "src"
    source.mkdir()
    (source / "PSA.usfm").write_text(PSALMS, encoding="utf-8")
    destination = tmp_path / "projects"
    destination.mkdir()
    imported = import_source(source, destination, {
        "languageId": "eng", "languageName": "English", "languageDirection": "ltr",
        "projectName": "Psalms review", "bibleName": "Test Bible",
    })
    root = Path(imported["primaryProjectPath"])
    engine = BridgeEngine()
    assert call(engine, "project.open", {"path": str(root)})["success"] is True
    return engine, root


def _headings(engine, chapter: str) -> dict:
    return call(engine, "chapter.verseData", {"chapter": chapter})["result"]["headings"]


def _exported(engine, tmp_path) -> str:
    out = tmp_path / "out.usfm"
    result = call(engine, "export.nonAligned", {"outputPath": str(out), "override": True})
    assert result["success"] is True, result
    assert result["result"]["fidelity"] == "source-preserving"
    return out.read_text(encoding="utf-8")


# --- where things are filed -----------------------------------------------------

def test_a_major_heading_before_a_chapter_opens_that_chapter(tmp_path):
    engine, _root = _import(tmp_path)
    # Before `\c 1` it used to be a line of the book's header and was not
    # shown; before `\c 42` it used to be filed under Psalm 3's last verse.
    assert _headings(engine, "1")["1"] == [{"tag": "ms", "text": "BOOK ONE"}]
    assert _headings(engine, "42")["1"][0] == {"tag": "ms", "text": "BOOK TWO"}
    assert "BOOK TWO" not in json.dumps(_headings(engine, "3"))


def test_a_psalm_title_before_verse_1_is_kept_with_that_verses_headings(tmp_path):
    engine, _root = _import(tmp_path)
    assert _headings(engine, "3")["1"] == [{"tag": "d", "text": "A Psalm of David, when he fled."}]
    assert _headings(engine, "42")["1"][1] == {"tag": "d", "text": "For the director."}
    # It is in no verse's text, so its words are not alignable target words...
    verses = call(engine, "chapter.verseData", {"chapter": "3"})["result"]
    assert "Psalm of David" not in verses["verses"]["1"]["text"]
    # ...and verse 1 still opens in the \q1 that follows the title.
    assert verses["openers"]["1"] == "q1"


def test_book_introduction_lists_the_introduction_with_a_display_for_each_line(tmp_path):
    engine, _root = _import(tmp_path)
    result = call(engine, "book.introduction")["result"]
    assert result["bookId"] == "psa"
    assert [(e["tag"], e["display"]["plain"]) for e in result["entries"]] == [
        ("is", "Introduction"),
        ("ip", "The book of Psalms is a hymn book."),
        ("iot", "Outline"),
        ("io1", "Book one 1-41"),
        ("io1", "Book two 42-72"),
    ]
    paragraph = result["entries"][1]
    assert paragraph["text"] == "The book of \\bk Psalms\\bk* is a hymn book."
    assert [(s["marker"], paragraph["display"]["plain"][s["start"]:s["end"]])
            for s in paragraph["display"]["styles"]] == [("bk", "Psalms")]
    # The header lines (\h, \toc1, \mt) and the heading before \c 1 are not in it.
    assert all(e["tag"].startswith("i") for e in result["entries"])


def test_a_book_with_no_introduction_has_none(tmp_path):
    root = tmp_path / "php"
    _write_minimal_book(root, "php", "A verse.")
    engine = BridgeEngine()
    assert call(engine, "project.open", {"path": str(root)})["success"] is True
    assert call(engine, "book.introduction")["result"]["entries"] == []


# --- editing ---------------------------------------------------------------------

def test_a_heading_is_edited_in_place_and_the_edit_is_journalled(tmp_path):
    engine, root = _import(tmp_path)
    result = call(engine, "heading.edit", {
        "chapter": "3", "verse": "3", "index": 0,
        "newText": "  The  Lord\nreplies ", "expectedOldText": "The Lord answers",
    })
    assert result["success"] is True, result
    # Whitespace is stored the way the import stores it: single spaces.
    assert result["result"]["headings"] == [{"tag": "s", "text": "The Lord replies"}, {"tag": "r", "text": "(Ps 4)"}]
    assert result["result"]["journalTransactionId"]
    assert json.loads((root / "psa" / "3.headings.json").read_text(encoding="utf-8"))["3"][0]["text"] == "The Lord replies"
    # The verse map is untouched: a heading is not a verse's text.
    assert call(engine, "verse.get", {"chapter": "3", "verse": "3"})["result"]["text"] == "But you"


def test_a_reference_line_a_major_heading_and_a_psalm_title_are_edited_the_same_way(tmp_path):
    engine, _root = _import(tmp_path)
    for chapter, verse, index, old, new in [
        ("3", "3", 1, "(Ps 4)", "(Ps 4:1-8)"),
        ("42", "1", 0, "BOOK TWO", "SECOND BOOK"),
        ("3", "1", 0, "A Psalm of David, when he fled.", "A Psalm of David, when he fled from Absalom."),
    ]:
        result = call(engine, "heading.edit", {"chapter": chapter, "verse": verse, "index": index,
                                               "newText": new, "expectedOldText": old})
        assert result["success"] is True, result
        assert result["result"]["headings"][index]["text"] == new
    assert _headings(engine, "3")["1"] == [{"tag": "d", "text": "A Psalm of David, when he fled from Absalom."}]


def test_a_heading_edit_is_refused_rather_than_guessed(tmp_path):
    engine, root = _import(tmp_path)
    before = (root / "psa" / "3.headings.json").read_bytes()
    for params, why in [
        ({"index": 0, "newText": "New", "expectedOldText": "Something else"}, "REVISION_CONFLICT"),
        ({"index": 0, "newText": "   ", "expectedOldText": "The Lord answers"}, "may not be left empty"),
        ({"index": 0, "newText": "A\\q1 B", "expectedOldText": "The Lord answers"}, "cannot hold \\q1"),
        ({"index": 0, "newText": "A \\v 4 B", "expectedOldText": "The Lord answers"}, "cannot hold \\v"),
        ({"index": 0, "newText": "A \\s B", "expectedOldText": "The Lord answers"}, "cannot hold \\s"),
        ({"index": 7, "newText": "New", "expectedOldText": ""}, "has no heading 7"),
        ({"index": 0, "newText": "The Lord answers", "expectedOldText": "The Lord answers"}, "No heading change"),
    ]:
        result = call(engine, "heading.edit", {"chapter": "3", "verse": "3", **params})
        assert result["success"] is False, params
        assert why in result["error"]["message"], (params, result)
    assert (root / "psa" / "3.headings.json").read_bytes() == before


def test_an_inline_marker_in_a_heading_is_kept_and_an_unbalanced_one_is_reported(tmp_path):
    engine, _root = _import(tmp_path)
    kept = call(engine, "heading.edit", {"chapter": "3", "verse": "3", "index": 0,
                                         "newText": "The \\nd Lord\\nd* answers", "expectedOldText": "The Lord answers"})
    assert kept["success"] is True and kept["result"]["warnings"] == []
    unbalanced = call(engine, "heading.edit", {"chapter": "3", "verse": "3", "index": 0,
                                               "newText": "The \\nd Lord answers", "expectedOldText": "The \\nd Lord\\nd* answers"})
    assert unbalanced["success"] is True
    assert unbalanced["result"]["warnings"] == ["Unbalanced \\nd: 1 open, 0 close"]


def test_an_introduction_line_is_edited_and_only_an_introduction_line(tmp_path):
    engine, root = _import(tmp_path)
    entries = call(engine, "book.introduction")["result"]["entries"]
    paragraph = entries[1]
    result = call(engine, "book.introduction.edit", {
        "index": paragraph["index"], "newText": "The book of \\bk Psalms\\bk* is Israel's hymn book.",
        "expectedOldText": paragraph["text"],
    })
    assert result["success"] is True, result
    entry = result["result"]["entry"]
    assert entry["index"] == paragraph["index"] and entry["tag"] == "ip"
    assert entry["display"]["plain"] == "The book of Psalms is Israel's hymn book."
    assert result["result"]["journalTransactionId"]
    stored = json.loads((root / "psa" / "headers.json").read_text(encoding="utf-8"))
    assert stored[paragraph["index"]] == {"tag": "ip", "content": "The book of \\bk Psalms\\bk* is Israel's hymn book."}
    # Every other line is exactly as it was.
    assert [line["content"] for line in stored if line["tag"] == "io1"] == ["Book one \\ior 1-41\\ior*", "Book two \\ior 42-72\\ior*"]
    assert call(engine, "book.introduction")["result"]["entries"][1]["text"] == entry["text"]

    title_index = next(index for index, line in enumerate(stored) if line["tag"] == "mt")
    for params, why in [
        ({"index": title_index, "newText": "Songs", "expectedOldText": "Psalms"}, "not part of the book's introduction"),
        ({"index": 99, "newText": "x", "expectedOldText": ""}, "not part of the book's introduction"),
        ({"index": paragraph["index"], "newText": "x", "expectedOldText": "stale"}, "REVISION_CONFLICT"),
        ({"index": paragraph["index"], "newText": "a \\ip b", "expectedOldText": entry["text"]}, "cannot hold \\ip"),
        ({"index": paragraph["index"], "newText": " ", "expectedOldText": entry["text"]}, "may not be left empty"),
    ]:
        refused = call(engine, "book.introduction.edit", params)
        assert refused["success"] is False and why in refused["error"]["message"], (params, refused)
    assert json.loads((root / "psa" / "headers.json").read_text(encoding="utf-8")) == stored


def test_a_project_with_no_headers_file_reads_its_introduction_from_the_source_and_can_edit_it(tmp_path):
    engine, root = _import(tmp_path)
    (root / "psa" / "headers.json").unlink()
    entries = call(engine, "book.introduction")["result"]["entries"]
    assert [e["tag"] for e in entries] == ["is", "ip", "iot", "io1", "io1"]
    heading = entries[0]
    result = call(engine, "book.introduction.edit", {"index": heading["index"], "newText": "About this book",
                                                     "expectedOldText": "Introduction"})
    assert result["success"] is True, result
    stored = json.loads((root / "psa" / "headers.json").read_text(encoding="utf-8"))
    assert stored[heading["index"]] == {"tag": "is", "content": "About this book"}
    assert [line["tag"] for line in stored][:4] == ["id", "h", "toc1", "mt"]


# --- export ----------------------------------------------------------------------

def test_an_untouched_book_exports_its_source_byte_for_byte(tmp_path):
    engine, _root = _import(tmp_path)
    assert _exported(engine, tmp_path) == PSALMS


def test_export_writes_each_edit_in_its_own_place_and_nothing_else_moves(tmp_path):
    engine, _root = _import(tmp_path)
    intro = call(engine, "book.introduction")["result"]["entries"]
    edits = [
        ("heading.edit", {"chapter": "3", "verse": "3", "index": 0, "newText": "The Lord replies",
                          "expectedOldText": "The Lord answers"}),
        ("heading.edit", {"chapter": "3", "verse": "3", "index": 1, "newText": "(Ps 4:1-8)", "expectedOldText": "(Ps 4)"}),
        ("heading.edit", {"chapter": "42", "verse": "1", "index": 0, "newText": "SECOND BOOK", "expectedOldText": "BOOK TWO"}),
        ("heading.edit", {"chapter": "1", "verse": "1", "index": 0, "newText": "FIRST BOOK", "expectedOldText": "BOOK ONE"}),
        ("heading.edit", {"chapter": "3", "verse": "1", "index": 0, "newText": "A Psalm of David.",
                          "expectedOldText": "A Psalm of David, when he fled."}),
        ("book.introduction.edit", {"index": intro[0]["index"], "newText": "About this book", "expectedOldText": "Introduction"}),
        ("book.introduction.edit", {"index": intro[4]["index"], "newText": "Book two \\ior 42-72\\ior* and on",
                                    "expectedOldText": intro[4]["text"]}),
        ("verse.edit", {"chapter": "3", "verse": "2", "newText": "Many are saying"}),
    ]
    for method, params in edits:
        assert call(engine, method, params)["success"] is True, (method, params)

    expected = (
        PSALMS
        .replace("\\s The Lord answers\n", "\\s The Lord replies\n")
        .replace("\\r (Ps 4)\n", "\\r (Ps 4:1-8)\n")
        .replace("\\ms BOOK TWO\n", "\\ms SECOND BOOK\n")
        .replace("\\ms BOOK ONE\n", "\\ms FIRST BOOK\n")
        .replace("\\d A Psalm of David, when he fled.\n", "\\d A Psalm of David.\n")
        .replace("\\is Introduction\n", "\\is About this book\n")
        .replace("\\io1 Book two \\ior 42-72\\ior*\n", "\\io1 Book two \\ior 42-72\\ior* and on\n")
        .replace("\\v 2 Many say\n", "\\v 2 Many are saying\n")
    )
    assert _exported(engine, tmp_path) == expected


def test_export_leaves_a_verse_alone_when_its_headings_do_not_line_up_with_the_source(tmp_path):
    """A project imported before #507 filed `\\ms BOOK TWO` under Psalm 3's
    last verse. Its headings cannot be matched to the source by order, so they
    are exported as the source has them, not guessed."""
    engine, root = _import(tmp_path)
    old_filing = json.loads((root / "psa" / "3.headings.json").read_text(encoding="utf-8"))
    old_filing["3"].append({"tag": "ms", "text": "BOOK TWO (edited)"})
    (root / "psa" / "3.headings.json").write_text(json.dumps(old_filing), encoding="utf-8")
    later = json.loads((root / "psa" / "42.headings.json").read_text(encoding="utf-8"))
    later["1"] = [later["1"][1]]
    (root / "psa" / "42.headings.json").write_text(json.dumps(later), encoding="utf-8")
    reopened = BridgeEngine()
    assert call(reopened, "project.open", {"path": str(root)})["success"] is True
    assert _exported(reopened, tmp_path) == PSALMS
