"""footnote.missing-ft (framework item 27, #245): footnote text with no \\ft
after the \\fr reference, and the fix that inserts it (human review
2026-10-13: EZR 4:7, MAT 22:44, LUK 11:50, 3 of 3)."""
from __future__ import annotations

from tc_ai_bridge.language_qa import scan_text

MAT_22_44 = ("தாவீதின் வார்த்தை\\f + \\fr 22:44 \\xt சங் 110:1\\xt* இங்கே கர்த்தர் என்பது யெகோவாவைக் "
             "குறிக்கும்.\\f* என்று சொன்னார்.")


def notes(text: str) -> list[dict]:
    return [f for f in scan_text(text, book="mat", chapter="22", verse="44")["findings"]
            if f["rule"] == "footnote.missing-ft"]


def test_text_after_a_cross_reference_with_no_ft_is_flagged_with_the_fix():
    [finding] = notes(MAT_22_44)
    assert finding["originalText"] == MAT_22_44[finding["start"]:finding["end"]]
    assert finding["originalText"].startswith("\\f + \\fr 22:44 \\xt") and finding["originalText"].endswith("\\f*")
    assert finding["suggestions"][0]["text"].startswith("\\f + \\fr 22:44 \\ft \\xt சங் 110:1\\xt*")
    assert (finding["context"], finding["category"], finding["ruleId"]) == ("footnote", "usfm", "common/footnote.missing-ft")
    assert finding["inline"] is False


def test_applying_the_fix_changes_only_the_note():
    [finding] = notes(MAT_22_44)
    fixed = MAT_22_44[:finding["start"]] + finding["suggestions"][0]["text"] + MAT_22_44[finding["end"]:]
    assert fixed == MAT_22_44.replace("\\fr 22:44 \\xt", "\\fr 22:44 \\ft \\xt")
    assert notes(fixed) == []


def test_a_note_with_ft_or_another_paragraph_marker_is_fine():
    assert notes("வசனம்\\f + \\fr 1:1 \\ft சில பிரதிகளில்\\f* முடிவு.") == []
    assert notes("வசனம்\\f + \\fr 1:1 \\fq மேற்கோள் \\fqa வேறு\\f* முடிவு.") == []


def test_a_reference_alone_is_not_text_to_mark():
    assert notes("வசனம்\\f + \\fr 1:1 \\f* முடிவு.") == []


def test_without_fr_the_ft_goes_after_the_caller():
    [finding] = notes("வசனம்\\f + சில பிரதிகளில்\\f* முடிவு.")
    assert finding["suggestions"][0]["text"] == "\\f + \\ft சில பிரதிகளில்\\f*"
