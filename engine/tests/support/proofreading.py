"""Builders for the proofreading tests (#505): small book projects with more
than one chapter and an introduction, a reference Bible folder, a staged run
folder, and a scripted AI transport.

Shared here so no test module imports another (CLAUDE.md rule 2, #74)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from tc_ai_bridge import proofreading as toolkit
from tests.support.projects import call, link_collection
from tests.support.waits import job_timeout

# Tamil on purpose: the tools print verse text, and the Windows default
# console encoding cannot hold it.
RUTH = {
    "1": {"1": "நியாயாதிபதிகள் நியாயம் விசாரித்த நாட்களில் தேசத்தில் பஞ்சம் உண்டானது.",
          "2": "அந்த மனிதனுடைய பெயர் எலிமெலேக்கு,  அவனுடைய மனைவியின் பெயர் நகோமி."},
    "2": {"1": "நகோமிக்கு அவளுடைய கணவனின் உறவினன் ஒருவன் இருந்தான்.",
          "2": "மோவாபிய பெண்ணான ரூத் நகோமியிடம் பேசினாள்."},
}
JONAH = {
    "1": {"1": "அமித்தாயின் மகனாகிய யோனாவுக்குக் கர்த்தருடைய வார்த்தை உண்டானது.",
          "2": "நீ எழுந்து மகா நகரமாகிய நினிவேக்குப் போ."},
}
REFERENCE = {
    "RUT": {"1": {"1": "In the days when the judges ruled there was a famine in the land.",
                  "2": "The name of the man was Elimelech and the name of his wife Naomi."},
            "2": {"1": "Now Naomi had a relative of her husband's.",
                  "2": "And Ruth the Moabite said to Naomi."}},
    "JON": {"1": {"1": "Now the word of the LORD came to Jonah the son of Amittai.",
                  "2": "Arise, go to Nineveh, that great city."}},
}
INTRODUCTION = "இந்த புத்தகம் ஒரு சிறிய அறிமுகத்தோடு தொடங்குகிறது."


def usfm_of(book_id: str, chapters: dict[str, dict[str, str]], introduction: str = "") -> str:
    lines = [f"\\id {book_id.upper()}", f"\\h {book_id.upper()}", f"\\mt {book_id.upper()}"]
    if introduction:
        lines.append(f"\\ip {introduction}")
    for chapter, verses in chapters.items():
        lines += [f"\\c {chapter}", "\\p"]
        lines += [f"\\v {verse} {text}" for verse, text in verses.items()]
    return "\n".join(lines) + "\n"


def write_book(root: Path, book_id: str, chapters: dict[str, dict[str, str]], *, introduction: str = INTRODUCTION,
               lang_id: str = "ta", lang_name: str = "Tamil") -> Path:
    """A materialized book project: manifest, chapter JSON, empty alignment
    data and the preserved USFM source, with an introduction line."""
    align_dir = root / ".apps" / "translationCore" / "alignmentData" / book_id
    align_dir.mkdir(parents=True)
    (root / book_id).mkdir(parents=True)
    (root / "manifest.json").write_text(json.dumps({
        "project": {"id": book_id, "name": book_id.upper()},
        "target_language": {"id": lang_id, "name": lang_name},
        "tc_version": "8", "tc_edit_version": "3.7.0",
    }), encoding="utf-8")
    for chapter, verses in chapters.items():
        (align_dir / f"{chapter}.json").write_text(
            json.dumps({verse: {"alignments": [], "wordBank": []} for verse in verses}), encoding="utf-8")
        (root / book_id / f"{chapter}.json").write_text(json.dumps(verses, ensure_ascii=False), encoding="utf-8")
    (root / f"{book_id}.usfm").write_text(usfm_of(book_id, chapters, introduction), encoding="utf-8")
    return root


def link_books(books: dict[str, Path], collection_id: str = "collection-under-test") -> None:
    """Link book folders as one collection with a collection id, as a real
    multi-book import does: the id is what the books' shared settings (the
    reference Bible, the run folder) are keyed by."""
    link_collection(books)
    for root in books.values():
        path = Path(root) / ".bridge" / "collection.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["collectionId"] = collection_id
        path.write_text(json.dumps(data), encoding="utf-8")


def reference_folder(root: Path, books: dict[str, dict[str, dict[str, str]]] | None = None) -> Path:
    """A reference Bible as USFM files, found by their `\\id` line."""
    root.mkdir(parents=True, exist_ok=True)
    for code, chapters in (REFERENCE if books is None else books).items():
        (root / f"{code}.SFM").write_text(usfm_of(code, chapters), encoding="utf-8")
    return root


def staged_run(root: Path, books: dict[str, dict[str, dict[str, str]]], *, reference: Path | None,
               language_code: str = "ta") -> tuple[toolkit.RunPaths, toolkit.ToolRunner]:
    """A run folder with the given books staged, as `_Run.prepare` leaves it."""
    paths = toolkit.RunPaths(root)
    paths.prepare()
    for book_id, chapters in books.items():
        toolkit.stage_book(paths, book_id, usfm_of(book_id, chapters, INTRODUCTION))
    if reference is not None:
        staged = toolkit.stage_reference(reference, paths)
        assert not staged["error"], staged
    toolkit.write_config(paths, project_name="Test", language_code=language_code, language_label="Tamil",
                         reference_name="Reference", notes_user="Tester", model="test-model", prices={})
    return paths, toolkit.ToolRunner(paths.config)


def row(chapter: str, verse: str, original: str, *, issue_type: str = "Possible typo", severity: str = "Low",
        suggested: str = "", check: str = "none", find: str = "", confidence: str = "Medium",
        decision: str = "Review") -> dict[str, str]:
    """One finding as a reader returns it (`proofreading.rows_schema`)."""
    return {
        "chapter": chapter, "verse": verse, "issue_type": issue_type, "priority_category": "Typo",
        "severity": severity, "confidence": confidence, "original": original, "suggested": suggested,
        "explanation": "Because the reference reads otherwise.", "reference_note": "REF",
        "decision_needed": decision, "evidence_check": check, "evidence_find": find,
    }


def keep_all(text: str) -> dict[str, Any]:
    """A verdict answer that keeps every row it was asked about."""
    indexes = [int(line.split()[1].rstrip(":")) for line in text.splitlines() if line.startswith("ROW ")]
    return {"verdicts": [{"index": i, "keep": True, "issue_type": "Possible typo", "severity": "Low",
                          "confidence": "High", "explanation": "Kept on the evidence.", "why": ""} for i in indexes]}


Reader = Callable[[str, str, str], dict[str, Any]]


def scripted_transport(reader: Reader, sent: list[dict[str, Any]] | None = None):
    """A provider that answers every structured request from `reader(schema
    name, instructions, input text)`, in the Responses API envelope. `sent`
    collects what was asked, to assert on."""
    def transport(url, headers, body, timeout):
        request = json.loads(body.decode("utf-8"))
        schema_format = request.get("text", {}).get("format", {})
        assert schema_format.get("type") == "json_schema" and schema_format.get("strict") is True
        text = request["input"] if isinstance(request["input"], str) else request["input"][0]["content"]
        if sent is not None:
            sent.append({"name": schema_format.get("name"), "input": text,
                         "instructions": request.get("instructions", "")})
        payload = reader(str(schema_format.get("name")), str(request.get("instructions", "")), text)
        return 200, json.dumps({
            "output_text": json.dumps(payload, ensure_ascii=False),
            "usage": {"input_tokens": 1000, "output_tokens": 100, "total_tokens": 1100,
                      "input_tokens_details": {"cached_tokens": 400}},
        }).encode("utf-8")
    return transport


def wait_for_proofreading(engine, job_id: str, timeout: float = 120.0) -> dict[str, Any]:
    deadline = time.monotonic() + job_timeout(timeout)
    while time.monotonic() < deadline:
        status = call(engine, "proofreading.status", {"jobId": job_id})
        assert status["success"] is True, status
        if status["result"]["state"] in {"succeeded", "failed", "cancelled"}:
            return status["result"]
        time.sleep(0.05)
    raise AssertionError("the proofreading run did not finish")
