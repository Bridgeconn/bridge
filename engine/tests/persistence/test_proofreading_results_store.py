"""`proofreading_results` (workbench v13, #505): a book's proofreading rows are
kept per chapter, replaced as a whole by the next run, and readable from a
sibling book without opening it."""
from __future__ import annotations

import sqlite3

from tc_ai_bridge.hub_sync import NOT_SYNCED_TABLES
from tc_ai_bridge.tc_project import TranslationCoreProject, _workbench_db_path, peek_proofreading_results
from tests.support.proofreading import RUTH, write_book


def _row(chapter: str, verse: str, original: str) -> dict[str, str]:
    return {"id": f"{chapter}-{verse}-{original}", "book": "RUT", "chapter": chapter, "verse": verse,
            "issueType": "Possible typo", "severity": "Low", "original": original}


def test_rows_are_kept_in_reading_order_and_a_new_run_replaces_them(tmp_path):
    project = TranslationCoreProject(write_book(tmp_path / "rut", "rut", RUTH))
    assert project.workbench.schema_version() == 13
    assert project.load_proofreading_results() == []
    project.save_proofreading_results({
        "2": [_row("2", "1", "later")], "intro": [_row("Intro", "", "first")],
        "1": [_row("1", "1", "a"), _row("1", "2", "b")],
    }, meta={"model": "test-model"})
    assert [r["original"] for r in project.load_proofreading_results()] == ["first", "a", "b", "later"]
    # A run that no longer finds chapter 1's rows writes that chapter empty.
    project.save_proofreading_results({"2": [_row("2", "2", "only")]})
    assert [r["original"] for r in project.load_proofreading_results()] == ["only"]
    # One row per chapter (and the introduction), not one per run.
    conn = sqlite3.connect(_workbench_db_path(project.path))
    try:
        stored = conn.execute("SELECT chapter, basis, revision FROM proofreading_results ORDER BY chapter").fetchall()
    finally:
        conn.close()
    assert [(chapter, basis) for chapter, basis, _ in stored] == [("1", "ai"), ("2", "ai"), ("intro", "ai")]
    assert all(revision == 2 for _, _, revision in stored)


def test_a_sibling_books_rows_are_read_without_opening_it(tmp_path):
    root = write_book(tmp_path / "rut", "rut", RUTH)
    assert peek_proofreading_results(root) == []  # no workbench yet: nothing is created
    assert not _workbench_db_path(root).exists()
    TranslationCoreProject(root).save_proofreading_results({"1": [_row("1", "1", "a")]})
    assert [r["original"] for r in peek_proofreading_results(root)] == ["a"]
    assert peek_proofreading_results(root, basis="other") == []


def test_the_rows_stay_on_this_device():
    assert "proofreading_results" in NOT_SYNCED_TABLES
