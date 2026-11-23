"""#502: several verses per review request, through `ai.review.start`.

A five-verse Titus 1 with a section heading before verse 4, real bundled
translationNotes / translationWords, and a transport that records every
request and answers from the request's own ids.
"""
from __future__ import annotations

import json
import time

import pytest

from bridge_service import BridgeEngine
from tc_ai_bridge import ai_review_windows
from tc_ai_bridge.chatgpt_session import ChatGPTSession
from tc_ai_bridge.secret_store import AppSettings
from tests.support import chatgpt as fake_chatgpt
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


@pytest.fixture
def titus_five(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # The tests are about window mechanics. #474's caps (24 checks, 60,000
    # characters) would cut these real Titus verses into windows of one or
    # two; the cap rule itself is unit-tested in tests/ai.
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


def _answer_review(review_input: dict, spoil=None) -> dict:
    """A grounded answer for a single-verse or a window review request."""
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
        for check in block["translationCore_checks"]:
            row = {"reference": block["reference"], **_row(check, target_id)}
            rows.append(spoil(block, row) if spoil else row)
    return {
        "summaries": [{"reference": b["reference"], "summary": f"Grounded {b['reference']}."} for b in review_input["verses"]],
        "check_reviews": rows,
        "qa_issues": [],
    }


def _row(check: dict, target_id: str) -> dict:
    return {
        "tool": check["tool"], "group_id": check["groupId"], "check_id": check["checkId"],
        "source_quote": check.get("source_quote") or "",
        "selection_ids": [target_id], "nothing_to_select": False,
        "verdict": "pass", "severity": "info", "rationale": "Supported by bundled evidence.",
        "suggested_correction": "", "confidence": 0.91, "evidence_ids": check["evidence_ids"][:1],
    }


def _transport(requests: list[dict], *, review=None, spoil=None):
    """Records each request. `review(request, input)` may return a raw
    `(status, bytes)` to stand in for the provider on a review request."""
    def transport(url, headers, body, timeout):
        request = json.loads(body.decode("utf-8"))
        request["_timeout"] = timeout
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
            if review is not None:
                raw = review(request, request_input)
                if raw is not None:
                    return raw
            payload = _answer_review(request_input, spoil)
        return 200, json.dumps({
            "output_text": json.dumps(payload),
            "usage": {"input_tokens": 1000, "output_tokens": 300, "total_tokens": 1300,
                      "input_tokens_details": {"cached_tokens": 0}},
        }).encode("utf-8")
    return transport


def _reviews(requests: list[dict]) -> list[dict]:
    return [r for r in requests if r["text"]["format"]["name"] in ("tc_full_review", "tc_window_review")]


def _window_verses(request: dict) -> list[str]:
    return [block["reference"].split(":")[1] for block in json.loads(request["input"])["verses"]]


def _run_chapter(engine):
    started = call(engine, "ai.review.start", {"scope": "chapter", "chapter": "1", "mode": "basic"})
    assert started["success"] is True, started
    return _wait_for_ai_job(engine, started["result"]["jobId"], timeout=60)


def _open(settings, path, requests, **transport_options):
    engine = BridgeEngine(settings=settings, ai_transport=_transport(requests, **transport_options))
    call(engine, "project.open", {"path": path})
    return engine


def test_one_verse_per_request_is_the_default_and_is_the_single_verse_review(titus_five):
    settings, path = titus_five
    requests: list[dict] = []
    engine = _open(settings, path, requests)
    assert call(engine, "settings.get")["result"]["aiReview"]["versesPerRequest"] == 1

    snapshot = _run_chapter(engine)
    assert snapshot["state"] == "succeeded", snapshot
    assert snapshot["currentWindow"] == []
    reviews = _reviews(requests)
    assert [r["text"]["format"]["name"] for r in reviews] == ["tc_full_review"] * 5
    assert all("verses" not in json.loads(r["input"]) for r in reviews)
    for verse in VERSES:
        stored = engine.project.load_ai_review_result("1", verse)
        assert "batch" not in stored
        assert engine.project.ai_review_cache_status("1", verse) == "current"


def test_a_window_is_one_request_and_one_stored_review_per_verse(titus_five):
    settings, path = titus_five
    requests: list[dict] = []
    engine = _open(settings, path, requests)
    changed = call(engine, "settings.set", {"aiReview": {"versesPerRequest": 4}})
    assert changed["result"]["aiReview"]["versesPerRequest"] == 4
    assert call(engine, "settings.set", {"aiReview": {"versesPerRequest": 7}})["success"] is False
    assert call(engine, "settings.set", {"aiReview": {"versesPerRequest": True}})["success"] is False

    snapshot = _run_chapter(engine)
    assert snapshot["state"] == "succeeded", snapshot
    assert snapshot["completedVerses"] == 5 and snapshot["failedVerses"] == 0

    reviews = _reviews(requests)
    # Verses 1-3, then the heading before verse 4 starts a new window.
    assert [r["text"]["format"]["name"] for r in reviews] == ["tc_window_review"] * 2
    assert [_window_verses(r) for r in reviews] == [["1", "2", "3"], ["4", "5"]]
    assert [r["_timeout"] for r in reviews] == [240.0, 240.0]

    first = json.loads(reviews[0]["input"])
    assert list(first)[:4] == ["language_context", "project_reviewer_decisions", "evidence_catalog", "verses"]
    total_checks = sum(len(b["translationCore_checks"]) for b in first["verses"])
    array = reviews[0]["text"]["format"]["schema"]["properties"]["check_reviews"]
    assert array["minItems"] == total_checks == array["maxItems"]
    assert f"{total_checks} input checks across 3 verse(s)" in reviews[0]["instructions"]
    # One catalog for the window: an article two verses cite is there once.
    cited = [eid for b in first["verses"] for c in b["translationCore_checks"] for eid in c["evidence_ids"]]
    assert set(cited) <= set(first["evidence_catalog"])
    shared = [eid for eid in set(cited) if eid.startswith(("tw:", "ta:"))
              and sum(1 for b in first["verses"] if any(eid in c["evidence_ids"] for c in b["translationCore_checks"])) > 1]
    assert shared, "Titus 1:1-3 share at least one article (God)"
    # Token ids name their verse.
    for block in first["verses"]:
        verse = block["reference"].split(":")[1]
        assert all(t["id"].startswith(f"{verse}|") for t in block["target_bottomWords"] + block["source_topWords"])

    # One stored review per verse, each with its own fingerprint, current.
    window_ids = set()
    for verse in VERSES:
        stored = engine.project.load_ai_review_result("1", verse)
        assert stored["verse"] == verse and stored["checkReviews"]
        assert stored["inputFingerprint"] and engine.project.ai_review_cache_status("1", verse) == "current"
        batch = stored["batch"]
        assert verse in batch["verses"] and batch["attempt"] == 0 and batch["chapterContext"] is False
        assert batch["windowUsage"]["inputTokens"] == 1000
        window_ids.add(batch["windowId"])
        # #501: the shadow record is stored for a window verse too, and is in no request.
        assert stored["localTwShadow"]["mode"] == "shadow" and "error" not in stored["localTwShadow"]
        # The verse's own usage: its mapping and gap-fill calls, and its share of the window call.
        assert stored["usage"]["calls"] >= 2 and stored["usage"]["inputTokens"] > 0
        assert stored["summary"] == f"Grounded tit 1:{verse}."
        selections = stored["checkReviews"][0]["proposed_selections"]
        assert selections and selections[0]["text"] in ("Paul", "In", "He", "To", "For")
    assert len(window_ids) == 2
    assert all("localTwShadow" not in r["input"] and "wouldPass" not in r["input"] for r in requests)
    fingerprints = {engine.project.load_ai_review_result("1", v)["inputFingerprint"] for v in VERSES}
    assert len(fingerprints) == 5
    # A window's shares add up to the window.
    for window in (["1", "2", "3"], ["4", "5"]):
        shares = [engine.project.load_ai_review_result("1", v)["batch"]["share"] for v in window]
        assert sum(shares) == pytest.approx(1.0, abs=1e-4)
    # The job's results are per verse, as ever, and safe selections were applied.
    assert set(snapshot["results"]) == {f"1:{v}" for v in VERSES}
    assert sum(item["appliedCount"] for item in snapshot["results"].values()) > 0

    # A second chapter run finds every verse current and sends nothing.
    requests.clear()
    again = _run_chapter(engine)
    assert again["totalVerses"] == 0 and again["skippedCurrentVerses"] == 5 and not _reviews(requests)


def test_a_failed_window_is_retried_at_half_size_then_verse_by_verse(titus_five):
    settings, path = titus_five
    requests: list[dict] = []

    def review(request, request_input):
        verses = request_input.get("verses") or []
        # Anything holding verse 2 together with another verse comes back as text that is not JSON.
        if len(verses) > 1 and any(b["reference"].endswith(":2") for b in verses):
            return 200, json.dumps({"output_text": "not json", "usage": {
                "input_tokens": 900, "output_tokens": 10, "total_tokens": 910}}).encode("utf-8")
        return None

    engine = _open(settings, path, requests, review=review)
    call(engine, "settings.set", {"aiReview": {"versesPerRequest": 4}})
    snapshot = _run_chapter(engine)
    assert snapshot["state"] == "succeeded", snapshot

    # [1,2,3] fails; halves [1,2] and [3]; [1,2] fails; then 1 and 2 alone.
    assert [_window_verses(r) for r in _reviews(requests)] == [
        ["1", "2", "3"], ["1", "2"], ["1"], ["2"], ["3"], ["4", "5"],
    ]
    attempts = {v: engine.project.load_ai_review_result("1", v)["batch"]["attempt"] for v in VERSES}
    assert attempts == {"1": 2, "2": 2, "3": 1, "4": 0, "5": 0}
    # What the failed attempts cost is in the verses' usage: verse 1 took part
    # in three review requests, verse 4 in one.
    usage = {v: engine.project.load_ai_review_result("1", v)["usage"] for v in VERSES}
    assert usage["1"]["calls"] - usage["4"]["calls"] == 2
    assert all(engine.project.ai_review_cache_status("1", v) == "current" for v in VERSES)


def test_a_verse_whose_rows_cannot_be_accepted_fails_alone(titus_five):
    settings, path = titus_five
    requests: list[dict] = []

    def spoil(block, row):
        if block["reference"].endswith(":2"):
            return {**row, "selection_ids": ["1|T001"]}  # verse 1's word in a verse 2 row
        return row

    engine = _open(settings, path, requests, spoil=spoil)
    call(engine, "settings.set", {"aiReview": {"versesPerRequest": 4}})
    snapshot = _run_chapter(engine)

    assert snapshot["state"] == "failed" and snapshot["failedVerses"] == 1, snapshot
    assert snapshot["results"]["1:2"]["status"] == "failed"
    assert "unknown target-language token" in snapshot["results"]["1:2"]["error"]
    for verse in ("1", "3", "4", "5"):
        assert snapshot["results"][f"1:{verse}"]["status"] == "succeeded"
        assert engine.project.ai_review_cache_status("1", verse) == "current"
    assert engine.project.load_ai_review_result("1", "2") is None
    # The window was not retried: only the one verse was wrong.
    assert [_window_verses(r) for r in _reviews(requests)] == [["1", "2", "3"], ["4", "5"]]

    # Retry sends the failed verse only.
    requests.clear()
    retried = call(engine, "ai.review.retry", {"jobId": snapshot["jobId"]})
    assert retried["success"] is True, retried
    _wait_for_ai_job(engine, retried["result"]["jobId"], timeout=60)
    assert [_window_verses(r) for r in _reviews(requests)] == [["2"]]


def test_a_verse_edited_while_its_window_is_in_flight_is_discarded_alone(titus_five):
    settings, path = titus_five
    requests: list[dict] = []
    holder: dict = {}

    def review(request, request_input):
        if "edited" not in holder and any(b["reference"].endswith(":2") for b in request_input["verses"]):
            holder["edited"] = True
            project = holder["engine"].project
            project.apply_scripture_edit("1", "2", project.target_verse_text("1", "2") + " Amen.")
        return None

    engine = _open(settings, path, requests, review=review)
    holder["engine"] = engine
    call(engine, "settings.set", {"aiReview": {"versesPerRequest": 4}})
    snapshot = _run_chapter(engine)

    assert snapshot["results"]["1:2"]["status"] == "failed"
    assert "stale" in snapshot["results"]["1:2"]["error"]
    assert engine.project.load_ai_review_result("1", "2") is None
    for verse in ("1", "3", "4", "5"):
        assert snapshot["results"][f"1:{verse}"]["status"] == "succeeded"


def test_chapter_context_puts_one_identical_block_first_in_every_request(titus_five):
    settings, path = titus_five
    requests: list[dict] = []
    engine = _open(settings, path, requests)
    call(engine, "settings.set", {"aiReview": {"versesPerRequest": 2, "chapterContext": True}})
    snapshot = _run_chapter(engine)
    assert snapshot["state"] == "succeeded", snapshot

    reviews = _reviews(requests)
    assert [_window_verses(r) for r in reviews] == [["1", "2"], ["3"], ["4", "5"]]
    # The instructions and the schema carry no number, so they are the same
    # for every request of the chapter.
    assert len({r["instructions"] for r in reviews}) == 1
    assert len({json.dumps(r["text"]["format"]["schema"], sort_keys=True) for r in reviews}) == 1
    inputs = [json.loads(r["input"]) for r in reviews]
    # The shared block: the same bytes at the front of every input, through the catalog.
    marker = ', "verses": ['
    heads = {r["input"][: r["input"].index(marker)] for r in reviews}
    assert len(heads) == 1
    head = heads.pop()
    assert len(head) > 5000 and '"evidence_catalog"' in head
    # It holds every article any verse of the chapter cites, once.
    catalog = inputs[0]["evidence_catalog"]
    for request_input in inputs:
        assert request_input["evidence_catalog"] == catalog
        assert request_input["expected_check_reviews"] == sum(
            len(b["translationCore_checks"]) for b in request_input["verses"])
        for block in request_input["verses"]:
            for check in block["translationCore_checks"]:
                assert set(check["evidence_ids"]) <= set(catalog)
    assert all(engine.project.load_ai_review_result("1", v)["batch"]["chapterContext"] for v in VERSES)


def test_whole_chapter_sends_a_small_chapter_in_one_request(titus_five, monkeypatch):
    settings, path = titus_five
    monkeypatch.setattr(ai_review_windows, "CHAPTER_MAX_CHECKS", 10_000)
    monkeypatch.setattr(ai_review_windows, "CHAPTER_MAX_INPUT_CHARS", 10_000_000)
    requests: list[dict] = []
    engine = _open(settings, path, requests)
    call(engine, "settings.set", {"aiReview": {"wholeChapter": True}})
    snapshot = _run_chapter(engine)
    assert snapshot["state"] == "succeeded", snapshot
    reviews = _reviews(requests)
    # Under the caps the heading does not split the chapter.
    assert [_window_verses(r) for r in reviews] == [VERSES]
    assert reviews[0]["_timeout"] == 290.0  # 90 + 40 x 5
    assert all(engine.project.ai_review_cache_status("1", v) == "current" for v in VERSES)


def test_a_chatgpt_plan_limit_stops_the_chapter_where_it_is_met(titus_five):
    """#506. Verses 1-2 are reviewed; the window holding verse 3 meets the
    plan's limit. That window is not halved and re-sent, verse 4 (prepared, not
    yet sent) fails with the same reason, verse 5 is never prepared and has no
    result, and the job ends there so Retry can pick up 3, 4 and 5."""
    settings, path = titus_five
    requests: list[dict] = []
    review_requests = {"count": 0}

    def review(request, review_input):
        review_requests["count"] += 1
        if review_requests["count"] == 2:
            return 429, json.dumps({"error": {
                "code": "subscription_sharing_usage_limit_exceeded", "message": "limit reached",
            }}).encode("utf-8")
        return None

    inner = _transport(requests, review=review)

    def plan_transport(url, headers, body, timeout):
        # What the plan client sends: the session's token, streamed, the input
        # as a one-message list. Unwrapped here for the helper above.
        request = json.loads(body.decode("utf-8"))
        assert headers["Authorization"] == "Bearer access-1" and request["stream"] is True
        request["input"] = request["input"][0]["content"]
        return inner(url, headers, json.dumps(request).encode("utf-8"), timeout)

    engine = BridgeEngine(settings=settings, ai_transport=plan_transport)
    engine._chatgpt = ChatGPTSession(
        settings, http=fake_chatgpt.FakeHttp(), sign_in=lambda **kwargs: fake_chatgpt.signed_in_result(),
    )
    engine.chatgpt_session.start_sign_in()
    deadline = time.monotonic() + 5
    while not engine.chatgpt_session.is_signed_in() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert call(engine, "settings.set", {"provider": "chatgpt", "aiReview": {"versesPerRequest": 2}})["success"]
    call(engine, "project.open", {"path": path})

    snapshot = _run_chapter(engine)

    assert snapshot["state"] == "failed" and "plan limit" in snapshot["error"], snapshot["error"]
    results = snapshot["results"]
    assert results["1:1"]["status"] == "succeeded" and results["1:2"]["status"] == "succeeded"
    assert results["1:3"]["status"] == "failed" and "plan limit" in results["1:3"]["error"]
    assert results["1:4"]["status"] == "failed" and "plan limit" in results["1:4"]["error"]
    assert "1:5" not in results
    # Two review requests in all: verses 1-2, then the refused one. No halving.
    assert [_window_verses(r) for r in _reviews(requests)] == [["1", "2"], ["3"]]
    retry = engine._ai_review_jobs.spec_for_retry(snapshot["jobId"])
    assert retry.chapter_verses == {"1": ["3", "4", "5"]}
