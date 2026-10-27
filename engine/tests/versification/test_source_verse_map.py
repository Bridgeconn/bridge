"""#352: the source verse map a book's recorded versification implies.

Detection at import, the manifest key, the derived map, and the unplaced
source verse (UGNT 3JN 1:15 against a 14-verse 3 John) that is never merged
by guess. Pure functions over the vendored versification data and the
bundled UGNT/UHB packs; the RPC-driven test is in tests/service/.
"""
from __future__ import annotations

import pytest

from tc_ai_bridge import versification as vt
from tc_ai_bridge.source_verse_map import (
    MANIFEST_KEY, UNPLACED_CHECK_ID, detect_versification, schema_from_manifest,
    source_refs_for_target_verse, source_tokens_for_target_verse, unplaced_source_verses,
)

pytestmark = pytest.mark.skipif(not vt.is_available(), reason="vendored versification data not present")

THREE_JOHN_14 = {"1": [str(n) for n in range(1, 15)]}


def test_a_book_every_schema_fits_equally_falls_back_to_org_and_says_so():
    entry = detect_versification("3jn", {f"1:{n}": "x" for n in range(1, 15)})
    assert entry["schema"] == "org" and entry["detected"] is False
    assert "fit equally" in entry["reason"] and entry["costBySchema"]["org"] == 0
    assert schema_from_manifest({MANIFEST_KEY: entry}) == "org"
    assert schema_from_manifest({}) == "org" and schema_from_manifest(None) == "org"


def test_the_derived_map_follows_a_real_mapped_and_split_entry():
    # eng Psalm 3:1 is org Psalm 3:2 (the descriptive-title shift).
    assert source_refs_for_target_verse("psa", "3", "1", "eng") == [("3", "2")]
    # eng PSA 51:0 expands to org 51:1-2: both org verses, tokens combined.
    assert source_refs_for_target_verse("psa", "51", "0", "eng") == [("51", "1"), ("51", "2")]
    combined = source_tokens_for_target_verse("psa", "51", "0", "eng")
    assert len(combined) == len(source_tokens_for_target_verse("psa", "51", "1", "org")) + \
        len(source_tokens_for_target_verse("psa", "51", "2", "org"))
    # Identity under org, bridges included, is the plain lookup.
    assert source_refs_for_target_verse("3jn", "1", "14", "org") == [("1", "14")]
    assert source_refs_for_target_verse("3jn", "1", "3-4", "org") == [("1", "3-4")]


def test_a_merge_gives_the_org_verse_to_its_first_target_verse_only():
    # eng NEH 7:68-69 -> org NEH 7:68.
    assert source_refs_for_target_verse("neh", "7", "68", "eng") == [("7", "68")]
    assert source_refs_for_target_verse("neh", "7", "69", "eng") == []


def test_three_john_1_15_is_unplaced_against_a_14_verse_book_and_anchored_on_1_14():
    [unplaced] = unplaced_source_verses("3jn", "org", THREE_JOHN_14)
    assert (unplaced["sourceChapter"], unplaced["sourceVerse"]) == ("1", "15")
    assert (unplaced["nearestChapter"], unplaced["nearestVerse"]) == ("1", "14")
    assert unplaced["wordCount"] == 11 and unplaced["words"][0].lower() == "εἰρήνη"
    # The greeting is never merged into 1:14: that verse keeps UGNT 1:14 only.
    assert len(source_tokens_for_target_verse("3jn", "1", "14", "org")) == 10
    # A 15-verse 3 John has nothing unplaced; a bridged 14-15 covers it too.
    assert unplaced_source_verses("3jn", "org", {"1": [str(n) for n in range(1, 16)]}) == []
    assert unplaced_source_verses("3jn", "org", {"1": [str(n) for n in range(1, 14)] + ["14-15"]}) == []
    assert UNPLACED_CHECK_ID.startswith("alignment.")


def test_an_unfinished_chapter_or_a_missing_chapter_is_untranslated_not_unplaced():
    # Ruth with only 1:1 translated: 1:2-22 missing is a run of 21, chapters 2-4 absent.
    assert unplaced_source_verses("rut", "org", {"1": ["1"]}) == []
    # A one-verse gap inside a chapter is a versification difference and is raised.
    [gap] = unplaced_source_verses("rut", "org", {"1": [str(n) for n in range(1, 23) if n != 7]})
    assert (gap["sourceVerse"], gap["nearestVerse"]) == ("7", "6")
