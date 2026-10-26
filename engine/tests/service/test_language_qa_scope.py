"""Scoped corrections through the real dispatcher: find what a chapter or
book scope covers, accept it as one ordinary journalled edit per verse with a
batch row, undo the batch, and ignore across a scope. Hindi: a reviewed
misspelling (सताईस -> सत्ताईस) in three verses across two chapters, and a
double space with no replacement."""
import pytest

from bridge_service import BridgeEngine
from tc_ai_bridge.language_qa_jobs import LanguageQaManager
from tc_ai_bridge.secret_store import AppSettings
from tests.support.indic_qa import wait, write_project
from tests.support.projects import call

CHAPTERS = {"1": {"1": "उसकी आयु सताईस वर्ष की थी।", "2": "वे सताईस  दिन रहे।", "3": "वे आए;; फिर गए।",
                  "4": "वे गए। "},  # a space at the verse edge: spacing.extra's fix is to remove it (#403)
            "2": {"1": "और सताईस लोग थे।"}}
OLD, NEW = "सताईस", "सत्ताईस"
RULE = "hi.lex.known-misspelling"


@pytest.fixture
def engine(tmp_path):
    project = write_project(tmp_path / "gen", "gen", CHAPTERS, lang_id="hin", lang_name="Hindi")
    bridge = BridgeEngine(settings=AppSettings(path=tmp_path / "settings" / "settings.json"))
    bridge._language_qa = LanguageQaManager(debounce=0, yield_seconds=0)
    bridge._configure_language_qa()
    assert call(bridge, "project.open", {"path": str(project)})["success"]
    wait(bridge._language_qa)
    yield bridge, project
    bridge._language_qa.unbind()


def rpc(bridge, method, **params):
    response = call(bridge, method, params)
    assert response["success"], response
    return response["result"]


def finding(bridge, project, chapter, verse, rule=RULE):
    wait(bridge._language_qa)
    found = rpc(bridge, "languageQa.verse", projectPath=str(project), chapter=chapter, verse=verse)["findings"]
    return next(f for f in found if f["rule"] == rule)


def text(bridge, chapter, verse):
    return rpc(bridge, "verse.get", chapter=chapter, verse=verse)["text"]


def scoped(bridge, project, method, origin, scope, **extra):
    return rpc(bridge, method, projectPath=str(project), chapter=origin["chapter"], verse=origin["verse"],
               findingId=origin["id"], scope=scope, **extra)


def test_find_lists_the_same_finding_within_the_scope_only(engine):
    bridge, project = engine
    origin = finding(bridge, project, "1", "1")
    assert scoped(bridge, project, "languageQa.scopeFind", origin, "verse", suggestion=NEW)["count"] == 1
    chapter = scoped(bridge, project, "languageQa.scopeFind", origin, "chapter", suggestion=NEW)
    assert (chapter["count"], chapter["verses"]) == (2, 2)
    book = scoped(bridge, project, "languageQa.scopeFind", origin, "book", suggestion=NEW)
    assert [(o["chapter"], o["verse"], o["old"], o["new"]) for o in book["occurrences"]] == [
        ("1", "1", OLD, NEW), ("1", "2", OLD, NEW), ("2", "1", OLD, NEW)]
    assert book["key"]["kind"] == "word" and book["key"]["originalText"] == OLD


def test_accept_writes_one_journalled_edit_per_verse_decides_each_and_records_a_batch(engine):
    bridge, project = engine
    origin = finding(bridge, project, "1", "1")
    result = scoped(bridge, project, "languageQa.scopeApply", origin, "book", action="accept", suggestion=NEW)
    assert result["count"] == 3 and result["skipped"] == [] and result["batchId"]
    assert [(c["chapter"], c["verse"]) for c in result["changed"]] == [("1", "1"), ("1", "2"), ("2", "1")]
    for chapter, verse in (("1", "1"), ("1", "2"), ("2", "1")):
        assert text(bridge, chapter, verse) == CHAPTERS[chapter][verse].replace(OLD, NEW)
        history = bridge.project.verse_edit_history(chapter, verse)
        assert len(history) == 1 and history[0]["contextId"]["batchId"] == result["batchId"]
    assert result["changed"][1]["newText"].count("  ") == 1, "the double space was not touched"
    [batch] = rpc(bridge, "languageQa.batches", projectPath=str(project))["batches"]
    assert (batch["batchId"], batch["state"], batch["count"], len(batch["items"])) == (result["batchId"], "applied", 3, 3)
    assert result["learned"]["old"] == OLD and result["learned"]["n"] == 3
    wait(bridge._language_qa)
    remaining = rpc(bridge, "languageQa.status", projectPath=str(project), limit=100)["findings"]
    assert not [f for f in remaining if f["rule"] == RULE]


def test_accept_skips_a_verse_whose_text_changed_after_the_check(engine):
    bridge, project = engine
    origin = finding(bridge, project, "1", "1")
    # Change verse 2:1 on disk behind the pass's back (as another editor would).
    bridge.project.apply_scripture_edit("2", "1", "और सताईस लोग वहाँ थे।", username="other")
    result = scoped(bridge, project, "languageQa.scopeApply", origin, "book", action="accept", suggestion=NEW)
    assert [(s["chapter"], s["verse"]) for s in result["skipped"]] == [("2", "1")]
    assert text(bridge, "2", "1") == "और सताईस लोग वहाँ थे।"
    assert result["count"] == 2


def test_undo_restores_every_verse_and_keeps_both_batches(engine):
    bridge, project = engine
    origin = finding(bridge, project, "1", "1")
    applied = scoped(bridge, project, "languageQa.scopeApply", origin, "chapter", action="accept", suggestion=NEW)
    undone = rpc(bridge, "languageQa.batchUndo", projectPath=str(project), batchId=applied["batchId"])
    assert sorted((r["chapter"], r["verse"]) for r in undone["reverted"]) == [("1", "1"), ("1", "2")]
    assert undone["conflicts"] == []
    assert text(bridge, "1", "1") == CHAPTERS["1"]["1"] and text(bridge, "1", "2") == CHAPTERS["1"]["2"]
    batches = {b["batchId"]: b for b in rpc(bridge, "languageQa.batches", projectPath=str(project))["batches"]}
    assert batches[applied["batchId"]]["state"] == "undone"
    assert batches[undone["undoBatchId"]]["kind"] == "undo"
    again = call(bridge, "languageQa.batchUndo", {"projectPath": str(project), "batchId": applied["batchId"]})
    assert not again["success"], "a batch is undone once"
    wait(bridge._language_qa)
    assert finding(bridge, project, "1", "1")["originalText"] == OLD, "the finding is back with its text"


def test_undo_leaves_a_verse_that_was_edited_after_the_batch(engine):
    bridge, project = engine
    origin = finding(bridge, project, "1", "1")
    applied = scoped(bridge, project, "languageQa.scopeApply", origin, "chapter", action="accept", suggestion=NEW)
    rpc(bridge, "verse.edit", chapter="1", verse="2", newText="वे सत्ताईस दिन वहाँ रहे।")
    undone = rpc(bridge, "languageQa.batchUndo", projectPath=str(project), batchId=applied["batchId"])
    assert [(c["chapter"], c["verse"]) for c in undone["conflicts"]] == [("1", "2")]
    assert text(bridge, "1", "2") == "वे सत्ताईस दिन वहाँ रहे।"
    assert text(bridge, "1", "1") == CHAPTERS["1"]["1"]


def test_ignore_a_chapter_decides_each_and_a_book_also_records_house_style(engine):
    bridge, project = engine
    origin = finding(bridge, project, "1", "1")
    chapter = scoped(bridge, project, "languageQa.scopeApply", origin, "chapter", action="ignore")
    assert chapter["count"] == 2 and "houseStyle" not in chapter
    wait(bridge._language_qa)
    other = finding(bridge, project, "2", "1")
    book = scoped(bridge, project, "languageQa.scopeApply", other, "book", action="ignore")
    assert book["houseStyle"]["scope"] == "word-in-book" and book["houseStyle"]["word"] == OLD
    wait(bridge._language_qa)
    shown = rpc(bridge, "languageQa.status", projectPath=str(project), limit=100)["findings"]
    assert not [f for f in shown if f["rule"] == RULE]
    assert text(bridge, "1", "1") == CHAPTERS["1"]["1"], "ignoring never writes"


def test_a_finding_without_a_replacement_cannot_be_accepted_but_can_be_ignored(engine):
    bridge, project = engine
    # punctuation.repeated offers no fix (spacing.extra does since revision 2)
    repeated = finding(bridge, project, "1", "3", rule="punctuation.repeated")
    refused = call(bridge, "languageQa.scopeApply", {"projectPath": str(project), "chapter": "1", "verse": "3",
                                                      "findingId": repeated["id"], "scope": "book", "action": "accept"})
    assert not refused["success"]
    assert scoped(bridge, project, "languageQa.scopeApply", repeated, "book", action="ignore")["count"] == 1


def test_a_spacing_fix_that_removes_an_edge_space_is_accepted_across_the_book(engine):
    """Robin's refusal (#403): the fix for a space at the verse edge is an
    empty replacement, which the scoped path rejected as "non-empty string"."""
    bridge, project = engine
    edge = finding(bridge, project, "1", "4", rule="spacing.extra")
    assert edge["suggestions"][0]["text"] == "", "the rule offers removal for an edge space"
    found = scoped(bridge, project, "languageQa.scopeFind", edge, "book", suggestion="")
    assert [(o["chapter"], o["verse"], o["old"], o["new"]) for o in found["occurrences"]] == [
        ("1", "2", "  ", " "), ("1", "4", " ", "")], "each spacing place keeps its own fix"
    result = scoped(bridge, project, "languageQa.scopeApply", edge, "book", action="accept", suggestion="")
    assert result["count"] == 2 and result["skipped"] == [] and "learned" not in result
    assert text(bridge, "1", "4") == "वे गए।" and text(bridge, "1", "2") == "वे सताईस दिन रहे।"
    undone = rpc(bridge, "languageQa.batchUndo", projectPath=str(project), batchId=result["batchId"])
    assert sorted((r["chapter"], r["verse"]) for r in undone["reverted"]) == [("1", "2"), ("1", "4")]
    assert undone["conflicts"] == []
    assert text(bridge, "1", "2") == CHAPTERS["1"]["2"], "the double space is back"
    # The writer trims every ordinary edit, so the edge space cannot return:
    # the verse counts as restored, with a note, instead of failing the undo.
    [edge_undo] = [r for r in undone["reverted"] if r["verse"] == "4"]
    assert text(bridge, "1", "4") == "वे गए।" and "edge space" in edge_undo["note"]
    assert len(bridge.project.verse_edit_history("1", "4")) == 1, "nothing was written for the no-op restore"


def test_parameters_are_checked_and_a_stale_finding_is_refused(engine):
    bridge, project = engine
    origin = finding(bridge, project, "1", "1")
    for bad in ({"scope": "testament"}, {"action": "delete"}, {"findingId": "nope"}, {"suggestion": 5}):
        params = {"projectPath": str(project), "chapter": "1", "verse": "1", "findingId": origin["id"],
                  "scope": "book", "action": "accept", **bad}
        assert not call(bridge, "languageQa.scopeApply", params)["success"], bad
