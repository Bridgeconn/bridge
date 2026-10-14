"""check.loadChapterFindings (#272): a chapter's stored findings are read back
on chapter entry while they still describe the chapter, so returning to a book
starts no job; any change to what they were computed from makes them stale."""
from __future__ import annotations

import os
import time

import pytest

from bridge_service import BridgeEngine
from check_jobs import finding_dict_check
from tests.support.alignment_books import bottom, top, unaligned_verse, write_alignment_book
from tests.support.projects import call, wait_for_job
from tests.support.tc_checks import check_entry, write_index, write_state, state_record

DEFAULT = ["tN", "tW", "alignment", "text", "languageQa"]


@pytest.fixture
def book(tmp_path):
    root = tmp_path / "php"
    write_alignment_book(root, "php", {"1": {
        "1": {"text": "அவன் வந்தான்", "complete": True, "alignment": {
            "alignments": [{"topWords": [top("ἦλθεν", "G20640")], "bottomWords": [bottom("வந்தான்")]}],
            "wordBank": [bottom("அவன்")]}},
        "2": unaligned_verse("அவள் போனாள் போனாள்", [("ἀπῆλθεν", "G05650")]),
    }})
    tn = "translationNotes"
    write_index(root, "php", tn, "figs-metaphor", [check_entry("php", "1", "1", tn, "figs-metaphor", "note")])
    old = time.time_ns() - 60_000_000_000
    for path in [root, *root.rglob("*")]:
        os.utime(path, ns=(old, old))
    return root


@pytest.fixture
def engine(book, monkeypatch):
    engine = BridgeEngine()
    assert call(engine, "project.open", {"path": str(book)})["success"]
    monkeypatch.setattr(engine, "_usfm_findings_for_book", lambda project=None, cancel_event=None: [])
    monkeypatch.setattr(engine, "_names_findings_for_book", lambda project=None: [])
    return engine


def _job(engine, checks) -> dict:
    started = call(engine, "checks.start", {"scope": "chapter", "chapters": ["1"], "checks": checks})["result"]
    finished = wait_for_job(engine, started["jobId"], timeout=30)
    assert finished["state"] == "succeeded", finished
    return finished


def _load(engine) -> dict:
    response = call(engine, "check.loadChapterFindings", {"chapter": "1"})
    assert response["success"], response
    return response["result"]


def _ids(verses: dict) -> dict[str, list[str]]:
    return {v: sorted(f["id"] for f in fs) for v, fs in verses.items()}


def test_nothing_stored_is_not_current(engine):
    assert _load(engine)["current"] is False


def test_after_a_job_the_stored_findings_are_current_and_equal_a_fresh_run(engine):
    job = _job(engine, DEFAULT)
    stored = _load(engine)
    assert stored["current"] is True
    assert set(stored["checkGroups"]) >= {"tN", "tW", "alignment", "text", "languageQa"}
    from_job = {r["verse"]: r["findings"] for r in job["results"].values()}
    assert _ids(stored["verses"]) == _ids(from_job)
    assert any(stored["verses"].values())


def test_a_decision_made_after_the_job_shows_on_read(engine):
    _job(engine, DEFAULT)
    finding = _load(engine)["verses"]["1"][0]
    assert call(engine, "verse.decide", {"chapter": "1", "verse": "1", "findingId": finding["id"],
                                         "status": "ignored"})["success"]
    again = {f["id"]: f for f in _load(engine)["verses"]["1"]}
    assert again[finding["id"]]["status"] == "ignored"


def test_an_edit_makes_the_chapter_stale(engine):
    _job(engine, DEFAULT)
    assert call(engine, "verse.edit", {"chapter": "1", "verse": "2", "newText": "அவள் போனாள்"})["success"]
    assert _load(engine)["current"] is False


def test_an_alignment_change_makes_the_chapter_stale(engine):
    _job(engine, DEFAULT)
    project = engine.project
    alignment = project.load_verse_alignment("1", "1")
    alignment.word_bank = []
    project.save_verse_alignment("1", "1", alignment)
    assert _load(engine)["current"] is False


def test_a_tc_selection_makes_the_chapter_stale(engine, book):
    _job(engine, DEFAULT)
    write_state(book, "php", "selections", "1", "1",
                state_record("php", "1", "1", "translationNotes", "figs-metaphor", "note",
                             modified="2026-10-14T00:00:00Z"), "s1")
    assert _load(engine)["current"] is False


def test_a_snapshot_written_before_272_is_not_current(engine):
    engine.project.save_check_findings_snapshot("1", {"1": [], "2": []})
    assert _load(engine)["current"] is False


def test_a_stale_snapshots_findings_are_not_carried_into_a_partial_run(engine):
    _job(engine, ["tN", "tW", "alignment", "text"])
    assert call(engine, "verse.edit", {"chapter": "1", "verse": "2", "newText": "அவள் போனாள்"})["success"]

    _job(engine, ["text"])

    stored = _load(engine)
    assert stored["current"] is True
    assert set(stored["checkGroups"]) == {"text"}
    groups = {finding_dict_check(f) for fs in stored["verses"].values() for f in fs}
    assert groups <= {"text"}


def test_a_current_snapshot_covers_the_union_of_its_runs(engine):
    _job(engine, ["tN", "tW"])
    _job(engine, ["alignment"])
    stored = _load(engine)
    assert stored["current"] is True
    assert set(stored["checkGroups"]) == {"tN", "tW", "tc", "alignment"}
    groups = {finding_dict_check(f) for fs in stored["verses"].values() for f in fs}
    assert {"tN", "alignment"} <= groups
