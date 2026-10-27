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


def _ids(context, words):
    return [next(t["id"] for t in context["bottomTokens"] if t["word"] == w) for w in words]


def test_a_discontinuous_group_round_trips_as_one_milestone_nest_per_run(tmp_path):
    """#339: 1:1 "Now the word ..." with one source token aligned to "Now" and
    "word" (positions 0 and 2). The export writes two `\\zaln-s` nests with
    identical source milestones, one around each run, the book exports whole,
    and a re-import rebuilds the one group with both target words."""
    source = tmp_path / "32-JON.usfm"
    source.write_text(JONAH, encoding="utf-8")
    root = _import(source, tmp_path / "projects")
    engine = BridgeEngine()
    assert call(engine, "project.open", {"path": str(root)})["success"]
    context = call(engine, "alignment.get", {"chapter": "1", "verse": "1"})["result"]
    top = context["topTokens"][0]
    realigned = call(engine, "alignment.realign", {
        "chapter": "1", "verse": "1", "topIds": [top["id"]], "bottomIds": _ids(context, ["Now", "word"]),
        "expectedOriginal": context["alignment"],
    })
    assert realigned["success"], realigned
    assert not any("non-adjacent" in issue for issue in realigned["result"]["issues"])

    output = tmp_path / "jon-aligned.usfm"
    exported = call(engine, "export.aligned", {"outputPath": str(output)})
    assert exported["success"], exported
    result = exported["result"]
    assert result["written"] is True
    # Only the lettered segments are reported; the discontinuous verse is not.
    assert [v["reference"] for v in result["unalignedVerses"]] == ["1:5a", "1:5b"]

    content = output.read_text(encoding="utf-8")
    line = next(l for l in content.splitlines() if l.startswith("\\v 1 "))
    starts = [m for m in line.split("\\zaln-s ")[1:]]
    assert len(starts) == 2 and line.count("\\zaln-e\\*") == 2
    first_attrs, second_attrs = (part.split("\\*", 1)[0] for part in starts)
    assert first_attrs == second_attrs and f'x-content="{top["word"]}"' in first_attrs
    assert line.index('\\w Now|') < line.index('\\w the|') < line.index('\\w word|')
    assert '\\w the|x-occurrence="1" x-occurrences="2"\\w*' in line  # "the" between the runs is unaligned

    reimported = TranslationCoreProject(_import(output, tmp_path / "reimported"))
    assert reimported.target_verse_text("1", "1") == TEXT["1"]
    round_trip = reimported.load_verse_alignment("1", "1")
    [group] = [g for g in round_trip.alignments if g.bottom_words]
    assert [t.word for t in group.top_words] == [top["word"]]
    assert [w.word for w in group.bottom_words] == ["Now", "word"]


def test_a_verse_whose_alignment_cannot_be_serialized_is_written_unaligned_and_reported(tmp_path):
    """#339 point 3: one verse never blocks the book. Alignment data naming a
    target word the verse no longer has (planted on disk, as a hand edit or an
    older build could leave it) is written without alignment and reported by
    reference; every other verse exports as usual."""
    import json
    source = tmp_path / "32-JON.usfm"
    source.write_text(JONAH, encoding="utf-8")
    root = _import(source, tmp_path / "projects")
    chapter_path = root / ".apps" / "translationCore" / "alignmentData" / "jon" / "1.json"
    chapter = json.loads(chapter_path.read_text(encoding="utf-8"))
    verse2 = chapter["2"]
    bank = verse2["wordBank"]
    stale = next(t for t in bank if t["word"].startswith("Nineveh"))
    stale["word"] = "Ninevah"  # not in the text any more
    verse2["alignments"][0]["bottomWords"] = [stale]
    verse2["wordBank"] = [t for t in bank if t is not stale]
    chapter_path.write_text(json.dumps(chapter, ensure_ascii=False), encoding="utf-8")

    engine = BridgeEngine()
    assert call(engine, "project.open", {"path": str(root)})["success"]
    context = call(engine, "alignment.get", {"chapter": "1", "verse": "1"})["result"]
    realigned = call(engine, "alignment.realign", {
        "chapter": "1", "verse": "1", "topIds": [context["topTokens"][0]["id"]],
        "bottomIds": _ids(context, ["Now"]), "expectedOriginal": context["alignment"],
    })
    assert realigned["success"], realigned

    output = tmp_path / "jon-aligned.usfm"
    exported = call(engine, "export.aligned", {"outputPath": str(output)})
    assert exported["success"], exported
    result = exported["result"]
    assert result["written"] is True and output.exists()
    reported = {v["reference"]: v for v in result["unalignedVerses"]}
    assert set(reported) == {"1:2", "1:5a", "1:5b"}
    assert reported["1:2"]["reason"] == "alignment-not-serializable"
    assert "do not exactly match" in reported["1:2"]["detail"]
    content = output.read_text(encoding="utf-8")
    line_2 = next(l for l in content.splitlines() if l.startswith("\\v 2 "))
    assert "\\zaln-s" not in line_2 and '\\w Arise|x-occurrence="1" x-occurrences="1"\\w*' in line_2
    assert content.count("\\zaln-s") == 1  # 1:1's one group
