"""Stage 9B.4 verification on a verse that carries USFM markup (#316).

The affected analysis job records `targetHashes` over the text the passage
index reads -- the lifted, visible verse (`usfm_verse.plain_text`), since #91.
Verification asks whether that analysis describes the current text, so it must
hash the same representation. It used to hash the raw stored verse instead, and
a verse with a footnote, a cross reference, `\\w` or `\\zaln` markup could
therefore never become verifiable: ANALYSIS_NOT_CURRENT even right after a
completed re-analysis of the current text.

The re-analysis here is the real job pipeline (AnalysisJobManager through
CorrectionAffectedAnalysisService) with stub Stage 5-8 services, so the
recorded `targetHashes` are the ones production writes.
"""
from __future__ import annotations

import pytest

from tc_ai_bridge.analysis_jobs import AnalysisJobManager
from tc_ai_bridge.correction_affected_analysis import CorrectionAffectedAnalysisService
from tc_ai_bridge.correction_verification import CorrectionVerificationService, ReasonCode
from tc_ai_bridge.passage_semantic_models import CorrectionApplicationState
from tc_ai_bridge.usfm_verse import plain_text

from tests.support.analysis_jobs import _stub_stages, _wait
from tests.support.correction_9b3b import _apply, _fixture, _hash


PLAIN = "நான் உங்களை நினைக்கும் போதெல்லாம் என் தேவனை ஸ்தோத்திரிக்கிறேன்."
FOOTNOTE = "\\f + \\fr 1:6 \\ft குறிப்பு\\f*"
CROSS_REFERENCE = "\\x - \\xo 1:6 \\xt அப் 16:12\\x*"


def _applied_and_reanalysed(tmp_path, before: str):
    _root, project, runtime, application_service, _finding, _proposal = _fixture(
        tmp_path, before, "என் தேவனை", "என் தேவனையே",
    )
    application = _apply(application_service)
    assert application["applicationState"] == CorrectionApplicationState.COMPLETED.value
    manager = AnalysisJobManager()
    manager.bind_runtime(runtime)
    _stub_stages(runtime)
    started = CorrectionAffectedAnalysisService(runtime, manager).start(
        application["applicationId"], requested_by="Reviewer",
    )
    job = _wait(manager, started["analysisJobId"])
    assert job["overallStatus"] in {"COMPLETED", "COMPLETED_WITH_WARNINGS"}
    service = CorrectionVerificationService(runtime, manager)
    return project, application, job, service


@pytest.mark.parametrize("before", [
    PLAIN + FOOTNOTE,
    CROSS_REFERENCE + " " + PLAIN,
], ids=["footnote", "cross-reference"])
def test_verification_is_available_after_reanalysis_of_a_marked_up_verse(
    tmp_path, before: str,
) -> None:
    project, application, job, service = _applied_and_reanalysed(tmp_path, before)
    raw = str(project.target_verse_text("1", "6"))
    assert "\\" in raw  # the corrected verse still carries its markup
    # What the job hashed is the visible text, not the stored string. The two
    # differ on this verse, which is the whole of #316.
    assert job["targetHashes"]["PHP 1:6"] == _hash(plain_text(raw))
    assert job["targetHashes"]["PHP 1:6"] != _hash(raw)

    state = service.get(application["applicationId"])
    assert ReasonCode.ANALYSIS_NOT_CURRENT not in state["verificationReasonCodes"]
    assert state["verificationReasonCodes"] == []
    assert state["mayVerify"] is True
    # Availability is all this changes: nothing was verified, nothing corrected.
    assert state["verificationStatus"] == "PENDING"
    assert state["mayAcknowledgeCorrected"] is False


def test_a_wording_edit_after_reanalysis_still_makes_the_analysis_not_current(
    tmp_path,
) -> None:
    project, application, _job, service = _applied_and_reanalysed(tmp_path, PLAIN + FOOTNOTE)
    raw = str(project.target_verse_text("1", "6"))
    project.apply_scripture_edit("1", "6", raw.replace("நான்", "நாங்கள்", 1))
    state = service.get(application["applicationId"])
    assert ReasonCode.ANALYSIS_NOT_CURRENT in state["verificationReasonCodes"]
    assert state["mayVerify"] is False
