"""#127: the one Scripture writer refuses a save made against text that has
since changed, on both protocol routes that reach it.

- `verse.edit` with `expectedOldText` (the text the editor opened with): a
  mismatch writes nothing and answers with a REVISION_CONFLICT message, which
  the editor shows while keeping the reviewer's typed text. Without
  `expectedOldText` the call behaves as it always has.
- `correction.applyProposal`: a reviewed correction whose verse moved after
  review is refused, and the newer verse stays.
"""
from __future__ import annotations

import json
from pathlib import Path

from bridge_service import BridgeEngine
from tc_ai_bridge.secret_store import AppSettings
from tests.support.correction_9b3b import _fixture
from tests.support.projects import call, fixture_project  # noqa: F401


def _text(engine: BridgeEngine) -> str:
    return call(engine, "verse.get", {"chapter": "1", "verse": "1"})["result"]["text"]


def test_verse_edit_refuses_a_save_made_against_older_text(fixture_project):
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})
    opened_with = _text(engine)
    # A second writer changes the verse while the editor is open.
    newer = call(engine, "verse.edit", {"chapter": "1", "verse": "1", "newText": "NEWER TEXT"})
    assert newer["success"] is True, newer

    stale = call(engine, "verse.edit", {
        "chapter": "1", "verse": "1", "newText": opened_with + " (stale edit)",
        "expectedOldText": opened_with,
    })
    assert stale["success"] is False
    assert stale["error"]["code"] == "project_error"
    assert "REVISION_CONFLICT" in stale["error"]["message"]
    assert _text(engine) == "NEWER TEXT"
    history = call(engine, "verse.history", {"chapter": "1", "verse": "1"})["result"]
    assert [entry["verseAfter"] for entry in history["entries"]] == ["NEWER TEXT"]


def test_verse_edit_writes_when_the_expected_text_still_matches(fixture_project):
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})
    opened_with = _text(engine)
    saved = call(engine, "verse.edit", {
        "chapter": "1", "verse": "1", "newText": "  matched edit  ", "expectedOldText": opened_with,
    })
    assert saved["success"] is True, saved
    # The stored (trimmed) text comes back, so the editor's next base is exact.
    assert saved["result"]["newText"] == "matched edit"
    assert _text(engine) == "matched edit"


def test_verse_edit_without_an_expected_text_keeps_its_old_behaviour(fixture_project):
    engine = BridgeEngine()
    call(engine, "project.open", {"path": str(fixture_project)})
    call(engine, "verse.edit", {"chapter": "1", "verse": "1", "newText": "first"})
    second = call(engine, "verse.edit", {"chapter": "1", "verse": "1", "newText": "second"})
    assert second["success"] is True, second
    assert _text(engine) == "second"


def test_correction_apply_refuses_a_verse_that_changed_after_review(tmp_path: Path) -> None:
    before = "நான் உங்களை நினைக்கும் போதெல்லாம் என் தேவனை ஸ்தோத்திரிக்கிறேன்."
    app_data = tmp_path / "Bridge" / "data"
    managed = app_data / "projects" / "ta_irv_php"
    root, _project, _runtime, _service, finding, proposal = _fixture(
        tmp_path, before, "என் தேவனை", "என் தேவனையே", project_root=managed,
    )
    identity = root / ".bridge" / "project.json"
    identity.parent.mkdir(parents=True, exist_ok=True)
    identity.write_text(json.dumps({
        "schemaVersion": 1, "projectId": "project-1", "collectionId": "",
        "sourceFingerprint": "stale-correction-fixture", "createdAt": "2026-10-22T00:00:00Z",
    }), encoding="utf-8")
    engine = BridgeEngine(settings=AppSettings(path=app_data / "settings.json"))
    opened = call(engine, "project.open", {"path": str(root)})
    assert opened["success"] is True, opened

    newer = "ஒரு புதிய வசனம், மதிப்பாய்வுக்குப் பின் எழுதப்பட்டது."
    edited = call(engine, "verse.edit", {"chapter": "1", "verse": "6", "newText": newer})
    assert edited["success"] is True, edited

    applied = call(engine, "correction.applyProposal", {
        "proposalId": proposal.id,
        "expectedProposalRevision": proposal.revision,
        "findingId": finding["id"],
        "expectedFindingRevision": finding["revision"],
        "applicationId": "stale-correction-apply",
    })
    assert applied["success"] is False, applied
    assert applied["error"]["code"] in {"revision_conflict", "semantic_validation_error"}
    verse = call(engine, "verse.get", {"chapter": "1", "verse": "6"})["result"]
    assert verse["text"] == newer
