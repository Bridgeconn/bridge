"""USFM-checker check types (#283): never built from verse text, so an edit
to a verse does not change its findings' ids, and a decision recorded under
the old, text-built check type is carried to the new id once (#273's rule)."""
from __future__ import annotations

import os
import re
import time
from collections import Counter

import pytest

from bridge_service import BridgeEngine, _stable_finding_id
from greek_room_engine.adapters.usfm_adapter import UsfmAdapter, _checker_command, _parse_report
from greek_room_engine.models.finding import FindingCategory, QaFinding, Severity
from tests.support.alignment_books import bottom, top, write_alignment_book
from tests.support.projects import call

# The shape of the real report around LUK 18:14 (43LUKIRVTam.SFM): an
# instance line that ends in a count, followed by more instances.
REPORT = """\
Errors (3)
    Nested tags (3)
        Nested tags '\\wj ... \\f ... \\f* ... \\wj*' should be changed to '\\wj ... \\wj* \\f ... \\f*' (3)
            LUK 18:13: \\wj one\\f + \\fr 18:13 \\ft note\\f*\\wj*
            LUK 18:14: \\wj two\\f + \\fr 18:14 \\ft a\\f*, three\\f + \\fr 18:14 \\ft b\\f*\\wj* (2)
            LUK 19:9: \\wj four\\f + \\fr 19:9 \\ft note\\f*\\wj*
"""
NESTED = "Nested tags '\\wj ... \\f ... \\f* ... \\wj*' should be changed to '\\wj ... \\wj* \\f ... \\f*'"


def test_an_instance_ending_in_a_count_is_an_instance_not_a_header():
    issues = _parse_report(REPORT)

    assert [(i["chapter"], i["verse"]) for i in issues] == [("18", "13"), ("18", "14"), ("19", "9")]
    assert {i["subcategory"] for i in issues} == {NESTED}
    # What the pre-#283 parse said: 19:9 sat under the 18:14 line.
    assert issues[2]["legacy_subcategory"].startswith("LUK 18:14:")
    assert [i["legacy_subcategory"] for i in issues[:2]] == [NESTED, NESTED]


@pytest.mark.skipif(_checker_command() is None, reason="USFM structural checker not available")
def test_no_check_type_on_luke_is_built_from_verse_text_and_an_edit_keeps_them(tamil_luk_usfm):
    text = tamil_luk_usfm.read_text(encoding="utf-8-sig")
    adapter = UsfmAdapter()

    def keys(usfm: str) -> Counter:
        findings = adapter.check_book(project_id="t", book_id="luk", usfm_text=usfm)
        assert not [f.check_type for f in findings if re.search(r"luk_\d+_\d+", f.check_type)]
        return Counter((f.chapter, f.verse, f.check_type) for f in findings)

    before = keys(text)
    # An edit to 19:9's wording (one of the nine findings that sat under the
    # 18:14 line), away from its markers.
    edited = text.replace("இயேசு அவனைப் பார்த்து: \\wj இன்றைக்கு இந்த",
                          "இயேசு அவனை நோக்கி: \\wj இன்றைக்கு இந்த", 1)
    assert edited != text
    assert keys(edited) == before
    assert (18, 14) in {(c, v) for c, v, _ in before}  # the line once taken for a header


def test_a_decision_under_the_old_check_type_moves_once(tmp_path, monkeypatch):
    root = tmp_path / "php"
    write_alignment_book(root, "php", {"1": {"1": {"text": "அவன் வந்தான்", "alignment": {
        "alignments": [{"topWords": [top("ἦλθεν", "G20640")], "bottomWords": [bottom("வந்தான்")]}],
        "wordBank": [bottom("அவன்")]}}}})
    old = time.time_ns() - 60_000_000_000
    for path in [root, *root.rglob("*")]:
        os.utime(path, ns=(old, old))
    engine = BridgeEngine()
    assert call(engine, "project.open", {"path": str(root)})["success"]
    monkeypatch.setattr(engine, "_names_findings_for_book", lambda project=None: [])

    old_type = "usfm.luk_18_14_wj_f_fr_18_14_ft_f_wj"

    def check_book_usfm(**_kwargs):
        finding = QaFinding(book="php", chapter=1, verse=1, engine="usfm", check_type="usfm.nested_tags",
                            category=FindingCategory.STRUCTURE, severity=Severity.HIGH, explanation="nested")
        finding._legacy_check_type = old_type
        return [finding]

    monkeypatch.setattr(engine.greek_room, "check_book_usfm", check_book_usfm)
    old_id = _stable_finding_id(chapter="1", verse="1", engine="usfm", check_type=old_type, disambiguator="#1")
    engine.project.record_qa_decision("1", "1", old_id, "ignored", "")

    response = call(engine, "verse.runChecks", {"chapter": "1", "verse": "1", "checks": ["usfm"]})
    assert response["success"], response
    [finding] = [f for f in response["findings"] if f["engine"] == "usfm"]

    assert finding["id"] == _stable_finding_id(chapter="1", verse="1", engine="usfm",
                                               check_type="usfm.nested_tags", disambiguator="#1")
    assert finding["status"] == "ignored"
    decisions = engine.project.qa_decisions_for_verse("1", "1")
    assert decisions[finding["id"]]["issue"]["rekeyedFrom"] == old_id
    assert old_id in decisions
