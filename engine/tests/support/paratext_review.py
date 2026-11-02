"""Builders for the Paratext QA review queue tests (#428-#434): QA notes in
the AI-QA shape, threads written into the synthetic Paratext folder, and the
queue / decide / verse-text calls over the protocol."""

from __future__ import annotations

from pathlib import Path

import bridge_service as bridge_service_module
from tests.support.paratext_fixture import write_notes_file
from tests.support.paratext_writeback import open_linked_review_project, reread_notes, stand_in
from tests.support.projects import call


def qa_note(original: str, suggested: str, *, category: str = "Sandhi / word-joining", reviewer: str = "No",
            pass_: str = "R2", reason: str = "Because.") -> list[str]:
    return [f"[AI-QA {pass_}] Check — {category}", f"Original: {original}", f"Suggested: {suggested}",
            f"Reason: {reason}", f"Confidence: 0.9 · Reviewer decision needed: {reviewer} · Severity: low"]


def threads(folder: Path, specs: list[dict], user: str = "QA Pass") -> None:
    comments = []
    for i, spec in enumerate(specs):
        comments.append({"thread": spec["thread"], "verse_ref": spec.get("verse_ref", "TIT 1:1"),
                         "date": spec.get("date", f"2026-10-2{i}T08:00:00.0000000+05:30"),
                         "status": spec.get("status", "todo"), "contents": spec["contents"],
                         "selected_text": spec.get("selected_text", "")})
    write_notes_file(folder, user, comments)


def open_queue(tmp_path, monkeypatch, specs, *, connector=None):
    connector = connector or stand_in()
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", connector)
    engine, folder = open_linked_review_project(tmp_path, monkeypatch)
    threads(folder, specs)
    reread_notes(engine)
    return engine, folder


def queue(engine, status="", scope=None):
    params = {"status": status}
    if scope is not None:
        params["scope"] = scope
    result = call(engine, "paratextReview.queue", params)
    assert result["success"] is True, result
    return result["result"]


def decide(engine, proposal_id, decision, **extra):
    return call(engine, "paratextReview.decide", {"proposalId": proposal_id, "decision": decision, **extra})


def verse_text(engine, chapter="1", verse="1"):
    return call(engine, "verse.get", {"chapter": chapter, "verse": verse})["result"]["text"]
