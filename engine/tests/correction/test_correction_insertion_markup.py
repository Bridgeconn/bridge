"""#314: a correction insertion point never falls inside USFM markup.

A manual correction for an unlocated finding is a zero-length insertion. The
stored verse string keeps its markup, so a raw offset can sit inside a note
such as `\\x … \\x*`. The engine offers only points outside markup, and both the
proposal save and the one Scripture writer refuse an offset strictly inside a
removed (markup or note) range.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from tc_ai_bridge.correction_eligibility import CurrentTextValidation
from tc_ai_bridge.correction_wording import CorrectionWordingService
from tc_ai_bridge.passage_semantic_models import (
    AffectedTargetSpan,
    CorrectionIntent,
    CoverageDimension,
)
from tc_ai_bridge.passage_semantic_repository import FoundationValidationError
from tc_ai_bridge.usfm_verse import lift_verse
from tests.support.correction_9b1 import REFERENCE, _Eligibility, _Runtime
from tests.support.correction_9b3b import _fixture


XREF = "\\x - \\xo 1:1 \\xt அப் 16:12\\x*"
VERSE = XREF + "இயேசு கிறிஸ்துவின் ஊழியக்காரர்களாகிய பவுலும்"
INSIDE = range(1, len(XREF))  # every offset strictly inside the cross-reference


class _XrefEligibility(_Eligibility):
    def validate_current_text(self, **kwargs) -> CurrentTextValidation:
        start, end = int(kwargs["start_code_point"]), int(kwargs["end_code_point"])
        observed = VERSE[start:end]
        assert kwargs.get("expected_span_text") == observed
        return CurrentTextValidation(
            valid=True, current_target_revision=self.runtime.text_revision(
                REFERENCE, self.runtime.text_hash(VERSE)),
            current_target_content_hash=self.runtime.text_hash(VERSE),
            observed_span_text=observed,
        )

    def current_text_snapshot(self) -> dict[str, str]:
        return {REFERENCE: VERSE}


def _runtime(tmp_path: Path) -> _Runtime:
    runtime = _Runtime(tmp_path / "semantic.sqlite3")
    runtime.correction_eligibility = _XrefEligibility(runtime)
    runtime.correction_wording = CorrectionWordingService(runtime)
    return runtime


def _insertion(runtime: _Runtime, offset: int) -> CorrectionIntent:
    content_hash = runtime.text_hash(VERSE)
    return CorrectionIntent(
        failed_dimension=CoverageDimension.LEXICAL_CONTENT,
        observed_meaning="not present", required_meaning="restore omitted meaning",
        affected_source_semantic_unit_ids=(),
        affected_target_span=AffectedTargetSpan(
            displayed_reference=REFERENCE, canonical_references=(REFERENCE,),
            start_code_point=offset, end_code_point=offset, original_text="",
            target_text_revision=runtime.text_revision(REFERENCE, content_hash),
            target_content_hash=content_hash,
        ),
    )


def test_offered_points_are_verse_start_and_word_ends_never_inside_the_xref() -> None:
    lifted = lift_verse(VERSE)
    assert lifted.removed[0] == (0, len(XREF))
    points = lifted.insertion_points()
    assert points[0] == 0
    assert points[-1] == len(VERSE)
    assert not any(point in INSIDE for point in points)
    assert all(lifted.removed_range_containing(point) is None for point in points)
    assert all(lifted.removed_range_containing(offset) == (0, len(XREF)) for offset in INSIDE)
    # Word ends only: each non-final point sits just before a space.
    assert all(VERSE[point] == " " for point in points[1:-1])


def test_review_context_carries_the_engine_insertion_points(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    context = runtime.correction_wording.review_context("qa-1")
    target = context["currentTargets"][0]
    assert target["text"] == VERSE
    assert target["insertionOffsets"] == list(lift_verse(VERSE).insertion_points())


def test_proposal_save_refuses_every_insertion_inside_the_xref(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    for offset in INSIDE:
        with pytest.raises(FoundationValidationError, match="inside USFM markup or a note"):
            runtime.correction_wording.create_proposal(
                finding_id="qa-1", intent=_insertion(runtime, offset),
                human_proposed_text="சேர்ப்பு", actor_id="Reviewer",
            )
    assert runtime.repository.correction_proposals_for_finding("qa-1") == []


@pytest.mark.parametrize("offset", [0, len(XREF), len(VERSE)])
def test_proposal_save_accepts_an_insertion_at_the_edge_of_markup(tmp_path: Path, offset: int) -> None:
    runtime = _runtime(tmp_path)
    proposal = runtime.correction_wording.create_proposal(
        finding_id="qa-1", intent=_insertion(runtime, offset),
        human_proposed_text="சேர்ப்பு", actor_id="Reviewer",
    )
    assert proposal["intent"]["affectedTargetSpan"]["startCodePoint"] == offset


def test_apply_refuses_a_stored_insertion_inside_the_xref(tmp_path: Path) -> None:
    """The writer fails closed even for a proposal saved before #314."""
    _root, project, runtime, service, _finding, proposal = _fixture(
        tmp_path, VERSE, "", "சேர்ப்பு",
    )
    span = proposal.intent.affected_target_span
    inside = replace(
        proposal, id="proposal-inside", supersedes_proposal_id="proposal-1",
        intent=replace(proposal.intent, affected_target_span=replace(
            span, start_code_point=5, end_code_point=5,
        )),
    )
    runtime.repository.supersede_and_save_correction_proposal(
        "proposal-1", expected_revision=1, replacement=inside, actor_id="Reviewer",
    )
    with pytest.raises(FoundationValidationError, match="inside USFM markup or a note"):
        service.apply(
            proposal_id="proposal-inside", expected_proposal_revision=1,
            finding_id="finding-1", expected_finding_revision=1,
            application_id="apply-inside",
            actor={"actorType": "HUMAN", "actorId": "Reviewer"},
        )
    assert project.target_verse_text("1", "6") == VERSE
    assert runtime.repository.applications_for_finding("finding-1") == []
