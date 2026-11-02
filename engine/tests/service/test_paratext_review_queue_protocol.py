"""#428 / #431 / #432 / #433 / #434 over the protocol: the Paratext QA review
queue on the one-verse Titus ("alpha beta gamma") linked to a synthetic
Paratext folder. An apply goes through verse.edit's writer and is read back;
a revert is refused once the verse moved on; decisions are the team's rows;
CSV and the HTML session report are written from them."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from tc_ai_bridge import paratext_review as review
from tests.support.paratext_review import decide, open_queue, qa_note, queue, verse_text
from tests.support.projects import call


def test_the_queue_lists_outstanding_proposals_in_order_with_presets_and_counts(tmp_path, monkeypatch):
    engine, _ = open_queue(tmp_path, monkeypatch, [
        {"thread": "B", "contents": qa_note("gamma", "gamma."), "date": "2026-10-22T08:00:00.0000000+05:30"},
        {"thread": "A", "contents": qa_note("alpha", "Alpha"), "date": "2026-10-21T08:00:00.0000000+05:30"},
        {"thread": "N", "contents": qa_note("beta", "(no change)", category="Source comparison")},
        {"thread": "H", "contents": ["Changed to: betta"]},
        {"thread": "R", "contents": qa_note("beta", "bet", category="Grammar"), "status": "deleted"},
    ])
    result = queue(engine)
    assert result["status"] == "unresolved" and result["book"] == "TIT" and result["indexState"] == "ready"
    assert [i["threadId"] for i in result["items"]] == ["A", "B"]          # by date within the verse
    assert result["counts"] == {"total": 2, "undecided": 2, "applied": 0, "rejected": 0, "manual": 0,
                                "deferred": 0, "reverted": 0}
    assert [p["id"] for p in result["presets"]] == ["accepted", "accepted-revised", "retained", "meaning", "already"]
    assert all(i["decision"] is None and i["thread"]["complete"] is False for i in result["items"])
    resolved = queue(engine, "resolved")
    assert [i["threadId"] for i in resolved["items"]] == ["R"]
    everything = queue(engine, "all")
    assert [i["threadId"] for i in everything["items"]] == ["A", "B", "R"]


def test_apply_edits_the_bridge_verse_through_the_writer_reads_it_back_and_completes_the_thread(
        tmp_path, monkeypatch):
    engine, _ = open_queue(tmp_path, monkeypatch, [{"thread": "A", "contents": qa_note("beta", "BETA")}])
    [item] = queue(engine)["items"]
    assert item["proposal"]["route"] == "literal"

    preview = call(engine, "paratextReview.preview", {"proposalId": item["proposalId"]})["result"]
    assert preview["ok"] and preview["after"] == "alpha BETA gamma" and preview["span"] == {"plainStart": 6, "plainEnd": 10}

    result = decide(engine, item["proposalId"], "applied", comment="ok")
    assert result["success"] is True, result
    decision = result["result"]["decision"]
    assert decision["decision"] == "applied" and decision["verified"] is True
    assert decision["before"]["plain"] == "alpha beta gamma" and decision["after"]["plain"] == "alpha BETA gamma"
    assert decision["journalTransactionId"]
    assert verse_text(engine) == "alpha BETA gamma"
    assert result["result"]["item"]["thread"] == {"complete": True, "blocking": []}
    # Apply again is refused; the row is the team's (synced table) and its history is in change_log.
    again = decide(engine, item["proposalId"], "applied")
    assert again["success"] is False and "revert it first" in again["error"]["message"]
    counts = queue(engine)["counts"]
    assert counts["applied"] == 1 and counts["undecided"] == 0


def test_a_stale_or_ambiguous_original_is_refused_and_nothing_is_written(tmp_path, monkeypatch):
    engine, _ = open_queue(tmp_path, monkeypatch, [
        {"thread": "S", "contents": qa_note("delta", "DELTA")},
        {"thread": "M", "contents": qa_note("a", "A")},
    ])
    items = {i["threadId"]: i for i in queue(engine)["items"]}
    stale = decide(engine, items["S"]["proposalId"], "applied")
    assert stale["success"] is False and "not found" in stale["error"]["message"]
    ambiguous = decide(engine, items["M"]["proposalId"], "applied")
    assert ambiguous["success"] is False and "occurs" in ambiguous["error"]["message"]
    assert verse_text(engine) == "alpha beta gamma"
    assert queue(engine)["counts"]["undecided"] == 2


def test_review_only_routes_and_structural_text_cannot_be_applied(tmp_path, monkeypatch):
    engine, _ = open_queue(tmp_path, monkeypatch, [
        {"thread": "I", "contents": qa_note("beta", "consider the source")},
        {"thread": "F", "contents": qa_note("beta", "BETA", category="USFM marker")},
        {"thread": "T", "contents": qa_note("beta", "BETA", category="Footnote / cross-reference")},
    ])
    items = {i["threadId"]: i for i in queue(engine)["items"]}
    assert "cannot be applied" in decide(engine, items["I"]["proposalId"], "applied")["error"]["message"]
    assert "review-only" in decide(engine, items["F"]["proposalId"], "applied")["error"]["message"]
    # A reviewer may still type the exact text for an instruction: it is then an ordinary replace.
    typed = decide(engine, items["I"]["proposalId"], "applied", replacement="BETA")
    assert typed["success"] is False, "an instruction is never applied, even with text supplied"
    marker = decide(engine, items["T"]["proposalId"], "applied", replacement="x\\f")
    assert marker["success"] is False


def test_rejection_and_manual_need_a_comment_and_record_the_observed_text_deferred_blocks_resolution(
        tmp_path, monkeypatch):
    engine, _ = open_queue(tmp_path, monkeypatch, [
        {"thread": "A", "contents": qa_note("alpha", "Alpha") + [""] + qa_note("gamma", "Gamma")},
    ])
    items = queue(engine)["items"]
    assert len(items) == 2 and {i["threadId"] for i in items} == {"A"}
    first, second = items
    assert "needs a comment" in decide(engine, first["proposalId"], "rejected")["error"]["message"]
    rejected = decide(engine, first["proposalId"], "rejected", comment="Reads fine.")["result"]
    assert rejected["decision"]["observed"]["plain"] == "alpha beta gamma"
    assert rejected["item"]["thread"]["complete"] is False
    deferred = decide(engine, second["proposalId"], "deferred")["result"]
    assert deferred["item"]["thread"]["blocking"] == [f"{second['proposalId']}: deferred"]
    manual = decide(engine, second["proposalId"], "manual", comment="Done in Paratext.")["result"]
    assert manual["item"]["thread"] == {"complete": True, "blocking": []}
    assert verse_text(engine) == "alpha beta gamma"


def test_a_deletion_needs_confirmation_and_an_alternative_is_applied_as_chosen(tmp_path, monkeypatch):
    engine, _ = open_queue(tmp_path, monkeypatch, [
        {"thread": "D", "contents": qa_note("beta ", "(delete)", category="Addition not in source")},
        {"thread": "C", "contents": qa_note("gamma", "GAMMA / Gamma", category="Grammar")},
    ])
    items = {i["threadId"]: i for i in queue(engine)["items"]}
    assert items["D"]["proposal"]["operation"] == "delete" and items["C"]["proposal"]["alternatives"] == ["GAMMA", "Gamma"]
    needs = decide(engine, items["D"]["proposalId"], "applied")
    assert needs["success"] is False and "confirm the deletion" in needs["error"]["message"]
    chosen = decide(engine, items["C"]["proposalId"], "applied", replacement="Gamma")["result"]["decision"]
    assert chosen["replacement"] == "Gamma" and verse_text(engine) == "alpha beta Gamma"
    deleted = decide(engine, items["D"]["proposalId"], "applied", confirmDelete=True)["result"]["decision"]
    # The parser trims field values, so the Original is "beta" and exactly that
    # span goes; the spacing around it is the reviewer's to see in the preview.
    assert deleted["replacement"] == "" and verse_text(engine) == "alpha  Gamma"


def test_revert_restores_the_latest_verified_apply_only_while_the_verse_still_matches(tmp_path, monkeypatch):
    engine, _ = open_queue(tmp_path, monkeypatch, [{"thread": "A", "contents": qa_note("beta", "BETA")}])
    [item] = queue(engine)["items"]
    nothing = call(engine, "paratextReview.revertLatest")
    assert nothing["success"] is False and "no verified applied" in nothing["error"]["message"]
    decide(engine, item["proposalId"], "applied")
    assert call(engine, "verse.edit", {"chapter": "1", "verse": "1", "newText": "alpha BETA gamma!"})["success"]
    refused = call(engine, "paratextReview.revertLatest")
    assert refused["success"] is False and "no longer reads as the correction left it" in refused["error"]["message"]
    assert verse_text(engine) == "alpha BETA gamma!"
    assert call(engine, "verse.edit", {"chapter": "1", "verse": "1", "newText": "alpha BETA gamma"})["success"]
    reverted = call(engine, "paratextReview.revertLatest")["result"]["decision"]
    assert reverted["decision"] == "reverted" and reverted["revertVerified"] is True
    assert verse_text(engine) == "alpha beta gamma"
    assert queue(engine)["counts"]["reverted"] == 1


def test_state_drafts_and_position_persist_and_a_decided_draft_is_dropped(tmp_path, monkeypatch):
    engine, _ = open_queue(tmp_path, monkeypatch, [{"thread": "A", "contents": qa_note("beta", "BETA")}])
    [item] = queue(engine)["items"]
    saved = call(engine, "paratextReview.saveState", {"state": {
        "status": "all", "position": item["proposalId"], "sessionStartedAt": "2026-11-02T00:00:00+00:00",
        "drafts": {item["proposalId"]: {"replacement": "Beta", "comment": "draft"}, "gone": {"replacement": "", "comment": ""}},
    }})["result"]["state"]
    assert saved["status"] == "all" and saved["position"] == item["proposalId"]
    assert list(saved["drafts"]) == [item["proposalId"]]
    listed = queue(engine)
    assert listed["status"] == "all" and listed["items"][0]["draft"] == {"replacement": "Beta", "comment": "draft"}
    bad = call(engine, "paratextReview.saveState", {"state": {"status": "weird"}})
    assert bad["success"] is False
    decide(engine, item["proposalId"], "applied", replacement="Beta", comment="draft")
    assert queue(engine)["state"]["drafts"] == {}


def test_csv_and_html_report_are_written_from_the_decisions_with_escaping(tmp_path, monkeypatch):
    engine, _ = open_queue(tmp_path, monkeypatch, [
        {"thread": "A", "contents": qa_note("beta", "BETA")},
        {"thread": "B", "contents": qa_note("gamma", "<b>gamma</b>", category="Grammar")},
    ])
    items = {i["threadId"]: i for i in queue(engine)["items"]}
    call(engine, "paratextReview.saveState", {"state": {"sessionStartedAt": "2026-01-01T00:00:00+00:00"}})
    empty = call(engine, "paratextReview.report")["result"]
    assert empty["written"] is False and "No decisions" in empty["reason"]
    decide(engine, items["A"]["proposalId"], "applied", comment="=SUM(1)\n\"quoted\" தமிழ்")
    decide(engine, items["B"]["proposalId"], "rejected", comment="keep <i>as is</i>")

    out = tmp_path / "decisions.csv"
    written = call(engine, "paratextReview.exportCsv", {"outputPath": str(out)})["result"]
    assert written["written"] is True and written["count"] == 2
    raw = out.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    assert [r["decision"] for r in rows] == ["applied", "rejected"]
    assert rows[0]["comment"] == "'=SUM(1)\n\"quoted\" தமிழ்" and rows[0]["verified"] == "yes"
    assert rows[1]["replacement"] == "<b>gamma</b>" and rows[1]["verified"] == ""

    report = call(engine, "paratextReview.report")["result"]
    assert report["written"] is True and report["count"] == 2
    html = Path(report["path"]).read_text(encoding="utf-8")
    assert html == report["html"] and "&lt;b&gt;gamma&lt;/b&gt;" in html and "<b>gamma</b>" not in html
    assert "Applied · verified" in html and "Rejected · text unchanged" in html
    assert '<mark class="now">BETA</mark>' in html
    assert Path(report["path"]).parent == Path(engine.project.path) / ".apps" / "translationCoreAI" / "paratext-review"
    latest = call(engine, "paratextReview.latestReport")["result"]
    assert latest["path"] == report["path"] and latest["html"] == html


def test_locate_disambiguates_by_context_and_refuses_text_across_markup():
    raw = "one \\w two|x=1\\w* three two \\f + \\fr 1:1 \\ft two\\f* four"
    assert review.locate(raw, "two").ok is False
    by_context = review.locate(raw, "two", context_before="three", context_after="four")
    assert by_context.ok and by_context.chosen.whole_word
    assert review.locate(raw, "two three").ok is False  # runs across the \w* markup
    assert "Original was not found" in review.locate(raw, "five").reason
    tamil = review.locate("அவர் இல்லை இல்லைஇல்லை", "இல்லை")
    # Three matches (one is the standalone word, two sit inside the joined
    # word); the whole-word one wins, and none cut a vowel sign or virama.
    assert tamil.ok and tamil.chosen.start == 5 and len(tamil.found) == 3 and tamil.chosen.whole_word


def test_decisions_are_a_synced_table_and_every_revision_is_in_change_log(tmp_path, monkeypatch):
    from tc_ai_bridge.hub_sync import SYNCED_TABLES
    assert "paratext_review_decisions" in SYNCED_TABLES and "paratext_review_state" not in SYNCED_TABLES
    engine, _ = open_queue(tmp_path, monkeypatch, [{"thread": "A", "contents": qa_note("beta", "BETA")}])
    [item] = queue(engine)["items"]
    decide(engine, item["proposalId"], "deferred")
    decide(engine, item["proposalId"], "rejected", comment="no")
    entries = [e for e in engine.project.workbench.change_log_entries(engine.project.workbench_identity.project_id)
               if e["table_name"] == "paratext_review_decisions"]
    assert [e["op"] for e in entries] == ["decision:deferred", "decision:rejected"]
    assert json.loads(entries[0]["payload_json"])["decision"] == "deferred"
