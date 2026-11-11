"""#480: a semantic-mapping call the provider never answers fails the verse.

On #469 run 2 the mapping call for GEN 1:1 and 1:25 ran past the client's
240 s read timeout. `prepare_semantic_mappings_for_review` folded that into a
`mapping_error` state, the review call still ran (and was billed), every check
came back `review` with no selection, and the verse was stored as a finished,
current review the chapter job's Retry would never touch.

Driven through the live ai.review job with a fake transport, against the real
Stage 3 semantic-source DB (the mapping call is only made when a unit resolves
there), so the whole path is the production one: the mapping request is sent,
the transport raises, the verse fails, no review request is sent, nothing is
stored as current, and Retry re-runs the verse. A non-transport mapping failure
keeps the fail-closed `mapping_error` behaviour: the verse completes.
"""
from __future__ import annotations

import json

import pytest
from bridge_service import BridgeEngine
from tc_ai_bridge.ai_client import AIError, AITransportError
from tests.support.ai_review import _wait_for_ai_job, imported_titus_project  # noqa: F401  (a fixture)
from tests.support.projects import call

MAPPING_SCHEMA = "bridge_semantic_mapping_v04"
REVIEW_SCHEMA = "tc_full_review"
ALIGNMENT_SCHEMA = "tc_alignment_proposal"


def _transport(mapping_failures: list[Exception], sent: list[str]):
    """Answer the gap-fill and review calls; raise the next queued exception
    for a mapping call, or answer it with a schema the engine rejects once the
    queue is empty (a non-transport failure, fail-closed to `mapping_error`)."""
    alignment_payload = {"links": [], "implicit_top_ids": [], "target_only_ids": [], "review_notes": []}

    def transport(url, headers, body, timeout):
        request = json.loads(body.decode("utf-8"))
        schema_name = request.get("text", {}).get("format", {}).get("name", "")
        sent.append(schema_name)
        if schema_name == MAPPING_SCHEMA:
            if mapping_failures:
                raise mapping_failures.pop(0)
            payload = {"not": "a mapping result"}
        elif schema_name == ALIGNMENT_SCHEMA:
            payload = alignment_payload
        else:
            review_input = json.loads(request["input"])
            target_id = review_input["target_bottomWords"][0]["id"]
            payload = {
                "summary": "Grounded automatic review.",
                "check_reviews": [
                    {
                        "tool": check["tool"], "group_id": check["groupId"],
                        "check_id": check["checkId"], "source_quote": check.get("source_quote") or "",
                        "selection_ids": [target_id], "nothing_to_select": False,
                        "verdict": "pass", "severity": "info", "rationale": "Supported by bundled evidence.",
                        "suggested_correction": "", "confidence": 0.91,
                        "evidence_ids": check["evidence_ids"][:1],
                    }
                    for check in review_input["translationCore_checks"]
                ],
                "qa_issues": [],
            }
        return 200, json.dumps({
            "output_text": json.dumps(payload),
            "usage": {"input_tokens": 200, "output_tokens": 80, "total_tokens": 280,
                      "input_tokens_details": {"cached_tokens": 0}},
        }).encode("utf-8")

    return transport


def _run_verse_job(engine):
    started = call(engine, "ai.review.start", {
        "scope": "verse", "chapter": "1", "verse": "1", "mode": "basic",
    })
    assert started["success"] is True, started
    return _wait_for_ai_job(engine, started["result"]["jobId"], timeout=30)


def test_mapping_timeout_fails_the_verse_and_retry_reruns_it(
    imported_titus_project, stage3_db, monkeypatch,
):
    if not stage3_db.is_file():
        pytest.skip(f"Stage 3 semantic-source DB not present: {stage3_db}")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # The autouse isolation fixture points this at a path that never exists so
    # mapping reports `unavailable`; this test needs the real mapping call.
    monkeypatch.setenv("BRIDGE_SEMANTIC_SOURCE_DB", str(stage3_db))
    settings, project_path = imported_titus_project
    settings.set_api_key("sk-test-123")
    sent: list[str] = []
    engine = BridgeEngine(settings=settings, ai_transport=_transport(
        [AITransportError("Network error contacting OpenAI: The read operation timed out")], sent,
    ))
    call(engine, "project.open", {"path": project_path})

    snapshot = _run_verse_job(engine)
    assert sent == [MAPPING_SCHEMA], sent  # the mapping request was sent, nothing after it
    assert snapshot["state"] == "failed", snapshot
    verse = snapshot["results"]["1:1"]
    assert verse["status"] == "failed"
    assert "Semantic mapping was not answered by the provider" in verse["error"]
    assert "timed out" in verse["error"]
    assert snapshot["latestResult"]["result"]["checkReviews"] == []
    # Nothing was stored as a finished review: the AI tab shows the verse as
    # unreviewed, not as current with every check forced to `review`.
    listed = call(engine, "check.listForVerse", {"chapter": "1", "verse": "1"})
    assert listed["success"] is True, listed
    assert listed["result"]["aiReviewState"] != "current"
    assert listed["result"].get("aiReviews", []) == []

    # Retry re-runs the failed verse. This time the mapping call is answered
    # with something the engine rejects (a schema failure, not a transport
    # one): that stays fail-closed to `mapping_error` and the verse completes.
    retried = call(engine, "ai.review.retry", {"jobId": snapshot["jobId"]})
    assert retried["success"] is True, retried
    again = _wait_for_ai_job(engine, retried["result"]["jobId"], timeout=30)
    assert again["state"] == "succeeded", again
    assert sent[1] == MAPPING_SCHEMA and REVIEW_SCHEMA in sent[2:], sent
    result = again["latestResult"]["result"]
    assert result["status"] == "succeeded"
    assert result["checkReviews"]
    listed = call(engine, "check.listForVerse", {"chapter": "1", "verse": "1"})
    assert listed["result"]["aiReviewState"] == "current"


def test_default_transport_wraps_a_body_read_timeout(monkeypatch):
    """A timeout while the body is read arrives as a raw TimeoutError, not a
    URLError; the default transport reports it as the same transport failure
    so the mapping and review paths treat it as "never answered"."""
    from tc_ai_bridge import ai_client

    class _Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            raise TimeoutError("The read operation timed out")

    monkeypatch.setattr(ai_client.ai_http, "urlopen", lambda req, timeout: _Response())
    with pytest.raises(AITransportError, match="timed out"):
        ai_client.default_transport("https://example.invalid/v1/responses", {}, b"{}", 1.0)
    assert issubclass(AITransportError, AIError)
