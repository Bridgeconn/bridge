"""AI-assisted evidence remains an open question, never a learned correction."""
import hashlib
import json

import pytest

from bridge_service import BridgeEngine
from tc_ai_bridge.language_qa_jobs import LanguageQaManager
from tc_ai_bridge.language_qa_review_import import PROVENANCE, SCHEMA
from tc_ai_bridge.secret_store import AppSettings
from tests.support.indic_qa import wait, write_project
from tests.support.projects import call

TEXT = "😀 அவர் தேவன் என்றார்."


def packet():
    return {"schema": SCHEMA, "packetId": "pilot-1", "provenance": PROVENANCE,
            "sourceArchiveSha256": "a" * 64, "cases": [{
                "id": "ta-E-1", "language": "ta", "book": "rut", "chapter": "1", "verse": "1",
                "start": TEXT.index("தேவன்"), "end": TEXT.index("தேவன்") + len("தேவன்"),
                "originalText": "தேவன்", "textHash": hashlib.sha256(TEXT.encode()).hexdigest(),
                "type": "spelling", "proposedCorrection": "கர்த்தர்", "reportedVerdict": "AI-proposed error",
                "reason": "Example proposal requiring human review", "sourceIds": ["ta-E-1"]}]}


@pytest.fixture
def setup(tmp_path):
    project = write_project(tmp_path / "rut", "rut", {"1": {"1": TEXT}}, lang_id="tam", lang_name="Tamil")
    engine = BridgeEngine(settings=AppSettings(path=tmp_path / "settings/settings.json"))
    engine._language_qa = LanguageQaManager(debounce=0, yield_seconds=0)
    engine._configure_language_qa()
    assert call(engine, "project.open", {"path": str(project)})["success"]
    wait(engine._language_qa)
    path = tmp_path / "review.json"
    yield engine, project, path
    engine._language_qa.unbind()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def rpc(setup, action, **extra):
    engine, project, path = setup
    result = call(engine, f"languageQa.reviewImport.{action}",
                  {"projectPath": str(project), "filePath": str(path), **extra})
    assert result["success"], result
    return result["result"]


def test_preview_is_read_only_and_import_never_learns_or_writes_scripture(setup):
    engine, project, path = setup
    write(path, packet())
    before = (project / "rut/1.json").read_bytes()
    preview = rpc(setup, "preview")
    assert preview["ready"] == 1 and preview["language"] == "ta"
    assert engine.project.language_qa_flags() == []
    imported = rpc(setup, "apply", expectedSha256=preview["sha256"])
    assert imported["imported"] == 1
    flag = engine.project.language_qa_flags()[0]
    assert flag["text"] == "தேவன்" and flag["status"] == "open"
    assert flag["suggested"] is None
    assert "கர்த்தர்" in flag["note"] and "native confirmation pending" in flag["note"]
    assert flag["aiReview"]["provenance"] == PROVENANCE
    assert engine.project.learned_fixes() == []
    assert engine.project.qa_decisions_for_verse("1", "1") == {}
    assert (project / "rut/1.json").read_bytes() == before


@pytest.mark.parametrize("status", ["open", "resolved", "deleted"])
def test_import_does_not_repeat_or_resurrect_a_question(setup, status):
    engine, _, path = setup
    write(path, packet())
    preview = rpc(setup, "preview")
    rpc(setup, "apply", expectedSha256=preview["sha256"])
    flag = engine.project.language_qa_flags()[0]
    engine.project.update_language_qa_flag(flag["flagId"], {"status": status, "note": "Human conclusion retained"})
    again = rpc(setup, "apply", expectedSha256=preview["sha256"])
    assert again["imported"] == 0 and again["existing"] == 1
    assert engine.project.language_qa_flag(flag["flagId"])["note"] == "Human conclusion retained"


def test_stale_text_foreign_language_and_other_books_are_skipped(setup):
    _, _, path = setup
    value = packet()
    original = value["cases"][0]
    value["cases"] = [dict(original, id="stale", textHash="b" * 64),
                      dict(original, id="span", originalText="different"),
                      dict(original, id="lang", language="hi"), dict(original, id="book", book="gen")]
    write(path, value)
    preview = rpc(setup, "preview")
    assert (preview["ready"], preview["stale"], preview["otherScope"]) == (0, 2, 2)


def test_modified_file_or_wrong_project_cannot_be_applied(setup):
    engine, _, path = setup
    write(path, packet())
    preview = rpc(setup, "preview")
    value = packet()
    value["cases"][0]["reason"] = "changed after preview"
    write(path, value)
    for params in ({"projectPath": str(engine.project.path), "expectedSha256": preview["sha256"]},
                   {"projectPath": "other", "expectedSha256": hashlib.sha256(path.read_bytes()).hexdigest()}):
        result = call(engine, "languageQa.reviewImport.apply", {"filePath": str(path), **params})
        assert not result["success"]
    assert engine.project.language_qa_flags() == []


@pytest.mark.parametrize("bad", ["provenance", "duplicate", "span", "note", "chapter-path", "verse-path"])
def test_bad_packet_is_rejected_before_any_flag_write(setup, bad):
    engine, project, path = setup
    value = packet()
    if bad == "provenance": value["provenance"] = "native-verified"
    elif bad == "duplicate": value["cases"].append(value["cases"][0].copy())
    elif bad == "span": value["cases"][0]["start"] = True
    elif bad == "chapter-path": value["cases"][0]["chapter"] = "../outside"
    elif bad == "verse-path": value["cases"][0]["verse"] = "../outside"
    else: value["cases"][0]["reason"] = "x" * 3000
    write(path, value)
    result = call(engine, "languageQa.reviewImport.apply", {"projectPath": str(project), "filePath": str(path),
                                                          "expectedSha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    assert not result["success"]
    assert engine.project.language_qa_flags() == []


def test_import_retains_exact_verse_bridges_and_segments(tmp_path):
    from tc_ai_bridge.language_qa_review_import import read_packet
    value = packet()
    value["cases"] = [dict(value["cases"][0], id=str(i), verse=verse)
                      for i, verse in enumerate(["3-4", "3a", "3a-4b"])]
    path = tmp_path / "segments.json"
    write(path, value)
    assert [c["verse"] for c in read_packet(str(path))[0]["cases"]] == ["3-4", "3a", "3a-4b"]
