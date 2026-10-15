"""#302: a chapter's verse keys come back in reading order, bridges and lettered
segments included (CLAUDE.md gotcha 12: they are real input)."""
from types import SimpleNamespace

from tc_ai_bridge.tc_project import TranslationCoreProject, verse_order_key


def test_bridges_and_segments_sit_at_their_number():
    keys = ["13", "5b", "1", "3-4", "front", "10", "5a", "2", "6"]
    assert sorted(keys, key=verse_order_key) == ["front", "1", "2", "3-4", "5a", "5b", "6", "10", "13"]


def test_plain_numbers_keep_numeric_order_and_unnumbered_keys_go_last():
    assert sorted(["10", "9", "x", "2"], key=verse_order_key) == ["2", "9", "10", "x"]


def test_project_verses_uses_the_reading_order():
    chapter = {"1": {}, "2": {}, "6": {}, "3-4": {}, "5a": {}, "5b": {}, "13": {}}
    stub = SimpleNamespace(_cached_alignment_chapter=lambda _chapter: chapter)
    assert TranslationCoreProject.verses(stub, "1") == ["1", "2", "3-4", "5a", "5b", "6", "13"]
