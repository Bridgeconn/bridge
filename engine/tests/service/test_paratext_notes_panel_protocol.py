"""#426 / #427 over the protocol: a note written from the Paratext notes
panel with no Bridge record behind it (create, reply, resolve through the
outbox, pending state on the verse), and the QA proposals a thread carries,
parsed on the wire. Connector 0.8.0 is a stand-in; the notes files are a
real synthetic Paratext folder, so the footer check reads it."""

from __future__ import annotations

import bridge_service as bridge_service_module
from tests.support.paratext_writeback import open_linked_review_project, reread_notes, stand_in, write_thread
from tests.support.projects import call

VERSE = {"chapter": "1", "verse": "1"}


def _create(engine, text="Please check the metaphor here.", **extra):
    result = call(engine, "paratext.createNote", {**VERSE, "text": text, **extra})
    assert result["success"] is True, result
    return result["result"]["item"]


def _verse(engine):
    result = call(engine, "paratext.notesForVerse", VERSE)
    assert result["success"] is True, result
    return result["result"]


def test_a_note_from_the_panel_goes_through_the_outbox_with_its_footer_and_shows_pending_until_read_back(
        tmp_path, monkeypatch):
    connector = stand_in()
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", connector)
    engine, folder = open_linked_review_project(tmp_path, monkeypatch)

    item = _create(engine, selectedText="beta")

    assert item["status"] == "sent" and item["kind"] == "note" and item["localId"] == item["messageId"]
    [(action, sent)] = connector.calls
    assert action == "create_note" and sent["reference"] == "TIT 1:1"
    assert sent["comment"].startswith("Please check the metaphor here.")
    assert sent["comment"].endswith(f"[Bridge ref {item['messageId']}]")
    assert sent["before_context"] == "alpha" and sent["after_context"] == "gamma"
    # Sent, but Paratext's file does not hold it yet: the verse shows it pending, not as a thread.
    before = _verse(engine)
    assert before["threads"] == []
    assert [(p["op"], p["status"], p["messageId"]) for p in before["pending"]] == [
        ("create_thread", "sent", item["messageId"])]

    write_thread(folder, "N1", ["Please check the metaphor here.", f"[Bridge ref {item['messageId']}]"],
                 user="Yesu Selva Benz")
    reread_notes(engine)
    call(engine, "paratext.flushOutbox")
    after = _verse(engine)
    assert [t["id"] for t in after["threads"]] == ["N1"] and after["pending"] == []
    links = call(engine, "paratext.outbox")["result"]["links"]
    assert links == [{"kind": "note", "localId": item["messageId"], "threadId": "N1",
                      "messageId": item["messageId"], "direction": "bridge_to_paratext"}]


def test_a_note_written_while_paratext_is_closed_stays_queued_on_the_verse_and_goes_later_once(
        tmp_path, monkeypatch):
    offline = stand_in(offline=True)
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", offline)
    engine, _ = open_linked_review_project(tmp_path, monkeypatch)

    item = _create(engine)
    assert item["status"] == "queued" and "offline" in item["lastError"]
    pending = _verse(engine)["pending"]
    assert [p["status"] for p in pending] == ["queued"] and pending[0]["text"].startswith("Please check")

    online = stand_in()
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", online)
    flushed = call(engine, "paratext.flushOutbox")["result"]
    assert [i["status"] for i in flushed["touched"]] == ["sent"]
    call(engine, "paratext.flushOutbox")
    assert len(online.calls) == 1


def test_an_empty_note_or_a_selection_not_unique_in_the_verse_is_refused_before_queueing(tmp_path, monkeypatch):
    connector = stand_in()
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", connector)
    engine, _ = open_linked_review_project(tmp_path, monkeypatch)

    empty = call(engine, "paratext.createNote", {**VERSE, "text": "   "})
    assert empty["success"] is False and "empty" in empty["error"]["message"]
    missing = call(engine, "paratext.createNote", {**VERSE, "text": "x", "selectedText": "delta"})
    assert missing["success"] is False and "not present" in missing["error"]["message"]
    assert connector.calls == [] and call(engine, "paratext.outbox")["result"]["items"] == []


def test_reply_and_resolve_on_a_paratext_thread_with_no_bridge_record_behind_it(tmp_path, monkeypatch):
    connector = stand_in()
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", connector)
    engine, folder = open_linked_review_project(tmp_path, monkeypatch)
    write_thread(folder, "P1", ["Is this the right term?"], user="Translator")
    reread_notes(engine)

    reply = call(engine, "paratext.replyThread", {"threadId": "P1", "text": "Yes, keep it.", "kind": "note",
                                                  "localId": "P1"})
    assert reply["success"] is True and reply["result"]["item"]["status"] == "sent"
    resolve = call(engine, "paratext.resolveThread", {"threadId": "P1", "kind": "note", "localId": "P1"})
    assert resolve["success"] is True and resolve["result"]["item"]["status"] == "sent"
    actions = [a for a, _ in connector.calls]
    assert actions == ["add_comment", "resolve_note"]
    assert connector.calls[0][1]["key"]["verse_ref"] == "TIT 1:1"
    assert connector.calls[0][1]["text"].startswith("Yes, keep it.")
    # Sent writes are not pending on the verse.
    assert _verse(engine)["pending"] == []


def test_a_queued_reply_is_pending_on_its_thread_s_verse(tmp_path, monkeypatch):
    offline = stand_in(offline=True)
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", offline)
    engine, folder = open_linked_review_project(tmp_path, monkeypatch)
    write_thread(folder, "P2", ["Is this the right term?"], user="Translator")
    reread_notes(engine)

    reply = call(engine, "paratext.replyThread", {"threadId": "P2", "text": "Later.", "kind": "note", "localId": "P2"})
    assert reply["result"]["item"]["status"] == "queued"
    pending = _verse(engine)["pending"]
    assert [(p["op"], p["threadId"], p["status"]) for p in pending] == [("add_comment", "P2", "queued")]


def test_qa_proposals_in_a_thread_are_parsed_on_the_wire_and_counted_in_the_summary(tmp_path, monkeypatch):
    connector = stand_in()
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", connector)
    engine, folder = open_linked_review_project(tmp_path, monkeypatch)
    write_thread(folder, "Q1", [
        "[AI-QA R2] Sandhi — Sandhi / word-joining",
        "Original: beta gamma",
        "Suggested: betagamma",
        "Reason: The words join.",
        "Confidence: 0.93 · Reviewer decision needed: No · Severity: low",
    ], user="QA Pass")
    reread_notes(engine)

    verse = _verse(engine)
    [thread] = verse["threads"]
    assert thread["proposals"] == {"total": 1, "outstanding": 1, "unreadable": 0, "byRoute": {
        "literal": 1, "review": 0, "structure": 0, "noChange": 0, "legacy": 0, "unreadable": 0}}
    [proposal] = thread["proposalItems"]
    assert proposal["route"] == "literal" and proposal["operation"] == "replace"
    assert proposal["original"] == "beta gamma" and proposal["suggested"] == "betagamma"
    assert proposal["category"] == "Sandhi / word-joining" and proposal["pass"] == "R2"
    assert proposal["author"] == "QA Pass" and proposal["reviewerDecision"] is False
    # The chapter listing carries the counts too (no full parse on the wire).
    chapter = call(engine, "paratext.notesForChapter", {"chapter": "1"})["result"]
    [summary] = chapter["verses"]["1"]
    assert summary["proposals"]["outstanding"] == 1 and "proposalItems" not in summary
    single = call(engine, "paratext.noteThread", {"threadId": "Q1"})["result"]["thread"]
    assert single["proposalItems"][0]["proposalId"] == proposal["proposalId"]
