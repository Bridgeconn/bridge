"""Chapter-level structure checks: quotation marks (framework item 9, #264) and
poetry indentation (item 33, #265).

Both read each verse's stored string through `usfm_verse` (gotcha 14): the
visible text from `lift_inline_usfm`, the paragraph markers in order from
`marker_names`. A chapter is read verse by verse. Neither parses the book, so a
pass stays inside the Tier A budget (parsing Psalms takes 3 s).

- `punctuation.unbalanced-quote`: a curly quotation mark (“ ” ‘ ’) whose pair is
  not in its chapter. A quotation may run over several verses, so the pairing is
  per chapter, not per verse. (Brackets pair inside a verse: scan_text.)
- `poetry.q2-without-q1`: an indented poetry line (`\\q2`, `\\q3`) with no `\\q1`
  (or `\\q`) before it since the last prose paragraph or stanza break (MAT 4:6
  in the IRV: the quotation of Psalm 91 opens at `\\q2`). The marker between
  `\\c` and the first verse, and between a heading and its verse, is in no stored
  verse string, so a poem opening at `\\q2` right there is not caught.
"""
from __future__ import annotations

from typing import Any, Callable

from .language_qa import RULE_VERSION, lift_inline_usfm, rule_fields, stable_finding_id, text_hash
from .usfm_verse import marker_names

QUOTES = {"“": "”", "‘": "’"}
CLOSERS = {close: open_ for open_, close in QUOTES.items()}
FIRST_LEVEL = frozenset({"q", "q1"})
INDENTED = frozenset({"q2", "q3", "q4"})
# Paragraph markers that end a stanza: prose, a stanza break, a heading. Every
# other marker (character styles, notes, \qs, \qac ...) leaves it as it is.
STANZA_ENDS = frozenset({"p", "m", "pi", "pi1", "pi2", "mi", "nb", "pc", "pm", "pmo", "pmc", "pmr", "li", "li1",
                         "li2", "b", "s", "s1", "s2", "s3", "ms", "ms1", "mr", "d", "sp", "cl", "qa"})


def _marker_at(raw: str, name: str, start: int) -> int:
    """Where the next `\\name` token is, from `start`: the name must end there
    (`\\q` is not the start of `\\q1`). -1 when there is none."""
    at = raw.find("\\" + name, start)
    while at >= 0:
        after = at + 1 + len(name)
        if after == len(raw) or not (raw[after].isalnum() or raw[after] in "-*"):
            return at
        at = raw.find("\\" + name, at + 1)
    return -1


def _verse_order(verse: str) -> tuple[int, str]:
    digits = "".join(c for c in verse.split("-")[0] if c.isdigit())
    return (int(digits) if digits else 0, verse)


def _chapter_order(chapter: str) -> int:
    return int(chapter) if chapter.isdigit() else 0


def structure_findings(book: str, chapter_texts: dict[str, dict[str, Any]],
                       headings: dict[str, dict[str, list[dict[str, Any]]]], *,
                       proceed: Callable[[], bool] = lambda: True) -> list[dict[str, Any]]:
    """`chapter_texts`: chapter -> verse -> stored (raw) verse text;
    `headings`: chapter -> verse -> [{tag, text}] (a heading introduces that verse)."""
    findings: list[dict[str, Any]] = []

    def add(rule: str, chapter: str, verse: str, raw: str, start: int, end: int, message: str) -> None:
        original = raw[start:end]
        findings.append({
            "id": stable_finding_id(book, chapter, verse, rule, f"{original}@{start}", 1),
            "book": book, "chapter": chapter, "verse": verse, "rule": rule, "severity": "medium",
            "start": start, "end": end, "originalText": original, "message": message,
            "textHash": text_hash(raw), "ruleVersion": RULE_VERSION, "status": "review-needed",
            **rule_fields(rule, []),
        })

    for chapter in sorted(chapter_texts, key=_chapter_order):
        if not proceed():
            break
        open_quotes: list[tuple[str, str, str, int]] = []   # mark, verse, raw, raw offset
        # The paragraph marker between \c and the first verse, and between a
        # heading and its verse ("\s …", "\q1", "\v 2" at JOL 1:2), is in no
        # stored verse string, so the level there is unknown: give it the
        # benefit of the doubt.
        first_level = True
        for verse in sorted(chapter_texts[chapter], key=_verse_order):
            raw = chapter_texts[chapter][verse]
            if not isinstance(raw, str):
                continue
            if headings.get(chapter, {}).get(verse):
                first_level = True
            lifted, _ = lift_inline_usfm(raw)
            if lifted is not None:
                for at, char in enumerate(lifted.visible):
                    if char in QUOTES:
                        open_quotes.append((char, verse, raw, lifted.raw_index[at]))
                    elif char in CLOSERS:
                        if open_quotes and open_quotes[-1][0] == CLOSERS[char]:
                            open_quotes.pop()
                        else:
                            offset = lifted.raw_index[at]
                            add("punctuation.unbalanced-quote", chapter, verse, raw, offset, offset + 1,
                                f"Closing {char} with no opening {CLOSERS[char]} before it in chapter {chapter}.")
            searched = 0
            for name in marker_names(raw):
                if name in FIRST_LEVEL:
                    first_level = True
                elif name in STANZA_ENDS:
                    first_level = False
                if name in FIRST_LEVEL | INDENTED | STANZA_ENDS:
                    at = _marker_at(raw, name, searched)
                    searched = at + 1 if at >= 0 else searched
                    if name in INDENTED and not first_level and at >= 0:
                        add("poetry.q2-without-q1", chapter, verse, raw, at, at + len(name) + 1,
                            f"\\{name} with no \\q1 before it in this stanza: the first line of a poem is \\q1.")
        for mark, verse, raw, offset in open_quotes:
            add("punctuation.unbalanced-quote", chapter, verse, raw, offset, offset + 1,
                f"Opening {mark} with no closing {QUOTES[mark]} after it in chapter {chapter}.")
    return findings
