"""The parts of the proofreading procedure that need no tool and no reader
(#505): the reading plan, what the reader is told, what a row may be, and the
findings file Bridge writes for the toolkit's `build.py`."""
from __future__ import annotations

import ast

from tc_ai_bridge import proofreading as toolkit
from tests.support.proofreading import row


def test_chapters_are_read_about_three_at_a_time_and_fewer_when_long():
    assert toolkit.plan_chunks({n: 3000 for n in range(1, 8)}) == [[1, 2, 3], [4, 5, 6], [7]]
    # A long chapter closes the chunk before it; one longer than the limit is alone.
    assert toolkit.plan_chunks({1: 9000, 2: 9000, 3: 2000, 4: 40000, 5: 100}) == [[1], [2, 3], [4], [5]]
    # A gap in the numbering never puts two unconnected chapters in one request.
    assert toolkit.plan_chunks({1: 100, 2: 100, 5: 100}) == [[1, 2], [5]]
    assert toolkit.plan_chunks({}) == []


def test_the_reader_is_given_the_toolkits_own_rules_checklist_and_profile():
    generic = toolkit.instructions(language_label="Malayalam", reference_name="ESV",
                                   profile=toolkit.load_profile("ml"))
    # SKILL.md sections 4 and 5, verbatim, and not the session-only sections.
    assert "## 4. Checks" in generic and "## 5. Row rules" in generic
    assert "Possible missed source word" in generic and "One finding = one row = one verse" in generic
    assert "AskUserQuestion" not in generic and "SendUserMessage" not in generic
    # The meaning and theology checklist.
    assert "Search nearby before calling anything missing" in generic and "Divine passive" in generic
    # A language with no profile is told so, and how to mark rows that rest on unreviewed rules.
    assert "No profile reviewed by a native linguist" in generic and "Confidence Medium" in generic
    telugu = toolkit.instructions(language_label="Telugu", reference_name="ESV", profile=toolkit.load_profile("te"))
    assert "sandhi_word_division" in telugu and "No profile reviewed by a native linguist" not in telugu
    assert toolkit.load_profile("te-IN")["_profile"] == "te" and toolkit.load_profile("xx")["_profile"] == "generic"


def test_the_answer_schemas_are_strict_everywhere():
    def strict(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert sorted(node["required"]) == sorted(node["properties"])
            for value in node.values():
                strict(value)
        elif isinstance(node, list):
            for value in node:
                strict(value)
    strict(toolkit.rows_schema())
    strict(toolkit.verdicts_schema())
    assert toolkit.rows_schema()["properties"]["rows"]["items"]["properties"]["issue_type"]["enum"] == list(
        toolkit.ISSUE_TYPES)


def test_a_row_is_tidied_and_one_that_cannot_be_a_row_is_refused():
    kept = toolkit.normalize_row(row("3", "16", "  some   words ", severity="high", check="count"), {3})
    assert (kept["chapter"], kept["verse"], kept["original"], kept["severity"], kept["check"]) == (
        3, 16, "some words", "High", "count")
    intro = toolkit.normalize_row(row("Intro", "9", "a word"), {3})
    assert (intro["chapter"], intro["verse"]) == ("Intro", "")
    bridge = toolkit.normalize_row(row("3", "4-5", "x"), {3})
    assert bridge["verse"] == "4-5"
    assert toolkit.normalize_row(row("4", "1", "outside the chapters it was given"), {3}) is None
    assert toolkit.normalize_row(row("3", "1", "   "), {3}) is None
    assert toolkit.normalize_row(row("three", "1", "x"), {3}) is None
    assert toolkit.normalize_row(row("3", "", "x"), {3}) is None
    assert toolkit.normalize_row("not a row", {3}) is None
    # A provider that ignored the schema: unknown values fall back, never through.
    odd = toolkit.normalize_row({**row("3", "1", "x"), "issue_type": "Made up", "severity": "Severe",
                                 "evidence_check": "run a shell"}, {3})
    assert (odd["issueType"], odd["severity"], odd["check"]) == ("Reviewer decision", "Low", "none")


def test_the_findings_file_is_literals_only_whatever_the_reader_wrote(tmp_path):
    hostile = "'), __import__('os').system('echo owned'), ('"
    rows = [toolkit.normalize_row(row("1", "2", hostile, suggested='"""\n' + hostile), {1})]
    path = tmp_path / "rows" / "rows_gen.py"
    toolkit.write_rows_file(path, rows, [(hostile, "why \\ \n not")], "whole book")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    # Nothing but assignments of literals: no call, no import, no name lookup.
    assert all(isinstance(node, ast.Assign) for node in tree.body)
    assert not [node for node in ast.walk(tree) if isinstance(node, (ast.Call, ast.Import, ast.ImportFrom,
                                                                        ast.Attribute, ast.Lambda))]
    values = {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body}
    assert values["ROWS"][0][6] == " ".join(hostile.split()) and values["REJECTED"] == [(hostile, "why \\ \n not")]
    assert len(values["ROWS"][0]) == 11 and values["REVIEWED"] == "whole book"


def test_a_stale_compiled_copy_of_the_findings_file_is_removed(tmp_path):
    path = tmp_path / "rows" / "rows_gen.py"
    cache = path.parent / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "rows_gen.cpython-312.pyc").write_bytes(b"stale")
    toolkit.write_rows_file(path, [], [], "whole book")
    assert not cache.exists()


def test_a_failed_row_is_recognised_by_the_line_the_tool_prints():
    rows = [toolkit.normalize_row(row("1", "2", "these words stand"), {1}),
            toolkit.normalize_row(row("1", "1", "these words do not"), {1}),
            toolkit.normalize_row(row("Intro", "", "nor these"), {1})]
    output = ("FAIL 1 1 these words do not\nFAIL Intro  nor these\n"
              "1 rows | {'Verse text': 1, 'fail': 2}\nseverity: {'Low': 1}\n")
    assert toolkit.build_failures(output, rows) == (2, [1, 2])
    assert toolkit.build_failures("3 rows | {'Verse text': 3, 'fail': 0}\n", rows) == (0, [])
    # A failure that is not one of ours (an automatic row) is counted, not guessed at.
    assert toolkit.build_failures("FAIL 9 9 automatic\n1 rows | {'fail': 1}\n", rows) == (1, [])
    assert toolkit.build_failures("Traceback ...", rows) == (-1, [])


def test_of_two_overlapping_findings_the_less_severe_goes_and_an_automatic_row_wins():
    rows = [toolkit.normalize_row(row("1", "2", "alpha beta", severity="Low"), {1}),
            toolkit.normalize_row(row("1", "2", "alpha beta gamma", severity="High"), {1}),
            toolkit.normalize_row(row("1", "3", "delta  epsilon", severity="Medium"), {1})]
    both_ours = "OVERLAP ((1, '2'), 'alpha beta', 'alpha beta gamma')\n"
    assert toolkit.build_overlaps(both_ours, rows) == [0]
    # The other pin is the toolkit's own double-space row: ours gives way.
    with_automatic = "OVERLAP ((1, '3'), 'delta  epsilon', 'an automatic row')\n"
    assert toolkit.build_overlaps(with_automatic, rows) == [2]
    assert toolkit.build_overlaps("OVERLAP not a tuple\n4 rows | {'fail': 0}\n", rows) == []


def test_reference_lines_come_from_the_side_by_side_dump():
    both = "1:1 T: target one\n1:1 R: reference one\n\n1:2 T: target two\n1:2 R: ?\n\n1:3-4 T: t\n1:3-4 R: bridged\n"
    assert toolkit.reference_lines(both) == "1:1 reference one\n1:3-4 bridged"


def test_a_stored_finding_keeps_its_id_across_runs_and_repeats_are_told_apart():
    found = [{"chapter": "1", "verse": "2", "issueType": "Possible typo", "original": "word", "severity": "Low"},
             {"chapter": "1", "verse": "2", "issueType": "Possible typo", "original": "word", "severity": "Low"},
             {"chapter": "Intro", "verse": "", "issueType": "Heading", "original": "w", "severity": "High"}]
    first = toolkit.stored_rows("gen", found)
    again = toolkit.stored_rows("GEN", found)
    assert sorted(first) == ["1", "intro"]
    assert [r["id"] for r in first["1"]] == [r["id"] for r in again["1"]]
    assert first["1"][0]["id"] != first["1"][1]["id"] and first["intro"][0]["book"] == "GEN"
    summary = toolkit.summarize([r for rows in first.values() for r in rows])
    assert summary == {"findings": 3, "bySeverity": {"High": 1, "Medium": 0, "Low": 2},
                       "byIssueType": {"Heading": 1, "Possible typo": 2}}


def test_a_tsv_reference_is_staged_as_usfm_the_tools_can_find(tmp_path):
    folder = tmp_path / "ov"
    folder.mkdir()
    (folder / "verses.tsv").write_text(
        "ref\tbook\tbook_idx\tchapter\tverse\tseg\ttext\n"
        "RUT 1:2\tRUT\t8\t1\t2\tv\tsecond  verse\nRUT 1:1\tRUT\t8\t1\t1\tv\tfirst verse\n"
        "RUT 1:0\tRUT\t8\t1\t0\th\ta heading row\n", encoding="utf-8")
    paths = toolkit.RunPaths(tmp_path / "run")
    paths.prepare()
    assert toolkit.stage_reference(folder, paths) == {"kind": "tsv", "files": 1, "error": ""}
    assert (paths.reference / "RUT.usfm").read_text(encoding="utf-8") == (
        "\\id RUT\n\\c 1\n\\p\n\\v 1 first verse\n\\v 2 second verse\n")
    empty = tmp_path / "empty"
    empty.mkdir()
    assert toolkit.stage_reference(empty, paths)["error"]


def test_the_run_folder_name_is_safe_for_any_project_key():
    assert toolkit.run_folder_name("3f2a-collection_1") == "3f2a-collection_1"
    assert "/" not in toolkit.run_folder_name("../..\\evil:name") and toolkit.run_folder_name("") != ""
