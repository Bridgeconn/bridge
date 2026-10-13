"""Book header and introduction checks (framework item 47, #253).

Language QA reads a book's header (`\\h`, `\\toc1-3`, `\\mt`) and introduction
(`\\is`, `\\ip`, `\\iot`, `\\io1` with `\\ior`) from its preserved source, through
`usfm_parser.identify_usfm` (the preamble) and `usfm_verse.lift_verse` (the
`\\ior` spans): gotcha 14, no pattern over the USFM here.

- `header.missing`: no, or an empty, `\\toc1`, `\\toc2`, `\\toc3` or `\\mt`.
- `intro.ior-space`: a space inside `\\ior … \\ior*` (MAT, 3 of 3 confirmed
  2026-10-13).
- `intro.ior-target`: an `\\ior` reference whose chapter or verse does not exist
  (read as `xref.target-missing` reads `\\xt`, #249).

A finding carries `context: "introduction"` and is anchored at the book's first
verse; start/end index `contextText` (the header line as shown) and no fix is
applied, because Bridge does not edit the header. A suggested form, if any, is
in the message.
"""
from __future__ import annotations

import threading
import unicodedata
from pathlib import Path
from typing import Any

from .language_qa import RULE_VERSION, rule_fields, stable_finding_id, text_hash
from .language_qa_xrefs import _ITEM, _targets, max_verses, normalize_name, source_of
from .usfm_parser import identify_usfm, read_usfm_text
from .usfm_verse import lift_verse

REQUIRED = ("toc1", "toc2", "toc3", "mt")
OUTLINE_TAGS = frozenset({"io", "io1", "io2", "io3", "io4"})

_lock = threading.Lock()
_source_cache: dict[str, tuple[int, str]] = {}


def book_source_text(project_root: str | Path) -> str | None:
    """The preserved source of the book, decoded; cached until it changes."""
    source = source_of(Path(project_root))
    if source is None:
        return None
    stamp = source.stat().st_mtime_ns
    with _lock:
        cached = _source_cache.get(str(source))
        if cached and cached[0] == stamp:
            return cached[1]
    text = read_usfm_text(source)
    with _lock:
        _source_cache[str(source)] = (stamp, text)
    return text


def _verse_order(verse: str) -> tuple[int, str]:
    digits = "".join(c for c in verse.split("-")[0] if c.isdigit())
    return (int(digits) if digits else 0, verse)


def _same(a: str, b: str) -> bool:
    flat = lambda s: " ".join(unicodedata.normalize("NFC", s).split())  # noqa: E731
    return flat(a) == flat(b)


def header_findings(book: str, source_text: str | None, chapter_verses: dict[str, list[str]],
                    names: dict[str, str]) -> list[dict[str, Any]]:
    """`chapter_verses`: chapter -> its verse keys (the anchor is the first verse)."""
    if not source_text or not chapter_verses:
        return []
    first_chapter = min(chapter_verses, key=lambda c: int(c) if c.isdigit() else 10 ** 6)
    if not chapter_verses[first_chapter]:
        return []
    anchor = min(chapter_verses[first_chapter], key=_verse_order)
    identity = identify_usfm(source_text)
    first: dict[str, str] = {}
    for header in identity.headers:
        first.setdefault("mt" if header.tag == "mt1" else header.tag, header.content.strip())
    findings: list[dict[str, Any]] = []
    seen: dict[tuple[str, str], int] = {}

    def add(rule: str, context_text: str, start: int, end: int, message: str) -> None:
        original = context_text[start:end]
        seen[(rule, original)] = seen.get((rule, original), 0) + 1
        findings.append({
            "id": stable_finding_id(book, first_chapter, anchor, f"{rule}@introduction", original,
                                    seen[(rule, original)]),
            "book": book, "chapter": first_chapter, "verse": anchor, "rule": rule, "severity": "low",
            "start": start, "end": end, "originalText": original, "message": message,
            "textHash": text_hash(context_text), "ruleVersion": RULE_VERSION, "status": "review-needed",
            "context": "introduction", "contextText": context_text, **rule_fields(rule, []),
        })

    for tag in REQUIRED:
        if not first.get(tag):
            add("header.missing", "", 0, 0, f"No \\{tag} in the book header.")

    tops = max_verses()
    own = book.upper()
    for header in identity.headers:
        if header.tag not in OUTLINE_TAGS or "\\ior" not in header.content:
            continue
        lifted = lift_verse(header.content)
        plain = lifted.plain
        for span in lifted.styles:
            if span.marker != "ior":
                continue
            text = plain[span.start:span.end]
            if text != text.strip():
                add("intro.ior-space", plain, span.start, span.end,
                    f"Space inside \\ior … \\ior* (suggested: \"{text.strip()}\").")
            match = _ITEM.match(text.strip())
            if match is None or not tops:
                continue
            target = names.get(normalize_name(match.group("name"))) if match.group("name") else own
            points = _targets(match.group("refs"))
            if target is None or points is None:
                continue
            missing = [(c, v) for c, v in points
                       if (target, c) not in tops or (v is not None and not 0 <= v <= tops[(target, c)])]
            if missing:
                c, v = missing[0]
                add("intro.ior-target", plain, span.start, span.end,
                    f"{target} {c}" + (f":{v}" if v is not None else "") + " does not exist.")
    return findings
