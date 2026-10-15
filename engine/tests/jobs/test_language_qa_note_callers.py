"""Note composition (framework item 44, #246): a caller unlike the book's
others (note.caller-mixed, book step), and a space between a word and its
note's caller (note.space-before-caller, per verse)."""
from __future__ import annotations

from tc_ai_bridge.language_qa import scan_text
from tc_ai_bridge.language_qa_jobs import LanguageQaManager
from tc_ai_bridge.language_qa_notes import caller_findings
from tests.support.language_qa import project_at, wait

XREF = "\\x {caller} \\xo 2:{v} \\xt ஆதி 1:1\\x*"


def spaces(text: str) -> list[tuple[str, str]]:
    return [(f["originalText"], f["suggestions"][0]["text"])
            for f in scan_text(text, book="gen", chapter="27", verse="36")["findings"]
            if f["rule"] == "note.space-before-caller"]


def test_the_minority_caller_in_a_book_is_flagged_with_the_usual_one():
    chapters = {"2": {str(v): XREF.format(caller="+", v=v) + "வசனம்." for v in range(1, 5)}}
    chapters["2"]["5"] = XREF.format(caller="-", v=5) + "வசனம்."
    [finding] = caller_findings("rut", chapters)
    assert (finding["verse"], finding["originalText"], finding["suggestions"][0]["text"]) == ("5", "\\x -", "\\x +")
    assert (finding["start"], finding["end"]) == (0, 4) and finding["ruleId"] == "common/note.caller-mixed"
    assert '"+" (4)' in finding["message"]


def test_footnotes_and_cross_references_are_counted_apart():
    chapters = {"1": {"1": "சொல்\\f - \\fr 1:1 \\ft குறிப்பு\\f*. " + XREF.format(caller="+", v=1)}}
    assert caller_findings("rut", chapters) == []


def test_a_space_before_a_mid_verse_footnote_is_flagged_with_a_remove_fix():
    text = "அவனுடைய பெயர் யாக்கோபு \\f + \\fr 27:36 \\ft பிடித்துக்கொள்பவன்\\f* என்பது சரிதான்."
    assert spaces(text) == [(" ", "")]


def test_a_markers_own_space_and_the_verse_end_are_not_flagged():
    assert spaces("\\q1 \\x + \\xo 9:33 \\xt ஏசா 28:16\\x*இதோ, சீயோனில்") == []
    assert spaces("\\wj \\x + \\xo 6:9 \\xt லூக் 11:2\\x*நீங்கள் ஜெபம்பண்ண") == []
    # at the verse end the space is spacing.extra's (ACT 12:25)
    assert spaces("திரும்பி வந்தார்கள். \\f + \\fr 12:25 \\ft சில பிரதிகளில்\\f*") == []


def test_the_pass_reports_the_book_level_caller_finding(tmp_path):
    verses = {str(v): XREF.format(caller="+", v=v) + "வசனம்." for v in range(1, 4)}
    verses["4"] = XREF.format(caller="-", v=4) + "வசனம்."
    project = project_at(tmp_path, verses=verses, book="rut")
    manager = LanguageQaManager(debounce=0, yield_seconds=0)
    manager.bind(project)
    try:
        result = wait(manager)
    finally:
        manager.unbind()
    found = [(f["verse"], f["originalText"]) for f in result["findings"] if f["rule"] == "note.caller-mixed"]
    assert found == [("4", "\\x -")]
