"""#431 / #433 / #434 over the protocol: the checked revert also reverses
the Paratext write and tells the thread; an interrupted apply is classified
and reconciled explicitly before another apply on the verse; a thread with
QA proposals resolves only through the completion gate, and a saved resolve
that could not go is retried without any Scripture; reports are listed with
interrupted generations cleared, written to a chosen destination, cumulative
or per session, and the CSV names the Bridge user and the Paratext actor."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import bridge_service as bridge_service_module
from tests.support.paratext_fixture import write_notes_file
from tests.support.paratext_review import decide, open_queue, qa_note, queue, threads, verse_text
from tests.support.paratext_writeback import reread_notes, stand_in
from tests.support.projects import call


def test_revert_reverses_the_paratext_write_and_comments_on_the_thread(tmp_path, monkeypatch):
    connector = stand_in()
    engine, _ = open_queue(tmp_path, monkeypatch, [{"thread": "A", "contents": qa_note("beta", "BETA")}],
                           connector=connector)
    [item] = queue(engine)["items"]
    applied = decide(engine, item["proposalId"], "applied", writeParatext=True)["result"]["decision"]
    assert applied["paratext"]["status"] == "sent" and "alpha BETA gamma" in connector.scripture["TIT 1"]

    reverted = call(engine, "paratextReview.revertLatest")["result"]["decision"]
    assert reverted["decision"] == "reverted" and reverted["revertVerified"] is True
    assert verse_text(engine) == "alpha beta gamma"
    reverse = reverted["paratextReverse"]
    assert reverse["request"] == {"original": "BETA", "replacement": "beta", "beforeContext": "alpha",
                                  "afterContext": "gamma", "region": "body", "allowDelete": False}
    assert reverse["status"] == "sent" and reverse["verified"] is True
    assert "alpha beta gamma" in connector.scripture["TIT 1"]
    calls = [(a, c) for a, c in connector.calls if a in ("put_verse_text", "add_comment")]
    assert calls[-2][0] == "put_verse_text" and calls[-2][1]["original"] == "BETA"
    assert calls[-1][0] == "add_comment" and "reverted in Bridge" in calls[-1][1]["text"]
    assert reverted["revertNoteMessageId"]


def test_a_deletion_is_reversed_by_restoring_the_window_around_the_gap(tmp_path, monkeypatch):
    connector = stand_in()
    engine, _ = open_queue(tmp_path, monkeypatch, [
        {"thread": "D", "contents": qa_note("beta ", "(delete)", category="Addition not in source")}], connector=connector)
    [item] = queue(engine)["items"]
    deleted = decide(engine, item["proposalId"], "applied", confirmDelete=True, writeParatext=True)["result"]["decision"]
    assert deleted["replacement"] == "" and verse_text(engine) == "alpha  gamma"
    assert "\\v 1 alpha  gamma" in connector.scripture["TIT 1"]
    reverted = call(engine, "paratextReview.revertLatest")["result"]["decision"]
    assert reverted["paratextReverse"]["request"]["original"] == "alpha  gamma"
    assert reverted["paratextReverse"]["request"]["replacement"] == "alpha beta gamma"
    assert reverted["paratextReverse"]["status"] == "sent"
    assert "\\v 1 alpha beta gamma" in connector.scripture["TIT 1"] and verse_text(engine) == "alpha beta gamma"


def test_an_interrupted_apply_is_classified_and_blocks_a_new_apply_until_reconciled(tmp_path, monkeypatch):
    from tc_ai_bridge import paratext_review as review
    engine, _ = open_queue(tmp_path, monkeypatch, [
        {"thread": "A", "contents": qa_note("beta", "BETA")},
        {"thread": "B", "contents": qa_note("gamma", "GAMMA", category="Grammar")},
    ])
    items = {i["threadId"]: i for i in queue(engine)["items"]}
    applied = decide(engine, items["A"]["proposalId"], "applied")["result"]["decision"]
    # Simulate a crash between the write and the verification: the row says
    # applied, not verified; the verse holds the result.
    store = engine._review_store()
    store.write_decision({**applied, "verified": False, "unverifiedReason": "interrupted"})
    listed = queue(engine)
    assert listed["uncertain"] == [items["A"]["proposalId"]]
    blocked = decide(engine, items["B"]["proposalId"], "applied")
    assert blocked["success"] is False and "reconcile it" in blocked["error"]["message"]

    uncertain = call(engine, "paratextReview.uncertain")["result"]["items"]
    assert [u["classified"] for u in uncertain] == ["verified"]
    wrong = call(engine, "paratextReview.reconcile", {"proposalId": items["A"]["proposalId"], "outcome": "notApplied"})
    assert wrong["success"] is False and "pre-image" in wrong["error"]["message"]
    done = call(engine, "paratextReview.reconcile", {"proposalId": items["A"]["proposalId"], "outcome": "verified",
                                                       "note": "Checked the verse."})["result"]
    assert done["decision"]["verified"] is True and done["decision"]["reconciled"]["state"] == "verified"
    assert done["decision"]["reconciled"]["by"] and done["decision"]["reconciled"]["note"] == "Checked the verse."
    assert queue(engine)["uncertain"] == []
    assert decide(engine, items["B"]["proposalId"], "applied")["success"] is True

    # The other two classes: the text is still the pre-image, or neither.
    pre = {**applied, "verified": False, "after": {**applied["after"], "raw": "alpha BETA gamma"}}
    assert review.classify_apply(pre, "alpha beta gamma") == "notApplied"
    assert review.classify_apply(pre, "alpha Beta gamma!") == "conflict"
    assert review.classify_apply(pre, "alpha BETA gamma") == "verified"
    # Every reconciliation revision is in change_log.
    ops = [e["op"] for e in engine.project.workbench.change_log_entries(engine.project.workbench_identity.project_id)
           if e["table_name"] == "paratext_review_decisions"]
    assert ops.count("decision:applied") >= 3


def test_not_applied_returns_the_proposal_to_deferred_and_conflict_keeps_it_blocked(tmp_path, monkeypatch):
    engine, _ = open_queue(tmp_path, monkeypatch, [{"thread": "A", "contents": qa_note("beta", "BETA")}])
    [item] = queue(engine)["items"]
    applied = decide(engine, item["proposalId"], "applied")["result"]["decision"]
    # Roll the verse back by hand (another editor) and lose the verification.
    assert call(engine, "verse.edit", {"chapter": "1", "verse": "1", "newText": "alpha beta gamma"})["success"]
    engine._review_store().write_decision({**applied, "verified": False})
    [u] = call(engine, "paratextReview.uncertain")["result"]["items"]
    assert u["classified"] == "notApplied"
    back = call(engine, "paratextReview.reconcile", {"proposalId": item["proposalId"], "outcome": "notApplied"})["result"]
    assert back["decision"]["decision"] == "deferred" and back["decision"]["reconciled"]["state"] == "notApplied"
    assert queue(engine)["counts"]["deferred"] == 1
    # Applied again from scratch, now verified.
    assert decide(engine, item["proposalId"], "applied")["result"]["decision"]["verified"] is True

    # Conflict: someone else changed the verse after an unverified apply.
    applied = engine._review_store().decision(item["proposalId"])
    assert call(engine, "verse.edit", {"chapter": "1", "verse": "1", "newText": "alpha Beta gamma!"})["success"]
    engine._review_store().write_decision({**applied, "verified": False})
    [u] = call(engine, "paratextReview.uncertain")["result"]["items"]
    assert u["classified"] == "conflict"
    kept = call(engine, "paratextReview.reconcile", {"proposalId": item["proposalId"], "outcome": "conflict",
                                                       "note": "Ask the translator."})["result"]["decision"]
    assert kept["decision"] == "applied" and kept["verified"] is False and kept["reconciled"]["state"] == "conflict"
    assert queue(engine)["items"][0]["thread"]["complete"] is False
    manual = decide(engine, item["proposalId"], "manual", comment="Fixed by hand after the conflict.")["result"]
    assert manual["item"]["thread"]["complete"] is True


def test_resolve_from_the_queue_passes_the_completion_gate_and_a_queued_resolve_retries_without_scripture(
        tmp_path, monkeypatch):
    connector = stand_in()
    engine, folder = open_queue(tmp_path, monkeypatch, [
        {"thread": "A", "contents": qa_note("alpha", "Alpha") + [""] + qa_note("gamma", "Gamma")},
    ], connector=connector)
    first, second = queue(engine)["items"]
    decide(engine, first["proposalId"], "applied", writeParatext=True)
    early = call(engine, "paratext.resolveThread", {"threadId": "A", "kind": "note", "localId": "A"})
    assert early["success"] is False and "without a terminal decision" in early["error"]["message"]
    assert not [a for a, _ in connector.calls if a == "resolve_note"]
    decide(engine, second["proposalId"], "rejected", comment="Reads fine.")
    # A new proposal appeared in the thread meanwhile: the gate reloads the discussion.
    write_notes_file(folder, "QA Pass", [
        {"thread": "A", "verse_ref": "TIT 1:1", "date": "2026-10-20T08:00:00.0000000+05:30", "status": "todo",
         "contents": qa_note("alpha", "Alpha") + [""] + qa_note("gamma", "Gamma")},
        {"thread": "A", "verse_ref": "TIT 1:1", "date": "2026-10-23T08:00:00.0000000+05:30", "status": "todo",
         "contents": qa_note("beta", "BETA", category="Grammar")},
    ])
    reread_notes(engine)
    again = call(engine, "paratext.resolveThread", {"threadId": "A", "kind": "note", "localId": "A"})
    assert again["success"] is False and "undecided" in again["error"]["message"]
    third = next(i for i in queue(engine)["items"] if i["proposal"]["original"] == "beta")
    decide(engine, third["proposalId"], "manual", comment="Done in Paratext.")

    # Paratext is away when the resolve is saved: it waits, and the retry sends only the resolve.
    connector.offline = True
    saved = call(engine, "paratext.resolveThread", {"threadId": "A", "kind": "note", "localId": "A"})["result"]
    assert saved["item"]["status"] == "queued"
    pending = call(engine, "paratextReview.reports")["result"]["pendingResolves"]
    assert [p["threadId"] for p in pending] == ["A"]
    writes_before = len([a for a, _ in connector.calls if a == "put_verse_text"])
    connector.offline = False
    call(engine, "paratext.flushOutbox")
    assert [a for a, _ in connector.calls if a == "resolve_note"] == ["resolve_note"]
    assert len([a for a, _ in connector.calls if a == "put_verse_text"]) == writes_before
    assert call(engine, "paratextReview.reports")["result"]["pendingResolves"] == []


def test_reports_are_listed_interrupted_ones_cleared_destinations_honoured_and_csv_names_the_actors(
        tmp_path, monkeypatch):
    connector = stand_in()
    engine, folder = open_queue(tmp_path, monkeypatch, [
        {"thread": "A", "contents": qa_note("beta", "BETA")},
        {"thread": "B", "contents": qa_note("gamma", "GAMMA", category="Grammar")},
    ], connector=connector)
    items = {i["threadId"]: i for i in queue(engine)["items"]}
    me = engine.local_user()
    call(engine, "paratextReview.saveState", {"state": {"sessionStartedAt": "2026-01-01T00:00:00+00:00"}})
    decide(engine, items["A"]["proposalId"], "applied", comment="ok", writeParatext=True)
    call(engine, "paratext.resolveThread", {"threadId": "A", "kind": "note", "localId": "A"})
    # Paratext's file shows the thread done; Bridge reads it on the next refresh.
    threads(folder, [{"thread": "A", "contents": qa_note("beta", "BETA"), "status": "done"},
                     {"thread": "B", "contents": qa_note("gamma", "GAMMA", category="Grammar")}])
    reread_notes(engine)
    folder_reports = Path(engine.project.path) / ".apps" / "translationCoreAI" / "paratext-review"
    folder_reports.mkdir(parents=True)
    (folder_reports / "report-20260101T000000Z.html.tmp").write_text("half", encoding="utf-8")

    listed = call(engine, "paratextReview.reports")["result"]
    assert listed["interrupted"] == ["report-20260101T000000Z.html.tmp"] and listed["reports"] == []
    assert not (folder_reports / "report-20260101T000000Z.html.tmp").exists()

    report = call(engine, "paratextReview.report")["result"]
    assert report["written"] and report["count"] == 1 and report["cumulative"] is False
    assert f"({me['userId']})" in report["html"] and "Paratext: written by Paratext user Yesu Selva Benz" in report["html"]
    assert "resolved in Bridge" in report["html"]
    listed = call(engine, "paratextReview.reports")["result"]
    assert [r["path"] for r in listed["reports"]] == [report["path"]]
    opened = call(engine, "paratextReview.latestReport", {"path": report["path"]})["result"]
    assert opened["html"] == report["html"]
    outside = call(engine, "paratextReview.latestReport", {"path": str(tmp_path / "report-x.html")})
    assert outside["success"] is False

    # A new session: the earlier decision is outside it, cumulative includes it.
    call(engine, "paratextReview.saveState", {"state": {"sessionStartedAt": "2099-01-01T00:00:00+00:00"}})
    empty = call(engine, "paratextReview.report")["result"]
    assert empty["written"] is False
    chosen = tmp_path / "elsewhere" / "report-session.html"
    cumulative = call(engine, "paratextReview.report", {"cumulative": True, "outputPath": str(chosen)})["result"]
    assert cumulative["written"] and cumulative["cumulative"] is True and Path(cumulative["path"]) == chosen
    assert chosen.read_text(encoding="utf-8") == cumulative["html"]
    unwritable = call(engine, "paratextReview.report", {"cumulative": True,
                                                         "outputPath": str(chosen / "nested" / "r.html")})
    assert unwritable["success"] is False and "could not be written" in unwritable["error"]["message"]

    out = tmp_path / "decisions.csv"
    call(engine, "paratextReview.exportCsv", {"outputPath": str(out)})
    [row] = list(csv.DictReader(io.StringIO(out.read_bytes().decode("utf-8-sig"))))
    assert row["bridgeUserId"] == me["userId"] and row["bridgeUserName"] == me["displayName"]
    assert row["paratextWrite"] == "sent" and row["paratextVerified"] == "yes" and row["paratextAuthor"] == "Yesu Selva Benz"
    assert row["region"] == "body" and row["resolutionOrigin"] == "resolved in Bridge"
    assert row["threadResolved"] == "yes" and row["resolvedBy"] == "QA Pass"
