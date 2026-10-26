"""Aligned USFM export of a book with lettered segments (#307).

A lettered segment (5a, 5b) has no original-language source tokens, because
the source has verse 5, not 5a/5b. The export used to stop at the first one and
refuse the whole book. It now writes such a verse unaligned, its words as `\\w`
words like any unaligned word, and reports it on the result."""
from __future__ import annotations

from pathlib import Path

from bridge_service import BridgeEngine
from tc_ai_bridge.project_import import import_source
from tc_ai_bridge.tc_project import TranslationCoreProject
from tests.support.projects import call

JONAH = (
    "\\id JON\n\\h Jonah\n\\c 1\n\\s1 Jonah runs\n\\p\n"
    "\\v 1 Now the word of the LORD came to Jonah.\n"
    "\\v 2 Arise, go to Nineveh.\n"
    "\\v 3-4 But Jonah rose to flee. The LORD hurled a wind.\n"
    "\\v 5a Then the mariners were afraid,\n"
    "\\v 5b and cried every man to his god.\n"
    "\\v 6 So the shipmaster came to him.\n"
)
TEXT = {
    "1": "Now the word of the LORD came to Jonah.",
    "2": "Arise, go to Nineveh.",
    "3-4": "But Jonah rose to flee. The LORD hurled a wind.",
    "5a": "Then the mariners were afraid,",
    "5b": "and cried every man to his god.",
    "6": "So the shipmaster came to him.",
}
METADATA = {
    "languageId": "eng", "languageName": "English", "languageDirection": "ltr",
    "projectName": "Jonah", "bibleName": "Test Bible",
}


def _import(source: Path, into: Path) -> Path:
    return Path(import_source(source, into, METADATA)["primaryProjectPath"])


def test_lettered_segments_are_written_unaligned_and_reported(tmp_path):
    source = tmp_path / "32-JON.usfm"
    source.write_text(JONAH, encoding="utf-8")
    root = _import(source, tmp_path / "projects")
    engine = BridgeEngine()
    assert call(engine, "project.open", {"path": str(root)})["success"]

    # The real import gives the bridge source tokens and the segments none.
    context = call(engine, "alignment.get", {"chapter": "1", "verse": "3-4"})["result"]
    assert context["topTokens"]
    for segment in ("5a", "5b"):
        assert call(engine, "alignment.get", {"chapter": "1", "verse": segment})["result"]["topTokens"] == []

    # Align one word of 1:1.
    context = call(engine, "alignment.get", {"chapter": "1", "verse": "1"})["result"]
    realigned = call(engine, "alignment.realign", {
        "chapter": "1", "verse": "1",
        "topIds": [context["topTokens"][0]["id"]], "bottomIds": [context["bottomTokens"][0]["id"]],
        "expectedOriginal": context["alignment"],
    })
    assert realigned["success"], realigned

    output = tmp_path / "jon-aligned.usfm"
    exported = call(engine, "export.aligned", {"outputPath": str(output)})

    assert exported["success"], exported
    result = exported["result"]
    assert result["written"] is True and result["format"] == "usfm3-aligned"
    assert [(v["reference"], v["reason"]) for v in result["unalignedVerses"]] == [
        ("1:5a", "no-source-tokens"), ("1:5b", "no-source-tokens"),
    ]
    assert all("source tokens" in v["detail"] for v in result["unalignedVerses"])

    content = output.read_text(encoding="utf-8")
    assert content.count("\\zaln-s") == 1 and content.count("\\zaln-e\\*") == 1
    assert "\\v 3-4 " in content and "\\s1 Jonah runs" in content
    line_5a = next(line for line in content.splitlines() if line.startswith("\\v 5a "))
    assert line_5a == (
        '\\v 5a \\w Then|x-occurrence="1" x-occurrences="1"\\w* '
        '\\w the|x-occurrence="1" x-occurrences="1"\\w* '
        '\\w mariners|x-occurrence="1" x-occurrences="1"\\w* '
        '\\w were|x-occurrence="1" x-occurrences="1"\\w* '
        '\\w afraid|x-occurrence="1" x-occurrences="1"\\w*,'
    )

    # Re-imported, every verse's text is intact and 1:1 keeps its alignment.
    reimported = TranslationCoreProject(_import(output, tmp_path / "reimported"))
    assert {verse: reimported.target_verse_text("1", verse) for verse in TEXT} == TEXT
    round_trip = reimported.load_verse_alignment("1", "1")
    assert len(round_trip.alignments) == 1
    assert [w.word for w in round_trip.alignments[0].bottom_words] == ["Now"]
    assert reimported.load_verse_alignment("1", "5a").alignments == []


def test_a_book_with_no_segments_reports_none(tmp_path):
    source = tmp_path / "32-JON.usfm"
    source.write_text(JONAH.replace("\\v 5a ", "\\v 5 ").replace("\\v 5b ", ""), encoding="utf-8")
    engine = BridgeEngine()
    assert call(engine, "project.open", {"path": str(_import(source, tmp_path / "projects"))})["success"]

    exported = call(engine, "export.aligned", {"outputPath": str(tmp_path / "jon-aligned.usfm")})

    assert exported["success"], exported
    assert exported["result"]["unalignedVerses"] == []
