"""The bundled proofreading toolkit, really run (#505): the tool runner, and
one book taken through the whole procedure with the real tools around a
scripted reader. These spawn a process per tool call, as the engine does."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tc_ai_bridge import proofreading as toolkit
from tests.support.paths import ENGINE_ROOT
from tests.support.proofreading import JONAH, REFERENCE, RUTH, keep_all, reference_folder, row, staged_run

SIZES = {1: 200, 2: 200}


def _reader(first_chunk_rows, calls=None):
    def ask(name, schema, instructions, text):
        if calls is not None:
            calls.append((name, text))
        if name == "proofreading_verdicts":
            return keep_all(text)
        return {"rows": first_chunk_rows if "== INTRODUCTION" in text else [], "rejected": []}
    return ask


def _run_tool(*args):
    return subprocess.run([sys.executable, str(ENGINE_ROOT / "proofread_tool_main.py"), *args],
                          capture_output=True, timeout=120, check=False)


def test_the_runner_only_runs_a_tool_it_names():
    assert _run_tool("--version").stdout.decode().startswith("bridge-proofread-tool ")
    for name in ("../tools/sweep", "project", "os", ""):
        refused = _run_tool(name, "GEN")
        assert refused.returncode == 2 and b"Unknown proofreading tool" in refused.stderr


def test_the_engine_exe_mode_answers_with_the_tools_output_alone():
    """`main.py --proofread-tool` must not load the engine first: its start-up
    prints would be read as the tool's answer."""
    done = subprocess.run([sys.executable, str(ENGINE_ROOT / "main.py"), "--proofread-tool", "--version"],
                          capture_output=True, timeout=120, check=False)
    assert done.returncode == 0 and done.stderr == b""
    assert done.stdout.decode().strip() == f"bridge-proofread-tool {toolkit_version()}"


def toolkit_version() -> str:
    import proofread_tool_main

    return proofread_tool_main.TOOLKIT_VERSION


def test_every_tool_the_run_calls_is_on_the_runners_list():
    import proofread_tool_main

    scripts = {p.stem for p in (toolkit.toolkit_root() / "tools").glob("*.py")} - {"project", "corpus"}
    assert scripts == set(proofread_tool_main.TOOLS)


def test_the_tools_print_non_latin_text(tmp_path):
    """`sweep.py` and `dump.py` died on their first verse on Windows as
    written: the runner makes their output UTF-8."""
    paths, tools = staged_run(tmp_path / "run", {"RUT": RUTH}, reference=reference_folder(tmp_path / "ref"))
    sweep = tools("sweep", "RUT")
    assert sweep.ok, sweep.err
    assert "double spaces: 1" in sweep.out
    both = toolkit.require(tools("dump", "RUT", "both", 1))
    assert RUTH["1"]["1"] in both and "In the days when the judges ruled" in both
    # No key-term data was staged: the tool says so and leaves; that is "skipped".
    terms = tools("terms", "RUT")
    assert not terms.ok and "term check skipped" in terms.err
    with pytest.raises(toolkit.ProofreadingError, match="term check skipped"):
        toolkit.require(terms)


def test_a_book_goes_through_the_whole_procedure(tmp_path):
    paths, tools = staged_run(tmp_path / "run", {"RUT": RUTH, "JON": JONAH},
                              reference=reference_folder(tmp_path / "ref"))
    calls: list[tuple[str, str]] = []
    stages: list[tuple[str, int, int]] = []
    rows = [
        row("1", "1", "பஞ்சம் உண்டானது", issue_type="Source comparison", severity="Medium"),
        row("1", "1", "these words are not in the verse"),
        row("2", "2", "ரூத் நகோமியிடம்", suggested="ரூத்து நகோமியிடம்", check="count"),
        row("Intro", "", "சிறிய அறிமுகத்தோடு", issue_type="Style"),
        row("7", "1", "a chapter it was not given"),
    ]
    outcome = toolkit.proofread_book(
        "rut", SIZES, paths=paths, tools=tools, ask=_reader(rows, calls), language_label="Tamil",
        reference_name="Reference", language_code="ta", has_reference=True, content_hash="h1",
        report=lambda stage, done, total: stages.append((stage, done, total)))

    # One request for the two chapters, one for the row that asked for a count.
    assert [name for name, _ in calls] == ["proofreading_rows", "proofreading_verdicts"]
    reading = calls[0][1]
    assert "BOOK: RUT" in reading and "-- sweep.py" in reading and "== INTRODUCTION" in reading
    assert "== TRANSLATION, chapters 1 to 2" in reading and "== REFERENCE (Reference), chapters 1 to 2" in reading
    assert "2:2 And Ruth the Moabite said to Naomi." in reading
    # The count came from the toolkit's own `q.py`, over the whole staged translation.
    assert "`ரூத் நகோமியிடம்` occurs 1/0 times" in calls[1][1] and "`ரூத்து நகோமியிடம்` occurs 0/0 times" in calls[1][1]

    assert (outcome.chunks, outcome.reported, outcome.unplaced) == (1, 4, 1)
    found = {(r["chapter"], r["verse"], r["original"]): r for r in outcome.rows}
    assert ("1", "1", "பஞ்சம் உண்டானது") in found and ("2", "2", "ரூத் நகோமியிடம்") in found
    assert found[("Intro", "", "சிறிய அறிமுகத்தோடு")]["location"] == "Introduction"
    assert found[("1", "1", "பஞ்சம் உண்டானது")]["location"] == "Verse text"
    # The verdict's wording replaced the first explanation of the counted row.
    assert found[("2", "2", "ரூத் நகோமியிடம்")]["explanation"] == "Kept on the evidence."
    # What could not be placed is not reported; the toolkit's own double-space row is.
    assert not [r for r in outcome.rows if "not in the verse" in r["original"]]
    automatic = [r for r in outcome.rows if r["issueType"] == "Punctuation"]
    assert len(automatic) == 1 and automatic[0]["verse"] == "2" and "Extra spaces" in automatic[0]["explanation"]
    assert stages[0] == ("Running the toolkit's checks", 0, 1) and stages[-1][0] == "Writing the workbook and the notes"

    # The toolkit's own deliverables are there, as it writes them.
    out = paths.book_output("RUT")
    assert (out / "RUT_QA_Report.xlsx").stat().st_size > 0
    notes = (out / "RUT_notes_only.xml").read_text(encoding="utf-8-sig")
    assert notes.count("<Comment ") == len(outcome.rows) and "[AI-QA]" in notes
    assert list(paths.output.glob("Notes_*.xml"))
    # The findings file holds literals only, and no compiled copy was left beside it.
    assert not (paths.rows / "__pycache__").exists()

    # Read again with the same text: the checkpoint answers, the reader is not asked.
    calls.clear()
    again = toolkit.proofread_book(
        "RUT", SIZES, paths=paths, tools=tools, ask=_reader([], calls), language_label="Tamil",
        reference_name="Reference", language_code="ta", has_reference=True, content_hash="h1")
    assert calls == [] and len(again.rows) == len(outcome.rows)
    # A changed text is a different hash: the book is read afresh.
    fresh = toolkit.proofread_book(
        "RUT", SIZES, paths=paths, tools=tools, ask=_reader([], calls), language_label="Tamil",
        reference_name="Reference", language_code="ta", has_reference=True, content_hash="h2")
    assert [name for name, _ in calls] == ["proofreading_rows"] and len(fresh.rows) == 1


def test_a_book_with_no_reference_is_read_without_source_comparison(tmp_path):
    # The reference has Ruth but not Jonah.
    paths, tools = staged_run(tmp_path / "run", {"JON": JONAH},
                              reference=reference_folder(tmp_path / "ref", {"RUT": REFERENCE["RUT"]}))
    calls: list[tuple[str, str]] = []
    outcome = toolkit.proofread_book(
        "JON", {1: 100}, paths=paths, tools=tools, ask=_reader([row("1", "2", "நினிவேக்குப் போ")], calls),
        language_label="Tamil", reference_name="Reference", language_code="ta", has_reference=False,
        content_hash="h1")
    assert "No reference text is available for this book" in calls[0][1] and "-- numchk.py" not in calls[0][1]
    assert [r["original"] for r in outcome.rows] == ["நினிவேக்குப் போ"]


def test_a_book_the_toolkit_cannot_cut_into_chapters_is_not_sent(tmp_path):
    """`dump.py` ends a chapter range only at a `\\c N` line with nothing after
    the number. With a trailing space it prints to the end of the book, and
    every request would carry most of the book: the book stops instead."""
    paths, tools = staged_run(tmp_path / "run", {"RUT": RUTH}, reference=reference_folder(tmp_path / "ref"))
    staged = paths.target / "RUT.usfm"
    staged.write_text(staged.read_text(encoding="utf-8").replace("\\c 2\n", "\\c 2 \n"), encoding="utf-8")
    asked: list[str] = []
    with pytest.raises(toolkit.ProofreadingError, match="could not cut chapters 1 to 1"):
        toolkit.proofread_book(
            "RUT", {1: toolkit.CHUNK_CHARS, 2: 10}, paths=paths, tools=tools,
            ask=lambda name, schema, instructions, text: asked.append(name) or {"rows": [], "rejected": []},
            language_label="Tamil", reference_name="Reference", language_code="ta", has_reference=True,
            content_hash="h1")
    assert asked == []  # nothing was sent


def test_a_cancel_stops_at_a_step_and_keeps_what_was_read(tmp_path):
    paths, tools = staged_run(tmp_path / "run", {"RUT": RUTH}, reference=reference_folder(tmp_path / "ref"))
    asked: list[str] = []
    state = {"cancel": False}

    def ask(name, schema, instructions, text):
        asked.append(name)
        if len(asked) == 2:
            state["cancel"] = True  # arrives while the second chunk is being read
        return {"rows": [], "rejected": []}

    sizes = {1: toolkit.CHUNK_CHARS, 2: 10}  # two chunks
    with pytest.raises(toolkit.ProofreadingCancelled):
        toolkit.proofread_book("RUT", sizes, paths=paths, tools=tools, ask=ask, language_label="Tamil",
                               reference_name="Reference", language_code="ta", has_reference=True,
                               content_hash="h1", cancelled=lambda: state["cancel"])
    assert not (paths.book_output("RUT") / "RUT_QA_Issues.csv").exists()
    # The first chunk was finished and is kept; the one cut short is read again.
    state["cancel"] = False
    asked.clear()
    toolkit.proofread_book("RUT", sizes, paths=paths, tools=tools, ask=ask, language_label="Tamil",
                           reference_name="Reference", language_code="ta", has_reference=True, content_hash="h1")
    assert asked == ["proofreading_rows"]
