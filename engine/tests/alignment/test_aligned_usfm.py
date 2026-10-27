import pytest

from tc_ai_bridge.aligned_usfm import (
    NO_SOURCE_TOKENS, AlignedUsfmError, render_aligned_verse, render_unaligned_verse, unaligned_reason,
)
from tc_ai_bridge.models import AlignmentGroup, TokenRef, VerseAlignment


def _top(word, occurrence=1, occurrences=1):
    return TokenRef(
        word, occurrence, occurrences,
        strong="H1", lemma=word, morph="He,Ncmsa",
    )


def _bottom(word, occurrence=1, occurrences=1):
    return TokenRef(word, occurrence, occurrences, type="bottomWord")


def test_repeated_words_keep_occurrence_identity_and_punctuation():
    alignment = VerseAlignment([
        AlignmentGroup([_top("א", 1, 2)], [_bottom("word", 1, 2)]),
        AlignmentGroup([_top("א", 2, 2)], [_bottom("word", 2, 2)]),
    ], [])

    rendered = render_aligned_verse("“word word.”", alignment)

    assert rendered.startswith("“\\zaln-s")
    assert 'x-occurrence="1" x-occurrences="2"\\w*' in rendered
    assert 'x-occurrence="2" x-occurrences="2"\\w*' in rendered
    assert rendered.endswith("\\zaln-e\\*.”")


def test_inline_markers_and_footnotes_are_preserved_without_aligning_note_text():
    alignment = VerseAlignment([
        AlignmentGroup([_top("א")], [_bottom("Added")]),
        AlignmentGroup([_top("ב")], [_bottom("text")]),
    ], [])
    source = "\\add Added\\add* text. \\f + \\ft note text\\f*"

    rendered = render_aligned_verse(source, alignment)

    assert "\\add " in rendered and "\\add*" in rendered
    assert "\\f + \\ft note text\\f*" in rendered
    assert "\\w note" not in rendered


def test_discontinuous_target_group_is_one_milestone_nest_per_contiguous_run():
    """#339: the shape translationCore's exporter writes (word-aligner
    `merge`): each contiguous run of the group's target words gets its own
    `\\zaln-s ... \\zaln-e` nest carrying the same source milestones."""
    alignment = VerseAlignment([
        AlignmentGroup([_top("א"), _top("ב")], [_bottom("one"), _bottom("three")]),
        AlignmentGroup([_top("ג")], [_bottom("two")]),
    ], [])

    rendered = render_aligned_verse("one two three", alignment)

    a = '\\zaln-s |x-strong="H1" x-lemma="א" x-morph="He,Ncmsa" x-occurrence="1" x-occurrences="1" x-content="א"\\*'
    b = '\\zaln-s |x-strong="H1" x-lemma="ב" x-morph="He,Ncmsa" x-occurrence="1" x-occurrences="1" x-content="ב"\\*'
    g = '\\zaln-s |x-strong="H1" x-lemma="ג" x-morph="He,Ncmsa" x-occurrence="1" x-occurrences="1" x-content="ג"\\*'
    assert rendered == (
        f'{a}{b}\\w one|x-occurrence="1" x-occurrences="1"\\w*\\zaln-e\\*\\zaln-e\\* '
        f'{g}\\w two|x-occurrence="1" x-occurrences="1"\\w*\\zaln-e\\* '
        f'{a}{b}\\w three|x-occurrence="1" x-occurrences="1"\\w*\\zaln-e\\*\\zaln-e\\*'
    )
    assert rendered.count(a) == 2 and rendered.count(b) == 2 and rendered.count(g) == 1
    assert rendered.count("\\zaln-e\\*") == 5


def test_render_unaligned_verse_matches_an_empty_alignment():
    assert render_unaligned_verse("target words.") == render_aligned_verse(
        "target words.", VerseAlignment([], [_bottom("target"), _bottom("words")]),
    )


def test_a_verse_with_no_source_tokens_is_written_unaligned_not_refused():
    # A lettered segment (5a) has no source tokens (#307): its words are
    # written exactly as unaligned words of an aligned verse, with no milestone.
    alignment = VerseAlignment([], [_bottom("target"), _bottom("words")])

    rendered = render_aligned_verse("target words.", alignment)

    assert rendered == (
        '\\w target|x-occurrence="1" x-occurrences="1"\\w* '
        '\\w words|x-occurrence="1" x-occurrences="1"\\w*.'
    )
    assert unaligned_reason("target words.", alignment) == NO_SOURCE_TOKENS


def test_unaligned_reason_is_only_for_verses_with_words_and_no_source():
    with_source = VerseAlignment([AlignmentGroup([_top("א")], [])], [_bottom("target")])
    assert unaligned_reason("target", with_source) is None
    assert unaligned_reason("", VerseAlignment([], [])) is None


def test_target_words_in_a_group_with_no_source_words_are_still_refused():
    alignment = VerseAlignment([AlignmentGroup([], [_bottom("target")])], [])

    with pytest.raises(AlignedUsfmError, match="has target words but no source words"):
        render_aligned_verse("target", alignment)
