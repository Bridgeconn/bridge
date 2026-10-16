"""The reference Bible and related words through the real dispatcher. A
Tamil project gets the 1957 OV that ta-irv ships, with no folder set; any
project, with a Language QA pack or not, can have one folder chosen for it
(#289), shared by every book of its collection."""
import json
import time

import pytest

from bridge_service import BridgeEngine
from tc_ai_bridge.language_qa_jobs import LanguageQaManager
from tc_ai_bridge.secret_store import AppSettings
from tests.support.indic_qa import wait, write_project
from tests.support.projects import call, link_collection

# RUT 1:1-2 as the IRV words them (two words differ from the OV in each verse).
VERSES = {"1": "நியாயாதிபதிகள் நியாயம் செய்த நாட்களில், தேசத்திலே பஞ்சம் உண்டாயிற்று;",
          "2": "அந்த மனிதனுடைய பெயர் எலிமெலேக்கு."}
TSV_HEADER = "ref\tbook\tbook_idx\tchapter\tverse\tseg\ttext\n"


@pytest.fixture
def engine(tmp_path):
    project = write_project(tmp_path / "rut", "rut", {"1": VERSES}, lang_id="tam", lang_name="Tamil")
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


def until_ready(bridge, method, deadline=60.0, **params):
    """Reference and related words load on a background thread; poll as the UI does."""
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        result = rpc(bridge, method, **params)
        if result.get("ready") or result.get("error"):
            return result
        time.sleep(0.05)
    pytest.fail(f"{method} never became ready")


def test_a_tamil_book_gets_the_bundled_ov_with_no_folder_set(engine):
    bridge, project = engine
    first = rpc(bridge, "languageQa.reference", projectPath=str(project), chapter="1")
    assert first["configured"] is True and first["source"]["label"] == "Old Version (bundled)"
    result = until_ready(bridge, "languageQa.reference", projectPath=str(project), chapter="1")
    assert result["ready"] and result["verses"][0]["verse"] == "1"
    assert result["verses"][0]["text"].startswith("நியாயாதிபதிகள் நியாயம் விசாரித்துவரும்")


def my_ov(tmp_path, name="my-ov", book="RUT", text="என் பழைய மொழிபெயர்ப்பு."):
    folder = tmp_path / name
    folder.mkdir()
    (folder / "verses.tsv").write_text(TSV_HEADER + f"{book} 1:1\t{book}\t8\t1\t1\tv\t{text}\n", encoding="utf-8")
    return folder


def test_a_folder_chosen_for_the_project_replaces_the_bundled_one(engine, tmp_path):
    """#289: one folder per project, set through languageQa.setReference."""
    bridge, project = engine
    folder = my_ov(tmp_path)
    chosen = rpc(bridge, "languageQa.setReference", projectPath=str(project), folder=str(folder))
    assert chosen == {"folder": str(folder), "origin": "project", "label": "my-ov", "path": str(folder)}
    result = until_ready(bridge, "languageQa.reference", projectPath=str(project), chapter="1")
    assert result["source"]["origin"] == "project" and result["source"]["label"] == "my-ov"
    assert result["verses"] == [{"verse": "1", "text": "என் பழைய மொழிபெயர்ப்பு."}]
    assert (tmp_path / "settings" / "reference-cache").is_dir(), "the plain text is cached in the app's data folder"
    # Settings shows the same field for the open project.
    assert rpc(bridge, "settings.get")["referenceBible"] == {"path": str(folder), "label": "my-ov", "origin": "project"}
    # Kept on this machine, keyed by the project, not by a Language QA pack.
    assert list(bridge.settings.reference_bibles.values()) == [str(folder)]
    assert "ta-irv" not in bridge.settings.reference_bibles


def test_clearing_the_choice_falls_back_to_the_bundled_ov(engine, tmp_path):
    bridge, project = engine
    rpc(bridge, "languageQa.setReference", projectPath=str(project), folder=str(my_ov(tmp_path)))
    cleared = rpc(bridge, "languageQa.setReference", projectPath=str(project), folder=None)
    assert cleared["origin"] == "bundled" and cleared["label"] == "Old Version (bundled)"
    result = rpc(bridge, "languageQa.reference", projectPath=str(project), chapter="1")
    assert result["source"]["origin"] == "bundled"
    assert bridge.settings.reference_bibles == {}


def test_a_missing_folder_is_refused_and_one_without_scripture_is_kept_with_its_error(engine, tmp_path):
    bridge, project = engine
    refused = call(bridge, "languageQa.setReference", {"projectPath": str(project), "folder": str(tmp_path / "nope")})
    assert not refused["success"] and "no such folder" in refused["error"]["message"]
    (tmp_path / "empty").mkdir()
    kept = rpc(bridge, "languageQa.setReference", projectPath=str(project), folder=str(tmp_path / "empty"))
    assert kept["origin"] == "project"
    result = until_ready(bridge, "languageQa.reference", projectPath=str(project), chapter="1")
    assert result["configured"] is True and result["ready"] is False
    assert "no verses.tsv" in result["error"], "the panel can show why and offer Change"


def test_a_book_without_a_language_qa_pack_can_have_a_reference_bible(tmp_path):
    """#289: the old lookup was keyed by pack, so these books could have none."""
    project = write_project(tmp_path / "rut", "rut", {"1": {"1": "In the days when the judges ruled."}},
                            lang_id="eng", lang_name="English")
    bridge = BridgeEngine(settings=AppSettings(path=tmp_path / "settings" / "settings.json"))
    bridge._language_qa = LanguageQaManager(debounce=0, yield_seconds=0)
    bridge._configure_language_qa()
    try:
        assert call(bridge, "project.open", {"path": str(project)})["success"]
        before = rpc(bridge, "languageQa.reference", projectPath=str(project), chapter="1")
        assert before["configured"] is False
        assert rpc(bridge, "settings.get")["referenceBible"] == {"path": "", "label": "", "origin": "none"}
        folder = my_ov(tmp_path, "kjv", text="Now it came to pass in the days when the judges ruled.")
        rpc(bridge, "languageQa.setReference", projectPath=str(project), folder=str(folder))
        result = until_ready(bridge, "languageQa.reference", projectPath=str(project), chapter="1")
        assert result["ready"] and result["verses"][0]["text"].startswith("Now it came to pass")
    finally:
        bridge._language_qa.unbind()


def test_every_book_of_a_collection_shares_the_projects_reference_bible(tmp_path):
    books = {"rut": tmp_path / "books" / "rut", "jdg": tmp_path / "books" / "jdg"}
    for book, root in books.items():
        write_project(root, book, {"1": {"1": "In the days when the judges ruled."}}, lang_id="eng", lang_name="English")
    link_collection(books)
    # A real multi-book import also writes the collection's id (schema 2).
    for root in books.values():
        path = root / ".bridge" / "collection.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(json.dumps({**data, "schemaVersion": 2, "collectionId": "col-289"}), encoding="utf-8")
    bridge = BridgeEngine(settings=AppSettings(path=tmp_path / "settings" / "settings.json"))
    bridge._language_qa = LanguageQaManager(debounce=0, yield_seconds=0)
    bridge._configure_language_qa()
    try:
        opened = rpc(bridge, "project.open", path=str(books["rut"]))
        assert opened["collectionId"], "linked books register as one collection"
        folder = my_ov(tmp_path, "shared")
        rpc(bridge, "languageQa.setReference", projectPath=str(books["rut"]), folder=str(folder))
        assert bridge.settings.reference_bibles == {opened["collectionId"]: str(folder)}
        rpc(bridge, "project.open", path=str(books["jdg"]))
        result = rpc(bridge, "languageQa.reference", projectPath=str(books["jdg"]), chapter="1")
        assert result["source"]["origin"] == "project" and result["source"]["path"] == str(folder)
    finally:
        bridge._language_qa.unbind()


def test_ov_occurrences_come_from_the_reference_text(engine):
    bridge, project = engine
    until_ready(bridge, "languageQa.reference", projectPath=str(project), chapter="1")
    result = rpc(bridge, "languageQa.occurrences", projectPath=str(project), word="எலிமெலேக்கு", source="ov", limit=5)
    assert result["ready"] and result["total"] >= 1
    assert result["hits"][0]["book"] == "rut"
    hit = result["hits"][0]
    assert hit["snippet"][hit["snippetStart"]:hit["snippetEnd"]] == "எலிமெலேக்கு"


def test_related_words_build_once_in_the_background_and_can_be_turned_off(engine):
    bridge, project = engine
    until_ready(bridge, "languageQa.reference", projectPath=str(project), chapter="1")
    result = until_ready(bridge, "languageQa.related", projectPath=str(project), word="மனிதனுடைய")
    assert result["ready"] and result["versesAligned"] >= 2
    assert result["irv"] == 1, "the IRV project uses it once (verse 2)"
    assert result["ov"] > 0, "counted over the whole 1957 OV"
    again = rpc(bridge, "languageQa.related", projectPath=str(project), word="மனிதனுடைய")
    assert again["ready"], "built once, kept for the session"
    rpc(bridge, "settings.set", languageQaRelatedWords=False)
    off = rpc(bridge, "languageQa.related", projectPath=str(project), word="மனிதனுடைய")
    assert off["ready"] is False and off["off"] is True
