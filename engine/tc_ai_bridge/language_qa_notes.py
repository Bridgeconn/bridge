"""Note composition checks (framework item 44, #246): callers and where a caller sits.

- `note.caller-mixed` (book step): a footnote or cross-reference whose caller
  differs from the one the book's other notes of that kind use (IRV: 4,831 "+",
  and "\\x -" at JOL 2:28 and RUT 2:1, 2 of 2 confirmed 2026-10-13). The
  finding spans the opening marker and caller (`\\x -`), so the fix is the
  same text everywhere and a book-wide apply is safe.
- `note.space-before-caller` (per verse, language_qa.scan_text): a space
  between a word and the note that annotates it, so the caller prints apart
  from its word (IRV: 53 footnotes). The fix removes the space (Benz,
  2026-10-13). A space at the end of the verse is spacing.extra's.

Where the note text falls on the page is the Typesetter's, on the proof.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Callable

from .language_qa import (RULE_VERSION, lift_inline_usfm, note_extent, rule_fields, stable_finding_id,
                          suggestion, text_hash)


def _chapter_order(chapter: str) -> int:
    return int(chapter) if chapter.isdigit() else 0


def _opener(raw: str, note: Any) -> tuple[str, str, int, int]:
    """(marker, caller, start, end) of the note's opener and caller, `\\x -`, from the
    parser's note (lift_verse): the marker is the word after the backslash."""
    start, _ = note_extent(raw, note)
    marker = raw[start + 1:].split(None, 1)[0]
    caller = note.caller.split()[0]  # a marker-less note reads as one long caller in lift_verse
    end = raw.index(caller, start + 1 + len(marker)) + len(caller)
    return marker, caller, start, end


def caller_findings(book: str, chapter_texts: dict[str, dict[str, Any]], *,
                    proceed: Callable[[], bool] = lambda: True) -> list[dict[str, Any]]:
    """`chapter_texts`: chapter -> verse -> stored (raw) verse text."""
    callers: dict[str, Counter] = {}
    places: list[tuple[str, str, str, str, str, int, int]] = []
    for chapter in sorted(chapter_texts, key=_chapter_order):
        for verse, raw in chapter_texts[chapter].items():
            if not isinstance(raw, str) or ("\\f" not in raw and "\\x" not in raw):
                continue
            lifted, _ = lift_inline_usfm(raw)
            if lifted is None:
                continue  # its markup is reported as a limitation by the verse scan
            for note in lifted.notes:
                marker, caller, start, end = _opener(raw, note)
                callers.setdefault(marker, Counter())[caller] += 1
                places.append((chapter, verse, raw, marker, caller, start, end))
    usual = {marker: counts.most_common(1)[0] for marker, counts in callers.items() if len(counts) > 1}
    findings: list[dict[str, Any]] = []
    occurrences: Counter = Counter()
    for chapter, verse, raw, marker, caller, start, end in places:
        if not proceed():
            break
        if marker not in usual or caller == usual[marker][0]:
            continue
        expected, count = usual[marker]
        original = raw[start:end]
        occurrences[(chapter, verse, original)] += 1
        findings.append({
            "id": stable_finding_id(book, chapter, verse, "note.caller-mixed", original,
                                    occurrences[(chapter, verse, original)]),
            "book": book, "chapter": chapter, "verse": verse, "rule": "note.caller-mixed",
            "severity": "low", "start": start, "end": end, "originalText": original,
            "message": f"Caller \"{caller}\" here; this book's other \\{marker} notes use \"{expected}\" ({count}).",
            "textHash": text_hash(raw), "ruleVersion": RULE_VERSION, "status": "review-needed",
            **rule_fields("note.caller-mixed", [suggestion(f"\\{marker} {expected}", "rule",
                                                           f"Use the book's caller \"{expected}\"")]),
        })
    return findings
