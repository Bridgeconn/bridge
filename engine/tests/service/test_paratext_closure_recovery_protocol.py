"""#425 over the protocol: the external closure of linked Bridge records
(DECISIONS 2026-11-02) under repeated delivery, re-reads, a record already
resolved locally, a link whose thread Bridge cannot see, and two threads
on one record -- one closure event per external resolution, no feedback
loop, nothing unrelated closed."""

from __future__ import annotations

import bridge_service as bridge_service_module
from tests.support.paratext_fixture import write_notes_file
from tests.support.paratext_writeback import (
    open_linked_review_project, reread_notes, saved_resolution, stand_in,
)
from tests.support.projects import call

VERSE = {"chapter": "1", "verse": "1"}


def _closures(engine):
    return [e for e in engine.project.workbench.change_log_entries(engine.project.workbench_identity.project_id)
            if e["table_name"] == "paratext_links" and e["op"] == "closure:resolved_in_paratext"]


def _resolution(engine, resolution_id):
    items = call(engine, "issueResolution.list", VERSE)["result"]["items"]
    return next(i for i in items if i["resolutionId"] == resolution_id)


def _thread(thread, message_id, status, date, contents=("Bridge review",), done_by="Yesu Selva Benz"):
    return {"thread": thread, "verse_ref": "TIT 1:1", "date": date, "status": status,
            "contents": list(contents) + [f"[Bridge ref {message_id}]"], "user": done_by}


def test_repeated_delivery_and_rereads_make_one_closure_and_never_reopen(tmp_path, monkeypatch):
    connector = stand_in()
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", connector)
    engine, folder = open_linked_review_project(tmp_path, monkeypatch)
    resolution_id = saved_resolution(engine)
    message_id = call(engine, "issueResolution.queueParatext", {**VERSE, "resolutionId": resolution_id})["result"]["handoff"]["messageId"]
    write_notes_file(folder, "Yesu Selva Benz", [
        _thread("R1", message_id, "todo", "2026-10-26T10:00:00.1234567+05:30")])
    reread_notes(engine)
    call(engine, "paratext.threadsFor", {"kind": "issue_resolution", "localId": resolution_id})
    assert _resolution(engine, resolution_id)["status"] != "resolved" and _closures(engine) == []

    # Resolved in Paratext; the same file is delivered three times and read many more.
    for _ in range(3):
        write_notes_file(folder, "Yesu Selva Benz", [
            _thread("R1", message_id, "done", "2026-10-26T10:00:00.1234567+05:30")])
        reread_notes(engine)
        for _ in range(3):
            call(engine, "paratext.threadsFor", {"kind": "issue_resolution", "localId": resolution_id})
            call(engine, "paratext.flushOutbox")
    record = _resolution(engine, resolution_id)
    assert record["status"] == "resolved"
    assert len(_closures(engine)) == 1
    history = [h for h in record.get("history", []) if h.get("event") == "resolved_from_paratext"]
    assert len(history) == 1
    assert not [a for a, _ in connector.calls if a == "resolve_note"], "closure never echoes a resolve back"


def test_a_record_resolved_in_bridge_first_keeps_its_origin_when_paratext_resolves_later(tmp_path, monkeypatch):
    connector = stand_in()
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", connector)
    engine, folder = open_linked_review_project(tmp_path, monkeypatch)
    resolution_id = saved_resolution(engine)
    message_id = call(engine, "issueResolution.queueParatext", {**VERSE, "resolutionId": resolution_id})["result"]["handoff"]["messageId"]
    write_notes_file(folder, "Yesu Selva Benz", [_thread("R1", message_id, "todo", "2026-10-26T10:00:00.1234567+05:30")])
    reread_notes(engine)
    call(engine, "paratext.threadsFor", {"kind": "issue_resolution", "localId": resolution_id})
    # Resolved from Bridge: the comment and the resolve go to Paratext.
    sent = call(engine, "paratext.resolveThread", {"threadId": "R1", "kind": "issue_resolution", "localId": resolution_id})["result"]
    assert sent["item"]["status"] == "sent"
    write_notes_file(folder, "Yesu Selva Benz", [_thread("R1", message_id, "done", "2026-10-26T10:00:00.1234567+05:30")])
    reread_notes(engine)
    links = call(engine, "paratext.threadsFor", {"kind": "issue_resolution", "localId": resolution_id})["result"]["links"]
    [link] = [l for l in links if l["threadId"] == "R1"]
    assert link["closure"]["origin"] == "bridge" and link["closure"]["status"] == "resolved in Bridge"
    assert len(_closures(engine)) == 1
    record = _resolution(engine, resolution_id)
    assert record["status"] == "resolved"
    # Three more reads do not add a second closure or a second history event.
    for _ in range(3):
        reread_notes(engine)
        call(engine, "paratext.threadsFor", {"kind": "issue_resolution", "localId": resolution_id})
    assert len(_closures(engine)) == 1


def test_an_unseen_or_unrelated_thread_closes_nothing(tmp_path, monkeypatch):
    connector = stand_in()
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", connector)
    engine, folder = open_linked_review_project(tmp_path, monkeypatch)
    resolution_id = saved_resolution(engine)
    message_id = call(engine, "issueResolution.queueParatext", {**VERSE, "resolutionId": resolution_id})["result"]["handoff"]["messageId"]
    # Linked by hand to a thread Bridge has read, then that thread disappears
    # from the files (deleted in Paratext) while another, unrelated, is done.
    write_notes_file(folder, "Yesu Selva Benz", [
        _thread("R1", message_id, "todo", "2026-10-26T10:00:00.1234567+05:30"),
        {"thread": "U1", "verse_ref": "TIT 1:1", "date": "2026-10-26T11:00:00.0000000+05:30", "status": "todo",
         "contents": ["Unrelated"]},
    ])
    reread_notes(engine)
    call(engine, "paratext.threadsFor", {"kind": "issue_resolution", "localId": resolution_id})
    write_notes_file(folder, "Yesu Selva Benz", [
        {"thread": "U1", "verse_ref": "TIT 1:1", "date": "2026-10-26T11:00:00.0000000+05:30", "status": "done",
         "contents": ["Unrelated"]},
    ])
    reread_notes(engine)
    call(engine, "paratext.threadsFor", {"kind": "issue_resolution", "localId": resolution_id})
    call(engine, "paratext.flushOutbox")
    assert _closures(engine) == []
    assert _resolution(engine, resolution_id)["status"] != "resolved"
    links = call(engine, "paratext.threadsFor", {"kind": "issue_resolution", "localId": resolution_id})["result"]["links"]
    assert [l["thread"] for l in links] == [None]        # the thread is gone; the link stays, unclosed


def test_two_threads_on_one_record_close_it_once_and_record_both_links(tmp_path, monkeypatch):
    connector = stand_in()
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", connector)
    engine, folder = open_linked_review_project(tmp_path, monkeypatch)
    resolution_id = saved_resolution(engine)
    message_id = call(engine, "issueResolution.queueParatext", {**VERSE, "resolutionId": resolution_id})["result"]["handoff"]["messageId"]
    write_notes_file(folder, "Yesu Selva Benz", [
        _thread("R1", message_id, "todo", "2026-10-26T10:00:00.1234567+05:30"),
        {"thread": "E1", "verse_ref": "TIT 1:1", "date": "2026-10-26T12:00:00.0000000+05:30", "status": "todo",
         "contents": ["Earlier discussion"]},
    ])
    reread_notes(engine)
    call(engine, "paratext.flushOutbox")       # the sent create finds its thread in the file and links it
    call(engine, "paratext.linkThread", {"threadId": "E1", "kind": "issue_resolution", "localId": resolution_id})
    write_notes_file(folder, "Yesu Selva Benz", [
        _thread("R1", message_id, "done", "2026-10-26T10:00:00.1234567+05:30"),
        {"thread": "E1", "verse_ref": "TIT 1:1", "date": "2026-10-26T12:00:00.0000000+05:30", "status": "done",
         "contents": ["Earlier discussion"]},
    ])
    reread_notes(engine)
    call(engine, "paratext.threadsFor", {"kind": "issue_resolution", "localId": resolution_id})
    assert len(_closures(engine)) == 2            # one per link
    record = _resolution(engine, resolution_id)
    assert record["status"] == "resolved"
    assert len([h for h in record.get("history", []) if h.get("event") == "resolved_from_paratext"]) == 1
