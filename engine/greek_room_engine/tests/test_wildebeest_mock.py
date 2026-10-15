"""The mock fallback raises the same check types as the real engine for the
#204/#205 cases, from the same helpers, so a build without wildebeest-nlp
(Python 3.13, or an install without the extra, which is what CI runs) still
surfaces them. Each test forces the mock path, as test_engine.py does; the
real-engine equivalents are in test_wildebeest_real.py.
"""
import unicodedata

import pytest

from greek_room_engine.adapters import wildebeest_adapter
from greek_room_engine.engine import GreekRoomEngine


@pytest.fixture(autouse=True)
def mock_path(monkeypatch):
    monkeypatch.setattr(wildebeest_adapter, "_WILDEBEEST_AVAILABLE", False)


def _check(text, lang="eng", params=None):
    return GreekRoomEngine().check_verse(
        project_id="p", lang_code=lang, ref="TIT 1:1", text=text, checks=["wildebeest"], params=params,
    )


def _of_type(findings, check_type):
    return [f for f in findings if f.check_type == check_type]


def test_mock_identifies_itself_on_every_finding():
    findings = _check("Earth was @ empty.")
    assert findings and all(
        any(e.label == "Mode" and "mock" in e.value for e in f.evidence) for f in findings
    )
    assert all(f.engine_version == "mock-0.0.0" for f in findings)


def test_mock_flags_nfd_text_once_per_form_and_suggests_nfc():
    text = unicodedata.normalize("NFD", "In the beginning, café was the test word; café again.")
    hits = _of_type(_check(text), "wildebeest.non_canonical")
    assert [f.original_text for f in hits] == [unicodedata.normalize("NFD", "é")]
    assert hits[0].suggested_replacement == unicodedata.normalize("NFC", "é")
    assert text[hits[0].start_offset:hits[0].end_offset] == hits[0].original_text
    assert _of_type(_check(unicodedata.normalize("NFC", text)), "wildebeest.non_canonical") == []


def test_mock_flags_a_lone_symbol_and_one_inside_a_token():
    text = "Earth was @ empty and dark. 50% of A&B."
    hits = _of_type(_check(text), "wildebeest.special_character")
    assert [f.original_text for f in hits] == ["@", "50%", "A&B."]
    assert all(text[f.start_offset:f.end_offset] == f.original_text for f in hits)
    assert "U+0040 COMMERCIAL AT" in hits[0].explanation


def test_mock_leaves_ordinary_punctuation_alone():
    assert _check("Day, night; dark-light. Why? 'Yes' ‘no’ — end… 3:16 1/2 (so)") == []


def test_mock_flags_a_whole_word_in_another_script():
    text = "ദൈവം called the light Day and darkness Night."
    hits = _of_type(_check(text, "eng"), "wildebeest.foreign_script")
    assert [f.original_text for f in hits] == ["ദൈവം"]
    assert (hits[0].start_offset, hits[0].end_offset) == (0, 4)
    tamil = "தேவன் called ஆதி"
    hits = _of_type(_check(tamil, "ta"), "wildebeest.foreign_script")
    assert [(f.original_text, f.start_offset, f.end_offset) for f in hits] == [("called", 6, 12)]


def test_mock_mixed_script_is_per_token_now():
    # Used to be "any Latin letter in a verse that also has Tamil": the first
    # letter of a whole English word was flagged as mixed script.
    findings = _check("தேவன் called ஆதி", "ta")
    assert [f.check_type for f in findings] == ["wildebeest.foreign_script"]
    mixed = _of_type(_check("தேவன்aஆதி ஒளி", "ta"), "wildebeest.script.mixed")
    assert [(f.original_text, f.start_offset, f.end_offset) for f in mixed] == [("தேவன்aஆதி", 0, 9)]
    # Malayalam counts too; the old regexes knew Tamil and Devanagari only.
    assert [f.original_text for f in _of_type(_check("ദൈവംcalled light", "eng"), "wildebeest.script.mixed")] == ["ദൈവംcalled"]


def test_mock_token_checks_stand_down_on_markup_without_a_lifted_verse():
    raw = "\\wj தேவன் called ஆதி\\wj* ஒளியை @."
    assert _check(raw, "ta") == []


def test_mock_token_checks_see_past_markup_with_a_lifted_verse():
    from tc_ai_bridge.usfm_verse import lift_verse

    raw = "\\wj தேவன் called ஆதி\\wj* \\f + \\ft note @ here\\f* ஒளியை @."
    findings = _check(raw, "ta", params={"lifted": lift_verse(raw)})
    assert sorted(f.check_type for f in findings) == ["wildebeest.foreign_script", "wildebeest.special_character"]
    assert all(raw[f.start_offset:f.end_offset] == f.original_text for f in findings)
    assert _of_type(findings, "wildebeest.special_character")[0].start_offset == raw.rindex("@")


def test_mock_clean_tamil_verse_has_no_findings():
    assert _check("ஆதியிலே தேவன் வானத்தையும் பூமியையும் படைத்தார்.", "ta") == []
