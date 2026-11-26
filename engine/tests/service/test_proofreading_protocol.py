"""`proofreading.*` end to end (#505): a two-book collection read by a scripted
provider through the real toolkit tools, then what is kept, what a second run
skips, and what stops a run."""
from __future__ import annotations

import csv
import json

import pytest

from bridge_service import BridgeEngine
from tc_ai_bridge.language_qa_jobs import LanguageQaManager
from tc_ai_bridge.secret_store import AppSettings
from tc_ai_bridge.tc_project import TranslationCoreProject
from tests.support.projects import call
from tests.support.proofreading import (
    JONAH, RUTH, keep_all, link_books, reference_folder, row, scripted_transport, wait_for_proofreading, write_book,
)


@pytest.fixture
def collection(tmp_path):
    # Linked out of canonical order, to show the run does not follow the link's order.
    books = {"jon": write_book(tmp_path / "jon", "jon", JONAH), "rut": write_book(tmp_path / "rut", "rut", RUTH)}
    link_books(books)
    return books


def _reader(name, instructions, text):
    if name == "proofreading_verdicts":
        return keep_all(text)
    if "BOOK: RUT" in text:
        return {"rows": [row("1", "1", "பஞ்சம் உண்டானது", issue_type="Source comparison", severity="High"),
                         row("2", "2", "these words are nowhere"),
                         row("Intro", "", "சிறிய அறிமுகத்தோடு", issue_type="Style")],
                "rejected": [{"lead": "double spaces", "why": "left for the automatic row"}]}
    return {"rows": [row("1", "2", "நினிவேக்குப் போ", severity="Medium")], "rejected": []}


def _engine(tmp_path, path, reader=_reader, sent=None, api_key="sk-test"):
    engine = BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json"))
    engine._language_qa = LanguageQaManager(debounce=0, yield_seconds=0)
    engine._ai_transport = scripted_transport(reader, sent)
    engine.settings.set_api_key(api_key, persist=False)
    assert call(engine, "project.open", {"path": str(path)})["success"]
    return engine


def _with_reference(engine, tmp_path):
    chosen = call(engine, "proofreading.setReference", {"folder": str(reference_folder(tmp_path / "esv"))})
    assert chosen["success"], chosen
    return chosen["result"]


def _run(engine, **params):
    started = call(engine, "proofreading.start", params)
    assert started["success"], started
    return wait_for_proofreading(engine, started["result"]["jobId"])


def test_preflight_says_what_a_run_needs_before_anything_is_sent(tmp_path, collection):
    sent: list = []
    engine = _engine(tmp_path, collection["rut"], sent=sent)
    before = call(engine, "proofreading.preflight")["result"]
    assert before["aiReady"] is True and before["planUsage"] is False and before["running"] is False
    assert before["reference"]["origin"] == "none" and before["reference"]["error"]
    assert before["language"] == {"code": "ta", "label": "Tamil"} and before["profile"]["code"] == "generic"
    # Canonical order, whatever order the collection lists them in.
    assert [b["bookId"] for b in before["books"]] == ["rut", "jon"]
    assert all(b["supported"] and b["previous"] is None and b["estimate"]["requests"] >= 2 for b in before["books"])
    # No reference yet: starting is refused, and says what is missing.
    refused = call(engine, "proofreading.start")
    assert refused["success"] is False and "Choose a reference Bible" in refused["error"]["message"]

    chosen = _with_reference(engine, tmp_path)
    assert (chosen["origin"], chosen["kind"], chosen["files"], chosen["error"]) == ("proofreading", "usfm", "2", "")
    assert call(engine, "proofreading.preflight")["result"]["reference"]["label"] == "esv"
    # Its own choice: the project's Language QA reference Bible is not touched.
    assert engine.settings.reference_bibles == {}
    missing = call(engine, "proofreading.setReference", {"folder": str(tmp_path / "nowhere")})
    assert missing["success"] is False
    assert sent == []  # nothing in this test reached the provider


def test_a_run_reads_the_chosen_books_and_keeps_what_the_toolkit_placed(tmp_path, collection):
    sent: list = []
    engine = _engine(tmp_path, collection["rut"], sent=sent)
    _with_reference(engine, tmp_path)
    done = _run(engine)
    assert done["state"] == "succeeded", done
    assert [(b["bookId"], b["state"]) for b in done["books"]] == [("rut", "done"), ("jon", "done")]
    rut, jon = done["books"]
    # Two of the reader's three Ruth rows could be placed, plus the toolkit's own double-space row.
    assert (rut["findings"], rut["bySeverity"]) == (3, {"High": 1, "Medium": 0, "Low": 2})
    assert (jon["findings"], jon["bySeverity"]) == (1, {"High": 0, "Medium": 1, "Low": 0})
    assert done["findings"] == 4 and done["usage"]["calls"] == 2 and done["usage"]["totalTokens"] == 2200
    assert [s["name"] for s in sent] == ["proofreading_rows", "proofreading_rows"]
    assert "## 5. Row rules" in sent[0]["instructions"]

    # Each book's rows are in its own workbench; the other book's are read without opening it.
    ruth_rows = call(engine, "proofreading.rows", {"bookId": "rut"})["result"]
    assert [(r["chapter"], r["verse"], r["issueType"]) for r in ruth_rows["rows"]] == [
        ("Intro", "", "Style"), ("1", "1", "Source comparison"), ("1", "2", "Punctuation")]
    assert ruth_rows["files"]["workbook"].endswith("RUT_QA_Report.xlsx")
    jonah_rows = call(engine, "proofreading.rows", {"bookId": "jon"})["result"]["rows"]
    assert [r["original"] for r in jonah_rows] == ["நினிவேக்குப் போ"] and len(jonah_rows[0]["id"]) == 20

    report = call(engine, "proofreading.report")["result"]
    assert (report["booksRead"], report["totalBooks"], report["findings"]) == (2, 2, 4)
    assert report["bySeverity"] == {"High": 1, "Medium": 1, "Low": 2}
    assert report["byIssueType"] == {"Possible typo": 1, "Punctuation": 1, "Source comparison": 1, "Style": 1}
    assert report["books"][0]["unplaced"] == 1 and report["books"][0]["reference"] == "esv"
    assert report["files"]["runReport"].endswith("QA_Run_Report.xlsx") and "paratextNotes" in report["files"]

    out = tmp_path / "findings.csv"
    exported = call(engine, "proofreading.export", {"outputPath": str(out), "format": "csv"})["result"]
    assert exported["rows"] == 4
    with out.open(encoding="utf-8-sig", newline="") as handle:
        table = list(csv.reader(handle))
    assert table[0][:4] == ["Book", "Chapter", "Verse", "Issue type"] and [line[0] for line in table[1:]] == [
        "RUT", "RUT", "RUT", "JON"]
    only = call(engine, "proofreading.export", {"outputPath": str(out), "format": "tsv", "books": ["jon"]})
    assert only["result"]["rows"] == 1

    # No Scripture, and nothing but the proofreading table, was written to the book.
    assert json.loads((collection["rut"] / "rut" / "1.json").read_text(encoding="utf-8")) == RUTH["1"]
    assert TranslationCoreProject(collection["jon"]).load_proofreading_results()[0]["severity"] == "Medium"
    # The run is the collection's: it is recorded on every book.
    for root in collection.values():
        recorded = json.loads((root / ".bridge" / "collection.json").read_text(encoding="utf-8"))["proofreadRuns"]
        assert sorted(r["bookId"] for r in recorded) == ["jon", "rut"]


def test_a_second_run_skips_what_is_unchanged_and_rereads_what_is_not(tmp_path, collection):
    sent: list = []
    engine = _engine(tmp_path, collection["rut"], sent=sent)
    _with_reference(engine, tmp_path)
    assert _run(engine)["state"] == "succeeded"

    # A new engine, opened on the other book: the bar shows the recorded run.
    sent.clear()
    engine = _engine(tmp_path, collection["jon"], sent=sent)
    idle = call(engine, "proofreading.status")["result"]
    assert idle["state"] == "idle" and [(b["bookId"], b["state"], b["findings"]) for b in idle["books"]] == [
        ("rut", "done", 3), ("jon", "done", 1)]
    previous = {b["bookId"]: b["previous"] for b in call(engine, "proofreading.preflight")["result"]["books"]}
    assert previous["rut"]["findings"] == 3 and previous["jon"]["reference"] == "esv"

    again = _run(engine)
    assert [(b["bookId"], b["state"], b["findings"]) for b in again["books"]] == [
        ("rut", "skipped", 3), ("jon", "skipped", 1)]
    assert sent == [] and again["usage"]["calls"] == 0

    # Ruth's text changes: only Ruth is read again.
    chapter = collection["rut"] / "rut" / "2.json"
    chapter.write_text(json.dumps({**RUTH["2"], "2": RUTH["2"]["2"] + " மேலும்."}, ensure_ascii=False),
                       encoding="utf-8")
    engine = _engine(tmp_path, collection["rut"], sent=sent)
    changed = _run(engine)
    assert [(b["bookId"], b["state"]) for b in changed["books"]] == [("rut", "done"), ("jon", "skipped")]
    assert [s["name"] for s in sent] == ["proofreading_rows"] and "மேலும்." in sent[0]["input"]

    # Asked to read one unchanged book again, the reader is asked again.
    sent.clear()
    forced = _run(engine, books=["jon"], force=True)
    assert [(b["bookId"], b["state"]) for b in forced["books"]] == [("jon", "done")]
    assert [s["name"] for s in sent] == ["proofreading_rows"]


def test_a_reached_plan_limit_stops_the_run_and_keeps_the_finished_book(tmp_path, collection):
    engine = _engine(tmp_path, collection["rut"])
    _with_reference(engine, tmp_path)
    state = {"reason": ""}
    engine._ai_halt_reason = lambda: state["reason"]

    def reader(name, instructions, text):
        if "BOOK: RUT" in text:
            state["reason"] = "Your ChatGPT plan limit has been reached."  # true from now on
        return _reader(name, instructions, text)

    engine._ai_transport = scripted_transport(reader)
    stopped = _run(engine)
    assert stopped["state"] == "failed" and stopped["halted"] is True
    assert stopped["error"] == "Your ChatGPT plan limit has been reached."
    assert [(b["bookId"], b["state"]) for b in stopped["books"]] == [("rut", "done"), ("jon", "pending")]
    recorded = json.loads((collection["rut"] / ".bridge" / "collection.json").read_text(encoding="utf-8"))
    assert [r["bookId"] for r in recorded["proofreadRuns"]] == ["rut"]
    # Later, with the limit gone, the run picks up at Jonah.
    state["reason"] = ""
    engine._ai_transport = scripted_transport(_reader)
    resumed = _run(engine)
    assert [(b["bookId"], b["state"]) for b in resumed["books"]] == [("rut", "skipped"), ("jon", "done")]


def test_a_cancel_records_nothing_for_the_book_in_flight(tmp_path, collection):
    engine = _engine(tmp_path, collection["rut"])
    _with_reference(engine, tmp_path)

    def reader(name, instructions, text):
        assert call(engine, "proofreading.cancel")["success"]
        return _reader(name, instructions, text)

    engine._ai_transport = scripted_transport(reader)
    cancelled = _run(engine)
    assert cancelled["state"] == "cancelled"
    assert [(b["bookId"], b["state"]) for b in cancelled["books"]] == [("rut", "pending"), ("jon", "pending")]
    assert "proofreadRuns" not in json.loads(
        (collection["rut"] / ".bridge" / "collection.json").read_text(encoding="utf-8"))
    assert call(engine, "proofreading.rows", {"bookId": "rut"})["result"]["rows"] == []


def test_a_book_the_reader_fails_on_does_not_stop_the_others(tmp_path, collection):
    engine = _engine(tmp_path, collection["rut"])
    _with_reference(engine, tmp_path)

    def reader(name, instructions, text):
        if "BOOK: RUT" in text:
            return {"rows": "not a list"}  # an answer the client refuses
        return _reader(name, instructions, text)

    def transport(url, headers, body, timeout):
        request = json.loads(body.decode("utf-8"))
        if "BOOK: RUT" in str(request["input"]):
            return 400, json.dumps({"error": {"code": "bad_request", "message": "The request was refused."}}).encode()
        return scripted_transport(_reader)(url, headers, body, timeout)

    engine._ai_transport = transport
    finished = _run(engine)
    assert finished["state"] == "failed" and finished["halted"] is False
    assert [(b["bookId"], b["state"]) for b in finished["books"]] == [("rut", "failed"), ("jon", "done")]
    assert "refused" in finished["books"][0]["error"] and finished["error"] == "1 book(s) could not be read."


def test_proofreading_collection_qa_and_a_check_never_run_at_once(tmp_path, collection):
    engine = _engine(tmp_path, collection["rut"])
    _with_reference(engine, tmp_path)
    engine._collection_jobs.active = lambda: True
    busy = call(engine, "proofreading.start")
    assert busy["success"] is False and busy["error"]["code"] == "job_conflict"
    assert call(engine, "proofreading.preflight")["result"]["checkRunning"] is True
    engine._collection_jobs.active = lambda: False
    engine._proofreading.jobs.active = lambda: True
    for method, params in (("checks.start", {"scope": "chapter", "chapters": ["1"]}),
                           ("collection.runChecks", {"checks": ["languageQa"]})):
        refused = call(engine, method, params)
        assert refused["success"] is False and "proofreading run is in progress" in refused["error"]["message"]


def test_without_an_ai_provider_nothing_starts(tmp_path, collection):
    sent: list = []
    engine = _engine(tmp_path, collection["rut"], sent=sent, api_key="")
    _with_reference(engine, tmp_path)
    assert call(engine, "proofreading.preflight")["result"]["aiReady"] is False
    refused = call(engine, "proofreading.start")
    assert refused["success"] is False and "API key" in refused["error"]["message"]
    assert sent == [] and call(engine, "proofreading.status")["result"]["state"] == "idle"


def test_a_mostly_empty_book_is_not_sent_and_the_others_are_read(tmp_path):
    """A book whose verses are mostly empty has little to proofread, and the
    toolkit's sweep fails on it. It is refused before anything is sent."""
    books = {"jon": write_book(tmp_path / "jon", "jon", {"1": {"1": "", "2": "", "3": JONAH["1"]["2"]}}),
             "rut": write_book(tmp_path / "rut", "rut", RUTH)}
    link_books(books)
    sent: list = []
    engine = _engine(tmp_path, books["rut"], sent=sent)
    _with_reference(engine, tmp_path)
    finished = _run(engine)
    assert [(b["bookId"], b["state"]) for b in finished["books"]] == [("rut", "done"), ("jon", "failed")]
    assert finished["books"][1]["error"] == "More than half of this book's verses have no text, so it was not read."
    assert all("BOOK: RUT" in s["input"] for s in sent) and sent  # nothing of Jonah reached the provider


def test_the_export_writes_a_formula_like_cell_as_text(tmp_path, collection):
    def reader(name, instructions, text):
        if "BOOK: RUT" in text:
            return {"rows": [row("1", "1", "பஞ்சம் உண்டானது", suggested="=1+1")], "rejected": []}
        return {"rows": [], "rejected": []}

    engine = _engine(tmp_path, collection["rut"], reader=reader)
    _with_reference(engine, tmp_path)
    assert _run(engine, books=["rut"])["state"] == "succeeded"
    # In the app the finding is shown as the reader gave it.
    stored = call(engine, "proofreading.rows", {"bookId": "rut"})["result"]["rows"]
    assert "=1+1" in [r["suggested"] for r in stored]
    out = tmp_path / "findings.csv"
    assert call(engine, "proofreading.export", {"outputPath": str(out), "format": "csv"})["success"]
    with out.open(encoding="utf-8-sig", newline="") as handle:
        cells = [cell for line in csv.reader(handle) for cell in line]
    assert "'=1+1" in cells and "=1+1" not in cells


def test_a_book_that_lost_a_chapter_is_read_again_and_loses_that_chapters_findings(tmp_path, collection):
    """The staged text of such a book can be word for word what it was: the
    export keeps the source's words for a chapter the book no longer has. So
    the unchanged-book skip is also asked which chapters the last run read."""
    def reader(name, instructions, text):
        if "BOOK: RUT" in text:
            return {"rows": [row("1", "1", "பஞ்சம் உண்டானது"), row("2", "1", "நகோமிக்கு")], "rejected": []}
        return {"rows": [], "rejected": []}

    sent: list = []
    engine = _engine(tmp_path, collection["rut"], reader=reader, sent=sent)
    _with_reference(engine, tmp_path)
    assert _run(engine, books=["rut"])["state"] == "succeeded"
    first = call(engine, "proofreading.rows", {"bookId": "rut"})["result"]["rows"]
    assert "2" in {r["chapter"] for r in first}
    recorded = json.loads((collection["rut"] / ".bridge" / "collection.json").read_text(encoding="utf-8"))
    assert recorded["proofreadRuns"][0]["chapters"] == ["1", "2"]

    # Unchanged: skipped, as before.
    sent.clear()
    assert [b["state"] for b in _run(engine, books=["rut"])["books"]] == ["skipped"]
    assert sent == []

    # Chapter 2 goes; the book's source file, and so its staged text, is as it was.
    (collection["rut"] / "rut" / "2.json").unlink()
    (collection["rut"] / ".apps" / "translationCore" / "alignmentData" / "rut" / "2.json").unlink()
    engine = _engine(tmp_path, collection["rut"], reader=reader, sent=sent)
    again = _run(engine, books=["rut"])
    assert [b["state"] for b in again["books"]] == ["done"] and [s["name"] for s in sent] == ["proofreading_rows"]
    assert "== TRANSLATION, chapter 1 " in sent[0]["input"]
    rows = call(engine, "proofreading.rows", {"bookId": "rut"})["result"]["rows"]
    assert "பஞ்சம் உண்டானது" in [r["original"] for r in rows]
    assert "நகோமிக்கு" not in [r["original"] for r in rows]  # the reader's row for the chapter that is gone


def test_a_run_recorded_before_chapters_were_kept_is_still_skipped_by_its_hash(tmp_path, collection):
    sent: list = []
    engine = _engine(tmp_path, collection["rut"], sent=sent)
    _with_reference(engine, tmp_path)
    assert _run(engine, books=["rut"])["state"] == "succeeded"
    # As the first build recorded it: no list of chapters.
    for root in collection.values():
        path = root / ".bridge" / "collection.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for run in data["proofreadRuns"]:
            run.pop("chapters")
        path.write_text(json.dumps(data), encoding="utf-8")
    sent.clear()
    engine = _engine(tmp_path, collection["rut"], sent=sent)
    assert [b["state"] for b in _run(engine, books=["rut"])["books"]] == ["skipped"]
    assert sent == []
