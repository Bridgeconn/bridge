"""Provisional AI review packets -> existing open reviewer flags (#417).

No spelling/grammar rule, decision, project word, learned fix or Scripture is
written. A closed flag is not native benchmark evidence. Exact verse hashes
and raw spans are required; a changed verse is never re-anchored by guessing.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .language_packs.registry import language_code
from .language_qa import text_hash

SCHEMA = "bridge-language-qa-provisional-review-v1"
PROVENANCE = "ai-assisted-native-pending"
MAX_BYTES = 8 * 1024 * 1024
MAX_CASES = 5000
TYPES = {"spelling", "grammar", "meaning", "style", "encoding", "font", "other"}


def _text(value: Any, field: str, maximum: int, *, empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        raise ValueError(f"{field} must be {'a' if not empty else 'an optionally empty'} string of at most {maximum} characters")
    return value


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return value


def read_packet(file_path: Any) -> tuple[dict[str, Any], str]:
    path = Path(_text(file_path, "filePath", 32768))
    with path.open("rb") as handle:
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("AI review packet exceeds the 8 MB limit")
    data = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or data.get("provenance") != PROVENANCE:
        raise ValueError("Expected a provisional AI review packet; native/approved labels are not accepted here")
    _text(data.get("packetId"), "packetId", 160)
    _digest(data.get("sourceArchiveSha256"), "sourceArchiveSha256")
    cases = data.get("cases")
    if not isinstance(cases, list) or len(cases) > MAX_CASES:
        raise ValueError("cases must be a list of at most 5,000 questions")
    seen = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("Every review case must be an object")
        ident = _text(case.get("id"), "case.id", 160)
        if ident in seen:
            raise ValueError(f"Duplicate review case id: {ident}")
        seen.add(ident)
        for key, limit in (("language", 40), ("book", 16), ("chapter", 24), ("verse", 24), ("originalText", 20000)):
            _text(case.get(key), f"case.{key}", limit)
        if (re.fullmatch(r"[A-Za-z0-9]{2,16}", case["book"]) is None
                or re.fullmatch(r"[0-9]{1,4}", case["chapter"]) is None
                or re.fullmatch(r"[0-9]{1,4}[a-z]?(?:-[0-9]{1,4}[a-z]?)?", case["verse"]) is None):
            raise ValueError("Review cases require book identifiers and numeric chapters/verse keys, including bridges or segments")
        _digest(case.get("textHash"), "case.textHash")
        start, end = case.get("start"), case.get("end")
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= 20000:
            raise ValueError("Review spans must be non-empty raw code-point offsets")
        if case.get("type") not in TYPES:
            raise ValueError("Unsupported review flag type")
        _text(case.get("reason", ""), "case.reason", 2000, empty=True)
        _text(case.get("reportedVerdict", ""), "case.reportedVerdict", 80, empty=True)
        if case.get("proposedCorrection") is not None:
            _text(case["proposedCorrection"], "case.proposedCorrection", 1000, empty=True)
        sources = case.get("sourceIds", [])
        if not isinstance(sources, list) or len(sources) > 30:
            raise ValueError("case.sourceIds must contain at most 30 review row ids")
        for value in sources:
            _text(value, "case.sourceIds", 100)
        if len(flag_note(data, case)) > 4000:
            raise ValueError("Combined review note exceeds the existing flag note limit")
    return data, hashlib.sha256(raw).hexdigest()


def flag_note(packet: dict[str, Any], case: dict[str, Any]) -> str:
    correction = case.get("proposedCorrection")
    proposed = ("No replacement proposed" if correction is None else
                "Delete the flagged text" if correction == "" else
                repr(correction) if correction.isspace() else correction)
    return ("AI-assisted review — native confirmation pending.\n"
            f"Reported judgement: {case.get('reportedVerdict') or 'Needs checking'}\n"
            f"Proposed wording: {proposed}\n"
            f"Reason: {case.get('reason', '')}\n"
            f"Review rows: {', '.join(case.get('sourceIds', []))}\n"
            "Check this passage in context. Record your conclusion before resolving. "
            "Resolving a question does not certify a rule or create native benchmark labels.")


def plan(project: Any, packet: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    language = language_code(str((project.manifest.get("target_language") or {}).get("id") or ""))
    book = project.book_id.lower()
    # Keep even deleted/resolved imports authoritative: rerunning an import
    # must never resurrect a dismissed question or lose a human conclusion.
    existing = {(r.get("aiReview", {}).get("sourceArchiveSha256"), r.get("aiReview", {}).get("caseId"))
                for r in project.language_qa_flags(include_deleted=True)
                if isinstance(r.get("aiReview"), dict)}
    counts = {"ready": 0, "existing": 0, "stale": 0, "otherScope": 0}
    ready = []
    examples = []
    verse_texts: dict[tuple[str, str], str | None] = {}
    for case in packet["cases"]:
        if language_code(case["language"]) != language or case["book"].lower() != book:
            counts["otherScope"] += 1
            continue
        if (packet["sourceArchiveSha256"], case["id"]) in existing:
            counts["existing"] += 1
            continue
        key = (case["chapter"], case["verse"])
        if key not in verse_texts:
            verse_texts[key] = project.target_verse_text(*key)
        current = verse_texts[key]
        if (not isinstance(current, str) or text_hash(current) != case["textHash"]
                or current[case["start"]:case["end"]] != case["originalText"]):
            counts["stale"] += 1
            continue
        counts["ready"] += 1
        ready.append(case)
        if len(examples) < 20:
            examples.append({"id": case["id"], "chapter": case["chapter"], "verse": case["verse"],
                             "text": case["originalText"], "note": flag_note(packet, case)})
    return {"packetId": packet["packetId"], "provenance": PROVENANCE,
            "book": book, "language": language, **counts, "examples": examples}, ready
