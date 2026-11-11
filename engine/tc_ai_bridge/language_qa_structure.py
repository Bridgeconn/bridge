"""Structure checks: book-wide quotation marks (#264, #456),
poetry indentation (item 33, #265) and Psalm 119's acrostic stanzas (item 34, #270).

Both read each verse's stored string through `usfm_verse` (gotcha 14): the
visible text from `lift_inline_usfm`, the paragraph markers in order from
`marker_names`. A chapter is read verse by verse. Neither parses the book, so a
pass stays inside the Tier A budget (parsing Psalms takes 3 s).

- `punctuation.unbalanced-quote`: delegated to quotation_rules, across the book.
  Chapter-local cached calls disable this delegation; jobs cache it separately.
- `poetry.q2-without-q1`: an indented poetry line (`\\q2`, `\\q3`) with no `\\q1`
  (or `\\q`) before it since the last prose paragraph or stanza break (MAT 4:6
  in the IRV: the quotation of Psalm 91 opens at `\\q2`). The marker between
  `\\c` and the first verse, and between a heading and its verse, is in no stored
  verse string, so a poem opening at `\\q2` right there is not caught.
- `acrostic.stanzas`: Psalm 119's 22 stanzas should each carry their letter
  (`\\qa`). The `\\qa` before verse 1 is in no stored verse string, so 21 or more
  counts as complete. One finding per chapter, at verse 1, in the chapter's
  heading context; no fix. The other alphabet poems (LAM 1-4, PSA 9-10, 25, 34,
  37, 111, 112, 145, PRO 31) are not marked by convention and are not checked.
"""
from __future__ import annotations

from typing import Any, Callable

from .language_qa import RULE_VERSION, rule_fields, stable_finding_id, text_hash
from .usfm_verse import marker_names

# Acrostic chapters whose stanzas are marked with their letter (\qa): book -> chapter -> stanzas.
ACROSTICS = {"psa": {"119": 22}}
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
                       quotes: bool = True,
                       proceed: Callable[[], bool] = lambda: True) -> list[dict[str, Any]]:
    """`chapter_texts`: chapter -> verse -> stored (raw) verse text;
    `headings`: chapter -> verse -> [{tag, text}] (a heading introduces that verse)."""
    findings: list[dict[str, Any]] = []
    if quotes:
        from .quotation_rules import quotation_findings
        findings.extend(quotation_findings(book, chapter_texts, proceed=proceed)[0])

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
        stanzas = ACROSTICS.get(book.lower(), {}).get(chapter)
        if stanzas:
            letters = sum(1 for raw in chapter_texts[chapter].values() if isinstance(raw, str)
                          for name in marker_names(raw) if name == "qa")
            if letters < stanzas - 1:
                first = min(chapter_texts[chapter], key=_verse_order)
                titles = [h.get("text", "") for items in headings.get(chapter, {}).values() for h in items]
                title = titles[0] if titles else ""
                findings.append({
                    "id": stable_finding_id(book, chapter, first, "acrostic.stanzas@heading0", title, 1),
                    "book": book, "chapter": chapter, "verse": first, "rule": "acrostic.stanzas",
                    "severity": "low", "start": 0, "end": 0, "originalText": "",
                    "message": (f"Psalm {chapter} is an acrostic of {stanzas} stanzas; "
                                + ("none carries its stanza letter (\\qa)." if not letters else
                                   f"only {letters} of the {stanzas - 1} after the first carry their stanza "
                                   f"letter (\\qa).")),
                    "textHash": text_hash(title), "ruleVersion": RULE_VERSION, "status": "review-needed",
                    "context": "heading", "contextText": title, **rule_fields("acrostic.stanzas", []),
                })
    return findings
