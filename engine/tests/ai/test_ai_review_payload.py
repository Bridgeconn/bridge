"""#500: what the review request carries, as distinct from what Bridge keeps.

Unit tests of `ai_review_payload`. The request as a whole, and what is still
stored with the review, is pinned in
`tests/service/test_ai_review_request_shape.py`.
"""
from __future__ import annotations

from types import SimpleNamespace

from tc_ai_bridge.ai_client import project_term_rendering, review_instructions
from tc_ai_bridge.ai_review_payload import (
    RENDERING_GROUP_FIELDS, ReviewPayloadOptions, approved_rendering_groups, drop_markdown_sections,
    sent_check_evidence, sent_evidence_item, sent_language_context, sent_mapping_states, sent_token,
    TA_DROPPED_SECTION_PREFIXES, TW_DROPPED_SECTIONS,
)
from tc_ai_bridge.security import contains_reviewer_identity

DEFAULT = ReviewPayloadOptions()
LEAN = ReviewPayloadOptions.from_settings({"leanEvidence": True})

TW_ARTICLE = """# God

## Definition:

In the Bible, the term "God" refers to the eternal being.

## Translation Suggestions:

* Other ways to translate "God" could include "Deity".

## Bible References:

* [1 John 1:7](rc://en/tn/help/1jn/01/07)

## Examples from the Bible stories:

* **[1:1](rc://en/tn/help/obs/01/01)** God created the universe.

## Word Data:

* Strong's: H0136, H0430"""

TA_ARTICLE = """### Description

A quote margin says who spoke.

#### Reasons This Is a Translation Issue

* Languages differ.

### Examples From the Bible

#### Quote margin before the quote

> Then Zechariah said (Luke 1:18)

### Translation Strategies

(1) Decide where to put the quote margin.

### Examples of Translation Strategies Applied

(1) Decide where to put the quote margin.

> "Therefore, those who can," he said"""


def test_every_switch_is_off_by_default():
    assert DEFAULT == ReviewPayloadOptions(False, False, False, False)
    assert ReviewPayloadOptions.from_settings(None) == DEFAULT
    assert ReviewPayloadOptions.from_settings({"leanEvidence": "yes"}) != DEFAULT  # truthy, not validated here
    assert LEAN.lean_tw_articles and LEAN.lean_twl_occurrences and LEAN.lean_ta_examples
    assert not LEAN.count_in_input


def test_a_dropped_section_takes_its_subsections_and_nothing_else():
    lean = drop_markdown_sections(TA_ARTICLE, prefixes=TA_DROPPED_SECTION_PREFIXES)
    assert "### Description" in lean and "Reasons This Is a Translation Issue" in lean
    assert "### Translation Strategies\n" in lean and "(1) Decide where to put the quote margin." in lean
    assert "Examples From the Bible" not in lean and "Zechariah" not in lean
    assert "Quote margin before the quote" not in lean  # the subsection went with its parent
    assert "Examples of Translation Strategies Applied" not in lean and "he said" not in lean

    lean_tw = drop_markdown_sections(TW_ARTICLE, exact=TW_DROPPED_SECTIONS)
    assert "## Definition:" in lean_tw and "## Translation Suggestions:" in lean_tw
    assert "Deity" in lean_tw
    for gone in ("Bible References", "Examples from the Bible stories", "Word Data", "H0430"):
        assert gone not in lean_tw
    # Nothing matched: the text is returned as it was.
    assert drop_markdown_sections("plain text\nmore", exact=TW_DROPPED_SECTIONS) == "plain text\nmore"


def test_an_evidence_item_is_sent_as_kind_title_and_content_only():
    full = {
        "kind": "translationWords", "title": "Translation Word: god", "content": TW_ARTICLE,
        "source_path": "C:\\Users\\someone\\AppData\\Local\\Bridge\\data\\resources\\en\\god.md",
        "version": "v90", "provider": "unfoldingWord", "identifier": "god", "authoritative": True,
        "sha256": "ab" * 32,
    }
    sent = sent_evidence_item(full, DEFAULT)
    assert sent == {"kind": "translationWords", "title": "Translation Word: god", "content": TW_ARTICLE}
    # The article is whole unless the switch is on.
    lean = sent_evidence_item(full, LEAN)
    assert "Word Data" not in lean["content"] and "## Definition:" in lean["content"]
    assert set(lean) == {"kind", "title", "content"}


def test_restated_evidence_is_left_out_but_a_check_keeps_something_to_cite():
    quote = ("E001", {"kind": "originalQuote", "content": "אֱלֹהִים"})
    note = ("E002", {"kind": "translationNote", "content": "A note."})
    article = ("E003", {"kind": "translationAcademy", "content": "An article."})
    occurrences = ("E004", {"kind": "translationWordsLinks", "content": "1:1 — x"})
    word = ("E005", {"kind": "translationWords", "content": "A word."})

    assert sent_check_evidence([quote, note, article], DEFAULT) == ["E003"]
    assert sent_check_evidence([quote, word, occurrences], DEFAULT) == ["E005", "E004"]
    assert sent_check_evidence([quote, word, occurrences], LEAN) == ["E005"]
    # A note whose Translation Academy article is not installed: the note stays
    # citable, because a review that cites nothing is never applied automatically.
    assert sent_check_evidence([quote, note], DEFAULT) == ["E002"]
    assert sent_check_evidence([quote], DEFAULT) == ["E001"]
    assert sent_check_evidence([], DEFAULT) == []


def test_renderings_are_grouped_by_what_was_selected_most_used_first():
    rows = [
        project_term_rendering({"reference": f"1:{n}", "source_quote": "אֱלֹהִים" if n % 2 else "אֱלֹהִ֑ים",
                                "selections": [{"text": "परमेश्वर", "occurrence": 1, "occurrences": 1}]})
        for n in range(1, 29)
    ]
    rows.insert(3, project_term_rendering({"reference": "2:4", "source_quote": "אֱלֹהִים", "selections": ["ईश्वर"]}))
    rows.append(project_term_rendering({"reference": "3:1", "source_quote": "אֱלֹהִים", "selections": [],
                                        "nothingToSelect": True}))
    groups = approved_rendering_groups(rows)
    assert [g["count"] for g in groups] == [28, 1, 1]
    assert groups[0] == {
        "selections": ["परमेश्वर"], "count": 28, "source_quotes": ["אֱלֹהִים", "אֱלֹהִ֑ים"],
        "nothingToSelect": False, "invalidated": False,
    }
    assert groups[1]["selections"] == ["ईश्वर"]  # ties keep first-seen order
    assert groups[2]["nothingToSelect"] is True
    for group in groups:
        assert tuple(group) == RENDERING_GROUP_FIELDS
    assert approved_rendering_groups(rows, limit=1) == groups[:1]
    assert approved_rendering_groups([]) == []
    # The grouped shape carries no reviewer identity as far as the manifest judges it.
    payload = {"translationCore_checks": [{"approved_project_renderings": groups}]}
    assert contains_reviewer_identity(payload) is False
    assert contains_reviewer_identity(
        {"translationCore_checks": [{"approved_project_renderings": [dict(groups[0], reviewer="x")]}]}
    ) is True


def test_a_word_carries_its_occurrence_only_when_it_repeats():
    once = SimpleNamespace(word="उजियाला", occurrence=1, occurrences=1, strong="", lemma="", morph="")
    twice = SimpleNamespace(word="हो", occurrence=2, occurrences=2, strong="H1961", lemma="הָיָה", morph="He,Vqj3ms")
    assert sent_token("b1", once, source=False) == {"id": "b1", "word": "उजियाला"}
    assert sent_token("b2", twice, source=False) == {"id": "b2", "word": "हो", "occurrence": 2, "occurrences": 2}
    assert sent_token("t1", twice, source=True) == {
        "id": "t1", "word": "हो", "occurrence": 2, "occurrences": 2,
        "strong": "H1961", "lemma": "הָיָה", "morph": "He,Vqj3ms",
    }


def test_language_context_is_the_pair_and_the_categories():
    language = SimpleNamespace(
        source_name="Hebrew", target_name="Hindi", qa_categories=("spelling", "punctuation"),
        prompt_guidance="Guidance.", target_font="Noto Sans Devanagari", detection_basis="manifest",
    )
    assert sent_language_context(language) == {
        "source": "Hebrew", "target": "Hindi", "qa_categories": ["spelling", "punctuation"],
    }


def test_mapping_states_carry_what_only_the_mapping_row_held():
    anchor = {"checkId": "mq1c", "tool": "translationNotes", "groupId": "other",
              "sourceQuote": "x", "state": "source_anchor_unresolved", "detail": "not found"}
    located = {"sourceUnitId": "translationWords:abcd", "checkId": "abcd", "tool": "translationWords",
               "groupId": "god", "state": "found_this_verse", "selectable": True,
               "targetSpans": [{"reference": "GEN 1:3", "quote": "परमेश्वर", "start": 3, "end": 11}],
               "meaningStatus": "PRESERVED", "relationships": ["SAME_VERSE"]}
    pending = {"sourceUnitId": "translationNotes:efgh", "checkId": "efgh", "tool": "translationNotes",
               "groupId": "figs-metaphor", "state": "needs_passage_review", "selectable": False,
               "targetSpans": [], "meaningStatus": "UNCERTAIN", "relationships": ["UNCERTAIN"], "detail": "d"}
    pack = {
        "mappings": [{
            "source_unit_id": "translationWords:abcd", "source_token_ids": ["GEN.1.3.T002"],
            "source_reference": "GEN 1:3", "target_spans": located["targetSpans"],
            "relationships": ["SAME_VERSE"], "meaning_status": "PRESERVED", "confidence": 0.99,
            "evidence": {"source": "אֱלֹהִים", "target": "परमेश्वर", "explanation": "The usual rendering."},
        }],
        "checkStates": [anchor, located, pending],
        "unresolved": [anchor, {"source_unit_id": "translationNotes:efgh", "reason": "AMBIGUOUS", "detail": "d"}],
    }
    states, unresolved = sent_mapping_states(pack)
    assert states[0] == anchor
    assert states[1] == {**located, "confidence": 0.99, "explanation": "The usual rendering."}
    assert states[2] == pending
    # The anchor row was in both lists verbatim; the mapper's own row is not a
    # check state and stays, with its reason.
    assert unresolved == [{"source_unit_id": "translationNotes:efgh", "reason": "AMBIGUOUS", "detail": "d"}]
    # The pack itself is what is stored with the review: untouched.
    assert "confidence" not in pack["checkStates"][1] and len(pack["unresolved"]) == 2
    assert sent_mapping_states(None) == ([], [])


def test_count_in_input_makes_the_instructions_the_same_for_every_verse():
    hindi = SimpleNamespace(source_name="Hebrew", target_name="Hindi", qa_categories=["spelling"],
                            prompt_guidance="Hindi guidance.")
    assert review_instructions(hindi, 8) != review_instructions(hindi, 3)
    assert review_instructions(hindi, 8, True) == review_instructions(hindi, 3, True)
    assert "expected_check_reviews" in review_instructions(hindi, 8, True)
    assert "8 input checks" not in review_instructions(hindi, 8, True)
    # Default is the sentence the provider has always been sent.
    assert "8 input checks require exactly 8 result rows" in review_instructions(hindi, 8)
