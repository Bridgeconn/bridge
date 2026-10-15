"""
Real-engine coverage for WildebeestAdapter, using the actual wildebeest-nlp
package rather than the fallback mock.

Skipped automatically wherever wildebeest-nlp isn't installed (a fresh
clone, most CI environments, or Python 3.13 — see docs/BUILD_LOG.md
for why 3.13 currently can't install it at all). The rest of the test suite
must stay green without this optional dependency; only this file requires it.
"""
import pytest

pytest.importorskip("wildebeest", reason="real wildebeest-nlp package not installed")

from greek_room_engine.engine import GreekRoomEngine


def test_real_engine_is_actually_active():
    engine = GreekRoomEngine()
    info = engine.info()
    assert info["adapters"]["wildebeest"]["usingRealEngine"] is True
    assert info["adapters"]["wildebeest"]["version"] != "mock-0.0.0"


def test_real_engine_flags_mixed_script_token():
    engine = GreekRoomEngine()
    text = "தேவன்aஆதி"
    findings = engine.check_verse(
        project_id="p", lang_code="tam", ref="TIT 1:1", text=text, checks=["wildebeest"],
    )
    hits = [f for f in findings if f.check_type == "wildebeest.notable_token"]
    assert len(hits) == 1
    assert hits[0].start_offset is not None and hits[0].end_offset is not None
    assert text[hits[0].start_offset:hits[0].end_offset] == hits[0].original_text


def test_real_engine_flags_zero_width_character():
    engine = GreekRoomEngine()
    text = "ஆதியில்​தேவன்"
    findings = engine.check_verse(
        project_id="p", lang_code="tam", ref="TIT 1:1", text=text, checks=["wildebeest"],
    )
    hits = [f for f in findings if f.check_type == "wildebeest.zero_width"]
    assert len(hits) == 1
    assert hits[0].original_text == "​"
    assert text[hits[0].start_offset:hits[0].end_offset] == "​"


def test_real_engine_flags_non_canonical_form_and_suggests_nfc():
    engine = GreekRoomEngine()
    text = "café word"  # NFD-decomposed é
    findings = engine.check_verse(
        project_id="p", lang_code="eng", ref="TIT 1:1", text=text, checks=["wildebeest"],
    )
    hits = [f for f in findings if f.check_type == "wildebeest.non_canonical"]
    assert len(hits) == 1
    assert hits[0].suggested_replacement == "é"  # precomposed é (NFC)


def test_real_engine_produces_no_findings_for_clean_text():
    engine = GreekRoomEngine()
    findings = engine.check_verse(
        project_id="p", lang_code="tam", ref="TIT 1:1",
        text="ஆதியிலே தேவன் வானத்தையும் பூமியையும் படைத்தார்", checks=["wildebeest"],
    )
    assert findings == []


def test_real_engine_failure_degrades_to_no_findings_not_a_crash(monkeypatch):
    from greek_room_engine.adapters import wildebeest_adapter

    def broken_process(*args, **kwargs):
        raise RuntimeError("simulated real-engine failure")

    monkeypatch.setattr(wildebeest_adapter.wb_ana, "process", broken_process)
    # An earlier test analysed this text; a cache hit (#230) would never reach
    # the broken process. Start from an empty cache so the failure path runs.
    monkeypatch.setattr(wildebeest_adapter, "_REPORT_CACHE", type(wildebeest_adapter._REPORT_CACHE)())

    engine = GreekRoomEngine()
    findings = engine.check_verse(
        project_id="p", lang_code="tam", ref="TIT 1:1",
        text="தேவன்aஆதி", checks=["wildebeest"],
    )
    assert findings == []


# -- #204: a lone symbol, and a whole word in another script ------------------
#
# Reproduced against wildebeest-nlp 0.9.2 before the adapter changed: `@` and
# `#` appear only under `pattern` ("TOKENS WITH @ (U+0040 COMMERCIAL AT)",
# beside "TOKENS WITH . (U+002E FULL STOP)" for `dark.`), and a standalone
# `ദൈവം` in an English verse only as a `letter-script` count. Neither was a
# finding. The adapter now scans for both itself (see its docstring).

def _check(text, lang="eng", params=None):
    return GreekRoomEngine().check_verse(
        project_id="p", lang_code=lang, ref="TIT 1:1", text=text, checks=["wildebeest"], params=params,
    )


def _of_type(findings, check_type):
    return [f for f in findings if f.check_type == check_type]


def _spans_match(text, findings):
    return all(text[f.start_offset:f.end_offset] == f.original_text for f in findings)


def test_real_engine_flags_a_lone_symbol_the_reporter_used():
    text = "Earth was @ empty and dark. Spirit of God moved over water."
    hits = _of_type(_check(text), "wildebeest.special_character")
    assert [f.original_text for f in hits] == ["@"]
    assert (hits[0].start_offset, hits[0].end_offset) == (10, 11)
    assert "U+0040 COMMERCIAL AT" in hits[0].explanation
    hash_hits = _of_type(_check("Earth was # empty and dark."), "wildebeest.special_character")
    assert [f.original_text for f in hash_hits] == ["#"]


def test_real_engine_flags_a_symbol_inside_a_token_once_per_token():
    text = "foo@bar and 50% off, A&B, under_score, a*b, x|y"
    hits = _of_type(_check(text), "wildebeest.special_character")
    assert [f.original_text for f in hits] == ["foo@bar", "50%", "A&B,", "under_score,", "a*b,", "x|y"]
    assert _spans_match(text, hits)


def test_real_engine_leaves_ordinary_punctuation_alone():
    text = "Day, night; dark-light. Why? 'Yes' ‘no’ — end… 3:16 1/2 (so)"
    assert _check(text) == []


def test_real_engine_flags_a_whole_word_in_another_script():
    text = "ദൈവം called the light Day and darkness Night. Evening and morning became first day."
    hits = _of_type(_check(text, "eng"), "wildebeest.foreign_script")
    assert [f.original_text for f in hits] == ["ദൈവം"]
    assert (hits[0].start_offset, hits[0].end_offset) == (0, 4)
    assert hits[0].explanation == "Malayalam word in Latin-script text."
    assert any("language id 'eng'" in e.value for e in hits[0].evidence)
    # The other way round, and a region suffix on the language id.
    tamil = "தேவன் ஒளியை (Light) உண்டாக்கினார்."
    hits = _of_type(_check(tamil, "ta-IN"), "wildebeest.foreign_script")
    assert [f.original_text for f in hits] == ["Light"]
    assert _spans_match(tamil, hits)


def test_real_engine_mixed_token_stays_notable_token_not_foreign_script():
    findings = _check("ദൈവംcalled the light Day.", "eng")
    assert [f.check_type for f in findings] == ["wildebeest.notable_token"]


def test_real_engine_unknown_language_id_uses_the_verse_majority_script():
    hits = _of_type(_check("ദൈവം called the light Day and darkness Night.", "xx"), "wildebeest.foreign_script")
    assert [f.original_text for f in hits] == ["ദൈവം"]
    assert any("most letters" in e.value for e in hits[0].evidence)
    # No strict majority (two Latin letters, two Malayalam; vowel signs are
    # marks, not letters), no expectation, nothing flagged.
    assert _of_type(_check("ab ദൈവ", "xx"), "wildebeest.foreign_script") == []


def test_real_engine_token_checks_stand_down_on_markup_without_a_lifted_verse():
    raw = "\\wj தேவன் called ஆதி\\wj* ஒளியை @."
    assert _check(raw, "ta") == []


def test_real_engine_token_checks_see_past_markup_with_a_lifted_verse():
    from tc_ai_bridge.usfm_verse import lift_verse  # the caller lifts, not the adapter

    raw = "\\wj தேவன் called ஆதி\\wj* \\f + \\ft note @ here\\f* ஒளியை @."
    findings = _check(raw, "ta", params={"lifted": lift_verse(raw)})
    assert sorted(f.check_type for f in findings) == ["wildebeest.foreign_script", "wildebeest.special_character"]
    assert _spans_match(raw, findings)
    # The `@` inside the footnote is not verse text; the one after it is.
    symbol = _of_type(findings, "wildebeest.special_character")[0]
    assert symbol.start_offset == raw.rindex("@")
    assert _of_type(findings, "wildebeest.foreign_script")[0].original_text == "called"
