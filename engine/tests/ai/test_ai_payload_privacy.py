"""#470: the reviewer-history lists in a tN/tW review request carry the
decision, never the reviewer.

A `human_decisions` check record holds a free-text `note`, the proposing
`model`, resource paths in `evidenceProvenance`, a timestamp and verse-local
selection ids; a `project_term_renderings` entry holds occurrence counters.
None of that helps the model review a verse, and the note is team data. The
projection keeps the fields the prompt uses and the manifest reports, on the
payload as handed to it, whether anything else got through.
"""
from __future__ import annotations

from tc_ai_bridge.ai_client import (
    PROJECT_RENDERING_FIELDS, REVIEWER_DECISION_FIELDS,
    project_reviewer_decision, project_term_rendering,
)
from tc_ai_bridge.security import ai_payload_manifest, contains_reviewer_identity

# The exact shape `TranslationCoreProject.record_human_decision` writes
# (schemaVersion 2), as read back on a worked project on 2026-11-05.
RAW_DECISION = {
    "bookId": "gen", "chapter": "1", "verse": "2", "checkId": "c2",
    "tool": "translationWords", "groupId": "god", "decision": "accepted",
    "note": "Reviewer note for verse 2: discussed with Benz",
    "selectionText": ["परमेश्वर"], "selectionIds": ["b1"], "model": "gpt-5.6",
    "evidenceProvenance": [{"kind": "translationWords", "title": "God",
                            "path": "C:/Users/someone/resources/en/translationWords/bible/kt/god.md",
                            "version": "v1", "provider": "uW", "identifier": "god", "authoritative": True}],
    "modifiedTimestamp": "2026-11-05T09:24:43.449093Z",
    "app": "translationCore AI Bridge", "schemaVersion": 2,
}

# The shape `TranslationHelpsKnowledgeBase.project_term_renderings` returns.
RAW_RENDERING = {
    "reference": "1:1", "source_quote": "אֱלֹהִים",
    "selections": [{"text": "परमेश्वर", "occurrence": 1, "occurrences": 2}],
    "nothingToSelect": False, "invalidated": False,
}


def test_reviewer_decision_is_projected_to_the_decision_alone():
    projected = project_reviewer_decision(RAW_DECISION)
    assert projected == {
        "reference": "1:2", "tool": "translationWords", "groupId": "god", "checkId": "c2",
        "decision": "accepted", "selectionText": ["परमेश्वर"],
    }
    assert tuple(projected) == REVIEWER_DECISION_FIELDS
    for dropped in ("note", "model", "evidenceProvenance", "modifiedTimestamp", "selectionIds", "bookId"):
        assert dropped not in projected


def test_term_rendering_is_projected_to_text_only():
    projected = project_term_rendering(RAW_RENDERING)
    assert projected == {
        "reference": "1:1", "source_quote": "אֱלֹהִים", "selections": ["परमेश्वर"],
        "nothingToSelect": False, "invalidated": False,
    }
    assert tuple(projected) == PROJECT_RENDERING_FIELDS


def test_manifest_reports_identity_on_the_payload_it_is_handed():
    projected_payload = {
        "reference": "GEN 1:2", "target_verse": "x",
        "project_reviewer_decisions": [project_reviewer_decision(RAW_DECISION)],
        "translationCore_checks": [
            {"tool": "translationWords", "approved_project_renderings": [project_term_rendering(RAW_RENDERING)]},
        ],
    }
    manifest = ai_payload_manifest("GEN 1:2", projected_payload)
    assert manifest["containsReviewerIdentity"] is False
    assert manifest["containsScripture"] is True

    raw_payload = dict(projected_payload, project_reviewer_decisions=[RAW_DECISION])
    assert contains_reviewer_identity(raw_payload) is True
    assert ai_payload_manifest("GEN 1:2", raw_payload)["containsReviewerIdentity"] is True

    raw_rendering_payload = dict(projected_payload, translationCore_checks=[
        {"tool": "translationWords", "approved_project_renderings": [RAW_RENDERING]},
    ])
    # The occurrence counters are inside `selections`, so the key set alone
    # cannot tell a raw rendering from a projected one; the projection is what
    # guarantees that. The manifest's job is the keys.
    assert contains_reviewer_identity(raw_rendering_payload) is False

    # A payload with no reviewer history at all (correction wording) is clean.
    assert ai_payload_manifest("GEN 1:2", {"currentTarget": {}})["containsReviewerIdentity"] is False
