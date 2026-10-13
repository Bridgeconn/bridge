"""Poetry indentation (framework item 33, #265): an indented line with no first
level line before it in its stanza. MAT 4:6 in the IRV quotes Psalm 91 as
\\m, \\q2, \\q1, \\q2."""
from __future__ import annotations

from tc_ai_bridge.language_qa_structure import structure_findings


def poetry(chapters: dict[str, dict[str, str]], headings=None) -> list[tuple[str, str, str]]:
    return [(f["chapter"], f["verse"], f["originalText"]) for f in structure_findings("mat", chapters, headings or {})
            if f["rule"] == "poetry.q2-without-q1"]


def test_a_poem_opening_at_the_second_level_is_reported():
    verse = ("நீர் தேவனுடைய குமாரன் என்றால் கீழே குதியும்;\n\\m ஏனென்றால்,\n\\q2 தம்முடைய தூதர்களுக்கு "
             "உம்மைக் குறித்துக் கட்டளையிடுவார்;\n\\q1 உமது பாதம் கல்லில் மோதாதபடி,\n\\q2 அவர்கள் உம்மைத் "
             "தங்களுடைய கைகளில் ஏந்திக் கொண்டு போவார்கள்")
    found = poetry({"4": {"6": verse}})
    assert found == [("4", "6", "\\q2")]
    [finding] = structure_findings("mat", {"4": {"6": verse}}, {})
    assert verse[finding["start"]:finding["end"]] == "\\q2" and verse.index("\\q2") == finding["start"]


def test_a_poem_opening_at_the_first_level_is_fine_across_verses():
    assert poetry({"5": {"1": "என்றார்:\n\\q1 முதல் வரி,", "2": "\\q2 இரண்டாம் வரி.\n\\q1 மூன்றாம் வரி,\n\\q2 நான்காம்."}}) == []
    assert poetry({"5": {"1": "\\q முதல் வரி,\n\\q2 இரண்டாம் வரி."}}) == []


def test_a_stanza_break_or_a_prose_paragraph_starts_a_new_stanza():
    assert poetry({"5": {"1": "\\q1 முதல் வரி,\n\\b\n\\q2 இரண்டாம் வரி."}}) == [("5", "1", "\\q2")]
    assert poetry({"5": {"1": "\\q1 முதல் வரி,\n\\p உரைநடை.", "2": "\\q2 இரண்டாம் வரி."}}) == [("5", "2", "\\q2")]


def test_after_a_heading_or_at_a_chapter_start_the_level_is_not_known():
    # JOL 1:2: "\s heading", "\q1", "\v 2 …", "\q2 …": the \q1 is in no stored verse string
    joel = {"1": {"1": "பெத்துவேலின் மகனாகிய யோவேலுக்கு கொடுக்கப்பட்ட வசனம்:", "2": "முதியோர்களே, இதைக் "
                  "கேளுங்கள்;\n\\q2 நாட்டின் அனைத்துக் குடிமக்களே, செவி கொடுங்கள்;"}}
    assert poetry(joel, {"1": {"2": [{"tag": "s", "text": "வெட்டுக்கிளிகளின் ஆக்கிரமிப்பு"}]}}) == []
    assert poetry({"2": {"1": "சீயோனிலே எக்காளம் ஊதுங்கள்,\n\\q2 என் பரிசுத்த மலையிலே"}}) == []


def test_q_is_not_mistaken_for_the_start_of_q2():
    found = structure_findings("mat", {"5": {"1": "உரை.\n\\p உரை.\n\\q2 வரி,\n\\q வரி,\n\\q2 வரி."}}, {})
    assert [(f["originalText"], f["start"]) for f in found] == [("\\q2", len("உரை.\n\\p உரை.\n"))]
