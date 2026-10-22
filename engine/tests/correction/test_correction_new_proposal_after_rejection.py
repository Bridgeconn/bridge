"""#315: after a proposal is rejected, a new one can be created for the finding.

A rejected proposal is INACTIVE and still owns the finding (eligibility reports
CONFLICTING_CORRECTION and the repository refuses a second owner), so a plain
create is refused. The new proposal names the rejected one it supersedes and
goes through the existing supersede path, the one regenerate uses: the
rejected proposal keeps its wording and HUMAN_REJECTED review status, gains a
SUPERSEDED event, and stays listed beside its replacement.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tc_ai_bridge.correction_eligibility import CorrectionEligibilityCode
from tc_ai_bridge.passage_semantic_models import LifecycleStatus, ReviewStatus
from tc_ai_bridge.passage_semantic_repository import FoundationValidationError
from tests.support.correction_9b3b import _fixture


BEFORE = "நான் உங்களை நினைக்கும் போதெல்லாம் என் தேவனை ஸ்தோத்திரிக்கிறேன்."


def _rejected_fixture(tmp_path: Path):
    root, project, runtime, service, finding, proposal = _fixture(
        tmp_path, BEFORE, "என் தேவனை", "என் தேவனையே",
    )
    runtime.correction_reject_proposal(
        "proposal-1", expected_revision=1, actor_id="Reviewer", reason="Not natural.",
    )
    return root, project, runtime, service, proposal


def _create(runtime, proposal, **options):
    return runtime.correction_create_proposal(
        finding_id="finding-1", intent=proposal.intent,
        human_proposed_text="என்னுடைய தேவனை", explanation="Better wording.",
        actor_id="Reviewer", **options,
    )


def test_rejected_proposal_still_blocks_a_plain_create(tmp_path: Path) -> None:
    _root, _project, runtime, _service, proposal = _rejected_fixture(tmp_path)
    eligibility = runtime.correction_eligibility.evaluate("finding-1")
    assert eligibility.eligible is False
    assert [reason.code for reason in eligibility.reasons] == [
        CorrectionEligibilityCode.CONFLICTING_CORRECTION,
    ]
    with pytest.raises(FoundationValidationError, match="not eligible"):
        _create(runtime, proposal)
    assert [item["id"] for item in runtime.repository.correction_proposals_for_finding("finding-1")] == [
        "proposal-1",
    ]


def test_new_proposal_supersedes_the_rejected_one_and_keeps_it_in_history(tmp_path: Path) -> None:
    _root, _project, runtime, _service, proposal = _rejected_fixture(tmp_path)

    created = _create(runtime, proposal, supersedes_proposal_id="proposal-1")

    assert created["id"] != "proposal-1"
    assert created["supersedesProposalId"] == "proposal-1"
    assert created["lifecycleStatus"] == LifecycleStatus.ACTIVE.value
    assert created["proposedText"] == "என்னுடைய தேவனை"
    old = runtime.repository.correction_proposal("proposal-1")
    assert old["reviewStatus"] == ReviewStatus.HUMAN_REJECTED.value
    assert old["lifecycleStatus"] == LifecycleStatus.SUPERSEDED.value
    assert old["proposedText"] == "என் தேவனையே"
    history = runtime.repository.correction_proposal_history("proposal-1")
    assert [event["eventType"] for event in history] == ["CREATED", "REJECTED", "SUPERSEDED"]
    assert history[1]["proposalSnapshot"]["proposedText"] == "என் தேவனையே"
    listed = runtime.repository.correction_proposals_for_finding("finding-1")
    assert {item["id"] for item in listed} == {"proposal-1", created["id"]}
    assert runtime.correction_eligibility.evaluate(
        "finding-1", ignore_proposal_ids=(created["id"],),
    ).eligible is True


def test_new_proposal_after_rejection_can_be_applied(tmp_path: Path) -> None:
    _root, project, runtime, service, proposal = _rejected_fixture(tmp_path)
    created = _create(runtime, proposal, supersedes_proposal_id="proposal-1")

    result = service.apply(
        proposal_id=created["id"], expected_proposal_revision=1,
        finding_id="finding-1", expected_finding_revision=1,
        application_id="apply-after-rejection",
        actor={"actorType": "HUMAN", "actorId": "Reviewer"},
    )

    assert result["applicationState"] == "COMPLETED"
    assert project.target_verse_text("1", "6") == BEFORE.replace("என் தேவனை", "என்னுடைய தேவனை")


@pytest.mark.parametrize("supersedes", ["proposal-1", "no-such-proposal"])
def test_create_refuses_to_supersede_a_proposal_that_is_not_rejected(
    tmp_path: Path, supersedes: str,
) -> None:
    _root, _project, runtime, _service, _finding, proposal = _fixture(
        tmp_path, BEFORE, "என் தேவனை", "என் தேவனையே",
    )
    with pytest.raises(FoundationValidationError):
        _create(runtime, proposal, supersedes_proposal_id=supersedes)
    current = runtime.repository.correction_proposal("proposal-1")
    assert current["lifecycleStatus"] == LifecycleStatus.ACTIVE.value
    assert len(runtime.repository.correction_proposals_for_finding("finding-1")) == 1
