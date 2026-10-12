"""#228: `complete_cross_verse` -- the fifth per-verse alignment status.

A verse aligned through a cross-verse link could never reach `complete`,
because translationCore's rule needs every word in a two-sided group and
aligned USFM cannot express the link; the verse ✓ therefore said "alignment
partial" forever. Now `status` reads `complete_cross_verse` when the verse's
remaining gaps -- net of active links and null decisions, the same rule
`gaps` and `gapScan` use -- are none and at least one was closed that way.
Export is untouched: `canComplete` and `completionState` still answer
translationCore's question.

Drives the protocol (CLAUDE.md test rule 1), on the #219 fixture shape: Greek
PHP 1:3 "I thank God" where "I thank" is rendered in Tamil v4 and the article
has no Tamil word.
"""
from __future__ import annotations

import pytest

from bridge_service import BridgeEngine
from tests.support.alignment_books import bottom, context_id, top, unaligned_verse, write_alignment_book
from tests.support.projects import call


@pytest.fixture
def root(tmp_path):
    root = tmp_path / "php"
    write_alignment_book(root, "php", {"1": {
        # Θεῷ is aligned to தேவனை in translationCore; εὐχαριστῶ and τῷ have
        # no counterpart in this verse, so the verse is `partial`.
        "3": {
            "text": "தேவனை",
            "alignment": {
                "alignments": [
                    {"topWords": [top("εὐχαριστῶ", "G21680")], "bottomWords": []},
                    {"topWords": [top("τῷ", "G35880")], "bottomWords": []},
                    {"topWords": [top("Θεῷ", "G23160")], "bottomWords": [bottom("தேவனை")]},
                ],
                "wordBank": [],
            },
        },
        "4": unaligned_verse("நான் எப்பொழுதும் ஸ்தோத்திரிக்கிறேன்", [("πάντοτε", "G38420")]),
    }})
    return root


@pytest.fixture
def engine(root):
    engine = BridgeEngine()
    assert call(engine, "project.open", {"path": str(root)})["success"] is True
    return engine


def _ctx(engine, verse: str) -> dict:
    return call(engine, "alignment.get", {"chapter": "1", "verse": verse})["result"]


def _link(engine) -> dict:
    v3, v4 = _ctx(engine, "3"), _ctx(engine, "4")
    return call(engine, "alignment.crossVerse.link", {
        "source": {"chapter": "1", "verse": "3", "topId": context_id(v3, top_word="εὐχαριστῶ")},
        "target": {"chapter": "1", "verse": "4", "bottomId": context_id(v4, bottom_word="ஸ்தோத்திரிக்கிறேன்")},
    })


def _null(engine) -> dict:
    v3 = _ctx(engine, "3")
    return call(engine, "alignment.null.set", {
        "chapter": "1", "verse": "3", "side": "source",
        "id": context_id(v3, top_word="τῷ"), "reason": "GRAMMATICAL", "note": "article",
    })


def _chapter_status(engine, verse: str) -> str:
    """What the editor's verse list is seeded from (`alignmentStatus` per verse)."""
    return str(engine.get_chapter_verse_data("1")["verses"][verse]["alignmentStatus"])


def test_a_verse_whose_remaining_gaps_are_all_closed_reads_complete_cross_verse(engine):
    assert _ctx(engine, "3")["status"] == "partial"
    assert _link(engine)["success"] is True
    # τῷ is still a gap: a tC group with a source and no target is a gap.
    assert _ctx(engine, "3")["status"] == "partial"
    assert _null(engine)["success"] is True

    v3 = _ctx(engine, "3")
    assert v3["status"] == "complete_cross_verse"
    assert v3["gaps"] == {"sourceUnmatched": 0, "targetUnmatched": 0}
    assert v3["fullyAccounted"] is True
    # Export is unchanged: translationCore's question still gets its answer.
    assert v3["canComplete"] is False
    assert v3["completionState"] == "pending"
    # The other end of the link has gaps of its own.
    assert _ctx(engine, "4")["status"] == "untouched"

    # The chapter scan, the range view and the chapter load all say the same.
    status = call(engine, "alignment.status", {"chapter": "1"})["result"]
    assert status["verses"]["1:3"] == "complete_cross_verse"
    assert status["counts"] == {
        "complete": 0, "complete_cross_verse": 1, "partial": 0, "untouched": 1, "invalid": 0,
    }
    rng = call(engine, "alignment.getRange", {"chapter": "1", "verses": ["3", "4"]})["result"]
    assert [c["status"] for c in rng["verses"]] == ["complete_cross_verse", "untouched"]
    assert rng["verses"][0]["chapterStatus"] == status["counts"]
    assert _chapter_status(engine, "3") == "complete_cross_verse"


def test_unlinking_or_clearing_the_null_reopens_the_gap(engine):
    link = _link(engine)["result"]["link"]
    decision_id = _null(engine)["result"]["decision"]["id"]
    assert _ctx(engine, "3")["status"] == "complete_cross_verse"

    assert call(engine, "alignment.crossVerse.unlink", {"linkId": link["id"]})["success"] is True
    assert _ctx(engine, "3")["status"] == "partial"
    assert call(engine, "alignment.status", {"chapter": "1"})["result"]["counts"]["complete_cross_verse"] == 0

    assert _link(engine)["success"] is True
    assert _ctx(engine, "3")["status"] == "complete_cross_verse"
    assert call(engine, "alignment.null.clear", {"decisionId": decision_id})["success"] is True
    assert _ctx(engine, "3")["status"] == "partial"


def test_an_edit_that_invalidates_the_link_drops_the_state_on_both_verses(engine):
    assert _link(engine)["success"] is True
    assert _null(engine)["success"] is True
    assert _ctx(engine, "3")["status"] == "complete_cross_verse"

    edited = call(engine, "verse.edit", {"chapter": "1", "verse": "4", "newText": "நான் எப்பொழுதும் நன்றி"})
    assert edited["success"] is True, edited
    assert edited["result"]["crossVerseLinksInvalidated"]
    # The link is no longer active, so 1:3's gap is open again; 1:4 is invalid.
    assert _ctx(engine, "3")["status"] == "partial"
    assert _ctx(engine, "4")["status"] == "invalid"
    assert [entry["state"] for entry in _ctx(engine, "3")["crossVerseLinks"]] == ["invalid"]


def test_the_touch_index_follows_writes_and_leaves_other_verses_alone(engine):
    assert engine._cross_verse_touch_index(engine.project) == {}
    link = _link(engine)["result"]["link"]
    index = engine._cross_verse_touch_index(engine.project)
    assert set(index) == {("1", "3"), ("1", "4")}
    assert index[("1", "3")]["realized"] == ["εὐχαριστῶ␟1␟1"]
    assert index[("1", "4")]["accounted"] == ["ஸ்தோத்திரிக்கிறேன்␟1␟1"]
    # Same generation, same object: no second read.
    assert engine._cross_verse_touch_index(engine.project) is index
    assert call(engine, "alignment.crossVerse.unlink", {"linkId": link["id"]})["success"] is True
    assert engine._cross_verse_touch_index(engine.project) == {}
