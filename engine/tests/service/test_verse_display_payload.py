"""The `display` payload (#91 Phase 2a): every RPC that hands the frontend a
verse's text also hands it what the reader shows -- plain text, notes, style
spans and the removed raw ranges, in code points -- so the frontend never
parses USFM. Drives the RPCs, so it lives here."""
from __future__ import annotations

from bridge_service import BridgeEngine
from tc_ai_bridge.project_import import import_source
from tests.support.projects import _write_minimal_book, call

PHP_1_6 = (
    "\\it இந்த\\it* நற்கிரியையை\\f + \\fr 1.6 \\fq நற்கிரியை \\ft தேவன் தொடங்கினார்.\\f* "
    "முடிப்பார் என்று \\nd கர்த்தர்\\nd* நம்புகிறேன்."
)


def _open(tmp_path, text):
    root = tmp_path / "php"
    _write_minimal_book(root, "php", text)
    engine = BridgeEngine()
    assert call(engine, "project.open", {"path": str(root)})["success"] is True
    return engine


def _check_display(display, raw):
    assert display["plain"] == "இந்த நற்கிரியையை முடிப்பார் என்று கர்த்தர் நம்புகிறேன்."
    [note] = display["notes"]
    assert note["kind"] == "footnote" and note["reference"] == "1.6"
    assert note["text"] == "நற்கிரியை தேவன் தொடங்கினார்."
    assert note["position"] == len("இந்த நற்கிரியையை")
    assert [s["marker"] for s in display["styles"]] == ["it", "nd"]
    it, nd = display["styles"]
    assert display["plain"][it["start"]:it["end"]] == "இந்த"
    assert display["plain"][nd["start"]:nd["end"]] == "கர்த்தர்"
    # Removed ranges cover exactly the markup: rebuilding plain from them works.
    kept = "".join(ch for i, ch in enumerate(raw) if not any(a <= i < b for a, b in display["removed"]))
    assert kept == display["plain"]
    assert display["warnings"] == []


def test_chapter_verse_data_carries_display_for_every_verse(tmp_path):
    engine = _open(tmp_path, PHP_1_6)
    result = call(engine, "chapter.verseData", {"chapter": "1"})["result"]
    row = result["verses"]["1"]
    assert row["text"] == PHP_1_6  # the raw string stays: the editor edits it
    _check_display(row["display"], PHP_1_6)


def test_verse_get_carries_the_same_display(tmp_path):
    engine = _open(tmp_path, PHP_1_6)
    result = call(engine, "verse.get", {"chapter": "1", "verse": "1"})["result"]
    _check_display(result["display"], PHP_1_6)


def test_verse_edit_returns_the_display_of_the_saved_text(tmp_path):
    engine = _open(tmp_path, "Old \\nd Lord\\nd* text.")
    new_text = "New \\f + \\ft note\\f* text with \\wj words\\wj*."
    result = call(engine, "verse.edit", {"chapter": "1", "verse": "1", "newText": new_text})
    assert result["success"] is True
    display = result["result"]["display"]
    assert display["plain"] == "New text with words."
    assert [n["text"] for n in display["notes"]] == ["note"]
    assert [s["marker"] for s in display["styles"]] == ["wj"]
    # And a later read agrees with what the edit returned.
    again = call(engine, "verse.get", {"chapter": "1", "verse": "1"})["result"]
    assert again["display"] == display


def test_a_verse_without_markup_has_an_identity_display(tmp_path):
    raw = "ஆதியிலே தேவன் வானத்தையும் பூமியையும் படைத்தார்."
    engine = _open(tmp_path, raw)
    display = call(engine, "verse.get", {"chapter": "1", "verse": "1"})["result"]["display"]
    assert display == {"plain": raw, "notes": [], "removed": [], "styles": [], "warnings": [], "paras": []}


# --- paragraph and poetry lines (#507) ----------------------------------------

POETRY_USFM = (
    "\\id PSA\n\\h Psalms\n\\mt Psalms\n"
    "\\c 3\n\\d A Psalm of David\n\\q1\n\\v 1 Lord, how\n\\q2 many are they \\qs Selah\\qs*\n\\q1\n"
    "\\v 2 Many say\n\\s The Lord answers\n\\q1\n\\v 3 But you\n\\q2 are a shield\n\\s Prose now\n\\p\n"
    "\\v 4 I lay down \\k and slept\\k*.\n"
)


def _import_poetry(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "PSA.usfm").write_text(POETRY_USFM, encoding="utf-8")
    destination = tmp_path / "projects"
    destination.mkdir()
    imported = import_source(source, destination, {
        "languageId": "eng", "languageName": "English", "languageDirection": "ltr",
        "projectName": "Psalms review", "bibleName": "Test Bible",
    })
    engine = BridgeEngine()
    assert call(engine, "project.open", {"path": imported["primaryProjectPath"]})["success"] is True
    return engine


def test_display_lists_the_paragraph_markers_inside_a_verse(tmp_path):
    engine = _import_poetry(tmp_path)
    verses = call(engine, "chapter.verseData", {"chapter": "3"})["result"]["verses"]
    display = verses["1"]["display"]
    assert display["plain"] == "Lord, how\nmany are they Selah\n"
    # Each line starts where its marker's content starts; the trailing \q1 is
    # the paragraph verse 2 opens in.
    assert display["paras"] == [
        {"marker": "q2", "position": len("Lord, how\n")},
        {"marker": "q1", "position": len(display["plain"])},
    ]
    assert [(s["marker"], display["plain"][s["start"]:s["end"]]) for s in display["styles"]] == [("qs", "Selah")]
    assert [(s["marker"], verses["4"]["display"]["plain"][s["start"]:s["end"]])
            for s in verses["4"]["display"]["styles"]] == [("k", "and slept")]
    assert verses["4"]["display"]["paras"] == []


def test_chapter_verse_data_says_which_paragraph_a_verse_opens_in(tmp_path):
    """The marker before a chapter's first verse and the one after a section
    heading are in no stored verse string; they come from the preserved source."""
    engine = _import_poetry(tmp_path)
    result = call(engine, "chapter.verseData", {"chapter": "3"})["result"]
    assert sorted(result["headings"]) == ["3", "4"]
    # Verse 2 is not here: the \q1 it opens in is the last marker of verse 1's
    # own text, which the reader carries forward.
    assert result["openers"] == {"1": "q1", "3": "q1", "4": "p"}


def test_verse_markup_edits_the_editor_string_and_writes_nothing(tmp_path):
    """verse.markup (#507) works on the string the editor holds: it needs no
    open project, and with one open it leaves the stored verse alone."""
    raw = "Lord, how\n\\q2 many are they Selah"
    start = raw.index("Selah")
    closed = call(BridgeEngine(), "verse.markup",
                  {"text": raw, "action": "style", "marker": "qs", "start": start, "end": len(raw)})
    assert closed["success"] is True
    assert closed["result"] == {
        "text": "Lord, how\n\\q2 many are they \\qs Selah\\qs*",
        "start": start + len("\\qs "), "end": start + len("\\qs Selah"), "changed": True, "reason": "",
    }

    engine = _open(tmp_path, raw)
    for params, expected in [
        ({"action": "level", "marker": "q1", "start": raw.index("many")}, "Lord, how\n\\q1 many are they Selah"),
        ({"action": "break", "start": raw.index(" are"), "opening": "q1"}, "Lord, how\n\\q2 many\n\\q2 are they Selah"),
        ({"action": "join", "start": raw.index("many")}, "Lord, how many are they Selah"),
    ]:
        result = call(engine, "verse.markup", {"text": raw, **params})["result"]
        assert result["changed"] is True and result["text"] == expected
    refused = call(engine, "verse.markup", {"text": raw, "action": "level", "marker": "q2", "start": 2})["result"]
    assert refused["changed"] is False and refused["text"] == raw and "verse before it" in refused["reason"]
    assert call(engine, "verse.get", {"chapter": "1", "verse": "1"})["result"]["text"] == raw
    assert call(engine, "verse.markup", {"action": "join", "start": 0})["success"] is False


def test_openers_are_empty_without_a_preserved_source(tmp_path):
    engine = _open(tmp_path, "Lord, how\n\\q2 many are they")
    result = call(engine, "chapter.verseData", {"chapter": "1"})["result"]
    assert result["openers"] == {}
    assert result["verses"]["1"]["display"]["paras"] == [{"marker": "q2", "position": len("Lord, how\n")}]
