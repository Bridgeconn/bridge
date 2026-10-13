"""Framework item 40 (line breaking), as far as the text can show it: a line
break or a space inside a Tamil grapheme cluster leaves a vowel sign or pulli
with no base, and ta-irv's tamil.dependent-sign reports it. Where the
typesetter breaks lines on the page is proofed on the PDF."""
from __future__ import annotations

from tc_ai_bridge.language_packs import default_pack
from tc_ai_bridge.language_qa import scan_text


def signs(text: str) -> list[str]:
    return [f["originalText"] for f in scan_text(text, book="gen", chapter="1", verse="1", pack=default_pack("ta-irv"))
            ["findings"] if f["rule"] == "tamil.dependent-sign"]


def test_a_line_break_inside_a_cluster_is_reported():
    assert signs("ஆதியிலே தேவன் வானத்தையும் பூமியையும் படைத்த\nார்.") == ["ா"]


def test_a_space_inside_a_cluster_is_reported():
    assert signs("ஆதியிலே தேவன் படைத்த ார்.") == [" ா"]


def test_a_line_break_between_words_is_not():
    assert signs("ஆதியிலே தேவன் வானத்தையும்\nபூமியையும் படைத்தார்.") == []
