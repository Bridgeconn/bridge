"""#476: a verse's usage is the sum of every request it made.

On #469 the OpenAI dashboard showed about 3.5 requests per verse while Bridge
counted the review call alone: the semantic mapping call and the gap-fill
alignment call were in neither the stored `usage`, nor `estimatedCostUSD`,
nor the lifetime counter (25-30% of the bill), and a call that timed out after
it was sent was billed by the provider and counted as free.

Driven through the live ai.review job with a fake transport that answers each
of the three schemas with its own token counts, against the real Stage 3 DB
(the mapping call is only made when a unit resolves there), so the whole
production path is covered: the job's usage line, the stored review's usage
and the lifetime counter all carry the sum. The second test times the review
call out after the mapping and gap-fill were answered: the verse fails (#480's
Retry path) and the counter still carries what was spent, with the unanswered
call's input estimated.
"""
from __future__ import annotations

import json

import pytest
from bridge_service import BridgeEngine
from tc_ai_bridge.ai_client import AITransportError, estimate_input_tokens
from tc_ai_bridge.model_router import estimate_cost
from tc_ai_bridge.tc_project import TranslationCoreProject
from tests.support.ai_review import _wait_for_ai_job, imported_titus_project  # noqa: F401  (a fixture)
from tests.support.projects import call

MAPPING_SCHEMA = "bridge_semantic_mapping_v04"
REVIEW_SCHEMA = "tc_full_review"
ALIGNMENT_SCHEMA = "tc_alignment_proposal"

# (input, output) per call; cached input on the review only.
TOKENS = {MAPPING_SCHEMA: (1000, 100), ALIGNMENT_SCHEMA: (300, 30), REVIEW_SCHEMA: (200, 80)}
REVIEW_CACHED = 50


def _transport(sent: list[str], bodies: dict[str, bytes], *, review_times_out: bool = False):
    alignment_payload = {"links": [], "implicit_top_ids": [], "target_only_ids": [], "review_notes": []}

    def transport(url, headers, body, timeout):
        request = json.loads(body.decode("utf-8"))
        schema_name = request.get("text", {}).get("format", {}).get("name", "")
        sent.append(schema_name)
        bodies[schema_name] = body
        if schema_name == MAPPING_SCHEMA:
            # Rejected by the engine (fail-closed `mapping_error`): the call was
            # still made and billed, which is all this test is about.
            payload = {"not": "a mapping result"}
        elif schema_name == ALIGNMENT_SCHEMA:
            payload = alignment_payload
        else:
            if review_times_out:
                raise AITransportError("Network error contacting OpenAI: The read operation timed out")
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
        inp, out = TOKENS[schema_name]
        cached = REVIEW_CACHED if schema_name == REVIEW_SCHEMA else 0
        return 200, json.dumps({
            "output_text": json.dumps(payload),
            "usage": {"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out,
                      "input_tokens_details": {"cached_tokens": cached}},
        }).encode("utf-8")

    return transport


def _engine(imported_titus_project, stage3_db, monkeypatch, transport):
    if not stage3_db.is_file():
        pytest.skip(f"Stage 3 semantic-source DB not present: {stage3_db}")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("BRIDGE_SEMANTIC_SOURCE_DB", str(stage3_db))
    settings, project_path = imported_titus_project
    settings.set_api_key("sk-test-123")
    settings.model = "gpt-5.6"
    engine = BridgeEngine(settings=settings, ai_transport=transport)
    call(engine, "project.open", {"path": project_path})
    assert settings.get_ai_usage_totals()["tokens"] == 0
    return engine, settings, project_path


def _run_verse_job(engine):
    started = call(engine, "ai.review.start", {
        "scope": "verse", "chapter": "1", "verse": "1", "mode": "basic",
    })
    assert started["success"] is True, started
    return _wait_for_ai_job(engine, started["result"]["jobId"], timeout=30)


def test_verse_usage_is_the_sum_of_mapping_gap_fill_and_review(imported_titus_project, stage3_db, monkeypatch):
    sent: list[str] = []
    engine, settings, project_path = _engine(
        imported_titus_project, stage3_db, monkeypatch, _transport(sent, {}),
    )
    snapshot = _run_verse_job(engine)
    assert snapshot["state"] == "succeeded", snapshot
    assert sorted(sent) == sorted([MAPPING_SCHEMA, ALIGNMENT_SCHEMA, REVIEW_SCHEMA]), sent

    expected_input = sum(i for i, _ in TOKENS.values())
    expected_output = sum(o for _, o in TOKENS.values())
    expected_total = expected_input + expected_output
    expected_cost = sum(
        estimate_cost("gpt-5.6", i, o, REVIEW_CACHED if name == REVIEW_SCHEMA else 0)
        for name, (i, o) in TOKENS.items()
    )

    usage = snapshot["results"]["1:1"]["usage"]
    assert usage["totalTokens"] == expected_total
    assert usage["cachedInputTokens"] == REVIEW_CACHED
    assert usage["calls"] == 3 and usage["unansweredCalls"] == 0
    assert usage["estimatedCostUSD"] == pytest.approx(expected_cost, abs=1e-6)

    stored = TranslationCoreProject(project_path).load_ai_review_result("1", "1")
    assert stored["usage"]["inputTokens"] == expected_input
    assert stored["usage"]["outputTokens"] == expected_output
    assert stored["usage"]["totalTokens"] == expected_total
    assert stored["usage"]["calls"] == 3
    assert stored["estimatedCostUSD"] == pytest.approx(expected_cost, abs=1e-6)

    totals = settings.get_ai_usage_totals()
    assert totals["tokens"] == expected_total
    assert totals["estimatedCostUSD"] == pytest.approx(expected_cost, abs=1e-6)


def test_a_call_sent_but_never_answered_is_counted_as_spent(imported_titus_project, stage3_db, monkeypatch):
    sent: list[str] = []
    bodies: dict[str, bytes] = {}
    engine, settings, project_path = _engine(
        imported_titus_project, stage3_db, monkeypatch, _transport(sent, bodies, review_times_out=True),
    )
    snapshot = _run_verse_job(engine)
    assert snapshot["state"] == "failed", snapshot
    assert sorted(sent) == sorted([MAPPING_SCHEMA, ALIGNMENT_SCHEMA, REVIEW_SCHEMA]), sent
    assert "timed out" in snapshot["results"]["1:1"]["error"]

    # Nothing stored as a review, but the counter carries the two answered
    # calls plus the unanswered review's estimated input.
    assert TranslationCoreProject(project_path).ai_review_cache_status("1", "1") != "current"
    estimated_review_input = estimate_input_tokens(bodies[REVIEW_SCHEMA])
    assert estimated_review_input > 0
    answered = [MAPPING_SCHEMA, ALIGNMENT_SCHEMA]
    expected_total = sum(sum(TOKENS[n]) for n in answered) + estimated_review_input
    expected_cost = sum(estimate_cost("gpt-5.6", *TOKENS[n]) for n in answered) + estimate_cost(
        "gpt-5.6", estimated_review_input, 0,
    )
    totals = settings.get_ai_usage_totals()
    assert totals["tokens"] == expected_total
    assert totals["estimatedCostUSD"] == pytest.approx(expected_cost, abs=1e-6)
