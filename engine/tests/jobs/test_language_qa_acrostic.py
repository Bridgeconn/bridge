"""Psalm 119's acrostic stanzas (framework item 34, #270): each of the 22
stanzas carries its letter (\\qa). The \\qa before verse 1 is in no stored
verse string, so 21 marked stanza letters count as complete."""
from __future__ import annotations

from tc_ai_bridge.language_qa_structure import structure_findings

HEADINGS = {"119": {"1": [{"tag": "ms", "text": "சங்கீதம் 119"}]}}


def psalm(letters: int) -> dict[str, dict[str, str]]:
    verses = {str(v): "\\q1 வரி." for v in range(1, 177)}
    for stanza in range(1, letters + 1):
        last = 8 * stanza  # the \qa before verse 8k+1 ends verse 8k
        verses[str(last)] += "\n\\qa ב"
    return {"119": verses}


def acrostic(book: str, chapters, headings=HEADINGS) -> list[dict]:
    return [f for f in structure_findings(book, chapters, headings) if f["rule"] == "acrostic.stanzas"]


def test_no_stanza_letter_is_reported_once_at_verse_1():
    [finding] = acrostic("psa", psalm(0))
    assert (finding["chapter"], finding["verse"], finding["context"], finding["contextText"]) == \
        ("119", "1", "heading", "சங்கீதம் 119")
    assert "none carries its stanza letter" in finding["message"] and finding["suggestions"] == []


def test_some_letters_are_counted():
    [finding] = acrostic("psa", psalm(10))
    assert "only 10 of the 21 after the first" in finding["message"]


def test_all_stanza_letters_after_the_first_are_complete():
    assert acrostic("psa", psalm(21)) == []


def test_only_psalm_119_is_checked():
    assert acrostic("psa", {"118": psalm(0)["119"]}) == []
    assert acrostic("lam", {"119": psalm(0)["119"]}) == []
