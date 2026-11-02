"""#429 / #430 over the protocol: a QA proposal is applied in its own region
and never mapped into another -- a footnote or cross-reference inside the
verse's raw string (through the verse writer), a heading in the chapter's
headings file (through the project's heading writer), a book introduction in
Paratext only, an allowlisted heading-marker rename in Paratext (and the
Bridge heading's tag kept in step) -- each with the connector stand-in
recording the region-scoped write."""

from __future__ import annotations

import json

import bridge_service as bridge_service_module
from tests.support.paratext_writeback import open_linked_review_project, reread_notes, stand_in
from tests.support.paratext_review import decide, qa_note, queue, threads, verse_text
from tests.support.projects import call


def open_regions(tmp_path, monkeypatch, specs, *, with_footnote=True, with_heading=True, connector=None):
    connector = connector or stand_in(scripture={
        "TIT 1": "\\c 1\n\\s1 Greeting to Titus\n\\p\n\\v 1 alpha beta\\f + \\fr 1:1 \\ft a beta note\\f* gamma\\x - \\xo 1:1 \\xt Gen 1:1\\x*\n",
        "TIT 0": "\\id TIT\n\\ip The intro says beta here.\n",
    })
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", connector)
    engine, folder = open_linked_review_project(tmp_path, monkeypatch)
    if with_footnote:
        assert call(engine, "verse.edit", {"chapter": "1", "verse": "1",
                                           "newText": "alpha beta\\f + \\fr 1:1 \\ft a beta note\\f* gamma\\x - \\xo 1:1 \\xt Gen 1:1\\x*"})["success"]
    if with_heading:
        (engine.project.book_dir / "1.headings.json").write_text(
            json.dumps({"1": [{"tag": "s1", "text": "Greeting to Titus"}]}), encoding="utf-8")
        engine.project._forget_chapter_files()
    threads(folder, specs)
    reread_notes(engine)
    return engine, folder, connector


def test_a_footnote_proposal_is_applied_inside_the_note_never_in_the_body(tmp_path, monkeypatch):
    engine, _, connector = open_regions(tmp_path, monkeypatch, [
        {"thread": "F", "contents": qa_note("beta", "BETA", category="Footnote / cross-reference") + ["Location: footnote"]},
    ])
    [item] = queue(engine)["items"]
    assert item["proposal"]["region"] == "footnote"
    preview = call(engine, "paratextReview.preview", {"proposalId": item["proposalId"]})["result"]
    assert preview["ok"] and preview["region"] == "footnote" and preview["plain"].startswith("\\f +")
    assert preview["after"] == "\\f + \\fr 1:1 \\ft a BETA note\\f*"
    result = decide(engine, item["proposalId"], "applied", writeParatext=True)
    assert result["success"] is True, result
    decision = result["result"]["decision"]
    assert decision["verified"] is True and decision["region"] == "footnote"
    # The body's "beta" is untouched; only the note changed.
    assert verse_text(engine) == "alpha beta\\f + \\fr 1:1 \\ft a BETA note\\f* gamma\\x - \\xo 1:1 \\xt Gen 1:1\\x*"
    assert decision["paratext"]["status"] == "sent" and decision["paratext"]["verified"] is True
    sent = [c for a, c in connector.calls if a == "put_verse_text"]
    assert sent[-1]["region"] == "footnote" and sent[-1]["original"] == "beta"
    assert "\\ft a BETA note" in connector.scripture["TIT 1"] and "\\v 1 alpha beta" in connector.scripture["TIT 1"]


def test_a_cross_reference_proposal_needs_a_cross_reference_and_the_body_is_never_a_fallback(tmp_path, monkeypatch):
    engine, _, _ = open_regions(tmp_path, monkeypatch, [
        {"thread": "X", "contents": qa_note("Gen 1:1", "Gen 1:2", category="Footnote / cross-reference") + ["Location: cross-reference"]},
        {"thread": "B", "contents": qa_note("gamma", "GAMMA", category="Footnote / cross-reference") + ["Location: footnote"]},
    ])
    items = {i["threadId"]: i for i in queue(engine)["items"]}
    assert items["X"]["proposal"]["region"] == "crossReference"
    ok = decide(engine, items["X"]["proposalId"], "applied")
    assert ok["success"] is True, ok
    assert "\\xt Gen 1:2\\x*" in verse_text(engine)
    # "gamma" is in the body, not in the footnote: refused, nothing written.
    refused = decide(engine, items["B"]["proposalId"], "applied")
    assert refused["success"] is False and "footnote" in refused["error"]["message"]
    assert "gamma\\x" in verse_text(engine)


def test_a_heading_proposal_goes_through_the_heading_writer_and_is_reverted_the_same_way(tmp_path, monkeypatch):
    engine, _, connector = open_regions(tmp_path, monkeypatch, [
        {"thread": "H", "contents": qa_note("Greeting", "Salutation", category="Grammar") + ["Location: heading"]},
    ])
    [item] = queue(engine)["items"]
    assert item["proposal"]["region"] == "heading"
    preview = call(engine, "paratextReview.preview", {"proposalId": item["proposalId"]})["result"]
    assert preview["ok"] and preview["plain"] == "Greeting to Titus" and preview["after"] == "Salutation to Titus"
    result = decide(engine, item["proposalId"], "applied", writeParatext=True)
    assert result["success"] is True, result
    decision = result["result"]["decision"]
    assert decision["verified"] is True and decision["region"] == "heading" and decision["journalTransactionId"]
    headings = json.loads((engine.project.book_dir / "1.headings.json").read_text(encoding="utf-8"))
    assert headings == {"1": [{"tag": "s1", "text": "Salutation to Titus"}]}
    assert verse_text(engine).startswith("alpha beta")          # the verse map was not touched
    sent = [c for a, c in connector.calls if a == "put_verse_text"][-1]
    assert sent["region"] == "heading" and "\\s1 Salutation to Titus" in connector.scripture["TIT 1"]
    # The journal recorded the heading edit as its own transaction kind.
    journal = sorted((engine.project.companion_dir() / "transactions").glob("*.json"))
    assert any(json.loads(j.read_text(encoding="utf-8")).get("label") == "headingEdit" for j in journal)

    reverted = call(engine, "paratextReview.revertLatest")["result"]["decision"]
    assert reverted["decision"] == "reverted" and reverted["revertVerified"] is True
    assert json.loads((engine.project.book_dir / "1.headings.json").read_text(encoding="utf-8"))["1"][0]["text"] == "Greeting to Titus"
    assert reverted["paratextReverse"]["status"] == "sent" and "\\s1 Greeting to Titus" in connector.scripture["TIT 1"]


def test_an_introduction_proposal_is_written_in_paratext_only_and_verified_by_its_read_back(tmp_path, monkeypatch):
    engine, _, connector = open_regions(tmp_path, monkeypatch, [
        {"thread": "I", "contents": qa_note("says beta", "says BETA", category="Grammar") + ["Location: book introduction"]},
    ])
    [item] = queue(engine)["items"]
    assert item["proposal"]["region"] == "introduction"
    preview = call(engine, "paratextReview.preview", {"proposalId": item["proposalId"]})["result"]
    assert preview["ok"] is False and preview["paratextOnly"] is True
    without = decide(engine, item["proposalId"], "applied")
    assert without["success"] is False and "Also write to Paratext" in without["error"]["message"]
    result = decide(engine, item["proposalId"], "applied", writeParatext=True)
    assert result["success"] is True, result
    decision = result["result"]["decision"]
    assert decision["bridgeCopy"] == "none" and decision["verified"] is True
    assert decision["paratext"]["status"] == "sent" and decision["paratext"]["verified"] is True
    assert connector.scripture["TIT 0"] == "\\id TIT\n\\ip The intro says BETA here.\n"
    assert verse_text(engine).startswith("alpha beta")


def test_an_allowlisted_marker_rename_is_written_in_paratext_and_the_bridge_tag_follows(tmp_path, monkeypatch):
    engine, _, connector = open_regions(tmp_path, monkeypatch, [
        {"thread": "M", "contents": qa_note("\\s1 Greeting to Titus", "\\s2 Greeting to Titus", category="USFM marker")},
        {"thread": "N", "contents": qa_note("\\s1 Greeting to Titus", "\\q1 Greeting to Titus", category="USFM marker")},
    ])
    items = {i["threadId"]: i for i in queue(engine)["items"]}
    assert items["M"]["proposal"]["operation"] == "markerRename"
    preview = call(engine, "paratextReview.preview", {"proposalId": items["M"]["proposalId"]})["result"]
    assert preview["ok"] and preview["paratextOnly"] and preview["after"] == "\\s2 Greeting to Titus"
    assert preview["bridgeHeadingIndex"] == 0
    outside = decide(engine, items["N"]["proposalId"], "applied", writeParatext=True)
    assert outside["success"] is False and "review-only" in outside["error"]["message"]
    result = decide(engine, items["M"]["proposalId"], "applied", writeParatext=True)
    assert result["success"] is True, result
    decision = result["result"]["decision"]
    assert decision["verified"] is True and decision["bridgeCopy"] == "heading"
    assert [c for a, c in connector.calls if a == "rename_marker"][-1]["to_marker"] == "s2"
    assert "\\s2 Greeting to Titus" in connector.scripture["TIT 1"]
    headings = json.loads((engine.project.book_dir / "1.headings.json").read_text(encoding="utf-8"))
    assert headings["1"][0] == {"tag": "s2", "text": "Greeting to Titus"}


def test_a_region_write_needs_the_region_aware_connector(tmp_path, monkeypatch):
    from tests.support.paratext_writeback import CAPABILITIES_090
    connector = stand_in(capabilities=CAPABILITIES_090, version="0.9.0", scripture={
        "TIT 1": "\\c 1\n\\p\n\\v 1 alpha beta\\f + \\fr 1:1 \\ft a beta note\\f* gamma\n"})
    engine, _, connector = open_regions(tmp_path, monkeypatch, [
        {"thread": "F", "contents": qa_note("beta", "BETA", category="Footnote / cross-reference") + ["Location: footnote"]},
    ], with_heading=False, connector=connector)
    [item] = queue(engine)["items"]
    decision = decide(engine, item["proposalId"], "applied", writeParatext=True)["result"]["decision"]
    # Bridge's copy is applied and verified; the Paratext write waits for a newer connector.
    assert decision["verified"] is True
    assert decision["paratext"]["status"] == "queued" and "0.10.0" in decision["paratext"]["lastError"]
    assert "\\ft a beta note" in connector.scripture["TIT 1"]
