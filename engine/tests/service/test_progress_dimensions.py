"""#239: the aligned and Language QA dimensions of the progress totals.

The totals row (and the workspace cache the dashboard reads) gains
`alignedVerseCount` over `alignedKnownVerseCount` and
`languageQaCleanVerseCount` over `languageQaCheckedVerseCount`. A check job
counts both for the chapters it covered; every alignment writer recounts its
chapter; a decision on a Language QA finding moves the clean count through
the same recompute decisions always used. Lives in tests/service because it
drives the dispatcher (checks.start, alignment.save, verse.decide); the
persistence half (the chapter row's new fields) is asserted through
`load_progress_rollup` here rather than from a second file.
"""
from __future__ import annotations

import json
from pathlib import Path

from bridge_service import BridgeEngine
from tc_ai_bridge.secret_store import AppSettings
from tc_ai_bridge.tc_project import TranslationCoreProject
import time

from tests.support.alignment_books import bottom, top, unaligned_verse, write_alignment_book
from tests.support.language_qa import issue_for
from tests.support.projects import call, wait_for_job
from tests.support.waits import job_timeout


def _aligned_verse(word: str, strong: str) -> dict:
    return {
        "text": word,
        "alignment": {
            "alignments": [{"topWords": [top(f"λ{word}", strong)], "bottomWords": [bottom(word)]}],
            "wordBank": [],
        },
        "complete": True,
    }


def _book(tmp_path: Path) -> Path:
    root = tmp_path / "php"
    write_alignment_book(root, "php", {
        "1": {"1": _aligned_verse("w1", "G10"), "2": unaligned_verse("w2", [("λ2", "G20")])},
        "2": {"1": unaligned_verse("w3", [("λ3", "G30")]), "2": unaligned_verse("w4", [("λ4", "G40")])},
    })
    return root


def _engine(tmp_path: Path, root: Path) -> BridgeEngine:
    engine = BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json"))
    assert call(engine, "project.open", {"path": str(root), "awaitSemantic": True})["success"] is True
    return engine


def _progress(engine) -> dict:
    books = call(engine, "project.listBookProgress")["result"]["books"]
    return books[0]["progress"]


def test_a_check_job_counts_aligned_verses_for_its_chapters_and_a_write_recounts(tmp_path):
    root = _book(tmp_path)
    engine = _engine(tmp_path, root)

    started = call(engine, "checks.start", {"scope": "chapter", "chapters": ["1"], "checks": ["local"]})
    assert started["success"] is True, started
    assert wait_for_job(engine, started["result"]["jobId"])["state"] == "succeeded"

    progress = _progress(engine)
    assert progress["alignedVerseCount"] == 1
    assert progress["alignedKnownVerseCount"] == 2       # chapter 1 only; chapter 2 was not counted
    assert progress["languageQaCheckedVerseCount"] == 0  # the Language QA stage did not run
    assert progress["verseCount"] == 4

    # An alignment write in chapter 2 recounts that chapter, so the dashboard
    # learns about it without a check job.
    project = engine.project
    before = project.load_verse_alignment("2", "1").to_dict()
    saved = call(engine, "alignment.save", {
        "chapter": "2", "verse": "1",
        "alignment": {"alignments": [{"topWords": [top("λ3", "G30")], "bottomWords": [bottom("w3")]}], "wordBank": []},
        "expectedOriginal": before,
    })
    assert saved["success"] is True, saved
    progress = _progress(engine)
    assert progress["alignedVerseCount"] == 2
    assert progress["alignedKnownVerseCount"] == 4

    # The chapter row carries the count, and the workspace cache is at the
    # totals write's own seq, so project.open will call it fresh.
    rollup = project.load_progress_rollup()
    assert rollup["chapters"]["2"]["alignedVerseCount"] == 1
    assert rollup["chapters"]["2"]["aiChecked"] is False
    cached = project.workspace.progress_cache_entry(project.path)
    assert cached["totals"]["alignedVerseCount"] == 2
    assert cached["sourceSeq"] == project.workbench.max_seq(
        project_id=project.workbench_identity.project_id, table="progress_totals",
    )
    assert project.sync_progress_cache() == "fresh"

    # An edit that invalidates the alignment takes the verse out again.
    assert call(engine, "verse.edit", {"chapter": "2", "verse": "1", "newText": "w3 changed"})["success"] is True
    assert _progress(engine)["alignedVerseCount"] == 1


def test_language_qa_clean_count_follows_the_stage_and_its_decisions(tmp_path):
    root = _book(tmp_path)
    engine = _engine(tmp_path, root)
    project: TranslationCoreProject = engine.project

    # What the check job's completion hook writes when the Language QA stage
    # ran: verse 1 clean, verse 2 with one finding still open.
    project.replace_progress_chapters({
        "1": {
            "verseCount": 2, "aiChecked": True, "aiCheckedAt": project.timestamp_iso(), "alignedVerseCount": 1,
            "verses": {
                "1": {"findings": {}, "languageQaFindingIds": []},
                "2": {"findings": {"lqa-1": "open"}, "languageQaFindingIds": ["lqa-1"]},
            },
        },
        "2": {  # the stage did not run here: nothing claimed
            "verseCount": 2, "aiChecked": True, "aiCheckedAt": project.timestamp_iso(),
            "verses": {"1": {"findings": {}}, "2": {"findings": {}}},
        },
    })
    rollup = project.load_progress_rollup()
    assert rollup["chapters"]["1"]["verses"]["2"]["languageQaFindingIds"] == ["lqa-1"]
    assert "languageQaFindingIds" not in rollup["chapters"]["2"]["verses"]["1"]
    BridgeEngine._recompute_progress_totals(project, rollup)
    assert rollup["totals"]["languageQaCheckedVerseCount"] == 2
    assert rollup["totals"]["languageQaCleanVerseCount"] == 1
    assert rollup["totals"]["alignedVerseCount"] == 1 and rollup["totals"]["alignedKnownVerseCount"] == 2
    project.save_progress_totals(rollup["totals"])

    # Deciding the finding (ignore it) makes the verse clean; reopening it does not.
    project.record_progress_decision("1", "2", "lqa-1", "ignored", verse_count=2)
    rollup = project.load_progress_rollup()
    BridgeEngine._recompute_progress_totals(project, rollup)
    assert rollup["totals"]["languageQaCleanVerseCount"] == 2
    project.record_progress_decision("1", "2", "lqa-1", "open", verse_count=2)
    rollup = project.load_progress_rollup()
    BridgeEngine._recompute_progress_totals(project, rollup)
    assert rollup["totals"]["languageQaCleanVerseCount"] == 1

    # A rollup written before #239 (no new fields) still totals, with both
    # dimensions unknown rather than wrong.
    old_rollup = {"chapters": {"1": {"verseCount": 2, "aiChecked": True, "verses": {"1": {"findings": {}}}}}}
    BridgeEngine._recompute_progress_totals(project, old_rollup)
    assert old_rollup["totals"]["alignedKnownVerseCount"] == 0
    assert old_rollup["totals"]["languageQaCheckedVerseCount"] == 0


def test_the_check_job_records_language_qa_ids_only_when_that_stage_ran(tmp_path):
    root = _book(tmp_path)
    engine = _engine(tmp_path, root)
    started = call(engine, "checks.start", {"scope": "chapter", "chapters": ["2"], "checks": ["local", "languageQa"]})
    assert started["success"] is True, started
    assert wait_for_job(engine, started["result"]["jobId"])["state"] == "succeeded"
    rollup = engine.project.load_progress_rollup()
    for verse_entry in rollup["chapters"]["2"]["verses"].values():
        assert isinstance(verse_entry.get("languageQaFindingIds"), list)
    progress = _progress(engine)
    assert progress["languageQaCheckedVerseCount"] == 2
    assert progress["languageQaCleanVerseCount"] <= 2
    # The row is JSON the way the workbench stores it.
    row = engine.project.workbench.get("progress_chapters", engine.project._progress_chapter_row_id("2"))
    assert "languageQaFindingIds" in json.loads(row["payload_json"])


def _until_clean(engine, wanted: int) -> dict:
    """The dashboard's progress once its clean count reads `wanted`: the
    background pass is debounced, so the count follows within one pass."""
    deadline = time.monotonic() + job_timeout(8)
    progress = _progress(engine)
    while progress["languageQaCleanVerseCount"] != wanted and time.monotonic() < deadline:
        time.sleep(0.1)
        progress = _progress(engine)
    return progress


def test_a_live_language_qa_pass_moves_the_clean_count_without_a_check_job(tmp_path):
    # #280: the count used to move only when a check job completed.
    root = tmp_path / "php"
    write_alignment_book(root, "php", {"1": {
        "1": _aligned_verse("w1", "G10"),
        "2": unaligned_verse("w2,, w5", [("λ2", "G20")]),  # ",,": punctuation.repeated
    }})
    engine = _engine(tmp_path, root)
    started = call(engine, "checks.start", {"scope": "chapter", "chapters": ["1"], "checks": ["local", "languageQa"]})
    assert started["success"] is True, started
    assert wait_for_job(engine, started["result"]["jobId"])["state"] == "succeeded"
    progress = _progress(engine)
    # Verse 1 carries the book's header.missing (#253, anchored at the first
    # verse), verse 2 the ",,": neither is clean yet.
    assert (progress["languageQaCheckedVerseCount"], progress["languageQaCleanVerseCount"]) == (2, 0)

    # Ignoring the verse's last finding: verse.decide, then the background pass.
    shown = call(engine, "languageQa.verse", {"projectPath": str(root), "chapter": "1",
                                              "verse": "2"})["result"]["findings"]
    finding = next(f for f in shown if f["rule"] == "punctuation.repeated")
    decided = call(engine, "verse.decide", {"chapter": "1", "verse": "2", "findingId": finding["id"],
                                            "status": "ignored", "issue": issue_for(finding)})
    assert decided["success"] is True, decided
    progress = _until_clean(engine, 1)
    assert (progress["languageQaCheckedVerseCount"], progress["languageQaCleanVerseCount"]) == (2, 1)
    entry = engine.project.load_progress_rollup()["chapters"]["1"]["verses"]["2"]
    assert entry["languageQaFindingIds"] == [finding["id"]] and entry["findings"][finding["id"]] == "ignored"

    # An edit that introduces a finding (a double space) takes it out again.
    edited = call(engine, "verse.edit", {"chapter": "1", "verse": "2", "newText": "w2,,  w5"})
    assert edited["success"] is True, edited
    progress = _until_clean(engine, 0)
    assert (progress["languageQaCheckedVerseCount"], progress["languageQaCleanVerseCount"]) == (2, 0)
    entry = engine.project.load_progress_rollup()["chapters"]["1"]["verses"]["2"]
    assert len(entry["languageQaFindingIds"]) == 2 and "open" in entry["findings"].values()
    # Nothing outside Language QA moved: the chapter row keeps the check job's fields.
    chapter = engine.project.load_progress_rollup()["chapters"]["1"]
    assert chapter["aiChecked"] is True and set(chapter["verses"]) == {"1", "2"}


def test_a_live_pass_claims_nothing_where_the_stage_never_ran(tmp_path):
    # #280: with no check job, the rollup holds no Language QA ids, and a live
    # pass must not invent them: the dashboard says "not checked", not "clean".
    root = tmp_path / "php"
    write_alignment_book(root, "php", {"1": {"1": _aligned_verse("w1", "G10"),
                                            "2": unaligned_verse("w2,, w5", [("λ2", "G20")])}})
    engine = _engine(tmp_path, root)
    edited = call(engine, "verse.edit", {"chapter": "1", "verse": "2", "newText": "w2 w5"})
    assert edited["success"] is True, edited
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        assert "1" not in engine.project.load_progress_rollup()["chapters"] or not any(
            "languageQaFindingIds" in v for v in engine.project.load_progress_rollup()["chapters"]["1"]["verses"].values())
        time.sleep(0.2)
