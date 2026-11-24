import threading
import time

from ai_review_jobs import AIReviewJobManager, AIReviewJobSpec
from tests.support.waits import job_timeout


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
        chapters=("1",), chapter_verses={"1": ["1", "2"]},
    )


def test_cancel_waits_for_inflight_request_and_keeps_a_verse_the_worker_finished():
    """#513. This test used to assert that a payload returned after a cancel
    was thrown away. The worker now decides: it looks at the cancel before it
    stores a verse's review and raises if it is set (the next test). A payload
    therefore means the verse was stored and finished, and the job must say
    so; the cancel stops the verses after it."""
    manager = AIReviewJobManager()
    entered = threading.Event()
    release = threading.Event()
    ran: list[str] = []

    def run_verse(chapter, verse, mode, progress, cancel_event):
        ran.append(verse)
        entered.set()
        assert release.wait(1)
        return {"summary": "finished remotely", "appliedSelections": [{"checkId": "applied"}]}

    started = manager.start(_spec(), run_verse=run_verse)
    assert entered.wait(1)
    cancelling = manager.cancel(started["jobId"])
    assert cancelling["state"] == "cancelling"
    release.set()
    terminal = _wait(manager, started["jobId"])

    assert terminal["state"] == "cancelled"
    assert ran == ["1"], "the second verse must not start after the cancel"
    assert list(terminal["results"]) == ["1:1"]
    assert terminal["results"]["1:1"]["status"] == "succeeded"
    assert terminal["latestResult"]["key"] == "1:1"
    # Retry resumes with the verse that has no result.
    assert manager.spec_for_retry(started["jobId"]).chapter_verses == {"1": ["2"]}


def test_a_cancel_with_nothing_left_to_stop_ends_the_job_as_what_it_is():
    """#513: the only verse was stored and finished when the cancel arrived.
    A job with all its work done is not a cancelled job."""
    manager = AIReviewJobManager()
    entered = threading.Event()
    release = threading.Event()

    def run_verse(chapter, verse, mode, progress, cancel_event):
        entered.set()
        assert release.wait(1)
        return {"summary": "stored before the cancel"}

    spec = AIReviewJobSpec(
        scope="verse", mode="basic", project_path="C:/project",
        chapters=("1",), chapter_verses={"1": ["1"]},
    )
    started = manager.start(spec, run_verse=run_verse)
    assert entered.wait(1)
    manager.cancel(started["jobId"])
    release.set()
    terminal = _wait(manager, started["jobId"])

    assert terminal["state"] == "succeeded"
    assert terminal["currentStage"] == "Complete"
    assert terminal["results"]["1:1"]["status"] == "succeeded"


def test_a_window_run_keeps_a_stored_verse_and_drops_an_error_after_a_cancel():
    """The same rule for several verses per request (#502): after a cancel a
    reported payload is a finished verse, a reported error is the cancel."""
    manager = AIReviewJobManager()

    def run_chapter(chapter, verses, mode, report, cancel_event):
        cancel_event.set()
        report.result("1", {"summary": "stored before the cancel was seen"})
        report.result("2", error="AI review cancelled")

    started = manager.start(_spec(), run_verse=lambda *a: {}, run_chapter=run_chapter)
    terminal = _wait(manager, started["jobId"])

    assert terminal["state"] == "cancelled"
    assert list(terminal["results"]) == ["1:1"]
    assert terminal["results"]["1:1"]["status"] == "succeeded"
    assert terminal["failedVerses"] == 0


def test_cancelled_inflight_worker_exception_is_not_reported_as_ai_failure():
    manager = AIReviewJobManager()
    entered = threading.Event()
    release = threading.Event()

    def raise_after_cancel(chapter, verse, mode, progress, cancel_event):
        entered.set()
        assert release.wait(1)
        assert cancel_event.is_set()
        raise RuntimeError("AI review cancelled; completed result was discarded")

    started = manager.start(_spec(), run_verse=raise_after_cancel)
    assert entered.wait(1)
    manager.cancel(started["jobId"])
    release.set()
    terminal = _wait(manager, started["jobId"])

    assert terminal["state"] == "cancelled"
    assert terminal["failedVerses"] == 0
    assert terminal["error"] is None
    assert terminal["results"] == {}
    assert terminal["latestResult"] is None


def test_failed_job_retains_compact_status_and_can_retry_from_same_spec():
    manager = AIReviewJobManager()

    def fail_first(chapter, verse, mode, progress, cancel_event):
        if verse == "1":
            raise RuntimeError("provider unavailable")
        return {"summary": "second verse", "checkReviews": [], "appliedSelections": []}

    started = manager.start(_spec(), run_verse=fail_first)
    failed = _wait(manager, started["jobId"])
    assert failed["state"] == "failed"
    assert failed["results"]["1:1"]["error"] == "provider unavailable"
    assert "checkReviews" not in failed["results"]["1:2"]
    assert failed["latestResult"]["result"]["checkReviews"] == []

    retry_spec = manager.spec_for_retry(started["jobId"])
    retried = manager.start(
        retry_spec,
        run_verse=lambda chapter, verse, mode, progress, cancel: {
            "summary": "ok", "checkReviews": [], "appliedSelections": [],
        },
    )
    succeeded = _wait(manager, retried["jobId"])
    assert succeeded["state"] == "succeeded"
    assert succeeded["completedVerses"] == 1
    assert succeeded["totalVerses"] == 1
    assert succeeded["skippedCurrentVerses"] == 1
    assert succeeded["resumeOf"] == started["jobId"]
