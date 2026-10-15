"""#205 and #204 through the protocol: the reporter's own USFM, imported, then
checked with the elective Greek Room check, on the live verse call and on the
background job. The adapter's unit tests cover the shapes; this is the path a
reviewer's click takes, so a finding lost between the adapter and the response
(as the bug reports described) fails here.

Runs on whichever Wildebeest path is installed: the real engine raises these
check types from its report and Bridge's scan, the mock from the same scan, so
the assertions hold on CI's extra-less install and on a 3.12 developer venv.
"""
from __future__ import annotations

import unicodedata

from bridge_service import BridgeEngine
from tests.support.projects import call, wait_for_job

NFD_CAFE = unicodedata.normalize("NFD", "café")
NFC_E = unicodedata.normalize("NFC", "é")
NFD_E = unicodedata.normalize("NFD", "é")

REPORTER_USFM = (
    "\\id TIT\n\\h Titus\n\\toc1 Titus\n\\toc2 Titus\n\\toc3 TIT\n\\c 1\n\\p\n"
    f"\\v 1 In the beginning, {NFD_CAFE} was used as the test word.\n"
    "\\v 2 This is a clean control verse with ordinary text.\n"
    "\\v 3 ദൈവം called the light Day and darkness Night. Evening and morning became first day.\n"
    "\\v 4 Earth was @ empty and dark. Spirit of God moved over water.\n"
)


def _import_reporter_project(tmp_path):
    source = tmp_path / "TIT.usfm"
    source.write_text(REPORTER_USFM, encoding="utf-8")
    engine = BridgeEngine()
    imported = call(engine, "project.import", {
        "path": str(source), "destinationRoot": str(tmp_path / "projects"),
        "metadata": {"languageId": "eng", "languageName": "English", "languageDirection": "ltr",
                     "projectName": "Titus", "bibleName": "Test Bible"},
    })
    assert imported["success"] is True, imported
    opened = call(engine, "project.open", {"path": imported["result"]["path"]})
    assert opened["success"] is True, opened
    return engine


def _wildebeest(findings):
    return {f["check_type"]: f for f in findings if f["engine"] == "wildebeest"}


def test_nfd_text_reaches_the_verse_response_with_an_nfc_suggestion(tmp_path):
    engine = _import_reporter_project(tmp_path)
    response = call(engine, "verse.runChecks", {"chapter": "1", "verse": "1", "checks": ["greekroom"]})
    assert response["success"] is True
    by_type = _wildebeest(response["findings"])
    finding = by_type["wildebeest.non_canonical"]
    assert finding["original_text"] == NFD_E
    assert finding["suggested_replacement"] == NFC_E
    text = call(engine, "verse.get", {"chapter": "1", "verse": "1"})["result"]["text"]
    assert text[finding["start_offset"]:finding["end_offset"]] == NFD_E
    assert (finding["chapter"], finding["verse"], finding["status"]) == (1, 1, "open")


def test_a_lone_symbol_and_a_word_in_another_script_are_findings(tmp_path):
    engine = _import_reporter_project(tmp_path)
    symbol = _wildebeest(call(engine, "verse.runChecks", {
        "chapter": "1", "verse": "4", "checks": ["greekroom"]})["findings"])
    assert symbol["wildebeest.special_character"]["original_text"] == "@"
    assert symbol["wildebeest.special_character"]["start_offset"] == len("Earth was ")
    foreign = _wildebeest(call(engine, "verse.runChecks", {
        "chapter": "1", "verse": "3", "checks": ["greekroom"]})["findings"])
    assert foreign["wildebeest.foreign_script"]["original_text"] == "ദൈവം"
    assert (foreign["wildebeest.foreign_script"]["start_offset"],
            foreign["wildebeest.foreign_script"]["end_offset"]) == (0, len("ദൈവം"))
    assert "Malayalam" in foreign["wildebeest.foreign_script"]["explanation"]


def test_the_clean_control_verse_has_no_greek_room_finding(tmp_path):
    engine = _import_reporter_project(tmp_path)
    response = call(engine, "verse.runChecks", {"chapter": "1", "verse": "2", "checks": ["greekroom"]})
    assert _wildebeest(response["findings"]) == {}


def test_the_background_job_reports_the_same_findings_per_verse(tmp_path):
    engine = _import_reporter_project(tmp_path)
    started = call(engine, "checks.start", {"scope": "chapter", "chapters": ["1"], "checks": ["greekroom"]})
    assert started["success"] is True, started
    snapshot = wait_for_job(engine, started["result"]["jobId"])
    assert snapshot["state"] == "succeeded"
    results = snapshot["results"]
    assert set(_wildebeest(results["1:1"]["findings"])) == {"wildebeest.non_canonical"}
    assert _wildebeest(results["1:2"]["findings"]) == {}
    assert set(_wildebeest(results["1:3"]["findings"])) == {"wildebeest.foreign_script"}
    assert set(_wildebeest(results["1:4"]["findings"])) == {"wildebeest.special_character"}
