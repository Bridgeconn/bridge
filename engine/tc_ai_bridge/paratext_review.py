"""The Paratext QA review queue: proposals in Scripture order across one or
several books, decisions, exact application to Bridge's copy of the text, a
checked revert in both applications, reconciliation of interrupted edits, and
the session's evidence (#428, #429, #430, #431, #432, #433, #434; parent #423).

What this module is careful about, and why:

* **One Scripture writer.** An accepted body, footnote or cross-reference
  proposal is applied through the caller's ``edit`` callable, which is
  ``BridgeEngine.edit_verse`` -- the same ``apply_scripture_edit`` path as the
  editor's Save and the scoped Language QA fix: a footnote lives inside the
  verse's raw string, so editing it is editing the verse. A heading is not
  Scripture (#180: it is kept beside the verse map because its words are not
  a translation of any source word) and goes through the project's own
  journalled heading writer. Nothing here writes a chapter file. Every write
  is refused unless the text still reads exactly as it did when the reviewer
  looked at it.
* **Exact target, or nothing.** The proposal's ``Original`` must occur exactly
  once in its region -- the verse body with notes and markup lifted away, one
  footnote or cross-reference of the verse, or one heading the verse
  introduces -- on text-element boundaries; a repeat in the body is
  disambiguated only by the note's own anchor context; otherwise the apply is
  refused and the reason shown. A region never falls back into another: a
  footnote proposal is never mapped into the body. Bridge keeps no copy of a
  book introduction, so an introduction proposal can only be written into
  Paratext (the plugin's region-scoped write), and a marker rename (#430) is a
  Paratext-only structural write; neither is ever faked on Bridge's copy.
* **A decision is not an edit.** ``rejected``, ``manual`` and ``deferred``
  record what the reviewer saw and said; only ``applied`` changes text, and it
  is recorded as verified only after the saved text was read back and found to
  hold the replacement at the span. A decision row is rewritten on change, and
  every revision is a ``change_log`` row (append-only).
* **Revert is checked, in both applications.** The latest verified apply in
  this book is reverted only while the text still equals its saved post-image;
  any intervening change is refused with the mismatch, never guessed around.
  When the apply was also written into Paratext, :func:`reverse_write` builds
  the exact reverse replacement the plugin can place, and the caller queues
  it; a reverse that cannot be built exactly is reported, not approximated.
* **An interrupted apply is classified, never retried blind.** An ``applied``
  decision that was not verified is compared with the current text:
  ``verified`` (the saved text is the intended one), ``notApplied`` (the text
  is still the pre-image) or ``conflict`` (neither). The reviewer reconciles
  it explicitly before another apply on that verse.
* **Nothing resolves a Paratext thread by itself.** ``thread_completion`` says
  whether every outstanding proposal in a thread has a terminal decision --
  applied and verified (in Paratext too, when written there), rejected, or
  completed manually -- so the reviewer may be offered "Resolve in Paratext";
  ``deferred`` is not terminal, an unreadable proposal blocks, and a new
  proposal in the thread is simply a new undecided item. The resolve itself
  stays a click through the existing outbox (automatic source-thread
  resolution from Bridge decisions remains a separate policy question, #424).
"""

from __future__ import annotations

import csv
import html
import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from .paratext_project import PARATEXT_CANON
from .paratext_proposals import (
    OP_ALTERNATIVES, OP_DELETE, OP_MARKER_RENAME, OP_REPLACE, REGION_BODY, REGION_CROSS_REFERENCE,
    REGION_FOOTNOTE, REGION_HEADING, REGION_INTRODUCTION, ROUTE_LITERAL, ROUTE_REVIEW, Proposal,
    thread_proposals,
)
from .usfm_verse import lift_verse
from .workbench_repository import WorkbenchIdentity, WorkbenchRepository, natural_row_id

DECISIONS = "paratext_review_decisions"
STATE = "paratext_review_state"

APPLIED = "applied"
REJECTED = "rejected"
MANUAL = "manual"
DEFERRED = "deferred"
REVERTED = "reverted"
DECISIONS_ALL = (APPLIED, REJECTED, MANUAL, DEFERRED, REVERTED)
TERMINAL = frozenset({APPLIED, REJECTED, MANUAL})

FILTER_UNRESOLVED = "unresolved"
FILTER_RESOLVED = "resolved"
FILTER_ALL = "all"
FILTERS = (FILTER_UNRESOLVED, FILTER_RESOLVED, FILTER_ALL)

# Regions Bridge holds a copy of and can apply to (#429); an introduction is
# written into Paratext only; a structural proposal only as a marker rename.
BRIDGE_REGIONS = frozenset({REGION_BODY, REGION_FOOTNOTE, REGION_CROSS_REFERENCE, REGION_HEADING})
NOTE_REGIONS = {REGION_FOOTNOTE: "footnote", REGION_CROSS_REFERENCE: "xref"}
# #430: the heading and chapter-label markers a rename may touch, as the
# reference plugin allowlists them and Bridge's parser files them as headings.
RENAME_MARKERS = frozenset({"ms", "ms1", "ms2", "ms3", "s", "s1", "s2", "s3", "s4", "cl", "cd"})

# Reconciliation outcomes of an interrupted apply (#431).
RECONCILED_VERIFIED = "verified"
RECONCILED_NOT_APPLIED = "notApplied"
RECONCILED_CONFLICT = "conflict"
RECONCILED_PARATEXT_CHECKED = "paratextChecked"
RECONCILE_OUTCOMES = (RECONCILED_VERIFIED, RECONCILED_NOT_APPLIED, RECONCILED_CONFLICT, RECONCILED_PARATEXT_CHECKED)

# #428: five reusable comment presets, editable in the UI; a preset only
# fills the comment box.
COMMENT_PRESETS: tuple[dict[str, str], ...] = (
    {"id": "accepted", "label": "Accepted", "text": "Accepted as suggested."},
    {"id": "accepted-revised", "label": "Accepted with revision", "text": "Accepted with a revised wording (see the replacement)."},
    {"id": "retained", "label": "Existing wording retained", "text": "The existing wording is retained; it reads correctly in context."},
    {"id": "meaning", "label": "Meaning-sensitive rejection", "text": "Not applied: the suggestion would change the meaning."},
    {"id": "already", "label": "Already corrected / no change", "text": "Already corrected in the text; no further change."},
)

_MARK_CATEGORIES = {"Mn", "Mc", "Me"}
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
_CANON_RANK = {code: index for index, code in enumerate(PARATEXT_CANON)}


class ReviewError(ValueError):
    """A request the queue refuses, with the reason for the reviewer."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def book_rank(book: str) -> int:
    return _CANON_RANK.get(str(book or "").upper(), len(PARATEXT_CANON))


# ---------------------------------------------------------------------------
# Locating the Original in its region
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Match:
    start: int          # span in the region's text (plain body, raw note, heading text)
    end: int
    raw_start: int      # span in the verse's raw string (body, notes); heading: in its text
    raw_end: int
    whole_word: bool
    region: str = REGION_BODY
    index: int = -1     # the note or heading the match is in, for those regions


@dataclass
class Location:
    found: list[Match]
    chosen: Match | None
    reason: str = ""    # why nothing was chosen, for the reviewer
    text: str = ""      # the region's text the spans index into

    @property
    def ok(self) -> bool:
        return self.chosen is not None


def _is_mark(ch: str) -> bool:
    return unicodedata.category(ch) in _MARK_CATEGORIES


def _boundary(plain: str, index: int) -> bool:
    """True when `index` does not fall before a combining mark: a span that
    ends before a vowel sign or virama would cut a text element in two."""
    return index <= 0 or index >= len(plain) or not _is_mark(plain[index])


def _whole_word(plain: str, start: int, end: int) -> bool:
    before = plain[start - 1] if start > 0 else " "
    after = plain[end] if end < len(plain) else " "
    return not (before.isalnum() or _is_mark(before)) and not (after.isalnum() or _is_mark(after))


def _occurrences(text: str, original: str) -> list[tuple[int, int, bool]]:
    found: list[tuple[int, int, bool]] = []
    start = 0
    while True:
        index = text.find(original, start)
        if index < 0:
            return found
        end = index + len(original)
        start = index + 1
        if _boundary(text, index) and _boundary(text, end):
            found.append((index, end, _whole_word(text, index, end)))


def _choose(found: list[Match], text: str, context_before: str, context_after: str, where: str) -> Location:
    if len(found) == 1:
        return Location(found, found[0], text=text)
    collapse = lambda s: re.sub(r"\s+", " ", s or "").strip()  # noqa: E731
    before, after = collapse(context_before), collapse(context_after)
    if before or after:
        anchored = [m for m in found
                    if (not before or collapse(text[:m.start]).endswith(before))
                    and (not after or collapse(text[m.end:]).startswith(after))]
        if len(anchored) == 1:
            return Location(found, anchored[0], text=text)
    whole = [m for m in found if m.whole_word]
    if len(whole) == 1:
        return Location(found, whole[0], text=text)
    return Location(found, None, f"The Original occurs {len(found)} times in {where} and the note's context "
                                 "does not identify one of them; nothing was changed.", text=text)


def locate(raw_verse: str, original: str, *, region: str = REGION_BODY,
           context_before: str = "", context_after: str = "") -> Location:
    """Where `original` is in the verse's `region`. Body: the plain text with
    notes and markup lifted away; exactly one match wins, several are
    narrowed by the note's own context (whitespace-collapsed, as the plugin
    compares it, #358 h), then by whole-word matches; still several is
    ambiguous and nothing is chosen. Footnote / cross-reference: inside one of
    the verse's notes of that kind (its raw text, markers and all), unique
    across them. Never another region: a footnote proposal is not looked for
    in the body."""
    if not original:
        return Location([], None, "The note has no Original text to find.")
    if "\\" in original:
        return Location([], None, "The Original carries a USFM marker; that is a structural proposal, review-only.")
    lifted = lift_verse(raw_verse or "")
    if region in NOTE_REGIONS:
        kind = NOTE_REGIONS[region]
        label = "footnote" if region == REGION_FOOTNOTE else "cross-reference"
        notes = [(i, n) for i, n in enumerate(lifted.notes) if n.kind == kind]
        if not notes:
            return Location([], None, f"This verse has no {label} in Bridge's copy; the proposal is review-only here.")
        found: list[Match] = []
        text = ""
        for index, note in notes:
            segment = lifted.raw[note.raw_start:note.raw_end]
            for start, end, whole in _occurrences(segment, original):
                found.append(Match(start, end, note.raw_start + start, note.raw_start + end, whole, region, index))
                text = segment
        if not found:
            return Location([], None, f"The exact Original was not found in this verse's {label}; it may be stale "
                                      "or already corrected.")
        if len({m.index for m in found}) > 1:
            return Location(found, None, f"The Original occurs in {len({m.index for m in found})} {label}s of this "
                                         "verse; nothing was changed.", text=text)
        return _choose(found, text, "", "", f"this {label}")
    if region != REGION_BODY:
        return Location([], None, f"The {region} is not located in the verse text.")
    plain = lifted.plain
    found = []
    for start, end, whole in _occurrences(plain, original):
        span = lifted.raw_span(start, end)
        if span is None:
            continue            # the text runs across markup or a note: not one span
        found.append(Match(start, end, span[0], span[1], whole, REGION_BODY))
    if not found:
        if original in plain:
            return Location([], None, "The Original is in the verse only across markup or a footnote; "
                                      "it cannot be replaced as one span.", text=plain)
        return Location([], None, "The exact Original was not found in this verse. It may be stale, "
                                  "already corrected, or in a footnote or heading rather than the body.", text=plain)
    return _choose(found, plain, context_before, context_after, "this verse")


def locate_heading(headings: list[dict[str, Any]], original: str) -> Location:
    """Where `original` is among the headings a verse introduces (#180's
    `<chapter>.headings.json` entries, `{tag, text}`): unique across them."""
    if not original:
        return Location([], None, "The note has no Original text to find.")
    if not headings:
        return Location([], None, "This verse introduces no heading in Bridge's copy; the proposal is review-only here.")
    found: list[Match] = []
    text = ""
    for index, heading in enumerate(headings):
        label = str(heading.get("text") or "")
        for start, end, whole in _occurrences(label, original):
            found.append(Match(start, end, start, end, whole, REGION_HEADING, index))
            text = label
    if not found:
        return Location([], None, "The exact Original was not found in this verse's heading; it may be stale "
                                  "or already corrected.")
    if len({m.index for m in found}) > 1:
        return Location(found, None, "The Original occurs in more than one heading at this verse; nothing was changed.",
                        text=text)
    return _choose(found, text, "", "", "this heading")


def replaced_raw(raw_verse: str, match: Match, replacement: str) -> str:
    return raw_verse[:match.raw_start] + replacement + raw_verse[match.raw_end:]


def widen_deletion(text: str, raw: str | None, match: Match) -> Match:
    """#442: a deletion whose span sits between two spaces takes the space
    after it, so one space remains. A bare deletion left a double space that
    Paratext normalises on save, so its text no longer matched Bridge's, the
    write could not be verified there and the exact reverse was unlocatable.
    Widened only when both neighbours in the region text are whitespace and,
    where a raw verse is given, the same character follows the span in it
    (markup between the two is left alone). The decision's `original` then
    carries the space, and so does every write and reverse built from it."""
    end = match.end
    if match.start <= 0 or end >= len(text) or not text[end].isspace() or not text[match.start - 1].isspace():
        return match
    if raw is not None and (match.raw_end >= len(raw) or raw[match.raw_end] != text[end]):
        return match
    return Match(match.start, end + 1, match.raw_start, match.raw_end + 1, match.whole_word, match.region, match.index)


def check_replacement(replacement: str) -> None:
    if "\\" in replacement or "\n" in replacement or "\r" in replacement or "\0" in replacement:
        raise ReviewError("A replacement cannot carry USFM markers or line breaks; that is a structural change, review-only.")


def region_text(raw_verse: str, match: Match) -> str:
    """The text a match's spans index into, from the verse as it reads now."""
    lifted = lift_verse(raw_verse or "")
    if match.region in NOTE_REGIONS:
        if 0 <= match.index < len(lifted.notes):
            note = lifted.notes[match.index]
            return lifted.raw[note.raw_start:note.raw_end]
        return ""
    return lifted.plain


def marker_rename(proposal: dict[str, Any]) -> dict[str, str]:
    """The exact marker rename a structural proposal asks for (#430), or a
    ReviewError: only the allowlisted heading / chapter-label markers, the
    label text unchanged, the markers different."""
    structural = proposal.get("structural") or {}
    if proposal.get("operation") != OP_MARKER_RENAME or not structural:
        raise ReviewError("Only an exact heading or chapter-label marker rename with the label text unchanged can "
                          "be applied; this structural proposal is review-only.")
    source, target = str(structural.get("fromMarker") or ""), str(structural.get("toMarker") or "")
    label = str(structural.get("label") or "").strip()
    if source not in RENAME_MARKERS or target not in RENAME_MARKERS:
        raise ReviewError(f"A rename from \\{source} to \\{target} is outside the allowed heading markers "
                          f"({', '.join(sorted(RENAME_MARKERS))}); review-only.")
    if source == target or not label:
        raise ReviewError("The rename names the same marker twice or has no label; review-only.")
    return {"fromMarker": source, "toMarker": target, "label": label}


# ---------------------------------------------------------------------------
# The queue
# ---------------------------------------------------------------------------

def _verse_number(verse: str) -> int:
    match = re.match(r"\s*(\d+)", str(verse or ""))
    return int(match.group(1)) if match else 0


def queue_items(threads: Iterable[Any], *, status: str = FILTER_UNRESOLVED,
                start_book: str = "") -> list[dict[str, Any]]:
    """One item per outstanding proposal of the given threads (NoteThread
    objects, from one or several books), in Scripture order: book (canon),
    chapter, verse, thread's first date, comment, block. `status` keeps open
    threads, resolved ones, or both. With `start_book` (#432) the order starts
    at that book and continues forward through the scope; the books before it
    come last, each of their items flagged `wrapped`, so the reviewer is told
    where the wraparound happens rather than finding it. No-change and
    historical proposals are not queued; unreadable ones are, so a person sees
    them."""
    if status not in FILTERS:
        raise ReviewError(f"status must be one of {list(FILTERS)}")
    start_rank = book_rank(start_book) if start_book else 0
    items: list[tuple[tuple[int, int, int, int, str, int, int], dict[str, Any]]] = []
    for thread in threads:
        if getattr(thread, "kind", "note") != "note" or thread.ref is None:
            continue
        if status == FILTER_UNRESOLVED and thread.resolved:
            continue
        if status == FILTER_RESOLVED and not thread.resolved:
            continue
        proposals = thread_proposals(thread.id, thread.comments)
        outstanding = [p for p in proposals if p.outstanding]
        rank = book_rank(thread.ref.book)
        wrapped = bool(start_book) and rank < start_rank
        for proposal in outstanding:
            key = (1 if wrapped else 0, rank, int(thread.ref.chapter), _verse_number(thread.ref.verse),
                   thread.comments[0].date, proposal.commentIndex, proposal.block)
            items.append((key, {
                "proposalId": proposal.proposalId, "threadId": thread.id,
                "book": str(thread.ref.book).upper(), "chapter": str(thread.ref.chapter), "verse": str(thread.ref.verse),
                "verseRef": thread.verse_ref, "threadResolved": thread.resolved,
                "selectedText": thread.selected_text,
                "contextBefore": thread.comments[0].context_before, "contextAfter": thread.comments[0].context_after,
                "proposal": proposal.to_json(),
                "threadOutstanding": len(outstanding),
                "wrapped": wrapped,
            }))
    items.sort(key=lambda pair: pair[0])
    return [item for _, item in items]


def normalize_state(current: dict[str, Any] | None, patch: dict[str, Any] | None) -> dict[str, Any]:
    """The queue's own state (#432): filter, scope (books and starting book),
    position, drafts and the session start, merged with a patch. Kept
    app-side per linked Paratext project so it survives a book switch, a
    close and a restart. An empty draft is dropped."""
    state = {"status": FILTER_UNRESOLVED, "scope": {"books": [], "startBook": ""}, "position": "", "drafts": {},
             "sessionStartedAt": ""}
    for source in (current or {}, patch or {}):
        for key in ("status", "position", "sessionStartedAt"):
            if key in source:
                state[key] = str(source[key] or "")
        if isinstance(source.get("scope"), dict):
            scope = source["scope"]
            books = [str(b).upper() for b in (scope.get("books") or []) if str(b).strip()]
            state["scope"] = {"books": sorted(set(books), key=book_rank),
                              "startBook": str(scope.get("startBook") or "").upper()}
        if isinstance(source.get("drafts"), dict):
            state["drafts"] = {k: v for k, v in source["drafts"].items() if isinstance(v, dict) and (
                str(v.get("replacement") or "").strip() or str(v.get("comment") or "").strip())}
    if state["status"] not in FILTERS:
        raise ReviewError(f"status must be one of {list(FILTERS)}")
    if state["scope"]["startBook"] and state["scope"]["books"] and state["scope"]["startBook"] not in state["scope"]["books"]:
        state["scope"]["startBook"] = state["scope"]["books"][0]
    return state


def prune_drafts(state: dict[str, Any], proposal_ids: set[str]) -> tuple[dict[str, Any], list[str]]:
    """Drafts for proposals no longer in the scanned notes are stale -- the
    thread changed, was deleted, or its comment was edited (a proposal id is
    a hash of its content) -- and are never offered as a valid correction
    again (#432). Returns the state and the dropped ids."""
    drafts = dict(state.get("drafts") or {})
    dropped = [pid for pid in drafts if pid not in proposal_ids]
    for pid in dropped:
        drafts.pop(pid)
    return {**state, "drafts": drafts}, dropped


class ReviewStore:
    """Decisions of one book, written as `identity`."""

    def __init__(self, workbench: WorkbenchRepository, identity: WorkbenchIdentity, book_id: str):
        self.workbench = workbench
        self.identity = identity
        self.book_id = book_id

    def _decision_id(self, proposal_id: str) -> str:
        return natural_row_id(self.identity.project_id, self.book_id, "paratext_review", proposal_id)

    @staticmethod
    def _row_payload(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        import json
        payload = json.loads(row.get("payload_json") or "{}")
        payload["revision"] = int(row.get("revision") or 1)
        payload["updatedAt"] = row.get("updated_at") or ""
        return payload

    def decision(self, proposal_id: str) -> dict[str, Any] | None:
        return self._row_payload(self.workbench.get(DECISIONS, self._decision_id(proposal_id)))

    def decisions(self) -> list[dict[str, Any]]:
        rows = self.workbench.rows(DECISIONS, project_id=self.identity.project_id, book_id=self.book_id)
        return [p for p in (self._row_payload(r) for r in rows) if p is not None]

    def decisions_for_thread(self, thread_id: str) -> list[dict[str, Any]]:
        rows = self.workbench.rows(DECISIONS, project_id=self.identity.project_id, book_id=self.book_id,
                                   equals={"thread_id": thread_id})
        return [p for p in (self._row_payload(r) for r in rows) if p is not None]

    def write_decision(self, payload: dict[str, Any]) -> dict[str, Any]:
        proposal_id = str(payload["proposalId"])
        payload = {k: v for k, v in payload.items() if k not in ("revision", "updatedAt")}
        self.workbench._write(
            DECISIONS, self._decision_id(proposal_id), project_id=self.identity.project_id, book_id=self.book_id,
            payload=payload, actor_id=self.identity.actor_id, device_id=self.identity.device_id,
            expected_revision=None, op=f"decision:{payload.get('decision')}",
            extra_columns={"proposal_id": proposal_id, "thread_id": str(payload.get("threadId") or ""),
                           "decision": str(payload.get("decision") or ""),
                           "verified": 1 if payload.get("verified") else 0},
        )
        return self.decision(proposal_id)  # type: ignore[return-value]


def peek_decisions(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Decision payloads from raw `paratext_review_decisions` rows read from a
    sibling's workbench (read-only; the dashboard's `_peek_workbench` route)."""
    out = []
    for row in rows:
        payload = ReviewStore._row_payload(dict(row))
        if payload is not None:
            out.append(payload)
    return out


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------

def paratext_pending(decision: dict[str, Any]) -> str:
    """Why an applied decision's Paratext write is not settled, or ""."""
    pt = decision.get("paratext") or {}
    if not pt:
        return ""
    status = str(pt.get("status") or "")
    if status == "sent":
        return "" if pt.get("verified") or (decision.get("reconciled") or {}).get("paratextChecked") else \
            "written to Paratext but not verified there"
    if status == "not_sent":
        return ""
    return f"Paratext write {status or 'pending'}"


def thread_completion(items_in_thread: list[dict[str, Any]], decisions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Whether every outstanding proposal of a thread has a terminal
    decision, so the reviewer may be offered "Resolve in Paratext" (#433). An
    unreadable proposal, a deferred one, an apply that was not verified, one
    whose Paratext write is still queued or unverified, or one left in
    conflict keeps the thread open."""
    blocking: list[str] = []
    for item in items_in_thread:
        proposal = item["proposal"]
        decision = decisions.get(item["proposalId"])
        if proposal.get("route") == "unreadable":
            blocking.append(f"{item['proposalId']}: unreadable")
        elif decision is None or decision.get("decision") not in TERMINAL:
            blocking.append(f"{item['proposalId']}: {decision.get('decision') if decision else 'undecided'}")
        elif decision.get("decision") == APPLIED and not decision.get("verified"):
            blocking.append(f"{item['proposalId']}: applied but not verified")
        elif decision.get("decision") == APPLIED and paratext_pending(decision):
            blocking.append(f"{item['proposalId']}: {paratext_pending(decision)}")
    return {"complete": not blocking and bool(items_in_thread), "blocking": blocking}


def apply_proposal(
    *, item: dict[str, Any], replacement: str, raw_verse: str,
    edit: Callable[[str, str, str, str], dict[str, Any]], read_back: Callable[[str, str], str],
    confirm_delete: bool = False,
) -> dict[str, Any]:
    """Apply one body, footnote or cross-reference proposal to Bridge's copy
    of the verse through `edit` (chapter, verse, new_raw, expected_old_raw)
    and verify by reading the verse again. Returns the decision payload
    fragment. Raises ReviewError with the reason when it must not happen."""
    proposal = item["proposal"]
    route, operation, region = proposal.get("route"), proposal.get("operation"), proposal.get("region")
    if route not in (ROUTE_LITERAL, ROUTE_REVIEW):
        raise ReviewError(f"A proposal routed \"{route}\" cannot be applied here; it is review-only.")
    if region == REGION_INTRODUCTION:
        raise ReviewError("Bridge keeps no copy of the book introduction; this correction can only be written into "
                          "Paratext (tick \"Also write to Paratext\").")
    if region not in (REGION_BODY, REGION_FOOTNOTE, REGION_CROSS_REFERENCE):
        raise ReviewError(f"The proposal targets the {region}, not the verse text; it is review-only here.")
    if operation not in (OP_REPLACE, OP_ALTERNATIVES, OP_DELETE):
        raise ReviewError(f"A \"{operation}\" proposal needs its text chosen by the reviewer; it cannot be applied as it is.")
    original = str(proposal.get("original") or "")
    replacement = str(replacement if replacement is not None else "")
    check_replacement(replacement)
    if operation == OP_DELETE or replacement == "":
        if not confirm_delete:
            raise ReviewError("This apply deletes text; confirm the deletion with its exact extent first.")
        replacement = ""
    if replacement == original:
        raise ReviewError("The replacement equals the Original; nothing would change.")
    location = locate(raw_verse, original, region=region, context_before=item.get("contextBefore", ""),
                      context_after=item.get("contextAfter", ""))
    if not location.ok:
        raise ReviewError(location.reason)
    match = location.chosen
    assert match is not None
    before_text = region_text(raw_verse, match)
    if replacement == "":
        match = widen_deletion(before_text, raw_verse, match)
        original = before_text[match.start:match.end]
    new_raw = replaced_raw(raw_verse, match, replacement)
    result = edit(item["chapter"], item["verse"], new_raw, raw_verse)
    saved_raw = read_back(item["chapter"], item["verse"])
    saved_text = region_text(saved_raw, match)
    # The writer trims an ordinary edit; the read-back is compared trimmed
    # the same way, and must hold the replacement where the span was.
    verified = saved_raw == new_raw.strip() and saved_text[match.start:match.start + len(replacement)] == replacement
    return {
        "original": original, "replacement": replacement, "region": region,
        "span": {"plainStart": match.start, "plainEnd": match.end, "rawStart": match.raw_start, "rawEnd": match.raw_end,
                 "index": match.index},
        "before": {"raw": raw_verse, "plain": before_text},
        "after": {"raw": saved_raw, "plain": saved_text},
        "verified": verified,
        "journalTransactionId": str(result.get("journalTransactionId") or ""),
        "unverifiedReason": "" if verified else "The saved text does not read as the apply intended; treat this edit as unverified.",
    }


def apply_heading_proposal(
    *, item: dict[str, Any], replacement: str, headings: list[dict[str, Any]],
    edit_heading: Callable[[str, str, int, str, str], dict[str, Any]],
    read_headings: Callable[[str, str], list[dict[str, Any]]],
    confirm_delete: bool = False,
) -> dict[str, Any]:
    """Apply one heading proposal (#429) to the heading the verse introduces,
    through the project's journalled heading writer `edit_heading`
    (chapter, verse, index, new_text, expected_old_text); verified by reading
    the headings again. The heading file is not Scripture (#180) and this is
    not the verse writer; nothing here touches a chapter's verse map."""
    proposal = item["proposal"]
    if proposal.get("route") not in (ROUTE_LITERAL, ROUTE_REVIEW) or proposal.get("region") != REGION_HEADING:
        raise ReviewError("Only a literal heading correction can be applied here.")
    if proposal.get("operation") not in (OP_REPLACE, OP_ALTERNATIVES, OP_DELETE):
        raise ReviewError(f"A \"{proposal.get('operation')}\" proposal needs its text chosen by the reviewer.")
    original = str(proposal.get("original") or "")
    replacement = str(replacement if replacement is not None else "")
    check_replacement(replacement)
    if proposal.get("operation") == OP_DELETE or replacement == "":
        if not confirm_delete:
            raise ReviewError("This apply deletes text from the heading; confirm the deletion with its exact extent first.")
        replacement = ""
    if replacement == original:
        raise ReviewError("The replacement equals the Original; nothing would change.")
    location = locate_heading(headings, original)
    if not location.ok:
        raise ReviewError(location.reason)
    match = location.chosen
    assert match is not None
    old_text = str(headings[match.index].get("text") or "")
    if replacement == "":
        match = widen_deletion(old_text, None, match)
        original = old_text[match.start:match.end]
    new_text = old_text[:match.start] + replacement + old_text[match.end:]
    if not new_text.strip():
        raise ReviewError("The heading would be left empty; remove a heading in the editor instead.")
    result = edit_heading(item["chapter"], item["verse"], match.index, new_text, old_text)
    saved = read_headings(item["chapter"], item["verse"])
    saved_text = str(saved[match.index].get("text") or "") if 0 <= match.index < len(saved) else ""
    verified = saved_text == new_text
    return {
        "original": original, "replacement": replacement, "region": REGION_HEADING,
        "span": {"plainStart": match.start, "plainEnd": match.end, "rawStart": match.start, "rawEnd": match.end,
                 "index": match.index},
        "before": {"raw": old_text, "plain": old_text, "tag": str(headings[match.index].get("tag") or "")},
        "after": {"raw": saved_text, "plain": saved_text, "tag": str(headings[match.index].get("tag") or "")},
        "verified": verified,
        "journalTransactionId": str(result.get("journalTransactionId") or ""),
        "unverifiedReason": "" if verified else "The saved heading does not read as the apply intended; treat this edit as unverified.",
    }


# ---------------------------------------------------------------------------
# Revert (#431), in both applications
# ---------------------------------------------------------------------------

def _word_before(text: str, at: int) -> tuple[int, str]:
    """(start, word) of the nearest word ending at or before `at`, stopping
    at a USFM marker; ("" when none)."""
    end = at
    while end > 0 and text[end - 1].isspace():
        end -= 1
    start = end
    while start > 0 and not text[start - 1].isspace() and text[start - 1] != "\\":
        start -= 1
    word = text[start:end]
    return (start, word) if word and "\\" not in word else (at, "")


def _word_after(text: str, at: int) -> tuple[int, str]:
    start = at
    while start < len(text) and text[start].isspace():
        start += 1
    end = start
    while end < len(text) and not text[end].isspace() and text[end] != "\\":
        end += 1
    word = text[start:end]
    return (end, word) if word and "\\" not in word else (at, "")


def reverse_write(decision: dict[str, Any]) -> dict[str, Any]:
    """The exact Paratext replacement that undoes an applied decision there
    (#431): `original` is what the apply wrote, `replacement` what stood
    before, with the words around them as context, as the plugin places a
    write. A deletion is undone by replacing the window of text around the
    gap (the word before, the word after) with the same window holding the
    deleted text again, because the plugin can only replace text it finds.
    Raises ReviewError when no exact reverse can be built; nothing is ever
    approximated."""
    after_text = str((decision.get("after") or {}).get("plain") or "")
    before_text = str((decision.get("before") or {}).get("plain") or "")
    span = decision.get("span") or {}
    start = int(span.get("plainStart") or 0)
    original = str(decision.get("original") or "")
    replacement = str(decision.get("replacement") or "")
    region = str(decision.get("region") or REGION_BODY)
    if not after_text or not before_text or not original:
        raise ReviewError("The decision carries no snapshot to build the reverse from.")
    if after_text[start:start + len(replacement)] != replacement:
        raise ReviewError("The saved snapshot does not hold the replacement at its span; the reverse cannot be built.")
    if replacement:
        _, before_word = _word_before(after_text, start)
        _, after_word = _word_after(after_text, start + len(replacement))
        return {"original": replacement, "replacement": original, "beforeContext": before_word,
                "afterContext": after_word, "region": region, "allowDelete": False}
    a, before_word = _word_before(after_text, start)
    b, after_word = _word_after(after_text, start)
    window = after_text[a:b]
    if not window.strip():
        raise ReviewError("The deleted text has no neighbouring words to anchor its restoration in Paratext.")
    restored = window[:start - a] + original + window[start - a:]
    _, before_ctx = _word_before(after_text, a)
    _, after_ctx = _word_after(after_text, b)
    return {"original": window, "replacement": restored, "beforeContext": before_ctx, "afterContext": after_ctx,
            "region": region, "allowDelete": False}


def latest_verified_apply(decisions: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    applied = [d for d in decisions if d.get("decision") == APPLIED and d.get("verified")]
    return max(applied, key=lambda d: str(d.get("decidedAt") or "")) if applied else None


def revert_latest(
    store: ReviewStore, *, read_back: Callable[[str, str], str],
    edit: Callable[[str, str, str, str], dict[str, Any]], username: str,
    read_headings: Callable[[str, str], list[dict[str, Any]]] | None = None,
    edit_heading: Callable[[str, str, int, str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Revert the latest verified apply in this book, only while the text
    still equals its saved post-image. Returns the reverted decision, with
    `paratextReverse` (the reverse write to queue for Paratext, or the reason
    none could be built) when the apply was written into Paratext."""
    latest = latest_verified_apply(store.decisions())
    if latest is None:
        raise ReviewError("There is no verified applied correction in this book to revert.")
    region = str(latest.get("region") or REGION_BODY)
    after_raw = str((latest.get("after") or {}).get("raw") or "")
    before_raw = str((latest.get("before") or {}).get("raw") or "")
    if region == REGION_HEADING:
        if read_headings is None or edit_heading is None:
            raise ReviewError("Heading reverts are not available here.")
        index = int((latest.get("span") or {}).get("index") or 0)
        headings = read_headings(latest["chapter"], latest["verse"])
        current = str(headings[index].get("text") or "") if 0 <= index < len(headings) else ""
        if current != after_raw:
            raise ReviewError(
                f"The heading at {latest['verseRef']} no longer reads as the correction left it (someone changed it "
                f"since); the revert is refused so that change is not lost. Current text: “{current}”")
        result = edit_heading(latest["chapter"], latest["verse"], index, before_raw, after_raw)
        saved = read_headings(latest["chapter"], latest["verse"])
        restored = str(saved[index].get("text") or "") if 0 <= index < len(saved) else ""
    else:
        current = read_back(latest["chapter"], latest["verse"])
        if current != after_raw:
            raise ReviewError(
                f"{latest['verseRef']} no longer reads as the correction left it (someone changed it since); "
                "the revert is refused so that change is not lost. Current text: "
                f"“{lift_verse(current).plain}”")
        result = edit(latest["chapter"], latest["verse"], before_raw, after_raw)
        restored = read_back(latest["chapter"], latest["verse"])
    payload = dict(latest)
    payload.update({
        "decision": REVERTED, "revertedAt": _now(), "revertedBy": username,
        "revertVerified": restored == before_raw,
        "revertJournalTransactionId": str(result.get("journalTransactionId") or ""),
    })
    pt = latest.get("paratext") or {}
    if pt.get("status") == "sent":
        try:
            payload["paratextReverse"] = {"request": reverse_write(latest), "status": "pending"}
        except ReviewError as exc:
            payload["paratextReverse"] = {"request": None, "status": "manual",
                                          "reason": f"{exc} Restore the text in Paratext by hand."}
    return store.write_decision(payload)


# ---------------------------------------------------------------------------
# Interrupted applies (#431)
# ---------------------------------------------------------------------------

def classify_apply(decision: dict[str, Any], current: str) -> str:
    """What an `applied` decision's text looks like now: `verified` (the
    saved text is the intended post-image), `notApplied` (still the
    pre-image) or `conflict` (neither: another edit, or a partial save)."""
    if decision.get("verified"):
        return RECONCILED_VERIFIED
    after_raw = str((decision.get("after") or {}).get("raw") or "")
    before_raw = str((decision.get("before") or {}).get("raw") or "")
    span = decision.get("span") or {}
    replacement = str(decision.get("replacement") or "")
    if current == after_raw and after_raw:
        region = str(decision.get("region") or REGION_BODY)
        text = current if region == REGION_HEADING else region_text(current, Match(
            int(span.get("plainStart") or 0), int(span.get("plainEnd") or 0), int(span.get("rawStart") or 0),
            int(span.get("rawEnd") or 0), True, region, int(span.get("index", -1))))
        start = int(span.get("plainStart") or 0)
        if text[start:start + len(replacement)] == replacement:
            return RECONCILED_VERIFIED
    if current == before_raw:
        return RECONCILED_NOT_APPLIED
    return RECONCILED_CONFLICT


def uncertain_decisions(decisions: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Applied decisions that need the reviewer's reconciliation: not
    verified in Bridge and not yet reconciled, or written to Paratext without
    verification there and not yet checked."""
    out = []
    for d in decisions:
        if d.get("decision") != APPLIED:
            continue
        reconciled = d.get("reconciled") or {}
        if not d.get("verified") and reconciled.get("state") != RECONCILED_CONFLICT and not reconciled.get("state"):
            out.append(d)
        elif reconciled.get("state") == RECONCILED_CONFLICT:
            out.append(d)
        elif paratext_pending(d) == "written to Paratext but not verified there":
            out.append(d)
    return out


def reconcile(store: ReviewStore, decision: dict[str, Any], outcome: str, *, observed: str, username: str,
              note: str = "") -> dict[str, Any]:
    """Record the reviewer's explicit reconciliation of an interrupted apply
    (#431). `verified` marks it verified from the observed text; `notApplied`
    returns it to `deferred` so it can be applied again (the observed text
    is kept); `conflict` keeps it applied-unverified and blocks further
    applies on the verse until a manual or rejected decision replaces it;
    `paratextChecked` records that the reviewer looked in Paratext. Each is
    a new revision of the row; the previous one is in change_log."""
    if outcome not in RECONCILE_OUTCOMES:
        raise ReviewError(f"outcome must be one of {list(RECONCILE_OUTCOMES)}")
    if decision.get("decision") != APPLIED:
        raise ReviewError("Only an applied decision can be reconciled.")
    payload = dict(decision)
    record = {"state": outcome, "at": _now(), "by": username, "note": note,
              "observed": observed, "classified": classify_apply(decision, observed)}
    previous = dict(decision.get("reconciled") or {})
    if outcome == RECONCILED_VERIFIED:
        if record["classified"] != RECONCILED_VERIFIED:
            raise ReviewError("The current text is not the intended result of this apply; it cannot be marked verified.")
        payload["verified"] = True
        payload["unverifiedReason"] = ""
        payload["after"] = {**(payload.get("after") or {}), "raw": observed}
    elif outcome == RECONCILED_NOT_APPLIED:
        if record["classified"] != RECONCILED_NOT_APPLIED:
            raise ReviewError("The current text is not the pre-image of this apply; it cannot be marked not applied.")
        payload["decision"] = DEFERRED
        payload["verified"] = False
    elif outcome == RECONCILED_PARATEXT_CHECKED:
        record = {**previous, "paratextChecked": True, "paratextCheckedAt": record["at"], "paratextCheckedBy": username,
                  "paratextNote": note}
        if "state" not in record:
            record["state"] = RECONCILED_VERIFIED if decision.get("verified") else previous.get("state", "")
    payload["reconciled"] = record
    return store.write_decision(payload)


# ---------------------------------------------------------------------------
# Evidence: CSV and the HTML session report (#434)
# ---------------------------------------------------------------------------

CSV_COLUMNS = ("reference", "book", "chapter", "verse", "region", "threadId", "proposalId", "pass", "category",
               "decision", "verified", "original", "replacement", "comment", "reviewer", "bridgeUserId",
               "bridgeUserName", "decidedAt", "paratextWrite", "paratextVerified", "paratextAuthor",
               "reconciled", "threadResolved", "resolutionOrigin", "resolvedBy")


def _csv_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    if text.startswith(_FORMULA_START):
        return "'" + text
    return text


def _closure(d: dict[str, Any]) -> dict[str, Any]:
    return dict(d.get("threadClosure") or {})


def _sort_key(x: dict[str, Any]) -> tuple[int, int, int, str]:
    return (book_rank(x.get("book") or ""), int(x.get("chapter") or 0), _verse_number(x.get("verse") or ""),
            str(x.get("decidedAt") or ""))


def decisions_csv(decisions: Iterable[dict[str, Any]]) -> str:
    """UTF-8 text (the writer adds the BOM) with spreadsheet-safe cells:
    quotes and newlines are quoted by the csv module, and a cell that would
    read as a formula is prefixed with an apostrophe. Names the Bridge user
    who initiated a change, Paratext's own editor of record when the text
    was written there, and where the thread was resolved (DECISIONS
    2026-11-02)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for d in sorted(decisions, key=_sort_key):
        pt = d.get("paratext") or {}
        user = d.get("bridgeUser") or {}
        closure = _closure(d)
        writer.writerow([
            _csv_cell(d.get("verseRef")), _csv_cell(d.get("book")), _csv_cell(d.get("chapter")), _csv_cell(d.get("verse")),
            _csv_cell(d.get("region") or ("body" if d.get("decision") in (APPLIED, REVERTED) else "")),
            _csv_cell(d.get("threadId")), _csv_cell(d.get("proposalId")), _csv_cell(d.get("pass")),
            _csv_cell(d.get("category")), _csv_cell(d.get("decision")),
            "yes" if d.get("verified") else "no" if d.get("decision") == APPLIED else "",
            _csv_cell(d.get("original")), _csv_cell(d.get("replacement")), _csv_cell(d.get("comment")),
            _csv_cell(d.get("reviewer")), _csv_cell(user.get("userId")), _csv_cell(user.get("displayName")),
            _csv_cell(d.get("decidedAt")),
            _csv_cell(pt.get("status") or ""), ("yes" if pt.get("verified") else "no") if pt.get("status") == "sent" else "",
            _csv_cell(pt.get("author") or ""), _csv_cell((d.get("reconciled") or {}).get("state") or ""),
            "yes" if d.get("threadResolved") or closure else "no",
            _csv_cell(closure.get("status") or ""), _csv_cell(closure.get("actor") or ""),
        ])
    return buffer.getvalue()


def write_csv(path: str | Path, decisions: Iterable[dict[str, Any]]) -> dict[str, Any]:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = list(decisions)
    target.write_text(decisions_csv(rows), encoding="utf-8-sig", newline="")
    return {"written": True, "path": str(target), "count": len(rows)}


def _highlight(plain: str, span: dict[str, Any] | None, text: str, cls: str) -> str:
    if not span or not text:
        return html.escape(plain)
    start = int(span.get("plainStart") or 0)
    end = start + len(text)
    if plain[start:end] != text:
        return html.escape(plain)
    return f"{html.escape(plain[:start])}<mark class=\"{cls}\">{html.escape(text)}</mark>{html.escape(plain[end:])}"


def _paratext_line(d: dict[str, Any]) -> str:
    pt = d.get("paratext") or {}
    if not pt:
        return ""
    status = str(pt.get("status") or "")
    if status == "sent":
        who = f" by Paratext user {html.escape(str(pt.get('author') or ''))}" if pt.get("author") else ""
        return (f"<p class=\"meta\">Paratext: written{who} · "
                f"{'read back and verified' if pt.get('verified') else 'NOT verified there'}</p>")
    return f"<p class=\"meta\">Paratext: {html.escape(status)} · {html.escape(str(pt.get('lastError') or ''))}</p>"


def session_report_html(*, project_name: str, book: str, reviewer: str, decisions: list[dict[str, Any]],
                        since: str, generated_at: str, bridge_user: dict[str, Any] | None = None) -> str:
    """A self-contained, offline HTML report of the decisions given. Every
    note and verse string is escaped. An applied decision is labelled
    verified only when its saved text was read back; a rejected one shows the
    text unchanged; a manual one shows what was observed, not who edited it;
    an interrupted one says so. Names the Bridge user, Paratext's own editor
    of record and the thread's resolution origin (DECISIONS 2026-11-02)."""
    rows = []
    for d in sorted(decisions, key=_sort_key):
        decision = str(d.get("decision") or "")
        before = (d.get("before") or {}).get("plain") or (d.get("observed") or {}).get("plain") or ""
        after = (d.get("after") or {}).get("plain") or ""
        reconciled = d.get("reconciled") or {}
        if decision == APPLIED:
            if d.get("verified"):
                label = "Applied · verified" + (" after reconciliation" if reconciled.get("state") == RECONCILED_VERIFIED else "")
            elif reconciled.get("state") == RECONCILED_CONFLICT:
                label = "Applied · interrupted, in conflict with the current text"
            else:
                label = "Applied · NOT verified (interrupted or unverified attempt)"
            snapshot = (f"<div class=\"snap\"><b>Before</b> {_highlight(before, d.get('span'), d.get('original', ''), 'was')}</div>"
                        f"<div class=\"snap\"><b>After</b> {_highlight(after, d.get('span'), d.get('replacement', ''), 'now')}</div>")
        elif decision == REVERTED:
            label = "Reverted" + ("" if d.get("revertVerified") else " · NOT verified")
            snapshot = f"<div class=\"snap\"><b>Restored</b> {html.escape(before)}</div>"
            reverse = d.get("paratextReverse") or {}
            if reverse:
                snapshot += f"<p class=\"meta\">Paratext reverse: {html.escape(str(reverse.get('status') or ''))} {html.escape(str(reverse.get('reason') or ''))}</p>"
        elif decision == REJECTED:
            label = "Rejected · text unchanged"
            snapshot = f"<div class=\"snap\"><b>Text</b> {html.escape(before)}</div>"
        elif decision == MANUAL:
            label = "Completed manually / no change · observed, not authored by Bridge"
            snapshot = f"<div class=\"snap\"><b>Observed</b> {html.escape(before)}</div>"
        else:
            label = "Left for later"
            if reconciled.get("state") == RECONCILED_NOT_APPLIED:
                label += " · an earlier apply was found not applied"
            snapshot = ""
        if not before and decision != DEFERRED:
            snapshot = "<div class=\"snap muted\">No snapshot was recorded for this decision.</div>"
        closure = _closure(d)
        user = d.get("bridgeUser") or {}
        who = html.escape(str(user.get("displayName") or d.get("reviewer") or ""))
        if user.get("userId"):
            who += f" ({html.escape(str(user['userId']))})"
        thread_state = ("resolved in Paratext" if closure.get("origin") == "paratext"
                        else "resolved in Bridge" if closure.get("origin") == "bridge"
                        else "resolved" if d.get("threadResolved") else "open")
        if closure.get("actor"):
            thread_state += f" by {html.escape(str(closure['actor']))}"
        region = str(d.get("region") or "")
        rows.append(
            f"<article class=\"d {html.escape(decision)}\" data-decision=\"{html.escape(decision)}\">"
            f"<h3>{html.escape(str(d.get('verseRef') or ''))}{(' · ' + html.escape(region)) if region and region != 'body' else ''} <small>{html.escape(label)}</small></h3>"
            f"<p class=\"meta\">{html.escape(str(d.get('category') or ''))} · {html.escape(str(d.get('pass') or ''))}"
            f" · thread {html.escape(str(d.get('threadId') or ''))} · proposal {html.escape(str(d.get('proposalId') or ''))}"
            f" · {who} · {html.escape(str(d.get('decidedAt') or ''))} UTC"
            f" · Paratext thread {thread_state}</p>"
            f"<p><b>Original</b> {html.escape(str(d.get('original') or ''))}<br><b>Replacement</b> {html.escape(str(d.get('replacement') or ''))}</p>"
            f"{snapshot}{_paratext_line(d)}"
            f"<p class=\"comment\"><b>Comment</b> {html.escape(str(d.get('comment') or ''))}</p>"
            f"</article>")
    body = "\n".join(rows) or "<p class=\"muted\">No decisions in this session.</p>"
    user_line = html.escape(reviewer)
    if bridge_user and bridge_user.get("userId"):
        user_line = f"{html.escape(str(bridge_user.get('displayName') or reviewer))} ({html.escape(str(bridge_user['userId']))})"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Paratext review session · {html.escape(book)}</title>
<style>
body{{font-family:system-ui,sans-serif;margin:24px;max-width:960px;color:#222}}
h1{{font-size:1.3em}} h3{{margin:0 0 4px;font-size:1.05em}} small{{font-weight:400;color:#555}}
.d{{border:1px solid #ccc;border-radius:8px;padding:10px 12px;margin:10px 0}} .meta,.muted{{color:#666;font-size:.9em}}
.snap{{white-space:pre-wrap;overflow-wrap:anywhere;margin:4px 0}} mark.was{{background:#fdd}} mark.now{{background:#dfd}}
.applied{{border-color:#7c7}} .rejected{{border-color:#c99}} .manual{{border-color:#99c}} .reverted{{border-color:#cc8}}
.toolbar{{margin:12px 0}} .toolbar label{{margin-right:12px}}
</style></head><body>
<h1>Paratext QA review session · {html.escape(project_name)} · {html.escape(book)}</h1>
<p class="meta">Reviewer {user_line} · {('session since ' + html.escape(since) + ' UTC') if since else 'all decisions'} · generated {html.escape(generated_at)} UTC · {len(rows)} decision{'' if len(rows) == 1 else 's'}</p>
<div class="toolbar"><input id="q" type="search" placeholder="Search…" oninput="filter()">
<label><input type="checkbox" class="f" value="applied" checked onchange="filter()">Applied</label>
<label><input type="checkbox" class="f" value="rejected" checked onchange="filter()">Rejected</label>
<label><input type="checkbox" class="f" value="manual" checked onchange="filter()">Manual</label>
<label><input type="checkbox" class="f" value="deferred" checked onchange="filter()">Deferred</label>
<label><input type="checkbox" class="f" value="reverted" checked onchange="filter()">Reverted</label></div>
{body}
<script>
function filter(){{var q=document.getElementById('q').value.toLowerCase();var on={{}};
document.querySelectorAll('.f').forEach(function(c){{on[c.value]=c.checked}});
document.querySelectorAll('.d').forEach(function(a){{var ok=on[a.dataset.decision]!==false&&(!q||a.textContent.toLowerCase().indexOf(q)>=0);a.style.display=ok?'':'none'}});}}
</script></body></html>
"""


def write_session_report(folder: str | Path, html_text: str, *, stamp: str | None = None,
                         name: str | None = None) -> Path:
    """Write the report atomically into `folder` as report-<stamp>.html (or
    `name`), so an interrupted write never leaves a half file behind the
    latest name: the temporary file is renamed only once fully written."""
    target_dir = Path(folder)
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = stamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = target_dir / (name or f"report-{stamp}.html")
    temporary = target.with_suffix(".html.tmp")
    temporary.write_text(html_text, encoding="utf-8")
    temporary.replace(target)
    return target


def list_reports(folder: str | Path) -> dict[str, Any]:
    """Every saved report, newest first, and the leftovers of interrupted
    generations (`.html.tmp`), which are removed: a report is derived
    evidence, regenerated from the decisions at any time, so a half-written
    file is never shown as one (#434)."""
    target_dir = Path(folder)
    if not target_dir.is_dir():
        return {"reports": [], "interrupted": []}
    interrupted = []
    for leftover in target_dir.glob("report-*.html.tmp"):
        try:
            leftover.unlink()
            interrupted.append(leftover.name)
        except OSError:
            interrupted.append(leftover.name + " (could not be removed)")
    reports = []
    for path in sorted((p for p in target_dir.glob("report-*.html") if p.is_file()), reverse=True):
        try:
            stat = path.stat()
        except OSError:
            continue
        reports.append({"path": str(path), "name": path.name, "size": stat.st_size,
                        "modifiedAt": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds")})
    return {"reports": reports, "interrupted": interrupted}


def latest_report(folder: str | Path) -> Path | None:
    target_dir = Path(folder)
    if not target_dir.is_dir():
        return None
    reports = sorted(p for p in target_dir.glob("report-*.html") if p.is_file())
    return reports[-1] if reports else None


def proposal_from_item(item: dict[str, Any]) -> Proposal:
    """A Proposal dataclass from a queue item's wire shape (tests, callers
    that want attribute access)."""
    p = dict(item["proposal"])
    return Proposal(
        proposalId=p["proposalId"], commentIndex=p["commentIndex"], block=p["block"], route=p["route"],
        operation=p["operation"], region=p["region"], pass_=p.get("pass", ""), topic=p.get("topic", ""),
        category=p.get("category", ""), categoryKnown=p.get("categoryKnown", False), original=p.get("original", ""),
        suggested=p.get("suggested", ""), reason=p.get("reason", ""), location=p.get("location", ""),
        reference=p.get("reference", ""), severity=p.get("severity", ""), confidence=p.get("confidence", ""),
        reviewerDecision=p.get("reviewerDecision", True), anchorWarning=p.get("anchorWarning", False),
        historical=p.get("historical", False), alternatives=list(p.get("alternatives") or []),
        structural=p.get("structural"), diagnostics=list(p.get("diagnostics") or []),
        author=p.get("author", ""), date=p.get("date", ""),
    )

