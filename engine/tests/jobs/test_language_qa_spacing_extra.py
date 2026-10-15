"""spacing.extra revision 2 (#230, DECISIONS 2026-10-13): every finding offers
its fix. Repeated spaces inside a verse become one; a space at the start or end
of the verse is removed. A verse-final space is still flagged (rounds
2026-09-28 and 2026-09-29: 18 of 18 confirmed), including before a closing
\\qs* and before a poetry line break, which stays."""
from __future__ import annotations

from tc_ai_bridge.language_qa import RULES, scan_text


def fixes(text: str) -> list[tuple[str, str]]:
    return [(f["originalText"], f["suggestions"][0]["text"])
            for f in scan_text(text, book="psa", chapter="84", verse="8")["findings"] if f["rule"] == "spacing.extra"]


def test_repeated_spaces_inside_a_verse_become_one():
    assert fixes("இருபத்து  நான்கு விரல்கள்") == [("  ", " ")]


def test_a_verse_final_space_is_flagged_with_a_remove_fix():
    assert fixes("யோசனை செய்வது என்ன? ") == [(" ", "")]
    assert fixes("\\wj யோசனை செய்வது என்ன? \\wj*") == [(" ", "")]


def test_a_space_before_a_closing_selah_and_a_line_break_is_removed_not_the_break():
    text = "செவிகொடும். \\qs (சேலா) \\qs*\n\\q"
    finding = next(f for f in scan_text(text, book="psa", chapter="84", verse="8")["findings"]
                   if f["rule"] == "spacing.extra")
    fixed = text[:finding["start"]] + finding["suggestions"][0]["text"] + text[finding["end"]:]
    assert fixed == "செவிகொடும். \\qs (சேலா)\\qs*\n\\q"


def test_a_leading_space_is_removed_and_a_space_before_a_note_too():
    assert fixes(" ஆதியிலே தேவன்") == [(" ", "")]
    assert fixes("திரும்பி வந்தார்கள். \\f + \\fr 12:25 \\ft சில பிரதிகளில்\\f*") == [(" ", "")]


def test_the_rule_revision_moved_so_earlier_ignores_expire():
    assert RULES["spacing.extra"].revision == 2
