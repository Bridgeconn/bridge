"""Framework item 41 (hyphenation), as far as the text can show it: a soft
hyphen (U+00AD) typed into a word is reported by unicode.invisible, so a
hyphenation choice never hides in the text. The hyphenation policy itself is
the typesetter's, proofed on the PDF."""
from __future__ import annotations

from tc_ai_bridge.language_qa import scan_text


def invisible(text: str) -> list[str]:
    return [f["originalText"] for f in scan_text(text, book="gen", chapter="1", verse="1")["findings"]
            if f["rule"] == "unicode.invisible"]


def test_a_soft_hyphen_inside_a_word_is_reported():
    assert invisible("ஆதியிலே தேவன் வானத்­தையும் பூமியையும் படைத்தார்.") == ["­"]


def test_a_visible_hyphen_is_not_an_invisible_character():
    assert invisible("யூத–கிறிஸ்தவச் சூழல்; கி.மு.-கி.பி.") == []
