"""#506: an AI review job stops when the provider will accept nothing more.

On a ChatGPT plan the limit can be reached in the middle of a whole-book pass.
Without `halt` every remaining verse would be prepared, refused and recorded as
its own failure. With it the job ends at that point as failed, with the reason,
and Retry picks up from the verses that have no succeeded result."""
from __future__ import annotations

import time

from ai_review_jobs import AIReviewJobManager, AIReviewJobSpec
from tests.support.waits import job_timeout

REASON = "Your ChatGPT plan limit has been reached."


def _wait(manager, job_id, timeout=2):
    deadline = time.monotonic() + job_timeout(timeout)
    while time.monotonic() < deadline:
        snapshot = manager.status(job_id)
        if snapshot["state"] in {"succeeded", "failed", "cancelled"}:
            return snapshot
        time.sleep(0.01)
    raise AssertionError("AI review manager did not reach a terminal state")


def _spec():
    return AIReviewJobSpec(
        scope="chapter", mode="basic", project_path="C:/project",
        chapters=("1", "2"), chapter_verses={"1": ["1", "2", "3"], "2": ["1"]},
    )


def test_job_stops_at_the_verse_that_met_the_limit_and_retry_resumes_from_there():
    manager = AIReviewJobManager()
    halted = {"reason": ""}
    ran: list[str] = []

    def run_verse(chapter, verse, mode, progress, cancel_event):
        ran.append(f"{chapter}:{verse}")
        if (chapter, verse) == ("1", "2"):
            halted["reason"] = REASON  # what the plan client's session does
            raise RuntimeError(REASON)
        return {"summary": "ok"}

    started = manager.start(_spec(), run_verse=run_verse, halt=lambda: halted["reason"])
    terminal = _wait(manager, started["jobId"])

    assert ran == ["1:1", "1:2"]  # 1:3 and 2:1 were never prepared or sent
    assert terminal["state"] == "failed" and terminal["error"] == REASON
    assert terminal["results"]["1:1"]["status"] == "succeeded"
    assert terminal["results"]["1:2"]["status"] == "failed"
    assert "1:3" not in terminal["results"] and "2:1" not in terminal["results"]

    retry = manager.spec_for_retry(started["jobId"])
    assert retry.chapter_verses == {"1": ["2", "3"], "2": ["1"]}


def test_job_that_meets_the_limit_on_its_last_verse_is_not_reported_as_finished():
    manager = AIReviewJobManager()
    halted = {"reason": ""}

    def run_verse(chapter, verse, mode, progress, cancel_event):
        if (chapter, verse) == ("2", "1"):
            halted["reason"] = REASON
            raise RuntimeError(REASON)
        return {"summary": "ok"}

    started = manager.start(_spec(), run_verse=run_verse, halt=lambda: halted["reason"])
    terminal = _wait(manager, started["jobId"])
    assert terminal["state"] == "failed" and terminal["error"] == REASON


def test_job_does_not_start_while_the_provider_is_already_refusing():
    manager = AIReviewJobManager()
    ran: list[str] = []
    started = manager.start(
        _spec(), run_verse=lambda *args: ran.append("sent") or {"summary": "ok"}, halt=lambda: REASON,
    )
    terminal = _wait(manager, started["jobId"])
    assert ran == [] and terminal["state"] == "failed" and terminal["error"] == REASON


def test_windowed_job_stops_between_chapters():
    manager = AIReviewJobManager()
    halted = {"reason": ""}
    chapters: list[str] = []

    def run_chapter(chapter, verses, mode, report, cancel_event):
        chapters.append(chapter)
        for verse in verses:
            report.result(verse, error=REASON)
        halted["reason"] = REASON

    started = manager.start(
        _spec(), run_verse=lambda *args: {"summary": "unused"}, run_chapter=run_chapter,
        halt=lambda: halted["reason"],
    )
    terminal = _wait(manager, started["jobId"])
    assert chapters == ["1"] and terminal["state"] == "failed" and terminal["error"] == REASON


def test_job_without_a_halt_check_runs_as_it_always_has():
    manager = AIReviewJobManager()
    started = manager.start(_spec(), run_verse=lambda *args: {"summary": "ok"})
    terminal = _wait(manager, started["jobId"])
    assert terminal["state"] == "succeeded" and len(terminal["results"]) == 4
