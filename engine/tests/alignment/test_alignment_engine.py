import pytest

from tc_ai_bridge.alignment_engine import AlignmentError, realign
from tc_ai_bridge.models import AlignmentGroup, TokenRef, VerseAlignment


def _token(word, *, bottom=False):
    return TokenRef(word, type="bottomWord" if bottom else "")


def test_realign_keeps_source_group_order_stable():
    h1, h2, h3 = (_token("h1"), _token("h2"), _token("h3"))
    t1, t2, t3 = (_token("t1", bottom=True), _token("t2", bottom=True), _token("t3", bottom=True))
    verse = VerseAlignment([
        AlignmentGroup([h1], [t1]),
        AlignmentGroup([h2], [t2]),
        AlignmentGroup([h3], [t3]),
    ], [])

    changed = realign(verse, [h2], [t3])

    assert [group.top_words[0].word for group in changed.alignments] == ["h1", "h2", "h3"]
    assert changed.alignments[1].bottom_words[0].word == "t3"


def _four():
    source = [_token(f"h{i}") for i in range(1, 5)]
    target = [_token(f"t{i}", bottom=True) for i in range(1, 5)]
    return source, target


def _order(verse):
    return [[token.word for token in group.top_words] for group in verse.alignments]


# #498 (Joel, 2026-11-17): an aligned target word moved to a LATER source word
# pulled that source word forward to the column the target word left.
def test_moving_an_aligned_target_word_to_a_later_source_word_keeps_source_order():
    (h1, h2, h3, h4), (t1, t2, t3, t4) = _four()
    verse = VerseAlignment([
        AlignmentGroup([h1], [t1]),
        AlignmentGroup([h2], [t2]),
        AlignmentGroup([h3], []),
        AlignmentGroup([h4], []),
    ], [t3, t4])

    changed = realign(verse, [h3], [t1])

    assert _order(changed) == [["h1"], ["h2"], ["h3"], ["h4"]]
    assert [t.word for t in changed.alignments[0].bottom_words] == []
    assert [t.word for t in changed.alignments[1].bottom_words] == ["t2"]
    assert [t.word for t in changed.alignments[2].bottom_words] == ["t1"]
    assert [t.word for t in changed.word_bank] == ["t3", "t4"]


def test_moving_an_aligned_target_word_to_an_earlier_source_word_keeps_source_order():
    (h1, h2, h3, h4), (t1, t2, t3, t4) = _four()
    verse = VerseAlignment([
        AlignmentGroup([h1], []),
        AlignmentGroup([h2], [t2]),
        AlignmentGroup([h3], [t3]),
        AlignmentGroup([h4], []),
    ], [t1, t4])

    changed = realign(verse, [h1], [t3])

    assert _order(changed) == [["h1"], ["h2"], ["h3"], ["h4"]]
    assert [t.word for t in changed.alignments[0].bottom_words] == ["t3"]
    assert [t.word for t in changed.alignments[2].bottom_words] == []


def test_a_word_from_the_bank_and_words_from_two_columns_keep_source_order():
    (h1, h2, h3, h4), (t1, t2, t3, t4) = _four()
    verse = VerseAlignment([
        AlignmentGroup([h1], [t1]),
        AlignmentGroup([h2], [t2]),
        AlignmentGroup([h3], []),
        AlignmentGroup([h4], [t4]),
    ], [t3])

    changed = realign(verse, [h3], [t1, t3, t4])

    assert _order(changed) == [["h1"], ["h2"], ["h3"], ["h4"]]
    assert [t.word for t in changed.alignments[2].bottom_words] == ["t1", "t3", "t4"]


def test_joining_a_column_with_the_one_before_it_keeps_source_order():
    (h1, h2, h3, h4), (t1, t2, t3, t4) = _four()
    verse = VerseAlignment([
        AlignmentGroup([h1], [t4]),
        AlignmentGroup([h2], []),
        AlignmentGroup([h3], [t3]),
        AlignmentGroup([h4], []),
    ], [t1, t2])

    # Join h2 and h3, with a target word that sat under h1.
    changed = realign(verse, [h2, h3], [t3, t4])

    assert _order(changed) == [["h1"], ["h2", "h3"], ["h4"]]


def test_splitting_a_joined_column_keeps_source_order_either_way():
    (h1, h2, h3, h4), (t1, t2, t3, t4) = _four()
    verse = VerseAlignment([
        AlignmentGroup([h1], [t1]),
        AlignmentGroup([h2, h3], [t2]),
        AlignmentGroup([h4], []),
    ], [t3, t4])

    # What the pages ask for: every source word but the last keeps the targets.
    assert _order(realign(verse, [h2], [t2])) == [["h1"], ["h2"], ["h3"], ["h4"]]
    # The later word taken out instead (#449): it follows the one that stays.
    assert _order(realign(verse, [h3], [t2])) == [["h1"], ["h2"], ["h3"], ["h4"]]
    # With a target word from an earlier column.
    assert _order(realign(verse, [h3], [t1])) == [["h1"], ["h2"], ["h3"], ["h4"]]


# 2026-11-18 (Joel): two source words merged, the target word then taken
# away, could not be split again, because realign refused an empty target
# selection outright.
def test_a_merged_group_with_no_target_word_splits_in_place():
    (h1, h2, h3, h4), (t1, t2, t3, t4) = _four()
    verse = VerseAlignment([
        AlignmentGroup([h1], [t1]),
        AlignmentGroup([h2, h3, h4], []),
    ], [t2, t3, t4])

    changed = realign(verse, [h2], [])

    assert _order(changed) == [["h1"], ["h2"], ["h3", "h4"]]
    assert all(not group.bottom_words for group in changed.alignments[1:])
    assert [t.word for t in changed.word_bank] == ["t2", "t3", "t4"]
    # At the second seam, and with the later words named instead.
    assert _order(realign(verse, [h2, h3], [])) == [["h1"], ["h2", "h3"], ["h4"]]
    assert _order(realign(verse, [h4], [])) == [["h1"], ["h2", "h3"], ["h4"]]


def test_a_split_with_no_target_named_leaves_the_target_words_with_the_rest():
    (h1, h2, h3, h4), (t1, t2, t3, t4) = _four()
    verse = VerseAlignment([AlignmentGroup([h1, h2], [t1, t2]), AlignmentGroup([h3], []), AlignmentGroup([h4], [])], [t3, t4])

    changed = realign(verse, [h1], [])

    assert _order(changed) == [["h1"], ["h2"], ["h3"], ["h4"]]
    assert [t.word for t in changed.alignments[0].bottom_words] == []
    assert [t.word for t in changed.alignments[1].bottom_words] == ["t1", "t2"]


def test_only_a_split_is_allowed_with_no_target_word():
    (h1, h2, h3, h4), (t1, t2, t3, t4) = _four()
    verse = VerseAlignment([
        AlignmentGroup([h1], []),
        AlignmentGroup([h2], []),
        AlignmentGroup([h3, h4], [t3]),
    ], [t1, t2, t4])

    # Joining two columns, emptying a whole group, and a selection that
    # reaches into two groups are all still refused.
    for selection in ([h1, h2], [h3, h4], [h2, h3], [h1]):
        with pytest.raises(AlignmentError):
            realign(verse, selection, [])


@pytest.mark.parametrize("source_count,target_count", [(1, 1), (1, 2), (2, 1), (2, 2)])
def test_realign_supports_every_group_cardinality(source_count, target_count):
    source = [_token("h1"), _token("h2")]
    target = [_token("t1", bottom=True), _token("t2", bottom=True)]
    verse = VerseAlignment([
        AlignmentGroup([source[0]], [target[0]]),
        AlignmentGroup([source[1]], [target[1]]),
    ], [])

    changed = realign(verse, source[:source_count], target[:target_count])

    assert any(
        len(group.top_words) == source_count and len(group.bottom_words) == target_count
        and {token.signature for token in group.top_words}
        == {token.signature for token in source[:source_count]}
        and {token.signature for token in group.bottom_words}
        == {token.signature for token in target[:target_count]}
        for group in changed.alignments
    )
