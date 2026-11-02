"""Benz's decisions of 2026-11-02 on #423 (DECISIONS.md), over the protocol
with the connector 0.9.0 stand-in and a synthetic Paratext folder:

* named attribution on every Bridge note write, Paratext's own author kept;
* a Bridge-origin resolve is recorded as "resolved in Bridge";
* a verified Paratext resolve closes the linked Bridge record with no click:
  an issue resolution becomes `resolved` with the external actor, a plain
  note link gets its closure, each once;
* the review queue's apply can also write the verse into Paratext through
  put_verse_text, after and never instead of the verified Bridge apply, and
  a refusal there is final."""

from __future__ import annotations

import bridge_service as bridge_service_module
from tests.support.paratext_fixture import write_notes_file
from tests.support.paratext_writeback import (
    CAPABILITIES_080, open_linked_review_project, reread_notes, saved_resolution, stand_in, write_thread,
)
from tests.support.projects import call

VERSE = {"chapter": "1", "verse": "1"}


def _user(engine):
    return call(engine, "users.list")["result"]


def test_every_note_write_names_the_bridge_user_and_a_bridge_resolve_says_resolved_in_bridge(tmp_path, monkeypatch):
    connector = stand_in()
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", connector)
    engine, folder = open_linked_review_project(tmp_path, monkeypatch)
    me = engine.local_user()
    write_thread(folder, "P1", ["Is this right?"], user="Translator")
    reread_notes(engine)

    call(engine, "paratext.createNote", {**VERSE, "text": "Please check."})
    call(engine, "paratext.replyThread", {"threadId": "P1", "text": "Yes.", "kind": "note", "localId": "P1"})
    resolved = call(engine, "paratext.resolveThread", {"threadId": "P1", "kind": "note", "localId": "P1"})["result"]
    resolution_id = saved_resolution(engine)
    call(engine, "issueResolution.queueParatext", {**VERSE, "resolutionId": resolution_id})

    actions = [a for a, _ in connector.calls]
    assert actions == ["create_note", "add_comment", "add_comment", "resolve_note", "create_note"]
    tag = f"[{me['displayName']} ({me['userId']}) via Bridge]"
    assert connector.calls[0][1]["comment"].startswith(tag + "\nPlease check.")
    assert connector.calls[1][1]["text"].startswith(tag + "\nYes.")
    assert connector.calls[2][1]["text"].startswith(tag + "\nResolved in Bridge.")
    assert connector.calls[4][1]["comment"].startswith(tag + "\nBridge Translation Note review for TIT 1:1")
    assert resolved["comment"]["status"] == "sent" and resolved["item"]["status"] == "sent"
    # The outbox keeps who did it; Paratext's author is still the PC's user.
    items = call(engine, "paratext.outbox")["result"]["items"]
    assert all(i["bridgeUser"] == {"userId": me["userId"], "displayName": me["displayName"]} for i in items)
    assert all(i["author"] == "Yesu Selva Benz" for i in items if i["op"] == "create_thread")


def test_a_verified_paratext_resolve_closes_the_linked_issue_resolution_and_note_once_with_the_external_actor(
        tmp_path, monkeypatch):
    connector = stand_in()
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", connector)
    engine, folder = open_linked_review_project(tmp_path, monkeypatch)
    resolution_id = saved_resolution(engine)
    queued = call(engine, "issueResolution.queueParatext", {**VERSE, "resolutionId": resolution_id})["result"]
    message_id = queued["handoff"]["messageId"]
    note = call(engine, "paratext.createNote", {**VERSE, "text": "Standalone."})["result"]["item"]
    # Paratext holds both threads; nothing is resolved yet.
    write_notes_file(folder, "Yesu Selva Benz", [
        {"thread": "R1", "verse_ref": "TIT 1:1", "date": "2026-10-26T10:00:00.1234567+05:30", "status": "todo",
         "contents": ["Bridge review", f"[Bridge ref {message_id}]"]},
        {"thread": "N1", "verse_ref": "TIT 1:1", "date": "2026-10-26T10:05:00.0000000+05:30", "status": "todo",
         "contents": ["Standalone.", f"[Bridge ref {note['messageId']}]"]},
    ])
    reread_notes(engine)
    call(engine, "paratext.flushOutbox")
    before = call(engine, "paratext.threadsFor", {"kind": "issue_resolution", "localId": resolution_id})["result"]
    assert before["links"][0]["threadId"] == "R1" and before["links"][0]["closure"] is None
    record = call(engine, "issueResolution.list", VERSE)["result"]["items"][0]
    assert record["status"] != "resolved"

    # A reviewer resolves both in Paratext (9.5 writes Status "deleted").
    write_notes_file(folder, "Reviewer Uma", [
        {"thread": "R1", "verse_ref": "TIT 1:1", "date": "2026-10-27T09:00:00.0000000+05:30", "status": "deleted",
         "contents": ["Done."]},
        {"thread": "N1", "verse_ref": "TIT 1:1", "date": "2026-10-27T09:01:00.0000000+05:30", "status": "deleted",
         "contents": [""]},
    ])
    reread_notes(engine)
    refreshed = call(engine, "paratext.refresh")["result"]
    closed = {c["threadId"]: c for c in refreshed["closed"]}
    assert set(closed) == {"R1", "N1"}
    assert closed["R1"]["closure"]["status"] == "resolved in Paratext"
    assert closed["R1"]["closure"]["origin"] == "paratext" and closed["R1"]["closure"]["actor"] == "Reviewer Uma"
    assert closed["R1"]["closure"]["evidence"]["threadId"] == "R1"

    record = call(engine, "issueResolution.list", VERSE)["result"]["items"][0]
    assert record["status"] == "resolved"
    event = next(h for h in record["history"] if h["event"] == "resolved_from_paratext")
    assert event["paratextDoneBy"] == "Reviewer Uma" and "resolved in Paratext" in event["by"]
    # Once: another refresh or read closes nothing again and the record keeps one event.
    assert call(engine, "paratext.refresh")["result"]["closed"] == []
    again = call(engine, "paratext.threadsFor", {"kind": "issue_resolution", "localId": resolution_id})["result"]
    assert again["links"][0]["closure"]["actor"] == "Reviewer Uma"
    record = call(engine, "issueResolution.list", VERSE)["result"]["items"][0]
    assert sum(1 for h in record["history"] if h["event"] == "resolved_from_paratext") == 1
    # The one click is now refused as already resolved: nothing to do twice.
    click = call(engine, "issueResolution.resolveFromParatext", {**VERSE, "resolutionId": resolution_id, "threadId": "R1"})
    assert click["success"] is False and "already resolved" in click["error"]["message"]


def test_a_resolve_bridge_sent_is_closed_as_bridge_origin_not_as_an_external_resolution(tmp_path, monkeypatch):
    connector = stand_in()
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", connector)
    engine, folder = open_linked_review_project(tmp_path, monkeypatch)
    write_thread(folder, "P1", ["Is this right?"], user="Translator")
    reread_notes(engine)
    call(engine, "paratext.resolveThread", {"threadId": "P1", "kind": "note", "localId": "P1"})
    write_notes_file(folder, "Yesu Selva Benz", [
        {"thread": "P1", "verse_ref": "TIT 1:1", "date": "2026-10-27T09:00:00.0000000+05:30", "status": "deleted",
         "contents": [""]},
    ])
    reread_notes(engine)
    [closed] = call(engine, "paratext.refresh")["result"]["closed"]
    assert closed["closure"]["origin"] == "bridge" and closed["closure"]["status"] == "resolved in Bridge"


def _qa_thread(folder):
    write_thread(folder, "Q1", ["[AI-QA R2] Check — Sandhi / word-joining", "Original: beta", "Suggested: BETA",
                                "Reason: Join.", "Confidence: 0.9 · Reviewer decision needed: No · Severity: low"],
                 user="QA Pass")


def test_apply_with_write_paratext_edits_bridge_first_then_paratext_through_the_outbox_and_verifies(
        tmp_path, monkeypatch):
    connector = stand_in()
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", connector)
    engine, folder = open_linked_review_project(tmp_path, monkeypatch)
    _qa_thread(folder)
    reread_notes(engine)
    [item] = call(engine, "paratextReview.queue", {})["result"]["items"]

    result = call(engine, "paratextReview.decide", {"proposalId": item["proposalId"], "decision": "applied",
                                                    "comment": "ok", "writeParatext": True})
    assert result["success"] is True, result
    decision = result["result"]["decision"]
    assert decision["verified"] is True
    assert decision["paratext"]["status"] == "sent" and decision["paratext"]["verified"] is True
    assert decision["paratext"]["author"] == "Yesu Selva Benz"
    assert call(engine, "verse.get", VERSE)["result"]["text"] == "alpha BETA gamma"
    [(action, sent)] = [c for c in connector.calls if c[0] == "put_verse_text"]
    assert sent["project_id"] == engine._paratext_session().guid and sent["book"] == "TIT"
    assert sent["verse"] == "1" and sent["original"] == "beta" and sent["replacement"] == "BETA"
    assert sent["before_context"] == "alpha" and sent["after_context"] == "gamma"
    me = engine.local_user()
    assert sent["bridge_user"] == f"{me['displayName']} ({me['userId']})"
    assert connector.scripture["TIT 1"] == "\\c 1\n\\p\n\\v 1 alpha BETA gamma\n"
    # The queue shows the Paratext status on the decision.
    [listed] = call(engine, "paratextReview.queue", {})["result"]["items"]
    assert listed["decision"]["paratext"]["status"] == "sent"


def test_paratext_write_waits_while_paratext_is_closed_and_a_final_refusal_is_never_retried_blind(
        tmp_path, monkeypatch):
    offline = stand_in(offline=True)
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", offline)
    engine, folder = open_linked_review_project(tmp_path, monkeypatch)
    _qa_thread(folder)
    reread_notes(engine)
    [item] = call(engine, "paratextReview.queue", {})["result"]["items"]
    decision = call(engine, "paratextReview.decide", {"proposalId": item["proposalId"], "decision": "applied",
                                                      "writeParatext": True})["result"]["decision"]
    assert decision["verified"] is True and decision["paratext"]["status"] == "queued"
    assert "offline" in decision["paratext"]["lastError"]
    assert call(engine, "verse.get", VERSE)["result"]["text"] == "alpha BETA gamma"

    # Paratext comes back, but someone already changed that verse there.
    online = stand_in(scripture={"TIT 1": "\\c 1\n\\p\n\\v 1 alpha Beta gamma\n"})
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", online)
    flushed = call(engine, "paratext.flushOutbox")["result"]
    [touched] = flushed["touched"]
    assert touched["status"] == "refused" and "was not found" in touched["lastError"]
    # A background flush leaves a refusal alone: no second attempt.
    call(engine, "paratext.flushOutbox")
    assert len([c for c in online.calls if c[0] == "put_verse_text"]) == 1
    [listed] = call(engine, "paratextReview.queue", {})["result"]["items"]
    assert listed["decision"]["paratext"]["status"] == "refused"
    assert online.scripture["TIT 1"] == "\\c 1\n\\p\n\\v 1 alpha Beta gamma\n"


def test_an_older_connector_keeps_the_scripture_write_queued_with_the_update_hint(tmp_path, monkeypatch):
    connector = stand_in(capabilities=CAPABILITIES_080, version="0.8.1")
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", connector)
    engine, folder = open_linked_review_project(tmp_path, monkeypatch)
    _qa_thread(folder)
    reread_notes(engine)
    [item] = call(engine, "paratextReview.queue", {})["result"]["items"]
    decision = call(engine, "paratextReview.decide", {"proposalId": item["proposalId"], "decision": "applied",
                                                      "writeParatext": True})["result"]["decision"]
    assert decision["paratext"]["status"] == "queued" and "cannot put verse text" in decision["paratext"]["lastError"]
    assert not [c for c in connector.calls if c[0] == "put_verse_text"]
