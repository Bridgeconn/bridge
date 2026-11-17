"""#500: the three requests of a verse review carry each fact once and no
local path, and Bridge still stores what it stored.

Driven through `ai.review.start` on an imported Titus with real bundled helps,
with a transport that records every request body and answers it.
"""
from __future__ import annotations

import json

from bridge_service import BridgeEngine
from tests.support.ai_review import _wait_for_ai_job, imported_titus_project  # noqa: F401  (fixture)
from tests.support.projects import call


def _recording_transport(requests: list[dict]):
    def transport(url, headers, body, timeout):
        request = json.loads(body.decode("utf-8"))
        requests.append(request)
        name = request["text"]["format"]["name"]
        review_input = json.loads(request["input"])
        if name == "tc_alignment_proposal":
            payload = {"links": [], "implicit_top_ids": [], "target_only_ids": [], "review_notes": []}
        elif name == "bridge_semantic_mapping_v04":
            payload = {
                "mappings": [],
                "unresolved_source_units": [
                    {"source_unit_id": unit["id"], "reason": "NOT_LOCATED", "detail": "test"}
                    for unit in review_input["source_units"]
                ],
                "passage_assessment": "NEEDS_REVIEW",
            }
        else:
            target_id = review_input["target_bottomWords"][0]["id"]
            payload = {
                "summary": "Grounded automatic review.",
                "check_reviews": [
                    {
                        "tool": check["tool"], "group_id": check["groupId"], "check_id": check["checkId"],
                        "source_quote": check.get("source_quote") or "",
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


def _review(engine):
    started = call(engine, "ai.review.start", {"scope": "verse", "chapter": "1", "verse": "1", "mode": "basic"})
    assert started["success"] is True, started
    snapshot = _wait_for_ai_job(engine, started["result"]["jobId"])
    assert snapshot["state"] == "succeeded", snapshot
    return snapshot


def _by_schema(requests: list[dict], name: str) -> list[dict]:
    return [r for r in requests if r["text"]["format"]["name"] == name]


def test_review_request_carries_each_fact_once_and_bridge_stores_what_it_did(imported_titus_project, monkeypatch):  # noqa: F811
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings, project_path = imported_titus_project
    settings.set_api_key("sk-test-123")
    requests: list[dict] = []
    engine = BridgeEngine(settings=settings, ai_transport=_recording_transport(requests))
    call(engine, "project.open", {"path": project_path})
    snapshot = _review(engine)

    [review] = _by_schema(requests, "tc_full_review")
    sent = json.loads(review["input"])
    # Not sent any more.
    for gone in ("resource_provenance", "semantic_passage_mappings"):
        assert gone not in sent
    assert "source_path" not in review["input"] and "sha256" not in review["input"]
    assert str(engine.project.path.parent.parent) not in review["input"].replace("\\\\", "\\")
    # Sent, in its compact form.
    assert sent["language_context"].keys() == {"source", "target", "qa_categories"}
    assert sent["target_verse"] == "Paul, a servant of God."
    top_ids = {t["id"] for t in sent["source_topWords"]}
    bottom_ids = {t["id"] for t in sent["target_bottomWords"]}
    assert bottom_ids
    for group in sent["current_alignment_groups"]:
        assert group.keys() == {"source_ids", "target_ids"}
        assert set(group["source_ids"]) <= top_ids and set(group["target_ids"]) <= bottom_ids
    for token in sent["target_bottomWords"]:
        assert ("occurrences" in token) == (token.get("occurrences", 1) > 1)
    checks = sent["translationCore_checks"]
    assert checks
    for item in sent["evidence_catalog"].values():
        assert item.keys() == {"kind", "title", "content"}
    cited = {eid for check in checks for eid in check["evidence_ids"]}
    assert cited <= set(sent["evidence_catalog"])
    for check in checks:
        # (A check past the pack's 42,000-character budget has no evidence at
        # all, before and after #500; the keep-one rule is unit-tested.)
        kinds = [sent["evidence_catalog"][eid]["kind"] for eid in check["evidence_ids"]]
        # The quote is on the check row; it is evidence only when nothing else is.
        assert "originalQuote" not in kinds or kinds == ["originalQuote"]
    # The count is in the instructions and the schema unless the experiment is on.
    count = len(checks)
    assert f"{count} input checks require exactly {count} result rows" in review["instructions"]
    assert review["text"]["format"]["schema"]["properties"]["check_reviews"]["minItems"] == count
    assert "expected_check_reviews" not in sent

    # What Bridge keeps is what it kept: provenance with its paths, and the
    # full evidence item behind each citation.
    stored = engine.project.load_ai_review_result("1", "1")
    assert stored["resourceProvenance"]["translationNotes"]["path"]
    assert stored["privacyManifest"]["containsReviewerIdentity"] is False
    assert "resource_provenance" not in stored["privacyManifest"]["sentFields"]
    evidence = stored["checkReviews"][0]["evidence_used"]
    assert evidence and {"kind", "title", "content"} <= set(evidence[0])
    assert snapshot["latestResult"]["result"]["appliedSelections"], "a grounded pass is still applied"

    # The mapping request describes the verse, not the bundled resources.
    for mapping in _by_schema(requests, "bridge_semantic_mapping_v04"):
        mapping_input = json.loads(mapping["input"])
        assert "resource_provenance" not in mapping_input
        assert {"contract", "source_units", "target_passage"} <= set(mapping_input)
    # The gap-fill request lists each word once.
    for alignment in _by_schema(requests, "tc_alignment_proposal"):
        alignment_input = json.loads(alignment["input"])
        assert "hebrew_topWords" not in alignment_input and "tamil_bottomWords" not in alignment_input
        assert alignment_input["target_tokens_to_consider"]


def test_review_options_are_off_by_default_and_change_only_what_they_name(imported_titus_project, monkeypatch):  # noqa: F811
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings, project_path = imported_titus_project
    settings.set_api_key("sk-test-123")
    requests: list[dict] = []
    engine = BridgeEngine(settings=settings, ai_transport=_recording_transport(requests))
    call(engine, "project.open", {"path": project_path})

    assert call(engine, "settings.get")["result"]["aiReview"] == {"leanEvidence": False, "countInInput": False}
    _review(engine)
    [default_request] = _by_schema(requests, "tc_full_review")
    default_input = json.loads(default_request["input"])

    refused = call(engine, "settings.set", {"aiReview": {"leanEvidence": "yes"}})
    assert refused["success"] is False
    assert call(engine, "settings.set", {"aiReview": {"unknown": True}})["success"] is False
    changed = call(engine, "settings.set", {"aiReview": {"leanEvidence": True, "countInInput": True}})
    assert changed["result"]["aiReview"] == {"leanEvidence": True, "countInInput": True}

    requests.clear()
    _review(engine)
    [lean_request] = _by_schema(requests, "tc_full_review")
    lean_input = json.loads(lean_request["input"])

    assert lean_input["expected_check_reviews"] == len(lean_input["translationCore_checks"])
    array = lean_request["text"]["format"]["schema"]["properties"]["check_reviews"]
    assert "minItems" not in array and "maxItems" not in array
    assert "input checks require exactly" not in lean_request["instructions"]
    kinds = {item["kind"] for item in lean_input["evidence_catalog"].values()}
    assert "translationWordsLinks" not in kinds
    for item in lean_input["evidence_catalog"].values():
        if item["kind"] == "translationWords":
            assert "## Word Data" not in item["content"] and "## Bible References" not in item["content"]
    assert len(lean_request["input"]) < len(default_request["input"])
    # The verse, its words and its checks are the same request either way.
    for same in ("reference", "target_verse", "source_topWords", "target_bottomWords", "current_alignment_groups"):
        assert lean_input[same] == default_input[same]
    assert [c["checkId"] for c in lean_input["translationCore_checks"]] == \
        [c["checkId"] for c in default_input["translationCore_checks"]]
