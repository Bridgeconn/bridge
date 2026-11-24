"""#513: what a cancelled AI review leaves behind, and usage counted once.

Decided 2026-11-24: a cancel leaves a verse as it was before the run. A verse
that had a review keeps it, exactly; a verse that had none still has none; a
verse whose new review was already stored is finished. Whatever was sent is
counted on the lifetime usage counter, once.

A five-verse Titus 1 with a section heading before verse 4, real bundled
translationNotes / translationWords, and a transport that records every
request, answers from the request's own ids, and can hold a review request
open so a cancel lands while it is in flight.
"""
from __future__ import annotations

import json
import threading

import pytest

from bridge_service import BridgeEngine
from tc_ai_bridge import ai_review_windows
from tc_ai_bridge.secret_store import AppSettings
from tc_ai_bridge.tc_project import TranslationCoreProject
from tests.support.ai_review import _metadata, _wait_for_ai_job
from tests.support.projects import call

VERSES = ["1", "2", "3", "4", "5"]
USFM = (
    "\\id TIT\n\\h Titus\n\\c 1\n\\p\n"
    "\\v 1 Paul, a servant of God and an apostle of Jesus Christ.\n"
    "\\v 2 In hope of eternal life, which God promised before time began.\n"
    "\\v 3 He revealed his word by the proclamation entrusted to me.\n"
    "\\s Instructions for Titus\n\\p\n"
    "\\v 4 To Titus, a true son in our common faith.\n"
    "\\v 5 For this purpose I left you in Crete.\n"
)
# Every answered request reports this many tokens, so the counter can be
# compared with the number of requests the transport saw.
TOKENS_PER_CALL = 1300
REVIEW_REQUESTS = ("tc_full_review", "tc_window_review")


class Hold:
    """Keeps a review request open until the test lets it go."""

    def __init__(self) -> None:
        self.armed = False
        self.entered = threading.Event()
        self.release = threading.Event()

    def wait_if_armed(self) -> None:
        if not self.armed:
            return
        self.entered.set()
        assert self.release.wait(30), "the test never released the held request"


@pytest.fixture
def titus(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # As in the window tests: #474's caps would cut these verses into windows
    # of one or two, and this file is about cancelling, not about the caps.
    monkeypatch.setattr(ai_review_windows, "WINDOW_MAX_CHECKS", 10_000)
    monkeypatch.setattr(ai_review_windows, "WINDOW_MAX_INPUT_CHARS", 10_000_000)
    settings = AppSettings(path=tmp_path / "settings.json")
    engine = BridgeEngine(settings=settings)
    source = tmp_path / "57-TIT.usfm"
    source.write_text(USFM, encoding="utf-8")
    result = engine.import_project(str(source), _metadata())
    call(engine, "verse.runChecks", {"chapter": "1", "verse": "1", "checks": ["local"]})
    settings.set_api_key("sk-test-123")
    return settings, result["path"]


def _row(check: dict, target_id: str) -> dict:
    return {
        "tool": check["tool"], "group_id": check["groupId"], "check_id": check["checkId"],
        "source_quote": check.get("source_quote") or "",
        "selection_ids": [target_id], "nothing_to_select": False,
        "verdict": "pass", "severity": "info", "rationale": "Supported by bundled evidence.",
        "suggested_correction": "", "confidence": 0.91, "evidence_ids": check["evidence_ids"][:1],
    }


def _answer_review(review_input: dict) -> dict:
    if "verses" not in review_input:
        target_id = review_input["target_bottomWords"][0]["id"]
        return {
            "summary": "Grounded.",
            "check_reviews": [_row(check, target_id) for check in review_input["translationCore_checks"]],
            "qa_issues": [],
        }
    rows = []
    for block in review_input["verses"]:
        target_id = block["target_bottomWords"][0]["id"]
        rows.extend(
            {"reference": block["reference"], **_row(check, target_id)}
            for check in block["translationCore_checks"]
        )
    return {
        "summaries": [
            {"reference": b["reference"], "summary": f"Grounded {b['reference']}."}
            for b in review_input["verses"]
        ],
        "check_reviews": rows,
        "qa_issues": [],
    }


def _transport(requests: list[dict], hold: Hold):
    def transport(url, headers, body, timeout):
        request = json.loads(body.decode("utf-8"))
        requests.append(request)
        name = request["text"]["format"]["name"]
        request_input = json.loads(request["input"])
        if name == "tc_alignment_proposal":
            payload = {"links": [], "implicit_top_ids": [], "target_only_ids": [], "review_notes": []}
        elif name == "bridge_semantic_mapping_v04":
            payload = {
                "mappings": [],
                "unresolved_source_units": [
                    {"source_unit_id": unit["id"], "reason": "NOT_LOCATED", "detail": "test"}
                    for unit in request_input["source_units"]
                ],
                "passage_assessment": "NEEDS_REVIEW",
            }
        else:
            assert name in REVIEW_REQUESTS, name
            hold.wait_if_armed()
            payload = _answer_review(request_input)
        return 200, json.dumps({
            "output_text": json.dumps(payload),
            "usage": {"input_tokens": 1000, "output_tokens": 300, "total_tokens": TOKENS_PER_CALL,
                      "input_tokens_details": {"cached_tokens": 0}},
        }).encode("utf-8")
    return transport


def _open(settings, path):
    requests: list[dict] = []
    hold = Hold()
    engine = BridgeEngine(settings=settings, ai_transport=_transport(requests, hold))
    call(engine, "project.open", {"path": path})
    return engine, requests, hold


def _start(engine, scope: str, verse: str = "1") -> str:
    started = call(engine, "ai.review.start", {
        "scope": scope, "chapter": "1", "verse": verse, "mode": "basic",
    })
    assert started["success"] is True, started
    return started["result"]["jobId"]


def _finish(engine, job_id: str) -> dict:
    return _wait_for_ai_job(engine, job_id, timeout=60)


def _cancel_while_held(engine, hold: Hold, job_id: str) -> dict:
    """Cancel while a review request is in flight, then let it be answered."""
    assert hold.entered.wait(60), "no review request was sent"
    cancelling = call(engine, "ai.review.cancel", {"jobId": job_id})
    assert cancelling["result"]["state"] == "cancelling", cancelling
    hold.release.set()
    return _finish(engine, job_id)


def _counted(settings) -> int:
    return settings.get_ai_usage_totals()["tokens"]


def _listed(engine, verse: str = "1") -> dict:
    return call(engine, "check.listForVerse", {"chapter": "1", "verse": verse})["result"]


# -- usage is counted once ---------------------------------------------------


def test_usage_is_counted_once_when_a_verse_fails_after_its_review_is_stored(titus, monkeypatch):
    """The double count: the verse's usage was added when its review finished,
    and again by the single-verse path's error handler for any failure after
    that point."""
    settings, path = titus
    engine, requests, _ = _open(settings, path)

    def fail(*args, **kwargs):
        raise RuntimeError("selections could not be applied")

    monkeypatch.setattr(BridgeEngine, "_apply_safe_ai_selections", fail)
    snapshot = _finish(engine, _start(engine, "verse"))

    assert snapshot["state"] == "failed", snapshot
    assert "selections could not be applied" in snapshot["results"]["1:1"]["error"]
    assert requests, "the verse sent nothing, so the test proves nothing"
    assert _counted(settings) == TOKENS_PER_CALL * len(requests)


# -- a cancel before the review is stored ------------------------------------


def test_a_cancelled_rerun_keeps_the_earlier_review_exactly(titus):
    settings, path = titus
    engine, requests, hold = _open(settings, path)
    assert _finish(engine, _start(engine, "verse"))["state"] == "succeeded"
    earlier = engine.project.load_ai_review_result("1", "1")
    assert earlier and earlier["checkReviews"]
    assert engine.project.ai_review_cache_status("1", "1") == "current"
    sent_by_first_run = len(requests)

    hold.armed = True
    snapshot = _cancel_while_held(engine, hold, _start(engine, "verse"))

    assert snapshot["state"] == "cancelled", snapshot
    assert snapshot["results"] == {} and snapshot["latestResult"] is None
    assert len(requests) > sent_by_first_run, "the second run sent nothing"
    # The stored review is the earlier one, untouched: same payload, still current.
    assert engine.project.load_ai_review_result("1", "1") == earlier
    assert engine.project.ai_review_cache_status("1", "1") == "current"
    listed = _listed(engine)
    assert listed["aiReviewState"] == "current"
    assert listed["aiSummary"] == earlier["summary"]
    # What the cancelled run sent was answered and is billed: counted, once.
    assert _counted(settings) == TOKENS_PER_CALL * len(requests)


def test_a_cancelled_first_run_leaves_the_verse_without_a_review(titus):
    settings, path = titus
    engine, requests, hold = _open(settings, path)
    hold.armed = True

    snapshot = _cancel_while_held(engine, hold, _start(engine, "verse"))

    assert snapshot["state"] == "cancelled", snapshot
    assert snapshot["results"] == {}
    assert engine.project.load_ai_review_result("1", "1") is None
    listed = _listed(engine)
    assert listed["aiReviewState"] == "missing"
    assert listed["aiSummary"] == "" and listed["aiReviews"] == []
    assert _counted(settings) == TOKENS_PER_CALL * len(requests)


def test_a_cancelled_window_stores_no_verse_and_counts_every_request(titus):
    """Several verses per request (#502): the window is answered after the
    cancel, and none of its verses is stored. Verse 4 was prepared (its own
    calls sent) before the first window went out and is never sent at all."""
    settings, path = titus
    engine, requests, hold = _open(settings, path)
    assert call(engine, "settings.set", {"aiReview": {"versesPerRequest": 4}})["success"] is True
    hold.armed = True

    snapshot = _cancel_while_held(engine, hold, _start(engine, "chapter"))

    assert snapshot["state"] == "cancelled", snapshot
    assert snapshot["results"] == {}
    windows = [r for r in requests if r["text"]["format"]["name"] == "tc_window_review"]
    assert len(windows) == 1, "only the window in flight when the cancel arrived"
    for verse in VERSES:
        assert engine.project.load_ai_review_result("1", verse) is None, verse
        assert engine.project.ai_review_cache_status("1", verse) == "missing"
    assert _counted(settings) == TOKENS_PER_CALL * len(requests)


# -- a cancel after the review is stored -------------------------------------


def _cancel_right_after_the_first_store(engine, monkeypatch) -> None:
    real = TranslationCoreProject.record_ai_review_result
    fired: list[bool] = []

    def record_then_cancel(self, chapter, verse, payload):
        row = real(self, chapter, verse, payload)
        if not fired:
            fired.append(True)
            engine._ai_review_jobs.cancel()
        return row

    monkeypatch.setattr(TranslationCoreProject, "record_ai_review_result", record_then_cancel)


def test_a_verse_stored_before_the_cancel_is_finished(titus, monkeypatch):
    """The cancel arrives when the new review has just replaced the old one.
    Going back is no longer possible, so the verse is finished: review,
    selections and job result agree."""
    settings, path = titus
    engine, requests, _ = _open(settings, path)
    _cancel_right_after_the_first_store(engine, monkeypatch)

    snapshot = _finish(engine, _start(engine, "verse"))

    # Nothing was left to cancel: the only verse of the job is done.
    assert snapshot["state"] == "succeeded", snapshot
    assert snapshot["results"]["1:1"]["status"] == "succeeded"
    assert snapshot["results"]["1:1"]["appliedCount"] > 0
    assert engine.project.ai_review_cache_status("1", "1") == "current"
    assert _listed(engine)["aiReviewState"] == "current"
    assert _counted(settings) == TOKENS_PER_CALL * len(requests)


def test_a_chapter_cancelled_after_its_first_verse_keeps_that_verse(titus, monkeypatch):
    settings, path = titus
    engine, requests, _ = _open(settings, path)
    _cancel_right_after_the_first_store(engine, monkeypatch)

    snapshot = _finish(engine, _start(engine, "chapter"))

    assert snapshot["state"] == "cancelled", snapshot
    assert list(snapshot["results"]) == ["1:1"]
    assert snapshot["results"]["1:1"]["status"] == "succeeded"
    assert engine.project.ai_review_cache_status("1", "1") == "current"
    for verse in VERSES[1:]:
        assert engine.project.load_ai_review_result("1", verse) is None, verse
    assert _counted(settings) == TOKENS_PER_CALL * len(requests)
    # Retry resumes with the four verses that have no result.
    retried = call(engine, "ai.review.retry", {"jobId": snapshot["jobId"]})
    assert retried["success"] is True, retried
    resumed = _finish(engine, retried["result"]["jobId"])
    assert resumed["state"] == "succeeded", resumed
    assert resumed["totalVerses"] == 4 and resumed["skippedCurrentVerses"] == 1
