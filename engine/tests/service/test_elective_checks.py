"""Elective checks (#251) and Greek Room on demand (#252), through the protocol.

A run names its checks and runs only those: one test per single check proves
the local bundle is filtered (it was one unfiltered bundle before #251). A run
of some checks replaces only those checks' findings, in the editor's results
and in the stored snapshot and rollup. Greek Room is Wildebeest plus the book
USFM and names scans, and a chapter or book Greek Room run starts those scans
fresh."""
from __future__ import annotations

import json
import os
import time

import pytest

from bridge_service import BridgeEngine
from check_jobs import finding_dict_check
from greek_room_engine.models.finding import FindingCategory, QaFinding
from tests.support.alignment_books import bottom, top, unaligned_verse, write_alignment_book
from tests.support.projects import call, wait_for_job
from tests.support.tc_checks import check_entry, write_index, write_state


@pytest.fixture
def book(tmp_path):
    """One chapter: 1 has a pending tN item, a pending tW item and a comment;
    2 is unaligned (alignment findings) and repeats a word (text); 3 is fine."""
    root = tmp_path / "php"
    write_alignment_book(root, "php", {
        "1": {
            "1": {"text": "அவன் வந்தான்", "complete": True, "alignment": {
                "alignments": [{"topWords": [top("ἦλθεν", "G20640")], "bottomWords": [bottom("வந்தான்")]}],
                "wordBank": [bottom("அவன்")]}},
            "2": unaligned_verse("அவள் போனாள் போனாள்", [("ἀπῆλθεν", "G05650")]),
            "3": {"text": "முடிவு", "complete": True, "alignment": {
                "alignments": [{"topWords": [top("τέλος", "G50560")], "bottomWords": [bottom("முடிவு")]}],
                "wordBank": []}},
        },
    })
    tn, tw = "translationNotes", "translationWords"
    write_index(root, "php", tn, "figs-metaphor", [check_entry("php", "1", "1", tn, "figs-metaphor", "note")])
    write_index(root, "php", tw, "kt", [check_entry("php", "1", "1", tw, "kt", "word")])
    write_state(root, "php", "comments", "1", "1", {"text": "look", "modifiedTimestamp": "2026-01-01T00:00:00Z",
                                                    "contextId": {"tool": tw}}, "c1")
    old = time.time_ns() - 60_000_000_000
    for path in [root, *root.rglob("*")]:
        os.utime(path, ns=(old, old))
    return root


def _book_finding(engine_name: str, check_type: str, verse: int = 1) -> QaFinding:
    return QaFinding(id=f"{engine_name}-{check_type}-{verse}", book="php", chapter=1, verse=verse,
                     engine=engine_name, check_type=check_type, category=FindingCategory.STRUCTURE,
                     explanation=f"{engine_name} finding")


@pytest.fixture
def engine(book, monkeypatch):
    engine = BridgeEngine()
    assert call(engine, "project.open", {"path": str(book)})["success"]
    # The book scans are stubbed: a finding each, and a count of real scans
    # (a cache hit is not a scan), so the cache clear is observable.
    scans = {"usfm": 0, "names": 0}

    def usfm(project=None, cancel_event=None):
        key = str((project or engine.project).path)
        if key not in engine._usfm_findings_by_book:
            scans["usfm"] += 1
            engine._usfm_findings_by_book[key] = [_book_finding("usfm", "usfm.missing_marker")]
        return engine._usfm_findings_by_book[key]

    def names(project=None):
        key = str((project or engine.project).path)
        if key not in engine._names_findings_by_book:
            scans["names"] += 1
            engine._names_findings_by_book[key] = [_book_finding("names", "names.spelling_similarity")]
        return engine._names_findings_by_book[key]

    monkeypatch.setattr(engine, "_usfm_findings_for_book", usfm)
    monkeypatch.setattr(engine, "_names_findings_for_book", names)
    engine.scans = scans  # type: ignore[attr-defined]
    return engine


def _run(engine, checks: list[str]) -> dict:
    started = call(engine, "checks.start", {"scope": "chapter", "chapters": ["1"], "checks": checks})
    assert started["success"], started
    finished = wait_for_job(engine, started["result"]["jobId"], timeout=30)
    assert finished["state"] == "succeeded", finished
    return finished


def _checks_of(snapshot: dict) -> set[str]:
    return {f["check"] for result in snapshot["results"].values() for f in result["findings"]}


def _stages(snapshot: dict) -> set[str]:
    return {name[len("stage:"):] for name in snapshot["timings"] if name.startswith("stage:")}


@pytest.mark.parametrize(("check", "stage", "groups"), [
    ("tN", "tN", {"tN", "tc"}),
    ("tW", "tW", {"tW", "tc"}),
    ("alignment", "Alignment", {"alignment"}),
    ("text", "Text", {"text"}),
    ("greekroom", "Greek Room", {"wildebeest", "usfm", "names"}),
])
def test_a_single_check_runs_only_its_own_stage_and_findings(engine, check, stage, groups):
    finished = _run(engine, [check])

    assert _stages(finished) == {stage}
    produced = _checks_of(finished)
    assert produced, f"{check} found nothing on a book built to trip it"
    assert produced <= groups, produced
    assert set(finished["checkGroups"]) == groups


def test_tn_and_tw_each_find_their_own_tool(engine):
    tn = [f for r in _run(engine, ["tN"])["results"].values() for f in r["findings"] if f["check"] == "tN"]
    tw = [f for r in _run(engine, ["tW"])["results"].values() for f in r["findings"] if f["check"] == "tW"]
    assert tn and all("translationNotes" in f["explanation"] for f in tn)
    assert tw and all("translationWords" in f["explanation"] for f in tw)


def test_language_qa_alone_runs_no_qafinding_stage(engine):
    finished = _run(engine, ["languageQa"])
    assert _stages(finished) == {"Language QA"}
    assert _checks_of(finished) == set()
    assert all("languageQa" in r for r in finished["results"].values())


def test_greek_room_is_the_three_tools_and_local_still_means_everything_but_wildebeest(engine):
    assert _checks_of(_run(engine, ["greekroom"])) >= {"usfm", "names"}
    local = _checks_of(_run(engine, ["local"]))
    assert local >= {"tN", "tW", "alignment", "text", "usfm", "names"}
    assert "wildebeest" not in local


def test_every_finding_check_matches_what_a_stored_finding_derives(engine):
    """The tag on a fresh finding and the one derived for a finding stored
    before the field existed (no `check` key) agree, so a merge treats both alike."""
    finished = _run(engine, ["local", "greekroom"])
    for result in finished["results"].values():
        for finding in result["findings"]:
            stored = {k: v for k, v in finding.items() if k != "check"}
            assert finding_dict_check(stored) == finding["check"], finding["check_type"]


def test_a_greek_room_run_keeps_the_stored_findings_of_the_other_checks(engine, book):
    full = _run(engine, ["tN", "tW", "alignment", "text", "languageQa"])
    before = engine.project.load_check_findings_snapshot("1")
    rollup_before = engine.project.load_progress_rollup()["chapters"]["1"]["verses"]
    assert {finding_dict_check(f) for fs in before.values() for f in fs} >= {"tN", "tW", "alignment", "text"}

    _run(engine, ["greekroom"])

    after = engine.project.load_check_findings_snapshot("1")
    for verse, findings in before.items():
        assert {f["id"] for f in findings} <= {f["id"] for f in after[verse]}, verse
    assert {finding_dict_check(f) for fs in after.values() for f in fs} >= {"tN", "usfm", "names"}
    rollup_after = engine.project.load_progress_rollup()["chapters"]["1"]["verses"]
    for verse, entry in rollup_before.items():
        # Every earlier finding still counted, Language QA ones included.
        assert set(entry["findings"]) <= set(rollup_after[verse]["findings"]), verse
        assert rollup_after[verse].get("languageQaFindingIds") == entry.get("languageQaFindingIds"), verse
    assert full["checks"] == ["tN", "tW", "alignment", "text", "languageQa"]


def test_a_run_replaces_the_findings_of_the_checks_it_ran(engine):
    _run(engine, ["greekroom", "text"])
    engine._usfm_findings_by_book[str(engine.project.path)] = []  # the next scan finds nothing
    engine.scans["usfm"] = 0

    _run(engine, ["text"])  # not Greek Room: the usfm finding is kept
    kept = engine.project.load_check_findings_snapshot("1")
    assert any(finding_dict_check(f) == "usfm" for fs in kept.values() for f in fs)


def test_a_chapter_greek_room_run_starts_the_book_scans_fresh(engine):
    _run(engine, ["greekroom"])
    _run(engine, ["greekroom"])
    assert engine.scans == {"usfm": 2, "names": 2}
    _run(engine, ["local"])  # not a Greek Room run: the cached scans are used
    assert engine.scans == {"usfm": 2, "names": 2}


def test_a_verse_greek_room_run_reads_the_cached_scans(engine):
    """verse.runChecks runs on the dispatcher: it must not pay for a rescan."""
    _run(engine, ["greekroom"])
    response = call(engine, "verse.runChecks", {"chapter": "1", "verse": "1", "checks": ["greekroom"]})
    assert response["success"], response
    assert engine.scans == {"usfm": 1, "names": 1}
    assert {f["check"] for f in response["findings"]} <= {"wildebeest", "usfm", "names"}


def test_greek_room_is_refused_while_collection_qa_runs(engine, monkeypatch):
    monkeypatch.setattr(engine._collection_jobs, "active", lambda: True)
    refused = call(engine, "verse.runChecks", {"chapter": "1", "verse": "1", "checks": ["greekroom"]})
    assert not refused["success"]
    assert "collection" in json.dumps(refused).lower()
    assert call(engine, "verse.runChecks", {"chapter": "1", "verse": "1", "checks": ["tN"]})["success"]
    assert not call(engine, "checks.start", {"scope": "chapter", "chapters": ["1"], "checks": ["greekroom"]})["success"]


def test_unknown_check_names_are_refused(engine):
    refused = call(engine, "checks.start", {"scope": "chapter", "chapters": ["1"], "checks": ["tN", "bogus"]})
    assert not refused["success"]
    assert "bogus" in json.dumps(refused)
