"""#502: the rules of the window review that need no project.

Window formation, the content-keyed evidence ids, the split of one answer into
verses, and the usage shares. The session itself, against an imported project,
is in `tests/service/test_ai_review_window_jobs.py`.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from tc_ai_bridge.ai_client import AIError, AIUsage, REVIEW_INSTRUCTIONS_STATIC
from tc_ai_bridge.ai_review_windows import (
    CHAPTER_MAX_CHECKS, EvidenceIds, WINDOW_MAX_CHECKS, WINDOW_MAX_INPUT_CHARS, WINDOW_RULES, WindowSettings,
    apportion_usage, heading_between, plan_windows, split_window_answer, verse_number, window_privacy_manifest,
    window_review_instructions, window_review_schema, window_timeout,
)

HINDI = SimpleNamespace(source_name="Hebrew", target_name="Hindi", qa_categories=["spelling"],
                        prompt_guidance="Hindi guidance.")


def test_the_defaults_are_the_single_verse_run():
    assert WindowSettings() == WindowSettings(1, False, False)
    assert WindowSettings().windowed is False
    assert WindowSettings.from_settings(None).windowed is False
    assert WindowSettings.from_settings({"versesPerRequest": 1}).windowed is False
    assert WindowSettings.from_settings({"versesPerRequest": 4}).windowed is True
    assert WindowSettings.from_settings({"wholeChapter": True}).windowed is True
    assert WindowSettings.from_settings({"chapterContext": True}).windowed is True
    # Out-of-range sizes are clamped, never trusted.
    assert WindowSettings.from_settings({"versesPerRequest": 40}).verses_per_request == 6
    assert WindowSettings.from_settings({"versesPerRequest": 0}).verses_per_request == 1
    assert WindowSettings.from_settings({"versesPerRequest": "x"}).verses_per_request == 1
    assert WindowSettings(4).max_verses == 4 and WindowSettings(4).max_checks == WINDOW_MAX_CHECKS
    whole = WindowSettings(1, whole_chapter=True)
    assert whole.max_verses is None and whole.max_checks == CHAPTER_MAX_CHECKS


def test_timeout_grows_with_the_window_and_is_never_below_the_clients():
    assert window_timeout(240, 1) == 240          # 130 s budget, the client's 240 stands
    assert window_timeout(240, 3) == 240          # 210
    assert window_timeout(240, 4) == 250          # #474: a 4-verse window gets 250 s
    assert window_timeout(240, 6) == 300          # the cap
    assert window_timeout(240, 30) == 300
    assert window_timeout(240, 30, whole_chapter=True) == 900
    assert window_timeout(600, 4) == 600


def test_verse_labels_and_headings():
    assert verse_number("3") == 3 and verse_number("3-4") == 3 and verse_number("3a") == 3
    assert verse_number("front") is None
    assert heading_between("3", "4", ["4"]) is True
    assert heading_between("3", "4", ["5"]) is False
    # A job that runs only stale verses 3 and 7: a heading at 5 lies between them.
    assert heading_between("3", "7", ["5"]) is True
    assert heading_between("3-4", "5", ["5"]) is True
    assert heading_between("1", "2", []) is False


def test_windows_are_contiguous_and_never_cross_a_heading():
    verses = [str(n) for n in range(1, 11)]
    four = WindowSettings(4)
    assert plan_windows(verses, settings=four) == [["1", "2", "3", "4"], ["5", "6", "7", "8"], ["9", "10"]]
    assert plan_windows(verses, settings=four, heading_verses=["1", "6"]) == [
        ["1", "2", "3", "4"], ["5"], ["6", "7", "8", "9"], ["10"],
    ]
    # Three stale verses of a chapter are one window of three.
    assert plan_windows(["2", "9", "17"], settings=four) == [["2", "9", "17"]]
    assert plan_windows([], settings=four) == []
    assert plan_windows(verses, settings=WindowSettings(1)) == [[v] for v in verses]


def test_the_check_and_size_caps_close_a_window_early():
    verses = ["1", "2", "3", "4"]
    four = WindowSettings(4)
    assert plan_windows(verses, settings=four, checks={"1": 10, "2": 10, "3": 10, "4": 2}) == [
        ["1", "2"], ["3", "4"],
    ]
    big = WINDOW_MAX_INPUT_CHARS
    assert plan_windows(verses, settings=four, chars={"1": big // 2, "2": big // 2, "3": 1, "4": 1}) == [
        ["1", "2"], ["3", "4"],
    ]
    # A verse that alone exceeds a cap goes as a window of one.
    assert plan_windows(verses, settings=four, checks={"2": WINDOW_MAX_CHECKS + 5}) == [["1"], ["2"], ["3", "4"]]


def test_whole_chapter_is_one_request_under_the_caps_and_cut_at_headings_over_them():
    verses = [str(n) for n in range(1, 13)]
    whole = WindowSettings(1, whole_chapter=True)
    small = {v: 3 for v in verses}
    assert plan_windows(verses, settings=whole, checks=small, heading_verses=["1", "5", "9"]) == [verses]
    # 12 verses of 20 checks: 240 checks do not fit one request. The first
    # window is already half full when it reaches the heading at 5, so it is
    # cut there, not mid-section at the cap.
    heavy = {v: 20 for v in verses}
    assert plan_windows(verses, settings=whole, checks=heavy, heading_verses=["1", "5", "9"]) == [
        ["1", "2", "3", "4"], ["5", "6", "7", "8"], ["9", "10", "11", "12"],
    ]
    # No headings: the cap alone cuts.
    assert plan_windows(verses, settings=whole, checks=heavy) == [
        ["1", "2", "3", "4", "5"], ["6", "7", "8", "9", "10"], ["11", "12"],
    ]


def test_an_article_is_one_catalog_entry_whichever_verse_cites_it():
    ids = EvidenceIds()
    god = {"kind": "translationWords", "title": "Translation Word: god", "content": "article", "identifier": "god"}
    cut = dict(god, content="artic\n[…truncated…]")
    note = {"kind": "translationNote", "title": "Translation Note: figs-metaphor", "content": "n1",
            "identifier": "figs-metaphor"}
    one, two = ids.for_verse("1", "1"), ids.for_verse("1", "2")
    assert one(1, god) == "tw:god" and two(1, god) == "tw:god"
    # The same id never names two texts: an article cut by one verse's evidence
    # budget is a different item.
    cut_id = two(2, cut)
    assert cut_id.startswith("tw:god#") and two(3, cut) == cut_id
    assert one(2, note) == "tn:1:1:figs-metaphor"
    assert two(4, note) == "tn:1:2:figs-metaphor"
    other_note = dict(note, content="n2")
    assert one(3, other_note).startswith("tn:1:1:figs-metaphor#")
    assert one(4, {"kind": "originalQuote", "content": "x", "identifier": ""}) == "quote:1:1:4"
    assert ids.full["tw:god"] is god and ids.full[cut_id] is cut


def _prepared(verse: str):
    return SimpleNamespace(verse=verse, reference=f"gen 1:{verse}")


def _row(reference: str, check_id: str, ids: list[str]):
    return {"reference": reference, "check_id": check_id, "selection_ids": ids, "verdict": "pass"}


def test_one_answer_is_split_by_verse_with_ids_back_in_each_verses_own():
    window = [_prepared("3"), _prepared("4")]
    answer = {
        "summaries": [{"reference": "GEN 1:3", "summary": "three"}, {"reference": "gen 1:4", "summary": "four"}],
        "check_reviews": [
            _row("gen 1:3", "a", ["3|T001", "3|T002"]),
            _row("GEN  1:4", "b", ["4|T001"]),
            _row("gen 1:4", "c", ["3|T009"]),  # another verse's id: stays unknown to verse 4
        ],
        "qa_issues": [{"reference": "gen 1:4", "title": "t"}],
    }
    rows = split_window_answer(answer, window)
    assert rows["3"]["summary"] == "three" and rows["4"]["summary"] == "four"
    assert [r["selection_ids"] for r in rows["3"]["check_reviews"]] == [["T001", "T002"]]
    assert [r["selection_ids"] for r in rows["4"]["check_reviews"]] == [["T001"], ["3|T009"]]
    assert rows["4"]["qa_issues"] == [{"title": "t"}] and rows["3"]["qa_issues"] == []
    assert all("reference" not in r for r in rows["3"]["check_reviews"])
    # A verse the model skipped has no rows; the parser turns its checks into review rows.
    assert split_window_answer({"check_reviews": [], "qa_issues": [], "summaries": []}, window)["3"] == {
        "check_reviews": [], "qa_issues": [], "summary": "",
    }


def test_a_row_for_a_verse_outside_the_window_makes_the_answer_unusable():
    with pytest.raises(AIError, match="not in the request"):
        split_window_answer({"check_reviews": [_row("gen 1:9", "a", [])], "qa_issues": []}, [_prepared("3")])
    with pytest.raises(AIError):
        split_window_answer({"check_reviews": "nope", "qa_issues": []}, [_prepared("3")])


def test_usage_shares_sum_to_the_requests_own():
    usage = AIUsage(input_tokens=1001, output_tokens=333, total_tokens=1334, cached_input_tokens=100, calls=1)
    shares = apportion_usage(usage, 0.9, [3000, 1000, 2000])
    assert sum(u.input_tokens for u, _ in shares) == 1001
    assert sum(u.output_tokens for u, _ in shares) == 333
    assert sum(u.total_tokens for u, _ in shares) == 1334
    assert sum(u.cached_input_tokens for u, _ in shares) == 100
    assert sum(c for _, c in shares) == pytest.approx(0.9)
    assert shares[0][0].input_tokens == 500 and shares[1][0].input_tokens == 166
    assert all(u.calls == 1 for u, _ in shares)  # the request is one call for each verse in it
    # No weights to go by: equal shares.
    equal = apportion_usage(usage, 0.9, [0, 0])
    assert equal[0][0].input_tokens == 500 and equal[1][0].input_tokens == 501


def test_window_schema_names_the_verse_on_every_row_and_pins_the_total():
    schema = window_review_schema(11, count_in_input=False)
    rows = schema["properties"]["check_reviews"]
    assert rows["minItems"] == 11 and rows["maxItems"] == 11
    assert rows["items"]["required"][0] == "reference"
    assert "reference" in schema["properties"]["qa_issues"]["items"]["required"]
    assert schema["required"] == ["summaries", "check_reviews", "qa_issues"]
    free = window_review_schema(11, count_in_input=True)["properties"]["check_reviews"]
    assert "minItems" not in free and "maxItems" not in free
    assert window_review_schema(11, True) == window_review_schema(4, True)


def test_window_instructions_keep_the_static_block_first_and_can_carry_no_number():
    a = window_review_instructions(HINDI, 11, 4, count_in_input=False)
    assert a.startswith(REVIEW_INSTRUCTIONS_STATIC + WINDOW_RULES)
    assert "11 input checks across 4 verse(s) require exactly 11 check_reviews rows" in a
    assert "Hindi guidance." in a and "Hindi" not in WINDOW_RULES
    b = window_review_instructions(HINDI, 11, 4, count_in_input=True)
    assert b == window_review_instructions(HINDI, 30, 6, count_in_input=True)
    assert "expected_check_reviews" in b and "11 input checks" not in b


def test_window_manifest_answers_for_the_nested_verses():
    manifest = window_privacy_manifest("gen 1:3-4", {
        "language_context": {}, "project_reviewer_decisions": [], "evidence_catalog": {"tw:god": {}},
        "verses": [
            {"reference": "gen 1:3", "target_verse": "x", "source_topWords": [{"id": "3|H001"}],
             "translationCore_checks": [{"approved_project_renderings": [{"selections": ["a"], "count": 2}]}]},
            {"reference": "gen 1:4", "target_verse": "y", "source_topWords": [],
             "translationCore_checks": [{"approved_project_renderings": [{"selections": ["a"], "reviewer": "r"}]}]},
        ],
    })
    assert manifest["containsScripture"] and manifest["containsOriginalLanguage"] and manifest["containsTranslationHelps"]
    assert manifest["containsReviewerIdentity"] is True  # judged on the nested records
    assert manifest["verses"] == ["gen 1:3", "gen 1:4"]
    assert {"verses", "target_verse", "evidence_catalog"} <= set(manifest["sentFields"])
