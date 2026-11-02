"""#427: the deterministic parser for QA proposals in Paratext notes. Every
note here is synthetic; nothing is copied from a real project."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tc_ai_bridge import paratext_proposals as pp

# Synthetic Tamil wordings with vowel signs and viramas (combining marks).
TA_A = "இல்லை"
TA_B = "இல்லைஇல்லை"
TA_SENTENCE = "அவர் வந்தார்கள்."


def note(pass_: str, topic: str, category: str, *, original: str = "", suggested: str = "", reason: str = "",
         location: str = "", reviewer: str | None = "No", confidence: str = "0.91", severity: str = "medium",
         extra: str = "") -> str:
    lines = [f"[AI-QA {pass_}] {topic} — {category}"]
    if original or original == "":
        lines.append(f"Original: {original}")
    lines.append(f"Suggested: {suggested}")
    if reason:
        lines.append(f"Reason: {reason}")
    if location:
        lines.append(f"Location: {location}")
    if extra:
        lines.append(extra)
    meta = [f"Confidence: {confidence}"]
    if reviewer is not None:
        meta.append(f"Reviewer decision needed: {reviewer}")
    meta.append(f"Severity: {severity}")
    lines.append(" · ".join(meta))
    return "\n".join(lines)


def one(text: str, **kw) -> pp.Proposal:
    found = pp.parse_comment(text, thread_id="T1", author="QA", date="2026-10-20T08:00:00.0000000+05:30", **kw)
    assert len(found) == 1, found
    return found[0]


# -- the sixteen categories --------------------------------------------------

LITERAL = ["Sandhi / word-joining", "Punctuation", "Grammar", "Name consistency", "Confirmed typo",
           "Plural agreement", "Case/object marker"]
REVIEW_ONLY = ["Source comparison", "Textual-basis review", "Footnote / cross-reference", "Possible typo",
               "Possible missed source word", "Reviewer decision", "Theological consistency", "Addition not in source"]


@pytest.mark.parametrize("category", LITERAL)
def test_a_plain_replacement_in_a_literal_category_routes_literal(category):
    p = one(note("R2", "Check", category, original=TA_A, suggested=TA_B, reason="Join the words."))
    assert p.category == category and p.categoryKnown
    assert p.route == pp.ROUTE_LITERAL and p.operation == pp.OP_REPLACE and p.region == pp.REGION_BODY
    assert p.original == TA_A and p.suggested == TA_B      # verbatim: no combining mark lost
    assert p.reason == "Join the words." and p.confidence == "0.91" and p.severity == "medium"
    assert p.reviewerDecision is False and p.anchorWarning is False and p.outstanding
    assert p.pass_ == "R2" and p.topic == "Check"


@pytest.mark.parametrize("category", REVIEW_ONLY)
def test_an_uncertain_category_is_review_even_with_a_plain_replacement(category):
    p = one(note("P3", "Check", category, original=TA_A, suggested=TA_B))
    assert p.categoryKnown and p.route == pp.ROUTE_REVIEW and p.operation == pp.OP_REPLACE


def test_usfm_marker_category_is_structural_and_review_only():
    p = one(note("R2", "Markers", "USFM marker", original="\\s Heading", suggested="\\s1 Heading"))
    assert p.route == pp.ROUTE_STRUCTURE and p.region == pp.REGION_STRUCTURE
    assert p.operation == pp.OP_MARKER_RENAME
    assert p.structural == {"fromMarker": "s", "toMarker": "s1", "label": "Heading"}


def test_every_category_is_recognised_case_and_space_insensitively():
    for category in pp.CATEGORIES:
        loose = category.upper().replace(" / ", "/")
        assert pp.canonical_category(loose) == (category, True)
    assert pp.canonical_category("Something new") == ("Something new", False)
    assert len(pp.CATEGORIES) == 16


def test_an_unknown_category_is_kept_as_written_and_routes_review():
    p = one(note("R2", "Check", "Tone", original=TA_A, suggested=TA_B))
    assert p.category == "Tone" and not p.categoryKnown and p.route == pp.ROUTE_REVIEW
    assert any("Unknown category" in d for d in p.diagnostics)


# -- what the Suggested field is -----------------------------------------------

def test_a_reviewer_flag_or_a_missing_flag_downgrades_literal_to_review():
    flagged = one(note("R2", "Check", "Grammar", original=TA_A, suggested=TA_B, reviewer="Yes"))
    assert flagged.reviewerDecision and flagged.route == pp.ROUTE_REVIEW
    missing = one(note("R2", "Check", "Grammar", original=TA_A, suggested=TA_B, reviewer=None))
    assert missing.reviewerDecision and missing.route == pp.ROUTE_REVIEW
    assert any("Reviewer decision needed" in d for d in missing.diagnostics)


def test_an_anchor_warning_in_location_downgrades_to_review():
    p = one(note("R2", "Check", "Grammar", original=TA_A, suggested=TA_B,
                 location="Original not found verbatim; anchored on the start of the verse"))
    assert p.anchorWarning and p.route == pp.ROUTE_REVIEW


def test_alternatives_are_split_and_never_a_literal_string():
    p = one(note("R2", "Check", "Grammar", original=TA_A, suggested=f"{TA_B} / {TA_SENTENCE}"))
    assert p.operation == pp.OP_ALTERNATIVES and p.route == pp.ROUTE_REVIEW
    assert p.alternatives == [TA_B, TA_SENTENCE]
    piped = one(note("R2", "Check", "Grammar", original=TA_A, suggested=f"{TA_B} | {TA_A}"))
    assert piped.alternatives == [TA_B, TA_A]


def test_a_slash_inside_a_word_is_not_an_alternatives_separator():
    p = one(note("R2", "Check", "Punctuation", original="3/4", suggested="3⁄4"))
    assert p.operation == pp.OP_REPLACE and p.alternatives == []


@pytest.mark.parametrize("suggested", ["(no change)", "No change proposed", "retain as is", "Keep the current wording", "unchanged"])
def test_no_change_wordings_have_no_operation(suggested):
    p = one(note("R2", "Check", "Source comparison", original=TA_A, suggested=suggested))
    assert p.route == pp.ROUTE_NO_CHANGE and p.operation == pp.OP_NO_CHANGE and not p.outstanding


def test_identical_original_and_suggested_is_no_change():
    p = one(note("R2", "Check", "Grammar", original=TA_A, suggested=TA_A))
    assert p.route == pp.ROUTE_NO_CHANGE and "identical" in p.diagnostics[0]


@pytest.mark.parametrize("suggested", [
    "Consider the source reading here",
    f"Use {TA_B} (see the Greek)",
    f"{TA_B}…",
    "Move the footnote to the end of the verse",
    "Check with the team",
])
def test_prose_in_suggested_is_an_instruction_not_a_replacement(suggested):
    p = one(note("R2", "Check", "Grammar", original=TA_A, suggested=suggested))
    assert p.operation == pp.OP_INSTRUCTION and p.route == pp.ROUTE_REVIEW


def test_latin_prose_against_a_tamil_original_is_an_instruction_but_latin_against_latin_is_not():
    tamil = one(note("R2", "Check", "Grammar", original=TA_A, suggested="the word order is odd"))
    assert tamil.operation == pp.OP_INSTRUCTION
    english = one(note("R2", "Check", "Grammar", original="recieve", suggested="receive"))
    assert english.operation == pp.OP_REPLACE and english.route == pp.ROUTE_LITERAL


@pytest.mark.parametrize("suggested", ["(delete)", "remove", "Delete this", "omit the word"])
def test_a_deletion_is_an_explicit_operation_that_always_needs_confirmation(suggested):
    p = one(note("R2", "Check", "Addition not in source", original=TA_A, suggested=suggested))
    assert p.operation == pp.OP_DELETE and p.route == pp.ROUTE_REVIEW


def test_an_insertion_without_an_original_needs_its_place_chosen():
    p = one(note("R2", "Check", "Possible missed source word", original="", suggested=TA_B))
    assert p.operation == pp.OP_INSERT and p.route == pp.ROUTE_REVIEW
    assert any("insertion" in d for d in p.diagnostics)


def test_a_missing_suggested_is_review_with_a_diagnostic():
    p = one(note("R2", "Check", "Grammar", original=TA_A, suggested="", reason="Look again."))
    assert p.route == pp.ROUTE_REVIEW and p.operation == pp.OP_NONE
    assert "No Suggested text." in p.diagnostics


def test_a_backslash_anywhere_or_a_structural_topic_is_structural():
    marker = one(note("R2", "Check", "Grammar", original=f"\\f + {TA_A}\\f*", suggested=f"\\f + {TA_B}\\f*"))
    assert marker.route == pp.ROUTE_STRUCTURE and marker.operation == pp.OP_STRUCTURAL
    bridge = one(note("R2", "Verse bridge 3-4", "Grammar", original=TA_A, suggested=TA_B))
    assert bridge.route == pp.ROUTE_STRUCTURE


# -- regions -------------------------------------------------------------------

@pytest.mark.parametrize("topic, location, region", [
    ("Introduction", "", pp.REGION_INTRODUCTION),
    ("Check", "Book introduction, paragraph 2", pp.REGION_INTRODUCTION),
    ("Section heading", "", pp.REGION_HEADING),
    ("Check", "chapter label", pp.REGION_HEADING),
    ("Check", "footnote 2 on verse 4", pp.REGION_FOOTNOTE),
    ("Cross-reference", "", pp.REGION_CROSS_REFERENCE),
    ("Check", "", pp.REGION_BODY),
])
def test_the_region_comes_from_topic_and_location(topic, location, region):
    p = one(note("R2", topic, "Punctuation", original=TA_A, suggested=TA_B, location=location))
    assert p.region == region
    # Only the verse body is ever a literal candidate from topic alone; the
    # others still parse, but a footnote edit must never fall into the body.
    assert p.route in (pp.ROUTE_LITERAL, pp.ROUTE_REVIEW)


# -- rich text, several proposals, legacy notes, unreadable notes --------------

def test_multiline_fields_keep_their_lines_and_stop_at_the_next_label():
    text = note("R2", "Check", "Grammar", original=TA_A, suggested=TA_B,
                reason="First line.\nSecond line with Original: not a label mid-line.")
    p = one(text)
    assert p.reason == "First line.\nSecond line with Original: not a label mid-line."
    assert p.original == TA_A and p.suggested == TA_B


def test_two_blocks_in_one_comment_are_two_proposals_with_distinct_ids():
    text = note("R2", "Check", "Grammar", original=TA_A, suggested=TA_B) + "\n\n" + \
        note("P3", "Check", "Punctuation", original=".", suggested="،")
    found = pp.parse_comment(text, thread_id="T1", author="QA", date="d")
    assert [p.block for p in found] == [0, 1]
    assert [p.pass_ for p in found] == ["R2", "P3"]
    assert found[0].proposalId != found[1].proposalId


def test_a_discussion_comment_has_no_proposal():
    assert pp.parse_comment("Looks fine to me, thanks.") == []
    assert pp.parse_comment("") == []


def test_legacy_labels_are_read_as_legacy_and_changed_to_is_historical():
    sug = one("sug: " + TA_B + "\nbecause of sandhi")
    assert sug.route == pp.ROUTE_LEGACY and sug.suggested == TA_B and not sug.historical and not sug.outstanding
    suggestion = one(f"Original: {TA_A}\nSuggestion: {TA_B}")
    assert suggestion.route == pp.ROUTE_LEGACY and suggestion.original == TA_A
    changed = one("Changed to: " + TA_B)
    assert changed.route == pp.ROUTE_LEGACY and changed.historical
    assert "already made" in changed.diagnostics[0]


def test_a_broken_header_is_unreadable_with_a_diagnostic_and_never_raises():
    p = one("[AI-QA R2] Grammar without a separator\nOriginal: x\nSuggested: y")
    assert p.route == pp.ROUTE_UNREADABLE and "separator" in p.diagnostics[0]
    inline = one("see [AI-QA R2 marker inside prose] and nothing else")
    assert inline.route == pp.ROUTE_UNREADABLE
    empty = one("[AI-QA R2] Check — Grammar\nConfidence: 0.5")
    assert empty.route == pp.ROUTE_UNREADABLE and "none of Original" in empty.diagnostics[0]
    assert empty.outstanding      # a person still has to look


def test_duplicate_fields_downgrade_to_review_and_are_named():
    text = note("R2", "Check", "Grammar", original=TA_A, suggested=TA_B, extra=f"Suggested: {TA_A}")
    p = one(text)
    assert p.route == pp.ROUTE_REVIEW and p.suggested == TA_B
    assert any('"Suggested" appears more than once' in d for d in p.diagnostics)


def test_a_hyphen_separated_header_and_a_hyphenated_topic_both_parse():
    p = one("[AI-QA R2] Cross-check of names - Name consistency\nOriginal: a\nSuggested: b\n"
            "Confidence: 0.9 · Reviewer decision needed: No")
    assert p.topic == "Cross-check of names" and p.category == "Name consistency"


# -- identity ------------------------------------------------------------------

def test_identity_survives_line_breaks_and_nfc_but_not_a_content_change():
    base = note("R2", "Check", "Grammar", original=TA_A, suggested=TA_B)
    a = one(base)
    b = one(base.replace("\n", "\r\n"))
    c = one(base.replace(TA_B, TA_SENTENCE))
    assert a.proposalId == b.proposalId != c.proposalId
    # A different comment (author or date) is a different proposal.
    d = pp.parse_comment(base, thread_id="T1", author="Other", date="d2")[0]
    assert d.proposalId != a.proposalId


def test_thread_proposals_and_summary_walk_every_comment():
    comments = [
        SimpleNamespace(contents=note("R2", "Check", "Grammar", original=TA_A, suggested=TA_B), user="QA", date="d1"),
        SimpleNamespace(contents="Agreed.", user="Translator", date="d2"),
        SimpleNamespace(contents="Changed to: " + TA_B, user="Translator", date="d3"),
        SimpleNamespace(contents="[AI-QA R2] broken", user="QA", date="d4"),
    ]
    found = pp.thread_proposals("T9", comments)
    assert [(p.commentIndex, p.route) for p in found] == [
        (0, pp.ROUTE_LITERAL), (2, pp.ROUTE_LEGACY), (3, pp.ROUTE_UNREADABLE)]
    summary = pp.summarize(found)
    assert summary["total"] == 3 and summary["outstanding"] == 2 and summary["unreadable"] == 1
    assert summary["byRoute"][pp.ROUTE_LITERAL] == 1 and summary["byRoute"][pp.ROUTE_LEGACY] == 1
    wire = found[0].to_json()
    assert wire["pass"] == "R2" and wire["outstanding"] is True and wire["author"] == "QA"
