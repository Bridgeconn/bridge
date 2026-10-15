"""Words of Jesus (framework item 29, #248): \\wj boundaries and \\wj where
Jesus does not speak. The three shapes the 2026-10-13 review confirmed."""
from __future__ import annotations

from tc_ai_bridge.language_qa import scan_text


def wj(text: str, book: str = "mrk", chapter: str = "2") -> list[tuple[str, str, str]]:
    return [(f["rule"], f["originalText"], f["suggestions"][0]["text"])
            for f in scan_text(text, book=book, chapter=chapter, verse="14")["findings"]
            if f["rule"].startswith("wj.")]


def apply(text: str, book: str = "mrk", chapter: str = "2") -> str:
    for f in sorted((f for f in scan_text(text, book=book, chapter=chapter, verse="1")["findings"]
                     if f["rule"].startswith("wj.")), key=lambda f: -f["start"]):
        text = text[:f["start"]] + f["suggestions"][0]["text"] + text[f["end"]:]
    return text


def test_a_word_glued_after_the_close_gets_a_space():
    text = "அவனை நோக்கி: \\wj என்னைப் பின்பற்றி வா\\wj*என்றார்; அவன் எழுந்து"
    assert wj(text) == [("wj.glued", "\\wj*", "\\wj* ")]
    assert "வா\\wj* என்றார்" in apply(text)


def test_a_space_inside_the_close_moves_outside():
    text = "\\wj கிறிஸ்து பாடுபடவும் வேண்டியதில்லையா? \\wj*என்று சொல்லி"
    assert wj(text, "luk", "24") == [("wj.space-inside", " \\wj*", "\\wj* ")]
    assert "வேண்டியதில்லையா?\\wj* என்று" in apply(text, "luk", "24")


def test_well_formed_boundaries_are_fine():
    assert wj("\\wj மனந்திரும்புங்கள்\\wj* என்றார்.", "mat", "4") == []
    assert wj("என்றார்: \\wj மனந்திரும்புங்கள்.\\wj*", "mat", "4") == []


def test_wj_outside_the_speech_books_is_flagged_with_the_markers_removed():
    text = "என்றும், \\wj வேலை செய்கிறவன் தன் கூலிக்குத் தகுதியானவன் \\wj* என்றும், வேத வாக்கியம் சொல்லுகிறதே."
    [(rule, original, fix)] = wj(text, "1ti", "5")
    assert rule == "wj.outside-speech" and original.startswith("\\wj ") and original.endswith("\\wj*")
    assert apply(text, "1ti", "5") == "என்றும், வேலை செய்கிறவன் தன் கூலிக்குத் தகுதியானவன் என்றும், வேத வாக்கியம் சொல்லுகிறதே."


def test_acts_revelation_and_the_named_epistle_chapters_may_carry_wj():
    text = "என்றார்: \\wj இது உங்களுக்காகப் பிட்கப்படுகிற என் சரீரமாயிருக்கிறது\\wj*."
    for book, chapter in (("act", "20"), ("rev", "1"), ("1co", "11"), ("2co", "12"), ("jhn", "3")):
        assert wj(text, book, chapter) == [], (book, chapter)
    assert [r for r, _o, _f in wj(text, "1co", "7")] == ["wj.outside-speech"]
