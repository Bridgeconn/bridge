"""USFM-checker findings on lettered segments and bridges (#303).

Decision (maintainer, 2026-10-15): lettered segments (5a, 5b) stay flagged as
the checker reports them; a bridge (3-4) is valid and is not flagged. Every
finding lands on the verse it is about, not on the chapter's first verse."""
from __future__ import annotations

import os
import time

import pytest

from bridge_service import BridgeEngine, _usfm_anchor_verse
from greek_room_engine.adapters.usfm_adapter import _checker_command, _parse_report
from greek_room_engine.models.finding import QaFinding
from tests.support.alignment_books import write_alignment_book
from tests.support.projects import call

KEYS = ["1", "2", "3-4", "5a", "5b", "6"]

# The real checker's report for a chapter keyed 1, 2, 3-4, 5a, 5b, 6.
REPORT = """\
Report of 3 errors/warnings/alerts/infos:
    Severe errors (1)
        Verse info (1)
            Duplicate verse number (1)
                2JN.usfm l.9 (2JN 1): Duplicate verse number 5
    Warnings (2)
        Verse info (2)
            Verse number includes letter (2)
                5a (1)
                    2JN.usfm l.8 (2JN 1): \\v 5a five a
                5b (1)
                    2JN.usfm l.9 (2JN 1): \\v 5b five b
"""


def test_a_segment_line_carries_its_own_reference():
    issues = _parse_report(REPORT)
    assert [(i["subcategory"], i["verse"]) for i in issues] == [
        ("Duplicate verse number", "5"),
        ("Verse number includes letter", "5a"),
        ("Verse number includes letter", "5b"),
    ]


@pytest.mark.parametrize(("verse", "ref", "expected"), [
    (5, "5b", "5b"),   # exact reference
    (5, "", "5a"),     # "Duplicate verse number 5": the first key numbered 5
    (3, "", "3-4"),    # a number inside a bridge
    (2, "", "2"),      # a plain verse
    (4, "", "1"),      # no key numbered 4 ("missing verse 4"): the chapter's first verse
    (0, "", "1"),      # no verse at all
])
def test_anchor_verse(verse, ref, expected):
    finding = QaFinding(engine="usfm", chapter=1, verse=verse, verse_ref=ref)
    assert _usfm_anchor_verse(finding, KEYS) == expected


@pytest.mark.skipif(_checker_command() is None, reason="USFM structural checker not available")
def test_segments_are_flagged_on_their_own_verses_and_a_bridge_is_not(tmp_path):
    root = tmp_path / "2jn"
    write_alignment_book(root, "2jn", {"1": {key: {"text": f"verse {key}", "alignment": {
        "alignments": [], "wordBank": []}} for key in KEYS}})
    (root / "2jn.usfm").write_text(
        "\\id 2JN\n\\h 2 John\n\\c 1\n\\p\n" + "".join(f"\\v {key} verse {key}\n" for key in KEYS),
        encoding="utf-8")
    old = time.time_ns() - 60_000_000_000
    for path in [root, *root.rglob("*")]:
        os.utime(path, ns=(old, old))
    engine = BridgeEngine()
    assert call(engine, "project.open", {"path": str(root)})["success"]

    by_verse = {}
    for key in KEYS:
        response = call(engine, "verse.runChecks", {"chapter": "1", "verse": key, "checks": ["usfm"]})
        assert response["success"], response
        by_verse[key] = sorted((f["check_type"], f["severity"]) for f in response["findings"] if f["engine"] == "usfm")

    assert by_verse["5a"] == [("usfm.duplicate_verse_number", "high"), ("usfm.verse_number_includes_letter", "low")]
    assert by_verse["5b"] == [("usfm.verse_number_includes_letter", "low")]
    assert by_verse["3-4"] == []
    assert by_verse["1"] == []  # nothing falls back to the first verse any more
