"""Section-heading rules (framework item 31, #244): trailing punctuation, mixed
\\s / \\s1, and a chapter with no heading. Pure rules, then one pass through the
Language QA manager reading a real `<chapter>.headings.json`."""
from __future__ import annotations

import json

from tc_ai_bridge.language_qa_headings import heading_findings
from tc_ai_bridge.language_qa_jobs import LanguageQaManager
from tests.support.language_qa import project_at, wait


def rules(findings):
    return sorted((f["rule"], f["chapter"], f["verse"], f["originalText"]) for f in findings)


def test_a_heading_ending_in_a_full_stop_is_flagged_and_a_question_is_not():
    headings = {"1": {"1": [{"tag": "s", "text": "படைப்பு."}], "5": [{"tag": "s", "text": "யார் இவர்?"}]}}
    found = heading_findings("gen", headings, {"1": ["1", "5"]})
    assert rules(found) == [("heading.trailing-punctuation", "1", "1", ".")]
    finding = found[0]
    assert (finding["context"], finding["contextText"], finding["start"], finding["end"]) == ("heading", "படைப்பு.", 7, 8)
    assert finding["ruleId"] == "common/heading.trailing-punctuation" and finding["suggestions"] == []
    assert finding["inline"] is False and finding["category"] == "punctuation"


def test_parallel_references_and_speakers_are_not_titles():
    headings = {"1": {"1": [{"tag": "r", "text": "(மத் 5:1-12;)"}, {"tag": "sp", "text": "மணவாட்டி:"}]}}
    assert heading_findings("sng", headings, {"1": ["1"]}) == []


def test_in_a_book_mixing_s_and_s1_the_minority_is_flagged():
    headings = {str(c): {"1": [{"tag": "s", "text": f"தலைப்பு {c}"}]} for c in range(1, 5)}
    headings["5"] = {"1": [{"tag": "s1", "text": "உதவிக்காரர்களுக்கான தகுதிகள்"}]}
    found = heading_findings("1ti", headings, {str(c): ["1"] for c in range(1, 6)})
    assert rules(found) == [("heading.marker-mixed", "5", "1", "உதவிக்காரர்களுக்கான தகுதிகள்")]
    assert "\\s (4)" in found[0]["message"]


def test_one_marker_throughout_is_not_mixed():
    headings = {str(c): {"1": [{"tag": "s1", "text": "தலைப்பு"}]} for c in range(1, 4)}
    assert heading_findings("jol", headings, {str(c): ["1"] for c in range(1, 4)}) == []


def test_a_chapter_without_a_heading_in_a_book_that_heads_its_chapters():
    chapters = {str(c): ["1", "2"] for c in range(1, 7)}
    headings = {str(c): {"1": [{"tag": "s", "text": "தலைப்பு"}]} for c in range(1, 6)}
    found = heading_findings("rut", headings, chapters)
    assert rules(found) == [("heading.missing", "6", "1", "")]
    assert found[0]["category"] == "consistency" and found[0]["contextText"] == ""


def test_a_book_that_rarely_heads_its_chapters_has_no_missing_heading():
    chapters = {str(c): ["1"] for c in range(1, 7)}
    headings = {"1": {"1": [{"tag": "s", "text": "தலைப்பு"}]}}
    assert heading_findings("psa", headings, chapters) == []


def test_the_pass_reads_headings_json_for_every_pack(tmp_path):
    project = project_at(tmp_path, verses={"1": "ஆதியிலே தேவன் வானத்தையும் பூமியையும் படைத்தார்."}, book="gen")
    (project.book_dir / "1.headings.json").write_text(
        json.dumps({"1": [{"tag": "s", "text": "உலகத்தின் படைப்பு."}]}, ensure_ascii=False), encoding="utf-8")
    manager = LanguageQaManager(debounce=0, yield_seconds=0)
    manager.bind(project)
    try:
        result = wait(manager)
    finally:
        manager.unbind()
    found = [f for f in result["findings"] if f["rule"] == "heading.trailing-punctuation"]
    assert [(f["chapter"], f["verse"], f["context"], f["originalText"]) for f in found] == [("1", "1", "heading", ".")]
