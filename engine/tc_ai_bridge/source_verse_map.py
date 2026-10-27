"""The source verse map a target book's versification implies (#352).

Decision (Revant, 2026-10-24): detect the versification at import from the
book's chapter/verse shape with the vendored Greek Room library (fall back to
``org`` -- the Hebrew/Greek numbering -- when it is unavailable or every
schema fits equally), record it in ``manifest.json`` as
``bridge_versification``, and derive the source verse map from it. A source
verse that lands in no target verse (UGNT 3JN 1:15 against a 14-verse
English 3 John) is never merged into a neighbour by guess: it is recorded as
unplaced, with the nearest target verse, and the check path raises a finding
there (``versification.source_verse_unplaced``) so the reviewer can see what
the source says and decide. The target text is not changed.

What the map does with each mapping shape ``versification.to_org_ref``
reports for a target verse:

- ``same`` / ``mapped``: the one org verse's tokens (through
  ``source_tokens_for_verse``, which also handles a USFM bridge ``3-4`` and
  returns nothing for a lettered segment ``5a``, as before);
- ``split`` (one target verse covers several org verses): the org verses'
  tokens combined in order, occurrences renumbered across the span, exactly
  as a bridge is handled;
- ``merge`` (several target verses map to one org verse): the org verse's
  tokens go to the first target verse of the merge only. Dividing them
  between target verses would be a guess.

Nothing here reads target Scripture text and nothing here writes.
"""
from __future__ import annotations

import re
from typing import Any

from . import versification as versification_tool
from .original_language_resources import (
    _renumber_occurrences, _validated_pack, resource_for_book, source_tokens_for_verse,
)

DEFAULT_SCHEMA = "org"
MANIFEST_KEY = "bridge_versification"
# A versification difference is a short tail or gap: 3JN 1:15 beyond a
# 14-verse letter, ROM 16:25-27, a Psalm superscription. A longer run of
# source verses the target chapter lacks, or a whole missing chapter, is an
# unfinished translation, which is ordinary work and not raised here.
MAX_UNPLACED_RUN = 3
# The finding's check_type. Under "alignment." so check_jobs.finding_check
# files it with the alignment group that raises it, and QAIssue code
# ALIGN_SOURCE_VERSE_UNPLACED so bridge_service categorizes it as alignment.
UNPLACED_CHECK_ID = "alignment.source_verse_unplaced"
UNPLACED_CODE = "ALIGN_SOURCE_VERSE_UNPLACED"


def detect_versification(book_id: str, verses: dict[str, str]) -> dict[str, Any]:
    """The ``bridge_versification`` manifest entry for a book: the detected
    schema, how it was chosen, and every schema's match cost. ``verses`` is
    Bridge's ``{"chapter:verse": text}`` map. Never raises: without the
    vendored library, or when every schema fits equally (a short book like
    3 John has no distinguishing verse), the answer is ``org``, flagged as a
    fallback rather than a detection."""
    entry: dict[str, Any] = {"schemaVersion": 1, "schema": DEFAULT_SCHEMA, "detected": False,
                             "reason": "", "costBySchema": {}}
    if not versification_tool.is_available():
        entry["reason"] = "versification library unavailable; org assumed"
        return entry
    try:
        detected = versification_tool.detect_schema(book_id, verses)
    except Exception as exc:  # noqa: BLE001 -- detection is advisory, never fatal to an import
        entry["reason"] = f"detection failed ({exc}); org assumed"
        return entry
    costs = {str(k): int(v) for k, v in (detected.get("costBySchema") or {}).items()}
    entry["costBySchema"] = costs
    best = str(detected.get("bestSchema") or "")
    if not best or not costs:
        entry["reason"] = "no schema matched; org assumed"
        return entry
    best_cost = costs.get(best)
    tied = [schema for schema, cost in costs.items() if cost == best_cost]
    if len(tied) > 1:
        # Every tied schema fits the book equally, so nothing in the book
        # chooses one. org is the source's own numbering, the safest default.
        entry["schema"] = DEFAULT_SCHEMA if DEFAULT_SCHEMA in tied else best
        entry["reason"] = f"{len(tied)} schemas fit equally ({', '.join(sorted(tied))}); org assumed"
        return entry
    entry.update({"schema": best, "detected": True,
                  "schemaName": detected.get("bestSchemaName") or "",
                  "reason": "detected from the book's chapter and verse shape"})
    return entry


def schema_from_manifest(manifest: dict[str, Any] | None) -> str:
    entry = (manifest or {}).get(MANIFEST_KEY)
    if isinstance(entry, dict) and str(entry.get("schema") or "").strip():
        return str(entry["schema"]).strip()
    return DEFAULT_SCHEMA


def _org_ref(book_id: str, chapter: str, verse: str, schema: str) -> dict[str, Any]:
    if schema == DEFAULT_SCHEMA or not versification_tool.is_available():
        return {"mapping": "same"}
    try:
        return versification_tool.to_org_ref(book_id, chapter, verse, schema)
    except Exception:  # noqa: BLE001 -- an unknown schema or book is identity, as the library itself does
        return {"mapping": "same"}


def _split_ref(ref: str) -> tuple[str, str] | None:
    """'3JN 1:15' -> ('1', '15')."""
    match = re.fullmatch(r"\s*\S+\s+(\d+):(\S+)\s*", str(ref or ""))
    return (match.group(1), match.group(2)) if match else None


def source_refs_for_target_verse(book_id: str, chapter: str, verse: str, schema: str) -> list[tuple[str, str]]:
    """The org (chapter, verse) refs whose tokens belong to this target verse
    under ``schema``; empty for the later verses of a merge."""
    mapping = _org_ref(book_id, chapter, verse, schema)
    kind = str(mapping.get("mapping") or "same")
    if kind == "mapped":
        return [(str(mapping.get("orgChapter") or chapter), str(mapping.get("orgVerse") or verse))]
    if kind == "split":
        refs = [_split_ref(r) for r in (mapping.get("splitInto") or [])]
        return [r for r in refs if r is not None] or [(str(chapter), str(verse))]
    if kind == "merge":
        # mergedWith is the library's pretty print: "NEH 7:68-69" or
        # "NEH 7:68; NEH 7:69". The first verse of the merge carries the tokens.
        merged = [str(v).strip() for v in re.split(r"[;,]", str(mapping.get("mergedWith") or "")) if str(v).strip()]
        first = _split_ref(merged[0]) if merged else None
        if first is not None:
            span = re.fullmatch(r"(\d+)-(\d+)", first[1])
            if span:
                first = (first[0], span.group(1))
        target = _split_ref(str(mapping.get("orgRef") or ""))
        if first is not None and first != (str(chapter), str(verse)):
            return []  # a later verse of the merge: the first one carries the tokens
        return [target] if target is not None else [(str(chapter), str(verse))]
    return [(str(chapter), str(verse))]


def source_tokens_for_target_verse(
    book_id: str, chapter: str, verse: str, schema: str, resources_root: Any = None,
) -> list[dict[str, Any]]:
    """Source tokens for a target verse under ``schema``. Identity mappings
    (every verse of a book in org numbering, every bridge and segment) go
    through ``source_tokens_for_verse`` unchanged."""
    refs = source_refs_for_target_verse(book_id, chapter, verse, schema)
    if refs == [(str(chapter), str(verse))]:
        return source_tokens_for_verse(book_id, chapter, verse, resources_root)
    combined: list[dict[str, Any]] = []
    for org_chapter, org_verse in refs:
        tokens = source_tokens_for_verse(book_id, org_chapter, org_verse, resources_root)
        if not tokens:
            return []
        combined.extend(tokens)
    return _renumber_occurrences(combined) if len(refs) > 1 else combined


def _nearest_target_verse(chapter: str, verse_number: int, target_verses: list[str]) -> str | None:
    """The target verse of the same chapter closest to a source verse number:
    the greatest numbered verse at or before it, else the smallest after it.
    A bridge '3-4' counts by its first number; a segment '5a' by its number."""
    numbered: list[tuple[int, str]] = []
    for value in target_verses:
        match = re.match(r"(\d+)", str(value))
        if match:
            numbered.append((int(match.group(1)), str(value)))
    if not numbered:
        return None
    before = [item for item in numbered if item[0] <= verse_number]
    if before:
        return max(before)[1]
    return min(numbered)[1]


def _source_verse_numbers(book_id: str, resources_root: Any = None) -> dict[str, list[str]]:
    resource = resource_for_book(book_id, resources_root)
    if resource is None:
        return {}
    pack = _validated_pack(resource, book_id)
    chapters = pack.get("chapters", {})
    return {str(chapter): [str(v) for v in verses] for chapter, verses in chapters.items()
            if isinstance(verses, dict)}


def _covered_source_refs(book_id: str, schema: str, target_verses_by_chapter: dict[str, list[str]]) -> set[tuple[str, str]]:
    covered: set[tuple[str, str]] = set()
    for chapter, verses in target_verses_by_chapter.items():
        for verse in verses:
            for org_chapter, org_verse in source_refs_for_target_verse(book_id, str(chapter), str(verse), schema):
                covered.add((org_chapter, org_verse))
                span = re.fullmatch(r"(\d+)-(\d+)", org_verse)
                if span:
                    for number in range(int(span.group(1)), int(span.group(2)) + 1):
                        covered.add((org_chapter, str(number)))
                segment = re.fullmatch(r"(\d+)[a-z]", org_verse)
                if segment:
                    # A lettered segment has no source tokens of its own, but
                    # the source verse it belongs to is the book's, not unplaced.
                    covered.add((org_chapter, segment.group(1)))
    return covered


def unplaced_source_verses(
    book_id: str, schema: str, target_verses_by_chapter: dict[str, list[str]], resources_root: Any = None,
) -> list[dict[str, Any]]:
    """Source verses that land in no target verse under ``schema``, each with
    the nearest target verse of its chapter (the finding's anchor) and the
    source words, so the reviewer can see what has no home. Empty when the
    bundled source has no pack for this book."""
    source = _source_verse_numbers(book_id, resources_root)
    if not source:
        return []
    covered = _covered_source_refs(book_id, schema, target_verses_by_chapter)
    unplaced: list[dict[str, Any]] = []
    for chapter, verses in source.items():
        targets = [str(v) for v in target_verses_by_chapter.get(chapter, [])]
        if not targets:
            continue  # a chapter the target does not have yet is untranslated, not unplaced
        missing = [verse for verse in verses if verse.isdigit() and (chapter, verse) not in covered]
        for run in _contiguous_runs([int(v) for v in missing]):
            if len(run) > MAX_UNPLACED_RUN:
                continue  # an unfinished chapter, not a versification difference
            for number in run:
                verse = str(number)
                tokens = source_tokens_for_verse(book_id, chapter, verse, resources_root)
                if not tokens:
                    continue
                nearest = _nearest_target_verse(chapter, number, targets)
                if nearest is None:
                    continue
                unplaced.append({
                    "sourceChapter": chapter, "sourceVerse": verse,
                    "nearestChapter": chapter, "nearestVerse": str(nearest),
                    "wordCount": len(tokens), "words": [str(t.get("word", "")) for t in tokens],
                })
    return unplaced


def _contiguous_runs(numbers: list[int]) -> list[list[int]]:
    runs: list[list[int]] = []
    for number in sorted(numbers):
        if runs and number == runs[-1][-1] + 1:
            runs[-1].append(number)
        else:
            runs.append([number])
    return runs


_UNPLACED_CACHE: dict[tuple[str, str, tuple[tuple[str, tuple[str, ...]], ...]], list[dict[str, Any]]] = {}


def unplaced_for_project(project: Any) -> list[dict[str, Any]]:
    """`unplaced_source_verses` for an open project, keyed on its path, its
    manifest's versification and its exact chapter/verse shape, so a check
    on every verse of a book costs one pass. A verse added or removed by an
    edit changes the key and the list is computed again."""
    try:
        chapters = {str(c): [str(v) for v in project.verses(c)] for c in project.chapters()}
    except Exception:  # noqa: BLE001 -- an unreadable project has no unplaced verses to report
        return []
    schema = schema_from_manifest(getattr(project, "manifest", None))
    key = (str(getattr(project, "path", "")), schema, tuple((c, tuple(v)) for c, v in chapters.items()))
    cached = _UNPLACED_CACHE.get(key)
    if cached is None:
        try:
            cached = unplaced_source_verses(str(getattr(project, "book_id", "")), schema, chapters)
        except Exception:  # noqa: BLE001 -- optional evidence never sinks a verse's checks
            cached = []
        if len(_UNPLACED_CACHE) > 64:
            _UNPLACED_CACHE.clear()
        _UNPLACED_CACHE[key] = cached
    return cached
