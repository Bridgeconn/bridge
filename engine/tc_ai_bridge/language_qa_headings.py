"""Section-heading checks (framework item 31, #244): consistency and presence.

Headings live beside the verse map (`<chapter>.headings.json`, #180), keyed by
the verse each introduces. Their wording is the indic-qa layer's (it reads the
same headings). These are the structure rules, language-independent, run for
every pack, panel-only:

- `heading.trailing-punctuation`: a section heading ending in . , ; or :
  (a question or exclamation heading is fine). 25 of 25 confirmed in the
  2026-10-13 review.
- `heading.marker-mixed`: \\s and \\s1 are the same level; in a book that uses
  both, the minority is flagged (4 of 4 confirmed, 2026-10-13).
- `heading.missing`: a chapter with no section heading, in a book where at
  least four in five chapters have one.

Each finding carries `context: "heading"`: start/end index `contextText`, the
heading's visible text, and no fix is offered (a fix would be written into the
verse; see LanguageQaFinding.context).
"""
from __future__ import annotations

from typing import Any, Callable

from .language_qa import RULE_VERSION, rule_fields, stable_finding_id, text_hash
from .usfm_verse import lift_verse

SECTION_TAGS = frozenset({"s", "s1", "s2", "s3", "s4", "s5", "ms", "ms1", "ms2", "ms3"})
TRAILING = frozenset(".,;:")
PRESENCE_SHARE = 0.8      # a book "heads its chapters" when this share of them have a heading
PRESENCE_MIN_CHAPTERS = 5


def _verse_order(verse: str) -> tuple[int, str]:
    digits = "".join(c for c in verse.split("-")[0] if c.isdigit())
    return (int(digits) if digits else 0, verse)


def heading_findings(book: str, headings: dict[str, dict[str, list[dict[str, Any]]]],
                     chapters: dict[str, list[str]], *,
                     proceed: Callable[[], bool] = lambda: True) -> list[dict[str, Any]]:
    """`headings`: chapter -> verse -> [{tag, text}] (tc_project.chapter_headings
    per chapter). `chapters`: chapter -> its verse keys, in order (a missing
    heading is anchored at the chapter's first verse)."""
    findings: list[dict[str, Any]] = []
    s_tags: dict[str, int] = {}
    for verses in headings.values():
        for items in verses.values():
            for item in items:
                tag = str(item.get("tag") or "")
                if tag in ("s", "s1"):
                    s_tags[tag] = s_tags.get(tag, 0) + 1
    minority = min(s_tags, key=lambda t: (s_tags[t], t)) if len(s_tags) == 2 else None
    majority = ({"s", "s1"} - {minority}).pop() if minority else None

    def add(rule: str, chapter: str, verse: str, index: int, visible: str, start: int, end: int,
            message: str) -> None:
        original = visible[start:end]
        findings.append({
            "id": stable_finding_id(book, chapter, verse, f"{rule}@heading{index}", original, 1),
            "book": book, "chapter": chapter, "verse": verse, "rule": rule,
            "severity": "low", "start": start, "end": end, "originalText": original,
            "message": message, "textHash": text_hash(visible), "ruleVersion": RULE_VERSION,
            "status": "review-needed", "context": "heading", "contextText": visible,
            **rule_fields(rule, []),
        })

    for chapter in sorted(headings, key=lambda c: int(c) if c.isdigit() else 0):
        if not proceed():
            return findings
        for verse in sorted(headings[chapter], key=_verse_order):
            for index, item in enumerate(headings[chapter][verse]):
                tag = str(item.get("tag") or "")
                if tag not in SECTION_TAGS:
                    continue  # \r parallel references, \sp speakers, \mr ranges: not titles
                visible = lift_verse(str(item.get("text") or "")).plain
                stripped = visible.rstrip()
                if stripped and stripped[-1] in TRAILING:
                    add("heading.trailing-punctuation", chapter, verse, index, visible,
                        len(stripped) - 1, len(stripped),
                        f"Section heading ends with \"{stripped[-1]}\"; a heading takes no closing punctuation.")
                if tag == minority:
                    add("heading.marker-mixed", chapter, verse, index, visible, 0, len(visible),
                        f"\\{tag} here; this book's other section headings use \\{majority} ({s_tags[majority]}). "
                        f"\\s and \\s1 are the same level: use one.")

    headed = {chapter for chapter, verses in headings.items()
              if any(str(item.get("tag") or "") in SECTION_TAGS for items in verses.values() for item in items)}
    if len(chapters) >= PRESENCE_MIN_CHAPTERS and len(headed) >= PRESENCE_SHARE * len(chapters):
        for chapter, verse_keys in chapters.items():
            if chapter not in headed and verse_keys:
                first = min(verse_keys, key=_verse_order)
                add("heading.missing", chapter, first, 0, "", 0, 0,
                    f"Chapter {chapter} has no section heading; {len(headed)} of this book's "
                    f"{len(chapters)} chapters have one.")
    return findings
