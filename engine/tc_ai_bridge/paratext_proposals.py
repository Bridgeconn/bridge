"""QA proposals carried in Paratext Project Notes (#427, parent #423).

A QA pass writes a Paratext note whose first comment is structured text::

    [AI-QA R2] Sandhi — Sandhi / word-joining
    Original: <the current wording>
    Suggested: <the proposed wording>
    Reason: <why>
    Location: <where, when it is not the verse body>
    Confidence: 0.82 · Reviewer decision needed: No · Severity: medium

This module reads that shape and nothing else. It is a deterministic
parser: it never raises, never consults the network or an AI, and never
decides that anything is written. Its result says what *kind* of thing the
``Suggested`` field is -- one literal replacement, a list of alternatives, an
instruction to the reviewer, a structural USFM change, "no change" -- and a
``route`` that is the strongest claim the parser is prepared to make:

``literal``
    Original and Suggested are both plain text, the category is one whose
    proposals are routinely literal, no reviewer decision was requested and
    the anchor was found. A human may offer this as a one-click correction
    later; nothing here applies it.
``review``
    A reviewer has to choose or type the correction: alternatives, prose,
    an insertion or deletion, an uncertain category, a reviewer flag, an
    anchor warning, a missing field.
``structure``
    A USFM marker or structural operation; review-only.
``noChange``
    The pass proposed leaving the text as it is.
``legacy``
    An older human note with a ``Suggestion:`` / ``sug:`` / ``Changed to``
    label; ``historical`` marks a report of a change already made, which is
    not an outstanding proposal.
``unreadable``
    The comment looked structured but could not be read; ``diagnostics``
    say why and the full source stays on the thread for a person to read.

Every proposal carries a stable ``proposalId`` (thread, author, date, block
and a hash of the normalized content), so an edited comment is a new
proposal and an unchanged one keeps its identity across re-indexing. Field
values are kept verbatim apart from trimming the ends: a Tamil word with its
vowel signs and viramas is returned exactly as written, never split.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable

# The sixteen categories observed in the reference inventory
# (selvabenz/Paratext-sug-in-context-menu, CATEGORY_HANDLING.md, 2026-10-31).
CATEGORIES: tuple[str, ...] = (
    "Sandhi / word-joining",
    "Source comparison",
    "Punctuation",
    "Textual-basis review",
    "Grammar",
    "Footnote / cross-reference",
    "USFM marker",
    "Name consistency",
    "Possible typo",
    "Possible missed source word",
    "Reviewer decision",
    "Confirmed typo",
    "Theological consistency",
    "Plural agreement",
    "Case/object marker",
    "Addition not in source",
)

# Categories whose Suggested value is routinely one literal replacement. The
# others need source evidence, a textual judgement or a reviewer's choice
# before any wording is settled, whatever the Suggested field holds.
LITERAL_CATEGORIES: frozenset[str] = frozenset({
    "Sandhi / word-joining", "Punctuation", "Grammar", "Name consistency",
    "Confirmed typo", "Plural agreement", "Case/object marker",
})

ROUTE_LITERAL = "literal"
ROUTE_REVIEW = "review"
ROUTE_STRUCTURE = "structure"
ROUTE_NO_CHANGE = "noChange"
ROUTE_LEGACY = "legacy"
ROUTE_UNREADABLE = "unreadable"
ROUTES = (ROUTE_LITERAL, ROUTE_REVIEW, ROUTE_STRUCTURE, ROUTE_NO_CHANGE, ROUTE_LEGACY, ROUTE_UNREADABLE)

OP_REPLACE = "replace"
OP_INSERT = "insert"
OP_DELETE = "delete"
OP_ALTERNATIVES = "alternatives"
OP_NO_CHANGE = "noChange"
OP_STRUCTURAL = "structural"
OP_MARKER_RENAME = "markerRename"
OP_INSTRUCTION = "instruction"
OP_NONE = "none"

REGION_BODY = "body"
REGION_INTRODUCTION = "introduction"
REGION_HEADING = "heading"
REGION_FOOTNOTE = "footnote"
REGION_CROSS_REFERENCE = "crossReference"
REGION_STRUCTURE = "structure"

# Outstanding: a proposal a reviewer still has to deal with.
OUTSTANDING_ROUTES = frozenset({ROUTE_LITERAL, ROUTE_REVIEW, ROUTE_STRUCTURE, ROUTE_UNREADABLE})

_HEADER_LINE = re.compile(r"^[ \t]*\[AI-QA[ \t]*([^\]]*)\][ \t]*([^\r\n]*)$", re.MULTILINE)
_HEADER_SPLIT_DASH = re.compile(r"\s+[—–]\s*")       # em or en dash, space before
_HEADER_SPLIT_HYPHEN = re.compile(r"\s+-\s+")                   # " - "
_FIELD = re.compile(r"^[ \t]*(Original|Suggested|Reason|Reference|Location|Severity)[ \t]*:[ \t]*", re.MULTILINE)
_META_SEPARATOR = re.compile(r"\s*[·|;]\s*|\r?\n")
_LEGACY_LABEL = re.compile(r"^[ \t]*(Suggestion|Suggested|Sugg|Sug|Changed to)[ \t]*:[ \t]*([^\r\n]*)$",
                           re.IGNORECASE | re.MULTILINE)
_LEGACY_ORIGINAL = re.compile(r"^[ \t]*(Original|Current|Was)[ \t]*:[ \t]*([^\r\n]*)$", re.IGNORECASE | re.MULTILINE)
_ANCHOR_WARNING = re.compile(r"not found verbatim|anchored on the start|differs from the current|could not be located",
                             re.IGNORECASE)
_NO_CHANGE = re.compile(
    r"^\s*[\(\[]?\s*(?:no change(?: proposed| needed| required)?|no edit|none|unchanged|retain(?: as is| current| existing)?"
    r"|keep(?: as is| the (?:current|existing)(?: wording| text)?)?)\b", re.IGNORECASE)
_DELETE = re.compile(r"^\s*[\(\[]?\s*(?:delete|remove|omit)(?:\s+(?:it|this|the\s+\w+))?\s*[\)\]]?\s*$", re.IGNORECASE)
_INSTRUCTION_START = re.compile(
    r"^\s*(?:consider|check|verify|retain|keep|use|see|should|review|ensure|add|move|replace|insert|change|compare|"
    r"confirm|read|translate|please|either|possibly|perhaps|maybe)\b", re.IGNORECASE)
_ALTERNATIVES = re.compile(r"\s+(?:/|\||or)\s+", re.IGNORECASE)
_PROSE_MARKS = re.compile(r"[()\[\]{}«»…]|\.\.\.")
_LATIN = re.compile(r"[A-Za-z]")
_STRUCTURAL_WORDS = re.compile(r"verse alignment|verse bridge|verse order|footnote placement|usfm|markup|marker",
                               re.IGNORECASE)
_HEADING_MARKER = re.compile(r"^\\(ms[123]?|s[1234]?|cl|cd)\s+(.+)$", re.DOTALL)
_WHITESPACE = re.compile(r"\s+")


@dataclass
class Proposal:
    proposalId: str
    commentIndex: int
    block: int
    route: str
    operation: str
    region: str
    pass_: str = ""
    topic: str = ""
    category: str = ""
    categoryKnown: bool = False
    original: str = ""
    suggested: str = ""
    reason: str = ""
    location: str = ""
    reference: str = ""
    severity: str = ""
    confidence: str = ""
    reviewerDecision: bool = True
    anchorWarning: bool = False
    historical: bool = False
    alternatives: list[str] = field(default_factory=list)
    structural: dict[str, str] | None = None
    diagnostics: list[str] = field(default_factory=list)
    author: str = ""
    date: str = ""

    @property
    def outstanding(self) -> bool:
        return self.route in OUTSTANDING_ROUTES and not self.historical

    def to_json(self) -> dict[str, Any]:
        return {
            "proposalId": self.proposalId, "commentIndex": self.commentIndex, "block": self.block,
            "route": self.route, "operation": self.operation, "region": self.region,
            "pass": self.pass_, "topic": self.topic, "category": self.category, "categoryKnown": self.categoryKnown,
            "original": self.original, "suggested": self.suggested, "reason": self.reason,
            "location": self.location, "reference": self.reference, "severity": self.severity,
            "confidence": self.confidence, "reviewerDecision": self.reviewerDecision,
            "anchorWarning": self.anchorWarning, "historical": self.historical, "outstanding": self.outstanding,
            "alternatives": list(self.alternatives), "structural": dict(self.structural) if self.structural else None,
            "diagnostics": list(self.diagnostics), "author": self.author, "date": self.date,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize_for_identity(text: str) -> str:
    """NFC with runs of whitespace collapsed: the form a proposal's identity
    is hashed from, so a re-exported note with different line breaks keeps
    its id. Field values themselves are never normalized."""
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFC", text or "")).strip()


def proposal_id(thread_id: str, author: str, date: str, block: int, content: str) -> str:
    digest = hashlib.sha256(normalize_for_identity(content).encode("utf-8")).hexdigest()
    raw = f"paratext-proposal|{thread_id}|{author}|{date}|{block}|{digest}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


_CATEGORY_LOOKUP = {_WHITESPACE.sub("", c).casefold(): c for c in CATEGORIES}


def canonical_category(value: str) -> tuple[str, bool]:
    """The category as the inventory spells it, when it is one of the sixteen;
    otherwise the text as written and False."""
    text = str(value or "").strip()
    found = _CATEGORY_LOOKUP.get(_WHITESPACE.sub("", text).casefold())
    return (found, True) if found else (text, False)


def _split_header_rest(rest: str) -> tuple[str, str] | None:
    """``"<topic> — <category>"`` -> (topic, category); None when there is no
    separator. An em or en dash wins; a spaced hyphen splits at its last
    occurrence so a hyphenated topic survives."""
    parts = _HEADER_SPLIT_DASH.split(rest, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    pieces = _HEADER_SPLIT_HYPHEN.split(rest)
    if len(pieces) >= 2:
        return " - ".join(pieces[:-1]).strip(), pieces[-1].strip()
    return None


def _metadata(text: str, key: str) -> str:
    match = re.search(re.escape(key) + r"\s*:\s*([^\r\n·|;]+)", text, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _non_latin_letters(text: str) -> bool:
    return any(ch.isalpha() and not _LATIN.match(ch) for ch in text)


def _region_for(topic: str, location: str) -> str:
    probe = f"{topic} {location}".casefold()
    if "introduction" in probe:
        return REGION_INTRODUCTION
    if re.search(r"heading|chapter label", probe):
        return REGION_HEADING
    if "cross-reference" in probe or "cross reference" in probe:
        return REGION_CROSS_REFERENCE
    if "footnote" in probe:
        return REGION_FOOTNOTE
    return REGION_BODY


def _alternatives_of(suggested: str) -> list[str]:
    parts = [p.strip() for p in _ALTERNATIVES.split(suggested)]
    return parts if len(parts) > 1 else []


def _looks_like_instruction(original: str, suggested: str) -> bool:
    if "\n" in suggested.strip():
        return True
    if _PROSE_MARKS.search(suggested):
        return True
    if _INSTRUCTION_START.match(suggested):
        return True
    # The target is in another script and the suggestion is written in Latin
    # letters: that is a sentence to the reviewer, not Scripture.
    if _non_latin_letters(original) and _LATIN.search(suggested) and not _non_latin_letters(suggested):
        return True
    return False


# ---------------------------------------------------------------------------
# One comment -> proposals
# ---------------------------------------------------------------------------

def parse_comment(contents: str, *, thread_id: str = "", author: str = "", date: str = "",
                  comment_index: int = 0) -> list[Proposal]:
    """The proposals in one comment's text: one per ``[AI-QA ...]`` block, or
    one legacy proposal, or none for an ordinary discussion comment. Never
    raises."""
    text = str(contents or "")
    if not text.strip():
        return []
    headers = list(_HEADER_LINE.finditer(text))
    if not headers:
        if "[AI-QA" in text:
            # The marker is there but not on a line of its own shape: the
            # header is broken. Keep the comment visible, say what is wrong.
            return [_unreadable(text, thread_id, author, date, comment_index, 0,
                                "The [AI-QA ...] header could not be read.")]
        legacy = _parse_legacy(text, thread_id, author, date, comment_index)
        return [legacy] if legacy else []
    proposals: list[Proposal] = []
    for block, match in enumerate(headers):
        end = headers[block + 1].start() if block + 1 < len(headers) else len(text)
        chunk = text[match.start():end]
        proposals.append(_parse_block(chunk, match, thread_id, author, date, comment_index, block))
    return proposals


def _unreadable(text: str, thread_id: str, author: str, date: str, comment_index: int, block: int,
                *diagnostics: str) -> Proposal:
    return Proposal(
        proposalId=proposal_id(thread_id, author, date, block, text), commentIndex=comment_index, block=block,
        route=ROUTE_UNREADABLE, operation=OP_NONE, region=REGION_BODY, diagnostics=list(diagnostics),
        author=author, date=date,
    )


def _parse_block(chunk: str, header: re.Match[str], thread_id: str, author: str, date: str,
                 comment_index: int, block: int) -> Proposal:
    diagnostics: list[str] = []
    split = _split_header_rest(header.group(2))
    if split is None:
        return _unreadable(chunk, thread_id, author, date, comment_index, block,
                           "The header has no \"topic — category\" separator.")
    topic, category_text = split
    category, known = canonical_category(category_text)
    if not known:
        diagnostics.append(f"Unknown category \"{category_text}\".")

    fields: dict[str, str] = {}
    duplicates: list[str] = []
    matches = list(_FIELD.finditer(chunk))
    for i, m in enumerate(matches):
        key = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(chunk)
        value = chunk[start:end]
        # The metadata line ("Confidence: … · Reviewer decision needed: …")
        # is not part of the last field's value.
        meta_at = re.search(r"^[ \t]*(?:Confidence|Reviewer decision needed)\s*:", value, re.MULTILINE | re.IGNORECASE)
        if meta_at:
            value = value[:meta_at.start()]
        value = value.strip()
        if key in fields:
            duplicates.append(key)
        else:
            fields[key] = value
    for key in duplicates:
        diagnostics.append(f"The field \"{key}\" appears more than once.")

    original = fields.get("Original", "")
    suggested = fields.get("Suggested", "")
    reason = fields.get("Reason", "")
    location = fields.get("Location", "")
    reference = fields.get("Reference", "")
    severity = fields.get("Severity", "") or _metadata(chunk, "Severity")
    confidence = _metadata(chunk, "Confidence")
    reviewer_text = _metadata(chunk, "Reviewer decision needed")
    reviewer_decision = reviewer_text.casefold() != "no"
    if not reviewer_text:
        diagnostics.append("No \"Reviewer decision needed\" value; treated as Yes.")
    anchor_warning = bool(_ANCHOR_WARNING.search(location))

    if not original and not suggested and not reason:
        return _unreadable(chunk, thread_id, author, date, comment_index, block,
                           "The block has none of Original, Suggested or Reason.")

    proposal = Proposal(
        proposalId=proposal_id(thread_id, author, date, block, chunk), commentIndex=comment_index, block=block,
        route=ROUTE_REVIEW, operation=OP_NONE, region=_region_for(topic, location),
        pass_=header.group(1).strip(), topic=topic, category=category, categoryKnown=known,
        original=original, suggested=suggested, reason=reason, location=location, reference=reference,
        severity=severity, confidence=confidence, reviewerDecision=reviewer_decision,
        anchorWarning=anchor_warning, diagnostics=diagnostics, author=author, date=date,
    )
    _classify(proposal, topic, location, duplicates)
    return proposal


def _classify(p: Proposal, topic: str, location: str, duplicates: list[str]) -> None:
    original, suggested = p.original, p.suggested
    structural = (
        p.category == "USFM marker" or "\\" in original or "\\" in suggested
        or bool(_STRUCTURAL_WORDS.search(f"{topic} {location}"))
    )
    if structural:
        p.region = REGION_STRUCTURE
        p.route = ROUTE_STRUCTURE
        p.operation = OP_STRUCTURAL
        a, b = _HEADING_MARKER.match(original.strip()), _HEADING_MARKER.match(suggested.strip())
        if a and b and a.group(2).strip() == b.group(2).strip() and a.group(1) != b.group(1):
            p.operation = OP_MARKER_RENAME
            p.structural = {"fromMarker": a.group(1), "toMarker": b.group(1), "label": a.group(2).strip()}
        return
    if _NO_CHANGE.match(suggested):
        p.route = ROUTE_NO_CHANGE
        p.operation = OP_NO_CHANGE
        return
    if not suggested:
        p.operation = OP_NONE
        p.diagnostics.append("No Suggested text.")
        p.route = ROUTE_REVIEW
        return
    if _DELETE.match(suggested) and original:
        p.operation = OP_DELETE
        p.route = ROUTE_REVIEW          # a deletion is always confirmed with its exact extent shown
        return
    alternatives = _alternatives_of(suggested)
    if alternatives:
        p.operation = OP_ALTERNATIVES
        p.alternatives = alternatives
        p.route = ROUTE_REVIEW
        if any(not alt for alt in alternatives):
            p.diagnostics.append("An alternative is empty.")
        return
    if _looks_like_instruction(original, suggested):
        p.operation = OP_INSTRUCTION
        p.route = ROUTE_REVIEW
        return
    if not original:
        p.operation = OP_INSERT
        p.route = ROUTE_REVIEW
        p.diagnostics.append("No Original text: an insertion needs its place chosen.")
        return
    if original == suggested:
        p.operation = OP_NO_CHANGE
        p.route = ROUTE_NO_CHANGE
        p.diagnostics.append("Original and Suggested are identical.")
        return
    p.operation = OP_REPLACE
    literal = (
        p.categoryKnown and p.category in LITERAL_CATEGORIES and not p.reviewerDecision
        and not p.anchorWarning and not duplicates
    )
    p.route = ROUTE_LITERAL if literal else ROUTE_REVIEW


def _parse_legacy(text: str, thread_id: str, author: str, date: str, comment_index: int) -> Proposal | None:
    match = _LEGACY_LABEL.search(text)
    if not match:
        return None
    label = match.group(1).casefold()
    suggested = match.group(2).strip()
    original_match = _LEGACY_ORIGINAL.search(text)
    original = original_match.group(2).strip() if original_match else ""
    historical = label == "changed to"
    return Proposal(
        proposalId=proposal_id(thread_id, author, date, 0, text), commentIndex=comment_index, block=0,
        route=ROUTE_LEGACY, operation=OP_NONE, region=REGION_BODY, category="Unstructured / discussion",
        original=original, suggested=suggested, historical=historical,
        diagnostics=[f"Older note label \"{match.group(1)}\"; read the discussion before acting."
                     + (" A \"Changed to\" reports an edit already made." if historical else "")],
        author=author, date=date,
    )


# ---------------------------------------------------------------------------
# A thread -> its proposals
# ---------------------------------------------------------------------------

def thread_proposals(thread_id: str, comments: Iterable[Any]) -> list[Proposal]:
    """Every proposal in a thread, in comment order. ``comments`` are
    ``NoteComment``-like objects with ``contents``, ``user`` and ``date``."""
    found: list[Proposal] = []
    for index, comment in enumerate(comments):
        found.extend(parse_comment(
            getattr(comment, "contents", "") or "", thread_id=thread_id,
            author=getattr(comment, "user", "") or "", date=getattr(comment, "date", "") or "", comment_index=index,
        ))
    return found


def summarize(proposals: Iterable[Proposal]) -> dict[str, Any]:
    items = list(proposals)
    by_route = {route: 0 for route in ROUTES}
    for p in items:
        by_route[p.route] = by_route.get(p.route, 0) + 1
    return {
        "total": len(items),
        "outstanding": sum(1 for p in items if p.outstanding),
        "byRoute": by_route,
        "unreadable": sum(1 for p in items if p.route == ROUTE_UNREADABLE),
    }
