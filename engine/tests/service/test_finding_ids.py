"""Finding-id audit (#273): ids that survive what should not change them, never
collide, and decisions recorded under a pre-#273 id are moved only where that is
unambiguous. The table and the rules are on issue #273."""
from __future__ import annotations

import os
import time

import pytest

from bridge_service import BridgeEngine, _qaissue_to_finding, _stable_finding_id
from greek_room_engine.models.finding import FindingCategory, QaFinding
from tc_ai_bridge.models import QAIssue
from tests.support.alignment_books import bottom, top, write_alignment_book
from tests.support.projects import call


def _book(root, text: str, alignment: dict) -> None:
    write_alignment_book(root, "php", {"1": {"1": {"text": text, "alignment": alignment}}})
    old = time.time_ns() - 60_000_000_000
    for path in [root, *root.rglob("*")]:
        os.utime(path, ns=(old, old))


def _open(root, monkeypatch) -> BridgeEngine:
    engine = BridgeEngine()
    assert call(engine, "project.open", {"path": str(root)})["success"]
    monkeypatch.setattr(engine, "_usfm_findings_for_book", lambda project=None, cancel_event=None: [])
    monkeypatch.setattr(engine, "_names_findings_for_book", lambda project=None: [])
    return engine


def _wildebeest_on(word: str):
    """A stub Wildebeest flagging every occurrence of `word`, at its offsets."""
    def check_verse(*, text, **_kwargs):
        found, start = [], text.find(word)
        while start >= 0:
            found.append(QaFinding(engine="wildebeest", check_type="wildebeest.script.mixed",
                                   category=FindingCategory.UNICODE, start_offset=start,
                                   end_offset=start + len(word), original_text=word, explanation="mixed"))
            start = text.find(word, start + 1)
        return found
    return check_verse


def _findings(engine, checks: list[str]) -> list[dict]:
    response = call(engine, "verse.runChecks", {"chapter": "1", "verse": "1", "checks": checks})
    assert response["success"], response
    return response["findings"]


def _edit(engine, text: str) -> None:
    assert call(engine, "verse.edit", {"chapter": "1", "verse": "1", "newText": text})["success"]


ALIGNED = {"alignments": [{"topWords": [top("ἦλθεν", "G20640")], "bottomWords": [bottom("வந்தான்")]}],
           "wordBank": [bottom("அவன்")]}


def test_a_wildebeest_decision_survives_an_edit_earlier_in_the_verse(tmp_path, monkeypatch):
    root = tmp_path / "php"
    _book(root, "அவன் Xவந்தான்", ALIGNED)
    engine = _open(root, monkeypatch)
    monkeypatch.setattr(engine.greek_room, "check_verse", _wildebeest_on("X"))
    [finding] = _findings(engine, ["wildebeest"])
    assert call(engine, "verse.decide", {"chapter": "1", "verse": "1", "findingId": finding["id"],
                                         "status": "ignored"})["success"]

    _edit(engine, "முதலில் அவன் Xவந்தான்")  # the X moves right

    [after] = _findings(engine, ["wildebeest"])
    assert after["id"] == finding["id"]
    assert after["status"] == "ignored"


def test_two_occurrences_of_the_same_flagged_text_get_two_ids(tmp_path, monkeypatch):
    root = tmp_path / "php"
    _book(root, "X அவன் X", ALIGNED)
    engine = _open(root, monkeypatch)
    monkeypatch.setattr(engine.greek_room, "check_verse", _wildebeest_on("X"))
    ids = [f["id"] for f in _findings(engine, ["wildebeest"])]
    assert len(ids) == 2 and len(set(ids)) == 2


def test_a_local_alignment_decision_survives_a_change_of_count(tmp_path, monkeypatch):
    root = tmp_path / "php"
    _book(root, "அவன் வந்தான் இன்று", {**ALIGNED, "wordBank": [bottom("அவன்"), bottom("இன்று")]})
    engine = _open(root, monkeypatch)
    [unaligned] = [f for f in _findings(engine, ["alignment"]) if f["check_type"] == "ALIGN_UNALIGNED_BOTTOM"]
    assert "2" in unaligned["explanation"]
    assert call(engine, "verse.decide", {"chapter": "1", "verse": "1", "findingId": unaligned["id"],
                                         "status": "ignored"})["success"]

    # One word fewer in the bank: the count in the text changes, the id does not.
    project = engine.project
    alignment = project.load_verse_alignment("1", "1")
    alignment.word_bank = alignment.word_bank[:1]
    project.save_verse_alignment("1", "1", alignment)
    [after] = [f for f in _findings(engine, ["alignment"]) if f["check_type"] == "ALIGN_UNALIGNED_BOTTOM"]
    assert "1" in after["explanation"]
    assert (after["id"], after["status"]) == (unaligned["id"], "ignored")


def _issue(code: str, detail: str = "detail", group: str = "", check_id: str = "") -> QAIssue:
    return QAIssue(code, "high", "title", detail, "translationCore" if code.startswith("TC_") else "local",
                   check_id, group)


def _id(issue: QAIssue) -> str:
    return _qaissue_to_finding(issue, project_id="p", book="php", chapter="1", verse="1").id


def test_the_three_tc_states_of_one_check_carry_three_ids():
    ids = {_id(_issue(code, group="kt", check_id="abc"))
           for code in ("TC_PENDING", "TC_INVALIDATED", "TC_STALE_AFTER_EDIT")}
    assert len(ids) == 3
    # TC_PENDING keeps the id it always had, so its decisions need nothing.
    assert _id(_issue("TC_PENDING", group="kt", check_id="abc")) == _stable_finding_id(
        chapter="1", verse="1", engine="translationCore", check_type="abc", disambiguator="kt")


def test_two_duplicated_tokens_with_the_same_count_no_longer_share_an_id():
    detail = "The same topWord identity appears in 2 alignment groups."
    first = _id(_issue("ALIGN_DUP_TOP", detail, group="a␟1␟1"))
    second = _id(_issue("ALIGN_DUP_TOP", detail, group="b␟1␟1"))
    assert first != second


@pytest.mark.parametrize("code", ["ALIGN_BANK_OVERLAP", "ALIGN_UNALIGNED_TOP", "ALIGN_UNALIGNED_BOTTOM",
                                  "ALIGN_TARGET_MISMATCH", "TC_COMMENTS", "TC_VERSE_EDITS"])
def test_a_one_per_verse_finding_is_not_keyed_on_its_count(code):
    assert _id(_issue(code, "1 token(s)")) == _id(_issue(code, "7 token(s)"))


def test_usfm_balance_is_keyed_on_the_marker_not_the_counts():
    assert _id(_issue("USFM_BALANCE", "Unbalanced \\wj: 2 open, 1 close", group="wj")) == \
        _id(_issue("USFM_BALANCE", "Unbalanced \\wj: 3 open, 1 close", group="wj"))


def _decide_under(engine, finding_id: str, status: str = "ignored") -> None:
    engine.project.record_qa_decision("1", "1", finding_id, status, "")


def test_a_decision_under_a_pre_273_id_moves_once_when_unambiguous(tmp_path, monkeypatch):
    root = tmp_path / "php"
    _book(root, "அவன் Xவந்தான்", ALIGNED)
    engine = _open(root, monkeypatch)
    monkeypatch.setattr(engine.greek_room, "check_verse", _wildebeest_on("X"))
    old_id = _stable_finding_id(chapter="1", verse="1", engine="wildebeest",
                                check_type="wildebeest.script.mixed", disambiguator="5:6:X")
    _decide_under(engine, old_id)

    [finding] = _findings(engine, ["wildebeest"])

    assert finding["id"] != old_id
    assert finding["status"] == "ignored"
    moved = engine.project.qa_decisions_for_verse("1", "1")[finding["id"]]
    assert moved["issue"]["rekeyedFrom"] == old_id
    assert old_id in engine.project.qa_decisions_for_verse("1", "1")  # the old row stays


def test_a_decision_under_a_colliding_pre_273_id_is_shown_not_applied(tmp_path, monkeypatch):
    # Two source tokens each aligned twice: before #273 both ALIGN_DUP_TOP
    # findings had one id.
    root = tmp_path / "php"
    twice = {"alignments": [
        {"topWords": [top("α", "G1")], "bottomWords": [bottom("அவன்")]},
        {"topWords": [top("α", "G1")], "bottomWords": [bottom("வந்தான்")]},
        {"topWords": [top("β", "G2")], "bottomWords": []},
        {"topWords": [top("β", "G2")], "bottomWords": []},
    ], "wordBank": []}
    _book(root, "அவன் வந்தான்", twice)
    engine = _open(root, monkeypatch)
    old_id = _stable_finding_id(chapter="1", verse="1", engine="local", check_type="ALIGN_DUP_TOP",
                                disambiguator="The same topWord identity appears in 2 alignment groups.")
    _decide_under(engine, old_id)

    dups = [f for f in _findings(engine, ["alignment"]) if f["check_type"] == "ALIGN_DUP_TOP"]

    assert len(dups) == 2 and dups[0]["id"] != dups[1]["id"]
    for finding in dups:
        assert finding["status"] == "open"
        assert finding["unmatched_decision"]["decision"] == "ignored"
        assert finding["unmatched_decision"]["findingId"] == old_id
    assert set(engine.project.qa_decisions_for_verse("1", "1")) == {old_id}


def test_a_pending_items_decision_never_lands_on_its_stale_or_invalidated_warning():
    finding = _qaissue_to_finding(_issue("TC_INVALIDATED", group="kt", check_id="abc"),
                                  project_id="p", book="php", chapter="1", verse="1")
    pending_id = _id(_issue("TC_PENDING", group="kt", check_id="abc"))
    assert finding.id != pending_id
    assert finding._legacy_id == pending_id  # type: ignore[attr-defined]
    assert finding._legacy_movable is False  # type: ignore[attr-defined]
