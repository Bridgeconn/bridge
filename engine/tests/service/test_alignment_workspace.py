"""Workspace resets and arbitrary existing-word separation (#381, #449)."""
import pytest

from bridge_service import BridgeEngine
from tc_ai_bridge import alignment_reset
from tests.support.alignment_books import context_id, unaligned_verse, write_alignment_book
from tests.support.projects import call


@pytest.fixture
def engine(tmp_path):
    root = tmp_path / "php"
    write_alignment_book(root, "php", {"1": {
        "3": unaligned_verse("ஒன்று இரண்டு மூன்று", [("Α", "G1"), ("Β", "G2"), ("Γ", "G3")]),
        "6": unaligned_verse("நான்கு ஐந்து", [("Δ", "G4")]),
    }})
    engine = BridgeEngine()
    assert call(engine, "project.open", {"path": str(root)})["success"]
    return engine


def get(engine, v="3"):
    return call(engine, "alignment.get", {"chapter": "1", "verse": v})["result"]


def ok(engine, method, **params):
    if method == "alignment.resetVerse" and "expectedStateToken" not in params:
        params["expectedStateToken"] = alignment_reset.summary(engine.project, "1", params.get("verse", "3"))["token"]
    response = call(engine, method, {"chapter": "1", "verse": "3", **params})
    assert response["success"], response
    return response["result"]


def link(engine):
    return ok(engine, "alignment.crossVerse.link", sources=[
        {"chapter": "1", "verse": "3", "topId": context_id(get(engine), top_word=w)} for w in ["Β", "Γ"]],
        targets=[{"chapter": "1", "verse": "6", "bottomId": context_id(get(engine, "6"), bottom_word="நான்கு")}])


def test_reset_clears_native_links_and_nulls_and_undo_restores_them(engine):
    c = get(engine)
    ok(engine, "alignment.realign", topIds=[context_id(c, top_word="Α")],
       bottomIds=[context_id(c, bottom_word="ஒன்று")], expectedOriginal=c["alignment"])
    link(engine)
    c = get(engine)
    ok(engine, "alignment.null.set", side="target", id=context_id(c, bottom_word="இரண்டு"), reason="GRAMMATICAL")
    before = get(engine)
    result = ok(engine, "alignment.resetVerse", expectedOriginal=before["alignment"])
    assert {c["verse"] for c in result["contexts"]} == {"3", "6"}
    c = get(engine)
    assert not any(g["bottomIds"] for g in c["groups"])
    assert not c["crossVerseLinks"] and not c["nullDecisions"]["target"]
    assert ok(engine, "alignment.resetStatus")["canUndo"]
    ok(engine, "alignment.restoreReset")
    restored = get(engine)
    assert restored["alignment"] == before["alignment"]
    assert len(restored["crossVerseLinks"]) == len(before["crossVerseLinks"])
    assert restored["nullDecisions"]["target"][0]["reason"] == "GRAMMATICAL"


def test_reset_undo_resumes_a_partially_restored_cross_verse_group(engine, monkeypatch):
    link(engine)
    before = get(engine)
    ok(engine, "alignment.resetVerse", expectedOriginal=before["alignment"])
    store = engine.project.cross_verse_links
    write_row = store._write_row
    writes = 0
    def interrupted(*args, **kwargs):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise RuntimeError("process stopped between pair writes")
        return write_row(*args, **kwargs)
    monkeypatch.setattr(store, "_write_row", interrupted)
    response = call(engine, "alignment.restoreReset", {"chapter": "1", "verse": "3"})
    assert not response["success"]
    assert len(get(engine)["crossVerseLinks"]) == 1
    monkeypatch.setattr(store, "_write_row", write_row)
    ok(engine, "alignment.restoreReset")
    assert len(get(engine)["crossVerseLinks"]) == len(before["crossVerseLinks"]) == 2
    assert alignment_reset.record(engine.project)["state"] == "restored"


def test_reset_is_resumable_after_failure_without_overwriting_a_newer_save(engine, monkeypatch):
    c = get(engine)
    ok(engine, "alignment.realign", topIds=[c["topTokens"][0]["id"]], bottomIds=[c["bottomTokens"][0]["id"]], expectedOriginal=c["alignment"])
    link(engine)
    before = get(engine)
    original = engine._save_alignment
    monkeypatch.setattr(engine, "_save_alignment", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("interrupted")))
    response = call(engine, "alignment.resetVerse", {"chapter": "1", "verse": "3", "expectedOriginal": before["alignment"], "expectedStateToken": alignment_reset.summary(engine.project, "1", "3")["token"]})
    assert not response["success"]
    assert alignment_reset.record(engine.project)["state"] == "resetting"
    denied = call(engine, "alignment.null.set", {"chapter": "1", "verse": "3", "side": "source", "id": "H001", "reason": "IMPLICIT"})
    assert not denied["success"] and "Resume reset" in denied["error"]["message"]
    preview = ok(engine, "alignment.resetChapter.preview")
    denied_chapter = call(engine, "alignment.resetChapter.start", {"chapter": "1", "token": preview["token"]})
    assert not denied_chapter["success"] and "Resume the verse reset" in denied_chapter["error"]["message"]
    monkeypatch.setattr(engine, "_save_alignment", original)
    ok(engine, "alignment.resetVerse", expectedOriginal=before["alignment"])
    assert alignment_reset.record(engine.project)["state"] == "reset"


def test_stale_reset_is_refused_and_undo_refuses_new_partner_work(engine):
    link(engine)
    before = get(engine)
    stale = call(engine, "alignment.resetVerse", {"chapter": "1", "verse": "3", "expectedOriginal": {}, "expectedStateToken": alignment_reset.summary(engine.project, "1", "3")["token"]})
    assert not stale["success"] and get(engine)["crossVerseLinks"]
    ok(engine, "alignment.resetVerse", expectedOriginal=before["alignment"])
    c = get(engine, "6")
    ok(engine, "alignment.realign", verse="6", topIds=[c["topTokens"][0]["id"]], bottomIds=[c["bottomTokens"][0]["id"]], expectedOriginal=c["alignment"])
    response = call(engine, "alignment.restoreReset", {"chapter": "1", "verse": "3"})
    assert not response["success"] and "overwrite newer work" in response["error"]["message"]


@pytest.mark.parametrize("word,direction", [("Α", "left"), ("Β", "right"), ("Γ", "left")])
def test_any_existing_source_word_can_be_separated_without_losing_tokens(engine, word, direction):
    c = get(engine)
    ok(engine, "alignment.realign", topIds=[t["id"] for t in c["topTokens"]], bottomIds=[c["bottomTokens"][0]["id"]], expectedOriginal=c["alignment"])
    c = get(engine)
    ok(engine, "alignment.splitSource", topId=context_id(c, top_word=word), direction=direction, expectedOriginal=c["alignment"])
    updated = get(engine)
    chosen = next(t for t in updated["topTokens"] if t["word"] == word)
    assert any(g["topIds"] == [chosen["id"]] and not g["bottomIds"] for g in updated["groups"])
    assert sorted(t["word"] for t in updated["topTokens"]) == ["Α", "Β", "Γ"]
    assert updated["sourceLayout"]["placements"]


def test_cross_verse_separation_keeps_targets_with_remaining_source(engine):
    link(engine)
    c = get(engine)
    ok(engine, "alignment.splitSource", topId=context_id(c, top_word="Β"), direction="left", expectedOriginal=c["alignment"])
    result = get(engine)
    assert [l["source"]["word"] for l in result["crossVerseLinks"]] == ["Γ"]
    assert get(engine, "6")["crossVerseAccounted"] == 1
    ok(engine, "alignment.splitSource", topId=context_id(result, top_word="Β"), direction="left", expectedOriginal=result["alignment"], undo=True)
    assert {l["source"]["word"] for l in get(engine)["crossVerseLinks"]} == {"Β", "Γ"}


def test_pending_cross_verse_separation_resumes_after_process_interruption(engine, monkeypatch):
    link(engine)
    c = get(engine)
    store = engine.project.cross_verse_links
    unlink = store.unlink_group
    def interrupted(*args, **kwargs):
        unlink(*args, **kwargs)
        raise RuntimeError("process stopped after unlink")
    monkeypatch.setattr(store, "unlink_group", interrupted)
    response = call(engine, "alignment.splitSource", {"chapter": "1", "verse": "3", "topId": context_id(c, top_word="Β"), "direction": "right", "expectedOriginal": c["alignment"]})
    assert not response["success"]
    assert get(engine)["sourceLayout"]["pending"]["kind"] == "sourceSplit"
    refused = call(engine, "alignment.resetVerse", {"chapter": "1", "verse": "3", "expectedOriginal": c["alignment"], "expectedStateToken": alignment_reset.summary(engine.project, "1", "3")["token"]})
    assert not refused["success"] and "Resume source separation" in refused["error"]["message"]
    monkeypatch.setattr(store, "unlink_group", unlink)
    ok(engine, "alignment.splitSource", topId=context_id(c, top_word="Β"), direction="right", expectedOriginal=c["alignment"])
    assert [l["source"]["word"] for l in get(engine)["crossVerseLinks"]] == ["Γ"]
    assert not get(engine)["sourceLayout"].get("pending")


def test_chapter_reset_progress_cancel_resume_and_writer_exclusion(engine):
    c = get(engine)
    ok(engine, "alignment.realign", topIds=[c["topTokens"][0]["id"]], bottomIds=[c["bottomTokens"][0]["id"]], expectedOriginal=c["alignment"])
    link(engine)
    partner = get(engine, "6")["alignment"]
    preview = ok(engine, "alignment.resetChapter.preview")
    assert preview["links"] == 1 and preview["verses"] == ["3", "6"]
    job = ok(engine, "alignment.resetChapter.start", token=preview["token"])
    refused = call(engine, "alignment.resetVerse", {"chapter": "1", "verse": "3", "expectedOriginal": get(engine)["alignment"], "expectedStateToken": alignment_reset.summary(engine.project, "1", "3")["token"]})
    assert not refused["success"] and "cancel the chapter reset" in refused["error"]["message"]
    first = ok(engine, "alignment.resetChapter.step", jobId=job["id"])
    assert first["job"]["completed"] == 1 and first["job"]["state"] == "running"
    assert get(engine, "6")["alignment"] == partner
    cancelled = ok(engine, "alignment.resetChapter.cancel", jobId=job["id"])
    assert cancelled["state"] == "cancelled"
    preview = ok(engine, "alignment.resetChapter.preview")
    resumed = ok(engine, "alignment.resetChapter.start", token=preview["token"])
    assert resumed["id"] == job["id"] and resumed["completed"] == 1
    result = ok(engine, "alignment.resetChapter.step", jobId=job["id"])
    assert result["job"]["state"] == "succeeded" and result["job"]["completed"] == 2


def test_chapter_reset_refuses_changed_preview(engine):
    preview = ok(engine, "alignment.resetChapter.preview")
    link(engine)
    response = call(engine, "alignment.resetChapter.start", {"chapter": "1", "token": preview["token"]})
    assert not response["success"] and "changed since" in response["error"]["message"]


def test_verse_reset_refuses_cross_verse_changes_after_its_preview(engine):
    c = get(engine)
    token = alignment_reset.summary(engine.project, "1", "3")["token"]
    link(engine)  # Native alignment is unchanged; the private decisions changed.
    response = call(engine, "alignment.resetVerse", {"chapter": "1", "verse": "3",
        "expectedOriginal": c["alignment"], "expectedStateToken": token})
    assert not response["success"] and "decisions changed since" in response["error"]["message"]
    assert get(engine)["crossVerseLinks"]
