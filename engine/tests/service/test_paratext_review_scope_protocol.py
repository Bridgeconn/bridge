"""#432 over the protocol: the queue scans several books of a collection
from the Paratext notes index (a lazy sibling is never materialized), orders
them from a chosen starting book and says where it wraps around, keeps its
state per linked project across a book switch and a reopen, shows a
sibling's decisions read-only, refuses to act on a proposal of a book that
is not open, and drops a stale draft rather than reuse it."""

from __future__ import annotations

import json

from tc_ai_bridge.secret_store import AppSettings
from tests.support.paratext_review import decide, open_queue, qa_note, queue, threads
from tests.support.paratext_writeback import add_lazy_sibling, reread_notes
from tests.support.projects import _write_minimal_book, call


def phm_notes(folder):
    threads(folder, [
        {"thread": "P", "verse_ref": "PHM 1:1", "contents": qa_note("PHM", "Philemon"),
         "date": "2026-10-25T08:00:00.0000000+05:30"},
    ], user="QA Pass 2")


def test_the_scope_spans_the_collection_without_materializing_a_lazy_sibling(tmp_path, monkeypatch):
    engine, folder = open_queue(tmp_path, monkeypatch, [{"thread": "A", "contents": qa_note("beta", "BETA")}])
    phm_notes(folder)
    sibling = add_lazy_sibling(engine.project.path)
    reread_notes(engine)

    single = queue(engine)
    assert [i["book"] for i in single["items"]] == ["TIT"]
    assert [b["book"] for b in single["books"]] == ["TIT", "PHM"] and single["books"][1]["lazy"] is True

    both = queue(engine, scope={"books": ["PHM", "TIT"], "startBook": "TIT"})
    assert [i["book"] for i in both["items"]] == ["TIT", "PHM"]
    assert both["state"]["scope"] == {"books": ["TIT", "PHM"], "startBook": "TIT"}
    assert both["wraparound"] == {"occurs": False, "books": [], "count": 0}
    assert [s["book"] for s in both["scanned"]] == ["TIT", "PHM"] and both["scanned"][1]["proposals"] == 1
    assert both["items"][1]["openBook"] is False and both["items"][1]["decision"] is None
    # The lazy sibling is still the placeholder it was.
    assert sorted(p.name for p in sibling.iterdir()) == [".bridge"]

    from_phm = queue(engine, scope={"books": ["TIT", "PHM"], "startBook": "PHM"})
    assert [i["book"] for i in from_phm["items"]] == ["PHM", "TIT"]
    assert from_phm["items"][1]["wrapped"] is True
    assert from_phm["wraparound"] == {"occurs": True, "books": ["TIT"], "count": 1}

    refused = decide(engine, from_phm["items"][0]["proposalId"], "applied")
    assert refused["success"] is False and refused["error"]["message"].startswith("OPEN_BOOK:PHM")
    preview = call(engine, "paratextReview.preview", {"proposalId": from_phm["items"][0]["proposalId"]})
    assert preview["success"] is False


def test_state_follows_the_linked_project_across_a_book_switch_and_a_restart(tmp_path, monkeypatch):
    engine, folder = open_queue(tmp_path, monkeypatch, [{"thread": "A", "contents": qa_note("beta", "BETA")}])
    phm_notes(folder)
    # A real sibling this time, so it can be opened.
    phm = engine.project.path.parent / "phm"
    _write_minimal_book(phm, "phm", "synthetic PHM 1:1.")
    add_lazy_sibling(engine.project.path)
    (phm / ".bridge" / "lazy-import.json").unlink()
    reread_notes(engine)
    first = queue(engine, scope={"books": ["TIT", "PHM"], "startBook": "PHM"})
    tit_item = next(i for i in first["items"] if i["book"] == "TIT")
    phm_item = next(i for i in first["items"] if i["book"] == "PHM")
    call(engine, "paratextReview.saveState", {"state": {
        "position": phm_item["proposalId"], "drafts": {phm_item["proposalId"]: {"replacement": "Philémon", "comment": "d"}}}})
    decide(engine, tit_item["proposalId"], "rejected", comment="Keep.")

    opened = call(engine, "project.open", {"path": str(phm)})
    assert opened["success"] is True, opened
    assert engine._paratext_session().wait_for_notes_index(30) == "ready"
    switched = queue(engine)
    assert switched["book"] == "PHM" and switched["state"]["position"] == phm_item["proposalId"]
    assert switched["state"]["scope"] == {"books": ["TIT", "PHM"], "startBook": "PHM"}
    assert [i["book"] for i in switched["items"]] == ["PHM", "TIT"]
    # TIT's decision is read from its own workbench, read-only; PHM's draft is here.
    tit_now = next(i for i in switched["items"] if i["book"] == "TIT")
    assert tit_now["decision"]["decision"] == "rejected" and tit_now["openBook"] is False
    phm_now = next(i for i in switched["items"] if i["book"] == "PHM")
    assert phm_now["draft"] == {"replacement": "Philémon", "comment": "d"} and phm_now["openBook"] is True
    applied = decide(engine, phm_now["proposalId"], "applied", replacement="Philemon")["result"]["decision"]
    assert applied["verified"] is True
    assert call(engine, "verse.get", {"chapter": "1", "verse": "1"})["result"]["text"] == "synthetic Philemon 1:1."

    # A restart: a fresh engine on the same settings file keeps the queue state.
    settings_path = engine.settings.path
    from bridge_service import BridgeEngine
    fresh = BridgeEngine(settings=AppSettings(path=settings_path))
    assert call(fresh, "project.open", {"path": str(engine.project.path)})["success"]
    assert fresh._paratext_session().wait_for_notes_index(30) == "ready"
    again = queue(fresh)
    assert again["state"]["scope"] == {"books": ["TIT", "PHM"], "startBook": "PHM"}
    assert again["state"]["position"] == phm_item["proposalId"]


def test_a_stale_draft_is_dropped_when_its_proposal_changed(tmp_path, monkeypatch):
    engine, folder = open_queue(tmp_path, monkeypatch, [{"thread": "A", "contents": qa_note("beta", "BETA")}])
    [item] = queue(engine)["items"]
    call(engine, "paratextReview.saveState", {"state": {"drafts": {item["proposalId"]: {"replacement": "Beta", "comment": "x"}}}})
    assert queue(engine)["items"][0]["draft"] == {"replacement": "Beta", "comment": "x"}
    # The QA pass edited its comment: the proposal's identity (a content hash) changed.
    threads(folder, [{"thread": "A", "contents": qa_note("beta", "BETA!")}])
    reread_notes(engine)
    listed = queue(engine)
    assert listed["staleDraftsDropped"] == [item["proposalId"]]
    assert listed["items"][0]["proposalId"] != item["proposalId"] and listed["items"][0]["draft"] is None
    assert listed["state"]["drafts"] == {}
    # The row for the old proposal, had there been a decision, would stay in history untouched.
    assert json.loads(json.dumps(listed["state"]))["scope"]["books"] == []
