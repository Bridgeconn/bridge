"""#221: chapter-wide automatic alignment as a background job.

Windows of three verses overlapping by one; each window is one
alignment.window.autoAlign. Fake transport only.
"""
import json
import threading
import time

import pytest

from alignment_auto_align_jobs import AutoAlignJobError, windows_for
from bridge_service import BridgeEngine
from tc_ai_bridge.chatgpt_session import ChatGPTSession
from tc_ai_bridge.secret_store import AppSettings
from tests.support import chatgpt as fake_chatgpt
from tests.support.alignment_books import unaligned_verse, write_alignment_book
from tests.support.projects import call
from tests.support.waits import job_timeout


def test_windows_overlap_by_one_and_cover_every_verse():
    assert windows_for(["1", "2", "3", "4", "5", "6"]) == [["1", "2", "3"], ["3", "4", "5"], ["5", "6"]]
    assert windows_for(["1", "2", "3", "4", "5"]) == [["1", "2", "3"], ["3", "4", "5"]]
    assert windows_for(["1", "2"]) == [["1", "2"]]
    assert windows_for([]) == []
    assert windows_for(["1", "2-3", "4", "5"], window=2, overlap=0) == [["1", "2-3"], ["4", "5"]]
    with pytest.raises(AutoAlignJobError):
        windows_for(["1", "2", "3"], window=3, overlap=3)


def _empty_reply():
    return {"links": [], "nulls": [], "unplaced": [], "review_notes": []}


def transport(captured, delay=0.0):
    def send(url, headers, request_body, timeout):
        captured.append(json.loads(request_body))
        if delay:
            time.sleep(delay)
        return 200, json.dumps({
            "output_text": json.dumps(_empty_reply()),
            "usage": {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
        }).encode("utf-8")
    return send


@pytest.fixture
def root(tmp_path):
    root = tmp_path / "php"
    verses = {str(v): unaligned_verse(f"w{v}", [(f"λ{v}", f"G{1000 + v}0")]) for v in range(1, 7)}
    write_alignment_book(root, "php", {"1": verses})
    return root


def _wait(engine, job_id, timeout=10.0):
    deadline = time.monotonic() + job_timeout(timeout)
    while time.monotonic() < deadline:
        snapshot = call(engine, "alignment.autoAlign.status", {"jobId": job_id})["result"]
        if snapshot["state"] in {"succeeded", "failed", "cancelled"}:
            return snapshot
        time.sleep(0.02)
    raise AssertionError("auto-align job did not finish")


def _engine(root, send, key="test-key"):
    engine = BridgeEngine(ai_transport=send)
    engine.settings.set_api_key(key, persist=False)
    assert call(engine, "project.open", {"path": str(root)})["success"] is True
    return engine


def test_estimate_is_offline_and_counts_windows_and_calls(root):
    captured = []
    engine = _engine(root, transport(captured))
    estimate = call(engine, "alignment.autoAlign.estimate", {"scope": "chapter", "chapters": ["1"]})
    assert estimate["success"] is True, estimate
    result = estimate["result"]
    assert result["windows"] == 3 and result["calls"] == 6
    assert result["estimatedInputTokens"] > 0 and result["hasApiKey"] is True
    assert captured == []


def test_a_chapter_job_runs_every_window_twice_and_records_verdicts(root):
    captured = []
    engine = _engine(root, transport(captured))
    started = call(engine, "alignment.autoAlign.start", {"scope": "chapter", "chapters": ["1"]})
    assert started["success"] is True, started
    snapshot = _wait(engine, started["result"]["jobId"])
    assert snapshot["state"] == "succeeded", snapshot
    assert snapshot["windowsTotal"] == 3 and snapshot["windowsDone"] == 3
    assert len(captured) == 6 and snapshot["usage"]["calls"] == 6
    # Every verse has a verdict; nothing was placed, so every word is reported.
    assert set(snapshot["verdicts"]) == {f"1:{v}" for v in range(1, 7)}
    assert set(snapshot["verdicts"].values()) == {"NEEDS_REVIEW"}
    stored = call(engine, "alignment.autoAlign.verdict", {"chapter": "1", "verse": "3"})["result"]["verdict"]
    assert stored["jobId"] == snapshot["jobId"] and stored["window"] == ["3", "4", "5"]


def test_without_a_key_the_job_does_not_start(root):
    captured = []
    engine = _engine(root, transport(captured), key="")
    started = call(engine, "alignment.autoAlign.start", {"scope": "chapter", "chapters": ["1"]})
    assert started["success"] is True
    assert started["result"]["unavailable"]["reason"] == "no-api-key"
    assert captured == []


def test_cancel_stops_between_requests_and_retry_runs_what_is_left(root):
    captured = []
    engine = _engine(root, transport(captured, delay=0.15))
    job_id = call(engine, "alignment.autoAlign.start", {"scope": "chapter", "chapters": ["1"]})["result"]["jobId"]
    deadline = time.monotonic() + job_timeout(5.0)
    while not captured and time.monotonic() < deadline:
        time.sleep(0.01)
    call(engine, "alignment.autoAlign.cancel", {"jobId": job_id})
    snapshot = _wait(engine, job_id)
    assert snapshot["state"] == "cancelled"
    assert snapshot["windowsDone"] < snapshot["windowsTotal"]
    retried = call(engine, "alignment.autoAlign.retry", {"jobId": job_id})
    assert retried["success"] is True, retried
    second = _wait(engine, retried["result"]["jobId"])
    assert second["state"] == "succeeded" and second["resumeOf"] == job_id
    assert second["windowsTotal"] == 3 - snapshot["windowsDone"]


def test_a_second_job_while_one_runs_is_refused(root):
    captured = []
    engine = _engine(root, transport(captured, delay=0.2))
    first = call(engine, "alignment.autoAlign.start", {"scope": "chapter", "chapters": ["1"]})["result"]
    second = call(engine, "alignment.autoAlign.start", {"scope": "chapter", "chapters": ["1"]})
    assert second["success"] is False and "already" in second["error"]["message"]
    call(engine, "alignment.autoAlign.cancel", {"jobId": first["jobId"]})
    _wait(engine, first["jobId"])


# -- several chapters in one job ("Align with AI", 2026-11-24) ----------------
#
# The dialog lets a reviewer pick several chapters or the whole book. The job
# has always accepted a list of chapters; nothing tested more than one.


@pytest.fixture
def two_chapters(tmp_path):
    root = tmp_path / "php"
    first = {str(v): unaligned_verse(f"w{v}", [(f"λ{v}", f"G{1000 + v}0")]) for v in range(1, 7)}
    second = {str(v): unaligned_verse(f"x{v}", [(f"μ{v}", f"G{2000 + v}0")]) for v in range(1, 5)}
    write_alignment_book(root, "php", {"1": first, "2": second})
    return root


def test_a_job_over_two_chapters_runs_every_window_of_both(two_chapters):
    captured = []
    engine = _engine(two_chapters, transport(captured))
    estimate = call(engine, "alignment.autoAlign.estimate", {"scope": "chapter", "chapters": ["1", "2"]})["result"]
    assert estimate["chapters"] == ["1", "2"] and estimate["windows"] == 5 and estimate["calls"] == 10
    assert captured == []

    started = call(engine, "alignment.autoAlign.start", {"scope": "chapter", "chapters": ["1", "2"]})
    assert started["success"] is True, started
    # What each chapter has to run, for a progress display per chapter.
    assert started["result"]["chapterWindows"] == {"1": 3, "2": 2}
    snapshot = _wait(engine, started["result"]["jobId"])

    assert snapshot["state"] == "succeeded", snapshot
    assert snapshot["chapters"] == ["1", "2"]
    assert snapshot["windowsTotal"] == 5 and snapshot["windowsDone"] == 5
    assert len(captured) == 10 and snapshot["usage"]["calls"] == 10
    assert set(snapshot["verdicts"]) == {f"1:{v}" for v in range(1, 7)} | {f"2:{v}" for v in range(1, 5)}
    assert sorted(snapshot["results"]) == ["1:1-3", "1:3-5", "1:5-6", "2:1-3", "2:3-4"]
    for chapter, verse in (("1", "6"), ("2", "4")):
        stored = call(engine, "alignment.autoAlign.verdict", {"chapter": chapter, "verse": verse})["result"]["verdict"]
        assert stored["jobId"] == snapshot["jobId"]


def test_the_whole_book_is_the_same_job_as_all_its_chapters(two_chapters):
    captured = []
    engine = _engine(two_chapters, transport(captured))
    started = call(engine, "alignment.autoAlign.start", {"scope": "book"})["result"]
    assert started["chapters"] == ["1", "2"] and started["chapterWindows"] == {"1": 3, "2": 2}
    assert _wait(engine, started["jobId"])["state"] == "succeeded"
    assert len(captured) == 10


def test_cancel_in_the_second_chapter_keeps_the_first_and_retry_runs_only_the_rest(two_chapters):
    """The reviewer cancels a long run. The chapter that was finished keeps
    what it wrote; Resume runs the windows that have no result."""
    captured = []
    reached_chapter_two = threading.Event()
    release = threading.Event()
    answer = transport(captured)

    def send(url, headers, request_body, timeout):
        # Chapter 1 is three windows, two requests each: the seventh request
        # is the first of chapter 2.
        if len(captured) == 6:
            reached_chapter_two.set()
            assert release.wait(10)
        return answer(url, headers, request_body, timeout)

    engine = _engine(two_chapters, send)
    job_id = call(engine, "alignment.autoAlign.start", {"scope": "chapter", "chapters": ["1", "2"]})["result"]["jobId"]
    assert reached_chapter_two.wait(job_timeout(10.0))
    call(engine, "alignment.autoAlign.cancel", {"jobId": job_id})
    release.set()
    snapshot = _wait(engine, job_id)

    assert snapshot["state"] == "cancelled", snapshot
    assert sorted(snapshot["results"]) == ["1:1-3", "1:3-5", "1:5-6"]
    assert all(result["status"] == "succeeded" for result in snapshot["results"].values())
    assert set(snapshot["verdicts"]) == {f"1:{v}" for v in range(1, 7)}
    # Chapter 1's verdicts are stored; chapter 2 has none: its window in
    # flight wrote nothing (#242).
    assert call(engine, "alignment.autoAlign.verdict", {"chapter": "1", "verse": "1"})["result"]["verdict"]
    assert call(engine, "alignment.autoAlign.verdict", {"chapter": "2", "verse": "1"})["result"]["verdict"] is None

    sent_before_retry = len(captured)
    retried = call(engine, "alignment.autoAlign.retry", {"jobId": job_id})
    assert retried["success"] is True, retried
    assert retried["result"]["chapterWindows"] == {"1": 0, "2": 2}
    second = _wait(engine, retried["result"]["jobId"])
    assert second["state"] == "succeeded" and second["resumeOf"] == job_id
    assert sorted(second["results"]) == ["2:1-3", "2:3-4"]
    assert len(captured) - sent_before_retry == 4


def test_a_chatgpt_plan_limit_stops_the_job_and_sends_nothing_more(root, tmp_path):
    """The stop the AI review job has (#506). Without it every window left
    after the limit was sent and refused in turn: a whole book of them."""
    captured = []
    answer = transport(captured)

    def plan_transport(url, headers, body, timeout):
        assert headers["Authorization"] == "Bearer access-1"
        if len(captured) == 2:  # window 1 is done; this is window 2's first request
            captured.append(json.loads(body))
            return 429, json.dumps({"error": {
                "code": "subscription_sharing_usage_limit_exceeded", "message": "limit reached",
            }}).encode("utf-8")
        return answer(url, headers, body, timeout)

    settings = AppSettings(path=tmp_path / "settings.json")
    engine = BridgeEngine(settings=settings, ai_transport=plan_transport)
    engine._chatgpt = ChatGPTSession(
        settings, http=fake_chatgpt.FakeHttp(), sign_in=lambda **kwargs: fake_chatgpt.signed_in_result(),
    )
    engine.chatgpt_session.start_sign_in()
    deadline = time.monotonic() + 5
    while not engine.chatgpt_session.is_signed_in() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert call(engine, "settings.set", {"provider": "chatgpt"})["success"]
    assert call(engine, "project.open", {"path": str(root)})["success"] is True

    started = call(engine, "alignment.autoAlign.start", {"scope": "chapter", "chapters": ["1"]})
    assert started["success"] is True, started
    snapshot = _wait(engine, started["result"]["jobId"])

    assert snapshot["state"] == "failed" and "plan limit" in snapshot["error"], snapshot
    assert snapshot["results"]["1:1-3"]["status"] == "succeeded"
    assert snapshot["results"]["1:3-5"]["status"] == "failed"
    # The third window was never asked about: no result, and no request.
    assert "1:5-6" not in snapshot["results"]
    assert len(captured) == 3
    retry = engine._auto_align_jobs.spec_for_retry(snapshot["jobId"])
    assert retry.windows == {"1": [["3", "4", "5"], ["5", "6"]]}
