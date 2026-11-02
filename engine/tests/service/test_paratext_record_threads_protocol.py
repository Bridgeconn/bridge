"""#433: a Paratext thread for a finding or a correction proposal, through
paratext.queueRecord, linked once Bridge reads it back, and closed by a
verified Paratext resolve (DECISIONS 2026-11-02) -- closure on the link only,
no finding status invented."""

from __future__ import annotations

import bridge_service as bridge_service_module
from tests.support.paratext_fixture import write_notes_file
from tests.support.paratext_writeback import open_linked_review_project, reread_notes, stand_in
from tests.support.projects import call

VERSE = {"chapter": "1", "verse": "1"}
FINDING = {"kind": "finding", "localId": "f-abc123", **VERSE,
           "lines": ["Bridge finding · names.spelling_similarity (greekroom)", "Text: beta"],
           "text": "Please check the spelling.", "selectedText": "beta"}


def test_a_finding_thread_is_queued_with_the_record_lines_and_the_reviewer_note_and_sends_once(
        tmp_path, monkeypatch):
    connector = stand_in()
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", connector)
    engine, folder = open_linked_review_project(tmp_path, monkeypatch)

    result = call(engine, "paratext.queueRecord", FINDING)
    assert result["success"] is True, result
    item = result["result"]["item"]
    assert item["status"] == "sent" and item["kind"] == "finding" and item["localId"] == "f-abc123"
    [(action, sent)] = connector.calls
    me = engine.local_user()
    assert action == "create_note" and sent["reference"] == "TIT 1:1"
    assert sent["comment"].startswith(f"[{me['displayName']} ({me['userId']}) via Bridge]\nBridge finding · names.spelling_similarity (greekroom)\n\nText: beta\n\nReviewer note: Please check the spelling.")
    assert sent["before_context"] == "alpha" and sent["after_context"] == "gamma"
    # Same record, same note: nothing is sent again; a different note is a new thread.
    call(engine, "paratext.queueRecord", FINDING)
    assert len(connector.calls) == 1
    call(engine, "paratext.queueRecord", {**FINDING, "text": "Second thought."})
    assert len(connector.calls) == 2
    # Sent but not yet read back: shown as a link-to-be with no thread yet.
    [to_be] = result["result"]["links"]
    assert to_be["threadId"] == "" and to_be["thread"] is None and result["result"]["pending"] == []

    # Paratext's file now holds it: the link appears, the verse shows the thread as the finding's.
    write_notes_file(folder, "Yesu Selva Benz", [
        {"thread": "F1", "verse_ref": "TIT 1:1", "date": "2026-10-26T10:00:00.1234567+05:30", "status": "todo",
         "contents": ["Bridge finding", f"[Bridge ref {item['messageId']}]"]},
    ])
    reread_notes(engine)
    call(engine, "paratext.flushOutbox")
    threads = call(engine, "paratext.threadsFor", {"kind": "finding", "localId": "f-abc123"})["result"]
    # The first note is linked to F1; the "Second thought." note is still a link-to-be.
    assert [l["threadId"] for l in threads["links"]] == ["F1", ""] and threads["links"][0]["closure"] is None
    [thread] = call(engine, "paratext.notesForVerse", VERSE)["result"]["threads"]
    assert thread["links"] == [{"kind": "finding", "localId": "f-abc123", "closure": None}]


def test_an_empty_note_or_an_unknown_kind_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", stand_in())
    engine, _ = open_linked_review_project(tmp_path, monkeypatch)
    empty = call(engine, "paratext.queueRecord", {"kind": "finding", "localId": "x", **VERSE, "lines": [], "text": " "})
    assert empty["success"] is False and "empty" in empty["error"]["message"]
    unknown = call(engine, "paratext.queueRecord", {"kind": "issue_resolution", "localId": "x", **VERSE, "text": "hi"})
    assert unknown["success"] is False and "finding or correction_proposal" in unknown["error"]["message"]


def test_a_verified_paratext_resolve_closes_the_finding_link_without_inventing_a_finding_decision(
        tmp_path, monkeypatch):
    connector = stand_in()
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", connector)
    engine, folder = open_linked_review_project(tmp_path, monkeypatch)
    proposal = {"kind": "correction_proposal", "localId": "prop-9", **VERSE,
                "lines": ["Bridge correction proposal", "Current: beta", "Proposed: BETA"], "text": ""}
    item = call(engine, "paratext.queueRecord", proposal)["result"]["item"]
    write_notes_file(folder, "Yesu Selva Benz", [
        {"thread": "P9", "verse_ref": "TIT 1:1", "date": "2026-10-26T10:00:00.1234567+05:30", "status": "todo",
         "contents": ["Bridge correction proposal", f"[Bridge ref {item['messageId']}]"]},
    ])
    reread_notes(engine)
    call(engine, "paratext.flushOutbox")
    write_notes_file(folder, "Reviewer Uma", [
        {"thread": "P9", "verse_ref": "TIT 1:1", "date": "2026-10-27T09:00:00.0000000+05:30", "status": "deleted",
         "contents": ["Agreed, done."]},
    ])
    # reread_notes refreshes too, so the closure may already have happened
    # there; what matters is the link's state, and that it closes once.
    reread_notes(engine)
    call(engine, "paratext.refresh")

    [link] = call(engine, "paratext.threadsFor", {"kind": "correction_proposal", "localId": "prop-9"})["result"]["links"]
    assert link["closure"]["status"] == "resolved in Paratext" and link["closure"]["actor"] == "Reviewer Uma"
    assert link["closure"]["origin"] == "paratext" and link["closure"]["evidence"]["threadId"] == "P9"
    [thread] = call(engine, "paratext.notesForVerse", VERSE)["result"]["threads"]
    assert thread["links"][0]["closure"]["status"] == "resolved in Paratext"
    # Only the link closed, once: no qa decision row was written for the record,
    # and the closure row has exactly one closure revision in the change log.
    assert call(engine, "paratext.refresh")["result"]["closed"] == []
    entries = [e for e in engine.project.workbench.change_log_entries(engine.project.workbench_identity.project_id)
               if e["table_name"] == "paratext_links" and e["op"] == "closure:resolved_in_paratext"]
    assert len(entries) == 1
    decisions = engine.project.qa_decisions_for_verse("1", "1")
    assert "prop-9" not in decisions
