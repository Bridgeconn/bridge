"""#315 over the protocol: `correction.createProposal` with `supersedesProposalId`.

After `correction.rejectProposal`, a plain create for the same finding is still
refused (the rejected proposal owns it); naming the rejected proposal creates
the new one and keeps both listed.
"""
from __future__ import annotations

from pathlib import Path

from bridge_service import BridgeEngine
from greek_room_engine.protocol import EngineRequest
from tc_ai_bridge.passage_semantic_models import to_wire
from tests.support.correction_9b1 import _intent, _Runtime


def test_create_after_rejection_needs_and_records_supersedes(tmp_path: Path) -> None:
    runtime = _Runtime(tmp_path / "semantic.sqlite3")
    bridge = BridgeEngine()
    bridge.project = object()
    bridge.passage_semantic_runtime = runtime

    def call(method: str, params: dict) -> dict:
        return bridge.handle_request(
            EngineRequest(id="request", method=method, params=params)
        ).to_dict()

    intent = to_wire(_intent(runtime))
    first = call("correction.createProposal", {
        "findingId": "qa-1", "intent": intent, "humanProposedText": "first wording",
    })
    assert first["success"] is True, first
    first_id = first["result"]["id"]
    rejected = call("correction.rejectProposal", {
        "proposalId": first_id, "expectedProposalRevision": 1, "note": "reject",
    })
    assert rejected["success"] is True, rejected

    plain = call("correction.createProposal", {
        "findingId": "qa-1", "intent": intent, "humanProposedText": "second wording",
    })
    assert plain["success"] is False, plain

    second = call("correction.createProposal", {
        "findingId": "qa-1", "intent": intent, "humanProposedText": "second wording",
        "supersedesProposalId": first_id,
    })
    assert second["success"] is True, second
    assert second["result"]["supersedesProposalId"] == first_id

    # The stub runtime has no listForFinding; read the same repository rows.
    listed = runtime.repository.correction_proposals_for_finding("qa-1")
    by_id = {item["id"]: item for item in listed}
    assert set(by_id) == {first_id, second["result"]["id"]}
    assert by_id[first_id]["proposedText"] == "first wording"
    assert by_id[first_id]["reviewStatus"] == "HUMAN_REJECTED"
    assert by_id[first_id]["lifecycleStatus"] == "SUPERSEDED"
    history = call("correction.getProposalHistory", {"proposalId": first_id})["result"]["events"]
    assert [event["eventType"] for event in history] == ["CREATED", "REJECTED", "SUPERSEDED"]
