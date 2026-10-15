"""Paired punctuation (framework item 9, #264): brackets pair inside a verse,
curly quotation marks inside a chapter (a quotation may run over verses)."""
from __future__ import annotations

from tc_ai_bridge.language_qa import scan_text
from tc_ai_bridge.language_qa_structure import structure_findings


def brackets(text: str) -> list[str]:
    return [f["originalText"] for f in scan_text(text, book="mrk", chapter="7", verse="11")["findings"]
            if f["rule"] == "punctuation.unbalanced-pair"]


def quotes(chapter: dict[str, str]) -> list[tuple[str, str]]:
    return [(f["verse"], f["originalText"]) for f in structure_findings("jhn", {"1": chapter}, {})
            if f["rule"] == "punctuation.unbalanced-quote"]


def test_brackets_that_pair_are_fine():
    assert brackets("அது கொர்பான் (அதாவது, காணிக்கை) என்று சொன்னால் [சில பிரதிகளில்].") == []


def test_an_unclosed_or_stray_bracket_is_reported():
    assert brackets("அது கொர்பான் (அதாவது, காணிக்கை என்று சொன்னால்.") == ["("]
    assert brackets("அது கொர்பான் அதாவது, காணிக்கை) என்று சொன்னால்.") == [")"]
    assert brackets("அது (கொர்பான்] என்று.") == ["]", "("]


def test_a_bracket_inside_a_footnote_is_not_the_verse_text():
    assert brackets("அது கொர்பான்\\f + \\fr 7:11 \\ft (எபிரெய சொல்\\f* என்று சொன்னால்.") == []


def test_a_quotation_running_over_verses_pairs_in_its_chapter():
    assert quotes({"1": "இயேசு சொன்னார்: “வாருங்கள்,", "2": "என்னைப் பின்பற்றுங்கள்.”"}) == []


def test_an_unclosed_quotation_is_reported_in_its_verse():
    assert quotes({"1": "இயேசு சொன்னார்: “வாருங்கள்.", "2": "அவர்கள் வந்தார்கள்."}) == [("1", "“")]
    assert quotes({"1": "இயேசு சொன்னார்: வாருங்கள்.”"}) == [("1", "”")]
