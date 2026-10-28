"""#358 (c): Paratext write-back through the outbox, over the protocol, with a
stand-in for connector 0.8.0. The book is linked to a synthetic Paratext folder
so the notes index is real: the footer check reads it."""

from __future__ import annotations

import pytest

import bridge_service as bridge_service_module
from tc_ai_bridge import paratext_outbox as outbox_module
from tc_ai_bridge.paratext_connector import ParatextConnectorError
from tests.support.paratext_fixture import DEFAULT_GUID
from tests.support.paratext_writeback import (
    CAPABILITIES_074, DVT, IRVT, open_linked_review_project, reread_notes, saved_resolution, stand_in, write_thread,
)
from tests.support.projects import call


def _queue(engine, resolution_id, **extra):
    result = call(engine, "issueResolution.queueParatext",
                  {"chapter": "1", "verse": "1", "resolutionId": resolution_id, **extra})
    assert result["success"] is True, result
    return result["result"]


def test_a_note_goes_to_the_linked_project_by_id_even_with_another_project_active(tmp_path, monkeypatch):
    connector = stand_in(projects=(DVT, IRVT), active=DVT)
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", connector)
    engine, _ = open_linked_review_project(tmp_path, monkeypatch)
    resolution_id = saved_resolution(engine)

    result = _queue(engine, resolution_id)

    handoff = result["handoff"]
    assert handoff["status"] == "sent", handoff
    assert handoff["expectedProjectId"] == DEFAULT_GUID
    assert result["record"]["paratext"]["status"] == "sent"
    [(action, sent)] = connector.calls
    assert action == "create_note" and sent["project_id"] == DEFAULT_GUID
    # Decision 1: the footer names the message; decision 2: the reviewer's own
    # note only, the AI-derived correction and evidence left out by default.
    assert sent["comment"].endswith(f"[Bridge ref {handoff['messageId']}]")
    assert "Please look at this in Paratext." in sent["comment"]
    assert "AI: use a natural metaphor" not in sent["comment"] and "Evidence" not in sent["comment"]
    # Sent once: queueing again sends nothing.
    _queue(engine, resolution_id)
    assert len(connector.calls) == 1
    outbox = call(engine, "paratext.outbox")["result"]
    assert [(i["op"], i["status"], i["resultKey"]) for i in outbox["items"]] == [
        ("create_thread", "sent", "Yesu Selva Benz|2026-10-26T10:00:00.1234567+05:30")]


def test_the_proposal_goes_in_only_when_the_reviewer_includes_it(tmp_path, monkeypatch):
    connector = stand_in()
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", connector)
    engine, _ = open_linked_review_project(tmp_path, monkeypatch)
    _queue(engine, saved_resolution(engine), includeProposal=True)
    comment = connector.calls[0][1]["comment"]
    assert "Proposed correction: AI: use a natural metaphor." in comment and "Evidence: Translation Academy" in comment


def test_a_project_not_on_this_pc_or_an_older_connector_keeps_the_note_queued_until_it_can_go(tmp_path, monkeypatch):
    connector = stand_in(projects=(DVT,), active=DVT)
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", connector)
    engine, _ = open_linked_review_project(tmp_path, monkeypatch)
    resolution_id = saved_resolution(engine)

    queued = _queue(engine, resolution_id)["handoff"]
    assert queued["status"] == "queued"
    assert f"Paratext has no project IRVT ({DEFAULT_GUID[:8]}…) on this computer" in queued["lastError"]

    connector.projects = [DVT, IRVT]
    connector.capabilities = CAPABILITIES_074
    connector.version = "0.7.4"
    params = {"chapter": "1", "verse": "1", "resolutionId": resolution_id}
    older = call(engine, "issueResolution.retryParatext", params)["result"]["handoff"]
    assert older["status"] == "queued" and "update it to 0.8.0" in older["lastError"]
    assert connector.calls == []

    connector.capabilities = stand_in().capabilities
    sent = call(engine, "issueResolution.retryParatext", params)["result"]["handoff"]
    assert sent["status"] == "sent" and sent["attempts"] == 3
    assert len(connector.calls) == 1


def test_a_note_already_in_paratext_is_recorded_from_the_file_and_never_sent_again(tmp_path, monkeypatch):
    """The footer check: a crash after the send, or another device that sent it."""
    offline = stand_in(offline=True)
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", offline)
    engine, folder = open_linked_review_project(tmp_path, monkeypatch)
    resolution_id = saved_resolution(engine)
    queued = _queue(engine, resolution_id)["handoff"]
    assert queued["status"] == "queued" and "offline" in queued["lastError"]

    write_thread(folder, "T1", ["Bridge Translation Note review for TIT 1:1", f"[Bridge ref {queued['messageId']}]"],
                 user="Yesu Selva Benz")
    reread_notes(engine)
    online = stand_in()
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", online)

    result = call(engine, "issueResolution.retryParatext",
                  {"chapter": "1", "verse": "1", "resolutionId": resolution_id})["result"]

    assert result["handoff"]["status"] == "sent" and result["handoff"]["remoteId"] == "T1"
    assert online.calls == []
    links = call(engine, "paratext.outbox")["result"]["links"]
    assert links == [{"kind": "issue_resolution", "localId": resolution_id, "threadId": "T1",
                      "messageId": queued["messageId"], "direction": "bridge_to_paratext"}]


def test_nothing_is_sent_while_the_notes_index_is_behind_the_files(tmp_path, monkeypatch):
    connector = stand_in()
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", connector)
    engine, _ = open_linked_review_project(tmp_path, monkeypatch)
    monkeypatch.setattr(engine._paratext_session(), "index_ready", lambda: False)

    handoff = _queue(engine, saved_resolution(engine))["handoff"]

    assert handoff["status"] == "queued" and "so nothing is sent twice" in handoff["lastError"]
    assert connector.calls == []


def test_a_sent_thread_gets_its_link_once_the_index_shows_it(tmp_path, monkeypatch):
    connector = stand_in()
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", connector)
    engine, folder = open_linked_review_project(tmp_path, monkeypatch)
    resolution_id = saved_resolution(engine)
    handoff = _queue(engine, resolution_id)["handoff"]
    assert handoff["status"] == "sent" and handoff["remoteId"] == ""

    # Paratext wrote the thread; the next flush (here, an explicit one) finds it.
    write_thread(folder, "T7", ["Bridge review", f"[Bridge ref {handoff['messageId']}]"], user="Yesu Selva Benz")
    reread_notes(engine)
    flushed = call(engine, "paratext.flushOutbox")["result"]

    assert [i["threadId"] for i in flushed["items"]] == ["T7"]
    assert flushed["links"][0]["threadId"] == "T7"
    record = call(engine, "issueResolution.list", {"chapter": "1", "verse": "1"})["result"]["items"][0]
    assert record["paratext"]["remoteId"] == "T7"
    assert len(connector.calls) == 1


def test_reply_resolve_and_link_name_the_thread_by_its_first_comment(tmp_path, monkeypatch):
    connector = stand_in()
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", connector)
    engine, folder = open_linked_review_project(tmp_path, monkeypatch)
    write_thread(folder, "T9", ["Is this the right word?"], user="Translator",
                 date="2026-10-20T08:00:00.0000000+05:30")
    reread_notes(engine)
    common = {"threadId": "T9", "kind": "issue_resolution", "localId": "r-1"}

    reply = call(engine, "paratext.replyThread", {**common, "text": "Changed in Bridge."})
    resolve = call(engine, "paratext.resolveThread", common)
    link = call(engine, "paratext.linkThread", {**common, "localId": "r-2"})
    missing = call(engine, "paratext.replyThread", {**common, "threadId": "nope", "text": "x"})

    assert reply["result"]["item"]["status"] == "sent" and resolve["result"]["item"]["status"] == "sent"
    (a1, comment), (a2, resolved) = connector.calls
    assert (a1, a2) == ("add_comment", "resolve_note")
    key = {"verse_ref": "TIT 1:1", "offset": -1, "selected_text": "", "first_author": "Translator",
           "first_created": "2026-10-20T08:00:00.0000000+05:30"}
    assert comment == {"project_id": DEFAULT_GUID, "book": "TIT", "chapter": "1", "key": key,
                       "text": f"Changed in Bridge.\n\n[Bridge ref {reply['result']['item']['messageId']}]"}
    assert resolved["key"] == key
    assert link["result"]["link"]["direction"] == "paratext_to_bridge"
    assert missing["success"] is False and "has not read that Paratext thread" in str(missing)


def test_the_navigation_probe_flushes_a_queued_note_when_paratext_answers(tmp_path, monkeypatch):
    offline = stand_in(offline=True)
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", offline)
    engine, _ = open_linked_review_project(tmp_path, monkeypatch)
    resolution_id = saved_resolution(engine)
    assert _queue(engine, resolution_id)["handoff"]["status"] == "queued"

    online = stand_in()
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", online)
    engine._outbox_flushed_at = 0.0
    engine._background_outbox_flush()       # what the probe calls after Paratext answered

    assert [action for action, _ in online.calls] == ["create_note"]
    record = call(engine, "issueResolution.list", {"chapter": "1", "verse": "1"})["result"]["items"][0]
    assert record["paratext"]["status"] == "sent"
    # Throttled: a second call within five seconds does nothing.
    engine._background_outbox_flush()
    assert len(online.calls) == 1


@pytest.mark.parametrize("method", ["paratext.replyThread", "paratext.resolveThread", "paratext.linkThread"])
def test_an_unknown_kind_is_refused(tmp_path, monkeypatch, method):
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", stand_in())
    engine, folder = open_linked_review_project(tmp_path, monkeypatch)
    write_thread(folder, "T9", ["x"])
    reread_notes(engine)
    result = call(engine, method, {"threadId": "T9", "kind": "verse", "localId": "r", "text": "x"})
    assert result["success"] is False and "kind must be one of" in str(result)


def test_a_card_shows_its_threads_with_paratext_replies_and_a_done_and_changes_nothing(tmp_path, monkeypatch):
    """#358 (e): the card's read. A sent note with no thread yet is a link-to-be;
    once Paratext's file has it, the thread comes with its replies; a `done` in
    Paratext is shown as resolved there and the resolution's own status stays."""
    connector = stand_in()
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", connector)
    engine, folder = open_linked_review_project(tmp_path, monkeypatch)
    resolution_id = saved_resolution(engine)
    handoff = _queue(engine, resolution_id)["handoff"]
    params = {"kind": "issue_resolution", "localId": resolution_id}

    before = call(engine, "paratext.threadsFor", params)["result"]
    assert [(l["threadId"], l["thread"]) for l in before["links"]] == [("", None)]
    assert before["pending"] == []

    from tests.support.paratext_fixture import write_notes_file
    write_notes_file(folder, "Yesu Selva Benz", [
        {"thread": "T5", "verse_ref": "TIT 1:1", "date": "2026-10-26T10:00:00.1234567+05:30", "status": "todo",
         "contents": ["Bridge review", f"[Bridge ref {handoff['messageId']}]"]},
    ])
    write_notes_file(folder, "Translator", [
        {"thread": "T5", "verse_ref": "TIT 1:1", "date": "2026-10-27T09:00:00.0000000+05:30", "status": "deleted",
         "contents": ["Fixed in Paratext."]},
    ])
    reread_notes(engine)
    call(engine, "paratext.flushOutbox")
    status_before = call(engine, "issueResolution.list", {"chapter": "1", "verse": "1"})["result"]["items"][0]["status"]

    after = call(engine, "paratext.threadsFor", params)["result"]

    [link] = after["links"]
    assert link["threadId"] == "T5" and link["thread"]["resolved"] is True
    assert [c["user"] for c in link["thread"]["comments"]] == ["Yesu Selva Benz", "Translator"]
    record = call(engine, "issueResolution.list", {"chapter": "1", "verse": "1"})["result"]["items"][0]
    assert record["status"] == status_before
    assert len(connector.calls) == 1


def _linked_thread(engine, folder, resolution_id, *, done: bool):
    """A sent note whose thread T5 Paratext's file shows, resolved there or not."""
    handoff = _queue(engine, resolution_id)["handoff"]
    from tests.support.paratext_fixture import write_notes_file
    write_notes_file(folder, "Yesu Selva Benz", [
        {"thread": "T5", "verse_ref": "TIT 1:1", "date": "2026-10-26T10:00:00.1234567+05:30", "status": "todo",
         "contents": ["Bridge review", f"[Bridge ref {handoff['messageId']}]"]},
    ])
    write_notes_file(folder, "Translator", [
        {"thread": "T5", "verse_ref": "TIT 1:1", "date": "2026-10-27T09:00:00.0000000+05:30",
         "status": "deleted" if done else "todo", "contents": ["Fixed in Paratext."]},
    ])
    reread_notes(engine)
    call(engine, "paratext.flushOutbox")


def test_one_click_after_a_paratext_done_resolves_the_issue_and_records_who_and_which_done(tmp_path, monkeypatch):
    """Decision 3: the `done` is only shown until the reviewer clicks; the click
    sets the resolution to resolved and names the Paratext comment it followed."""
    connector = stand_in()
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", connector)
    engine, folder = open_linked_review_project(tmp_path, monkeypatch)
    resolution_id = saved_resolution(engine)
    _linked_thread(engine, folder, resolution_id, done=True)
    params = {"chapter": "1", "verse": "1", "resolutionId": resolution_id, "threadId": "T5"}

    result = call(engine, "issueResolution.resolveFromParatext", params)

    assert result["success"] is True, result
    record = result["result"]["record"]
    assert record["status"] == "resolved"
    event = record["history"][-1]
    assert event["event"] == "resolved_from_paratext" and event["previousStatus"] == "open"
    assert (event["threadId"], event["paratextDoneBy"]) == ("T5", "Translator")
    assert event["paratextDoneAt"] == "2026-10-27T09:00:00.0000000+05:30"
    listed = call(engine, "issueResolution.list", {"chapter": "1", "verse": "1"})["result"]
    assert listed["resolved"] == 1
    # Bridge-side only: nothing more went to Paratext.
    assert len(connector.calls) == 1
    again = call(engine, "issueResolution.resolveFromParatext", params)
    assert again["success"] is False and "already resolved" in str(again)


def test_one_click_is_refused_while_paratext_has_not_resolved_the_thread_or_it_is_not_linked(tmp_path, monkeypatch):
    connector = stand_in()
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", connector)
    engine, folder = open_linked_review_project(tmp_path, monkeypatch)
    resolution_id = saved_resolution(engine)
    _linked_thread(engine, folder, resolution_id, done=False)
    base = {"chapter": "1", "verse": "1", "resolutionId": resolution_id}

    open_thread = call(engine, "issueResolution.resolveFromParatext", {**base, "threadId": "T5"})
    unlinked = call(engine, "issueResolution.resolveFromParatext", {**base, "threadId": "T9"})

    assert open_thread["success"] is False and "does not show that thread as resolved" in str(open_thread)
    assert unlinked["success"] is False and "not linked to this issue" in str(unlinked)
    record = call(engine, "issueResolution.list", {"chapter": "1", "verse": "1"})["result"]["items"][0]
    assert record["status"] == "open"


def test_a_note_on_a_selection_carries_the_neighbouring_words_so_paratext_can_tell_repeats_apart(tmp_path, monkeypatch):
    connector = stand_in()
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", connector)
    engine, _ = open_linked_review_project(tmp_path, monkeypatch)

    handoff = _queue(engine, saved_resolution(engine, selected_text="beta"))["handoff"]

    assert handoff["status"] == "sent", handoff
    [(action, sent)] = connector.calls
    assert action == "create_note"
    assert (sent["before_context"], sent["after_context"]) == ("alpha", "gamma")
    [item] = call(engine, "paratext.outbox")["result"]["items"]
    assert (item["beforeContext"], item["afterContext"]) == ("alpha", "gamma")


@pytest.mark.parametrize(("verse", "selected", "expected"), [
    # #358 h: the NTB PSA 1:1 shape -- the first word repeated in its own footnote.
    (r"பாவிகளுடைய வழியில் நில்லாமல்\f + \fr 1:1 \ft பாவிகளுடைய எனவும்\f* இருக்கிறான்.",
     "பாவிகளுடைய", ("", "வழியில்")),
    ("alpha beta, gamma", "beta", ("alpha", ", gamma")),
    ("alpha beta gamma", "gamma", ("beta", "")),
    # A repeat in the verse itself is the reviewer's to pick in Paratext: no context.
    ("beta alpha beta", "beta", ("", "")),
    ("alpha beta gamma", "delta", ("", "")),
    ("alpha beta gamma", "", ("", "")),
])
def test_selection_context_is_one_word_each_side_and_only_for_a_selection_found_once(verse, selected, expected):
    assert outbox_module.selection_context(verse, selected) == expected
# -- (h): a selection Paratext cannot anchor -------------------------------------
# The verse of `open_linked_review_project` is "alpha beta gamma".

def _save_with_selection(engine, selected_text):
    check = call(engine, "check.listForVerse", {"chapter": "1", "verse": "1"})["result"]["checks"][0]
    return call(engine, "issueResolution.save", {
        "chapter": "1", "verse": "1", "tool": check["tool"], "groupId": check["groupId"],
        "checkId": check["checkId"], "expectedFingerprint": check["stateFingerprint"],
        "selectedText": selected_text, "issueSummary": "Wording to confirm with the team.",
        "reviewerNote": "Please look at this in Paratext.",
    })


def test_a_selection_that_repeats_in_the_verse_is_refused_at_save(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", stand_in())
    engine, _ = open_linked_review_project(tmp_path, monkeypatch)

    repeated = _save_with_selection(engine, "a")

    assert repeated["success"] is False
    assert "occurs 5 times in this verse" in repeated["error"]["message"]
    assert _save_with_selection(engine, "beta")["success"] is True


def test_a_selection_that_repeats_since_the_save_is_not_queued(tmp_path, monkeypatch):
    connector = stand_in()
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", connector)
    engine, _ = open_linked_review_project(tmp_path, monkeypatch)
    resolution_id = _save_with_selection(engine, "beta")["result"]["resolutionId"]
    assert call(engine, "verse.edit", {"chapter": "1", "verse": "1", "newText": "alpha beta beta"})["success"] is True

    queued = call(engine, "issueResolution.queueParatext", {"chapter": "1", "verse": "1", "resolutionId": resolution_id})

    assert queued["success"] is False and "occurs 2 times" in queued["error"]["message"]
    assert connector.calls == []
    assert call(engine, "paratext.outbox")["result"]["items"] == []


def test_a_selection_repeated_only_in_a_footnote_can_be_saved_and_sent(tmp_path, monkeypatch):
    connector = stand_in()
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", connector)
    engine, _ = open_linked_review_project(tmp_path, monkeypatch)
    edited = call(engine, "verse.edit", {"chapter": "1", "verse": "1",
                  "newText": r"alpha beta gamma\f + \ft beta\f*"})
    assert edited["success"] is True, edited

    saved = _save_with_selection(engine, "beta")
    assert saved["success"] is True, saved
    assert _queue(engine, saved["result"]["resolutionId"])["handoff"]["status"] == "sent"
    assert connector.calls[0][1]["before_context"] == "alpha"
    assert connector.calls[0][1]["after_context"] == "gamma"


def test_a_note_paratext_refuses_as_ambiguous_stops_until_the_reviewer_retries(tmp_path, monkeypatch):
    """The plugin's "occurs more than once" (its selection matching counts text
    Bridge may not see the same way) used to leave the note queued and retried
    on every probe for ever. It now stops as `refused`; the card's retry sends."""
    connector = stand_in()
    sent = connector.create_note

    def refuse(self, reference, selected_text, comment, **kwargs):
        connector.calls.append(("create_note", {"reference": reference, "comment": comment, **kwargs}))
        raise ParatextConnectorError(
            "The selected text occurs more than once in this verse. Select the exact occurrence inside "
            "Paratext, then retry so the note cannot attach to the wrong word.")

    connector.create_note = refuse
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", connector)
    engine, _ = open_linked_review_project(tmp_path, monkeypatch)
    resolution_id = _save_with_selection(engine, "beta")["result"]["resolutionId"]

    handoff = _queue(engine, resolution_id)["handoff"]

    assert handoff["status"] == "refused" and "occurs more than once" in handoff["lastError"]
    threads = call(engine, "paratext.threadsFor", {"kind": "issue_resolution", "localId": resolution_id})["result"]
    assert [(i["op"], i["status"]) for i in threads["pending"]] == [("create_thread", "refused")]
    # The background pass leaves it: nothing to retry, no second call.
    assert engine._outbox_work is False
    engine._outbox_flushed_at = 0.0
    engine._background_outbox_flush()
    assert len(connector.calls) == 1

    # The reviewer selects that occurrence in Paratext and retries from the card.
    connector.create_note = sent
    retried = call(engine, "issueResolution.retryParatext",
                   {"chapter": "1", "verse": "1", "resolutionId": resolution_id})["result"]["handoff"]
    assert retried["status"] == "sent" and retried["attempts"] == 2
    assert len(connector.calls) == 2
