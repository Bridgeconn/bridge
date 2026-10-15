"""Collection QA after a restart (#274): the whole-collection stage a run
recorded comes back from collection.qaStatus in a new engine, whichever book of
the collection is opened, and a book whose termbase changed since its recorded
run is checked again."""
from __future__ import annotations

import json
import time

from bridge_service import BridgeEngine
from tc_ai_bridge.language_qa_jobs import LanguageQaManager
from tc_ai_bridge.tc_project import TranslationCoreProject
from tests.support.projects import _write_minimal_book, call, link_collection
from tests.support.waits import job_timeout


def _collection(tmp_path):
    books = {name: tmp_path / name for name in ("rut", "gen")}
    _write_minimal_book(books["rut"], "rut", "அந்த காகம் பறந்தது.")
    _write_minimal_book(books["gen"], "gen", "இந்த பெண் வந்தாள்.")
    link_collection(books)
    return books


def _engine(path):
    engine = BridgeEngine()
    engine._language_qa = LanguageQaManager(debounce=0, yield_seconds=0)
    assert call(engine, "project.open", {"path": str(path)})["success"]
    return engine


def _run(engine):
    started = call(engine, "collection.runChecks", {"checks": ["languageQa"]})
    assert started["success"], started
    deadline = time.monotonic() + job_timeout(60)
    while time.monotonic() < deadline:
        snapshot = call(engine, "collection.qaStatus", {"jobId": started["result"]["jobId"]})["result"]
        if snapshot["state"] in {"succeeded", "failed", "cancelled"}:
            return snapshot
        time.sleep(0.05)
    raise AssertionError("collection run did not finish")


def test_the_final_stage_comes_back_after_a_restart_from_any_book(tmp_path):
    books = _collection(tmp_path)
    engine = _engine(books["rut"])
    try:
        live = _run(engine)["finalStage"]
    finally:
        engine._language_qa.unbind()
    assert live["completedAt"] and [c["bookId"] for c in live["termbaseCoverage"]] == ["rut", "gen"]
    for opened in ("rut", "gen"):  # a new engine, and the other book too
        engine = _engine(books[opened])
        try:
            idle = call(engine, "collection.qaStatus", {})["result"]
        finally:
            engine._language_qa.unbind()
        assert idle["state"] == "idle"
        assert [b["state"] for b in idle["books"]] == ["done", "done"]
        stage = idle["finalStage"]
        assert stage["completedAt"] == live["completedAt"]
        assert stage["termbaseCoverage"] == live["termbaseCoverage"]
        assert stage["houseStylePropagation"] == live["houseStylePropagation"]
        assert stage["crossBookNames"] == live["crossBookNames"]


def test_a_termbase_change_reruns_a_book_whose_text_is_unchanged(tmp_path):
    books = _collection(tmp_path)
    engine = _engine(books["rut"])
    try:
        assert [b["state"] for b in _run(engine)["books"]] == ["done", "done"]
        assert [b["state"] for b in _run(engine)["books"]] == ["skipped", "skipped"]
        TranslationCoreProject(books["gen"]).record_terminology_rule("woman", approved_renderings=["பெண்"])
        assert [b["state"] for b in _run(engine)["books"]] == ["skipped", "done"]
    finally:
        engine._language_qa.unbind()
