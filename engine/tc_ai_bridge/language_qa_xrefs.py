"""Cross-reference checks (framework item 28, #249): targets and origins.

- `xref.target-missing` (book step): a reference inside `\\xt` whose chapter or
  verse exists in none of the six standard versifications (the vendored
  `versification` data), so a different numbering is never an error. Book
  names are resolved against every book of the collection (`\\toc3`, `\\toc2`,
  `\\h`); an unknown name is flagged only when the collection holds the whole
  Bible, because in a partial collection the book may simply not be there.
  Text that does not read as a reference is skipped, never flagged.
- `xref.origin-mismatch` (book step): an `\\xo` whose chapter:verse is not the
  verse the note sits in. The fix is the verse's own reference.

Notes come from the parser (`lift_verse`, gotcha 14); the reference text inside
`\\xt` is plain text and is read here.
"""
from __future__ import annotations

import threading
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import regex

from .language_qa import RULE_VERSION, lift_inline_usfm, note_extent, rule_fields, stable_finding_id, \
    suggestion, text_hash
from .usfm_parser import identify_usfm, read_usfm_text

WHOLE_BIBLE = 66
NAME_HEADERS = ("toc3", "toc2", "h")
# "2நாளா 24:20-22", "சங் 59", "142", "யாத் 7:8-12:13", "5:1,2"
_ITEM = regex.compile(r"^(?P<name>(?:\d\s?)?[\p{L}\p{M}][\p{L}\p{M}\s.]*?)?\.?\s*(?P<refs>\d[\d\s:,\-–]*)$")
_ORIGIN = regex.compile(r"^(?P<ch>\d+)[:.](?P<v>\d+)(?:\s*[-–]\s*(?P<end>\d+))?")

_lock = threading.Lock()
_names_cache: dict[str, tuple[tuple, dict[str, str]]] = {}
_max_verse: dict[tuple[str, int], int] | None = None


def normalize_name(name: str) -> str:
    return "".join(unicodedata.normalize("NFC", name).split()).rstrip(".")


def max_verses() -> dict[tuple[str, int], int]:
    """(BOOK, chapter) -> the highest verse any standard versification gives
    it; {} when the vendored data is unavailable (the rule then stays quiet)."""
    global _max_verse
    with _lock:
        if _max_verse is None:
            from . import versification  # noqa: PLC0415 (0.4 s to load, once)
            merged: dict[tuple[str, int], int] = {}
            try:
                versification._ensure_loaded()
                for scheme in versification._module.Versification.versification_d.values():
                    for key, top in scheme.chapter_max_verse.items():
                        merged[key] = max(merged.get(key, 0), top)
            except versification.VersificationUnavailable:
                merged = {}
            _max_verse = merged
        return _max_verse


def _source_of(project_root: Path) -> Path | None:
    """A book project's preserved USFM: `<book>.usfm` once materialized, the
    copy named in `.bridge/lazy-import.json` while lazy."""
    import json  # noqa: PLC0415
    descriptor = project_root / ".bridge" / "lazy-import.json"
    if descriptor.is_file():
        try:
            copy = str(json.loads(descriptor.read_text(encoding="utf-8")).get("sourceCopy") or "")
        except (OSError, ValueError):
            copy = ""
        return (project_root / copy) if copy and (project_root / copy).is_file() else None
    for pattern in ("*.usfm", "*.USFM", "*.sfm", "*.SFM"):
        found = sorted(project_root.glob(pattern))
        if found:
            return found[0]
    return None


def collection_names(project_root: str | Path) -> dict[str, str]:
    """Normalized book name -> book id (upper case) for every book of the
    project's collection, this book included. Cached until a source changes."""
    from .project_import import collection_projects  # noqa: PLC0415 (it imports tc_project)
    root = Path(project_root).resolve()
    roots = [root] + [Path(str(entry.get("path"))) for entry in collection_projects(root)
                      if entry.get("path") and Path(str(entry.get("path"))).resolve() != root]
    sources = [(r, _source_of(r)) for r in roots]
    key = tuple((str(src), src.stat().st_mtime_ns) for _r, src in sources if src is not None)
    with _lock:
        cached = _names_cache.get(str(root))
        if cached and cached[0] == key:
            return cached[1]
    names: dict[str, str] = {}
    for _r, src in sources:
        if src is None:
            continue
        try:
            identity = identify_usfm(read_usfm_text(src))
        except Exception:  # an unreadable sibling only narrows the map
            continue
        book = identity.book_code.upper()
        for header in identity.headers:
            if header.tag in NAME_HEADERS and header.content.strip():
                names.setdefault(normalize_name(header.content), book)
    with _lock:
        _names_cache[str(root)] = (key, names)
    return names


def _targets(refs: str) -> list[tuple[int, int | None]] | None:
    """(chapter, verse or None) for every point a reference names; None when
    the text does not read as one."""
    refs = refs.replace("–", "-").replace(" ", "")
    out: list[tuple[int, int | None]] = []
    if ":" not in refs:
        for part in refs.split(","):
            ends = part.split("-")
            if not all(e.isdigit() for e in ends):
                return None
            out += [(int(e), None) for e in ends]
        return out
    chapter: int | None = None
    for part in refs.split(","):
        if not part:
            return None
        ends = part.split("-")
        if len(ends) > 2:
            return None
        for index, end in enumerate(ends):
            if ":" in end:
                c, _, v = end.partition(":")
                if not (c.isdigit() and v.isdigit()):
                    return None
                chapter = int(c)
                out.append((chapter, int(v)))
            elif end.isdigit() and chapter is not None:
                out.append((chapter, int(end)))
            else:
                return None
    return out


def _verse_number(verse: str) -> int | None:
    digits = ""
    for char in verse:
        if not char.isdigit():
            break
        digits += char
    return int(digits) if digits else None


def xref_findings(book: str, chapter_texts: dict[str, dict[str, Any]], names: dict[str, str], *,
                  proceed: Callable[[], bool] = lambda: True,
                  stats: Counter | None = None) -> list[dict[str, Any]]:
    """`chapter_texts`: chapter -> verse -> stored (raw) verse text. `stats`, when
    given, counts the references checked and the ones skipped (unreadable,
    unknown book), for measurement."""
    stats = Counter() if stats is None else stats
    tops = max_verses()
    whole_bible = len(set(names.values())) >= WHOLE_BIBLE
    findings: list[dict[str, Any]] = []
    occurrences: Counter = Counter()

    def add(rule: str, chapter: str, verse: str, raw: str, start: int, end: int, message: str,
            fixes: list[dict[str, Any]]) -> None:
        original = raw[start:end]
        occurrences[(chapter, verse, rule, original)] += 1
        findings.append({
            "id": stable_finding_id(book, chapter, verse, rule, original, occurrences[(chapter, verse, rule, original)]),
            "book": book, "chapter": chapter, "verse": verse, "rule": rule, "severity": "medium",
            "start": start, "end": end, "originalText": original, "message": message,
            "textHash": text_hash(raw), "ruleVersion": RULE_VERSION, "status": "review-needed",
            **rule_fields(rule, fixes),
        })

    for chapter in sorted(chapter_texts, key=lambda c: int(c) if c.isdigit() else 0):
        if not proceed():
            break
        for verse, raw in chapter_texts[chapter].items():
            if not isinstance(raw, str) or "\\x" not in raw:
                continue
            lifted, _ = lift_inline_usfm(raw)
            if lifted is None:
                continue
            for note in lifted.notes:
                if note.kind != "xref":
                    continue
                start, end = note_extent(raw, note)
                body = raw[start:end]
                # The \xo origin: the verse the note belongs to.
                origin = _ORIGIN.match(note.reference.strip()) if note.reference else None
                here = _verse_number(verse)
                if origin and here is not None and chapter.isdigit():
                    o_ch, o_v = int(origin.group("ch")), int(origin.group("v"))
                    o_end = int(origin.group("end") or o_v)
                    last = _verse_number(verse.split("-")[-1]) or here
                    # "\xo 1:6-11" may sit at any verse it names; a bridge "3-4" at either end
                    if o_ch != int(chapter) or o_end < here or o_v > last:
                        at = body.index(note.reference, body.index("\\xo"))
                        add("xref.origin-mismatch", chapter, verse, raw, start + at,
                            start + at + len(origin.group()),
                            f"\\xo {origin.group()} in a note at {chapter}:{verse}.",
                            [suggestion(f"{chapter}:{verse.split('-')[0]}", "rule", "This verse's reference")])
                # The \xt targets.
                if not tops:
                    continue
                current: str | None = book.upper()
                cursor = 0
                for name, text in note.parts:
                    if name != "xt":
                        continue
                    for item in text.split(";"):
                        item = item.strip()
                        if not item:
                            continue
                        match = _ITEM.match(item)
                        if match is None:
                            stats["unreadable"] += 1
                            continue
                        if match.group("name"):
                            current = names.get(normalize_name(match.group("name")))
                            if current is None:
                                stats["unknown book"] += 1
                                if whole_bible:
                                    at = body.find(item, cursor)
                                    if at >= 0:
                                        cursor = at + len(item)
                                        add("xref.target-missing", chapter, verse, raw, start + at,
                                            start + at + len(item),
                                            f"\"{match.group('name').strip()}\" is not the name of any book "
                                            f"in this Bible.", [])
                                continue
                        if current is None:
                            continue
                        points = _targets(match.group("refs"))
                        if points is None:
                            stats["unreadable"] += 1
                            continue
                        stats["checked"] += 1
                        missing = [(c, v) for c, v in points
                                   if (current, c) not in tops or (v is not None and not 0 <= v <= tops[(current, c)])]
                        if missing:
                            at = body.find(item, cursor)
                            if at < 0:
                                continue
                            cursor = at + len(item)
                            c, v = missing[0]
                            where = f"{current} {c}" + (f":{v}" if v is not None else "")
                            add("xref.target-missing", chapter, verse, raw, start + at, start + at + len(item),
                                f"{where} does not exist in any standard versification.", [])
    return findings
