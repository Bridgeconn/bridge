"""Book header and introduction (framework item 47, #253): the title and contents
markers, and the introduction outline's \\ior spans."""
from __future__ import annotations

from tc_ai_bridge.language_qa_header import header_findings
from tc_ai_bridge.language_qa_jobs import LanguageQaManager
from tests.support.language_qa import project_at, wait

HEADER = ("\\id MAT\n\\h மத்தேயு\n\\toc1 மத்தேயு எழுதின நற்செய்தி\n\\toc2 மத்தேயு\n\\toc3 மத்\n\\mt மத்தேயு\n"
          "\\is பொருளடக்கம்\n\\io1 \\ior மத் 1\\ior* ராஜா அறிமுகப்படுத்தப்படுதல்\n{extra}\\c 1\n\\p\n\\v 1 வசனம்.\n")
NAMES = {"மத்": "MAT", "மத்தேயு": "MAT"}
VERSES = {"1": ["1", "2"], "2": ["1"]}


def rules(found):
    return [(f["rule"], f["originalText"]) for f in found]


def test_a_complete_header_and_outline_is_clean():
    assert header_findings("mat", HEADER.format(extra=""), VERSES, NAMES) == []


def test_a_space_inside_ior_is_flagged_in_the_introduction():
    found = header_findings("mat", HEADER.format(extra="\\io1 \\ior மத் 8 \\ior* அதிசயங்கள்\n"), VERSES, NAMES)
    assert rules(found) == [("intro.ior-space", "மத் 8 ")]
    finding = found[0]
    assert (finding["context"], finding["chapter"], finding["verse"]) == ("introduction", "1", "1")
    assert finding["contextText"][finding["start"]:finding["end"]] == "மத் 8 "
    assert finding["suggestions"] == [] and '"மத் 8"' in finding["message"]


def test_an_outline_reference_to_a_chapter_that_does_not_exist():
    found = header_findings("mat", HEADER.format(extra="\\io1 \\ior மத் 29\\ior* முடிவு\n"), VERSES, NAMES)
    assert rules(found) == [("intro.ior-target", "மத் 29")]


def test_a_missing_title_or_contents_marker():
    text = HEADER.format(extra="").replace("\\toc3 மத்\n", "").replace("\\mt மத்தேயு\n", "\\mt \n")
    assert rules(header_findings("mat", text, VERSES, NAMES)) == [("header.missing", ""), ("header.missing", "")]
    assert [f["message"] for f in header_findings("mat", text, VERSES, NAMES)] == \
        ["No \\toc3 in the book header.", "No \\mt in the book header."]


def test_no_source_no_findings():
    assert header_findings("mat", None, VERSES, NAMES) == []


def test_the_pass_reads_the_preserved_source(tmp_path):
    project = project_at(tmp_path, verses={"1": "வசனம்."}, book="mat")
    (tmp_path / "mat.usfm").write_text(HEADER.format(extra="\\io1 \\ior மத் 8 \\ior* அதிசயங்கள்\n"),
                                       encoding="utf-8")
    manager = LanguageQaManager(debounce=0, yield_seconds=0)
    manager.bind(project)
    try:
        result = wait(manager)
    finally:
        manager.unbind()
    assert [(f["rule"], f["context"]) for f in result["findings"] if f["rule"].startswith(("intro.", "header."))] == \
        [("intro.ior-space", "introduction")]
    assert not [line for line in result["limitations"] if "header" in line.lower()]
