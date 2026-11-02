"""The Paratext QA review queue: proposals in Scripture order, decisions,
exact application to Bridge's copy of the verse, a checked revert, and the
session's evidence (#428, #431, #432, #433, #434; parent #423).

What this module is careful about, and why:

* **One Scripture writer.** An accepted proposal is applied through the
  caller's ``edit`` callable, which is ``BridgeEngine.edit_verse`` -- the same
  ``apply_scripture_edit`` path as the editor's Save and the scoped Language
  QA fix. Nothing here writes a chapter file. The write is refused unless the
  verse still reads exactly as it did when the reviewer looked at it
  (``expected_old_text``).
* **Exact target, or nothing.** The proposal's ``Original`` must occur exactly
  once in the verse's plain text (notes and markup lifted away), on text-element
  boundaries; a repeat is disambiguated only by the note's own anchor context;
  otherwise the apply is refused and the reason shown. Only the verse body is
  ever edited: an introduction, heading, footnote or cross-reference proposal
  is review-only here, never mapped into the body by fallback.
* **A decision is not an edit.** ``rejected``, ``manual`` and ``deferred``
  record what the reviewer saw and said; only ``applied`` changes text, and it
  is recorded as verified only after the saved verse was read back and found to
  hold the replacement at the span. A decision row is rewritten on change, and
  every revision is a ``change_log`` row (append-only).
* **Revert is checked.** The latest verified apply in this book is reverted
  only while the verse still equals its saved post-image; any intervening
  change is refused with the mismatch, never guessed around.
* **Nothing resolves a Paratext thread by itself.** ``thread_completion`` says
  whether every outstanding proposal in a thread has a terminal decision; the
  resolve itself stays a click through the existing outbox.
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

from .paratext_proposals import (
    OP_ALTERNATIVES, OP_DELETE, OP_REPLACE, REGION_BODY, ROUTE_LITERAL, ROUTE_REVIEW, Proposal,
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


class ReviewError(ValueError):
    """A request the queue refuses, with the reason for the reviewer."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Locating the Original in the verse
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Match:
    start: int          # plain code-point span
    end: int
    raw_start: int      # raw span, contiguous (no markup inside)
    raw_end: int
    whole_word: bool


@dataclass
class Location:
    found: list[Match]
    chosen: Match | None
    reason: str = ""    # why nothing was chosen, for the reviewer

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


def locate(raw_verse: str, original: str, *, context_before: str = "", context_after: str = "") -> Location:
    """Where `original` is in the verse body. Exactly one match wins; several
    are narrowed by the note's own context (whitespace-collapsed, as the
    plugin compares it, #358 h), then by whole-word matches; still several is
    ambiguous and nothing is chosen."""
    if not original:
        return Location([], None, "The note has no Original text to find.")
    lifted = lift_verse(raw_verse or "")
    plain = lifted.plain
    found: list[Match] = []
    start = 0
    while True:
        index = plain.find(original, start)
        if index < 0:
            break
        end = index + len(original)
        start = index + 1
        if not (_boundary(plain, index) and _boundary(plain, end)):
            continue
        span = lifted.raw_span(index, end)
        if span is None:
            continue            # the text runs across markup or a note: not one span
        found.append(Match(index, end, span[0], span[1], _whole_word(plain, index, end)))
    if not found:
        if original in plain:
            return Location([], None, "The Original is in the verse only across markup or a footnote; "
                                      "it cannot be replaced as one span.")
        return Location([], None, "The exact Original was not found in this verse. It may be stale, "
                                  "already corrected, or in a footnote or heading rather than the body.")
    if len(found) == 1:
        return Location(found, found[0])
    collapse = lambda s: re.sub(r"\s+", " ", s or "").strip()  # noqa: E731
    before, after = collapse(context_before), collapse(context_after)
    if before or after:
        anchored = [m for m in found
                    if (not before or collapse(plain[:m.start]).endswith(before))
                    and (not after or collapse(plain[m.end:]).startswith(after))]
        if len(anchored) == 1:
            return Location(found, anchored[0])
    whole = [m for m in found if m.whole_word]
    if len(whole) == 1:
        return Location(found, whole[0])
    return Location(found, None, f"The Original occurs {len(found)} times in this verse and the note's context "
                                 "does not identify one of them; nothing was changed.")


def replaced_raw(raw_verse: str, match: Match, replacement: str) -> str:
    return raw_verse[:match.raw_start] + replacement + raw_verse[match.raw_end:]


def check_replacement(replacement: str) -> None:
    if "\\" in replacement or "\n" in replacement or "\r" in replacement or "\0" in replacement:
        raise ReviewError("A replacement cannot carry USFM markers or line breaks; that is a structural change, review-only.")


# ---------------------------------------------------------------------------
# The queue
# ---------------------------------------------------------------------------

def _verse_number(verse: str) -> int:
    match = re.match(r"\s*(\d+)", str(verse or ""))
    return int(match.group(1)) if match else 0


def queue_items(threads: Iterable[Any], *, status: str = FILTER_UNRESOLVED) -> list[dict[str, Any]]:
    """One item per outstanding proposal of the given threads (NoteThread
    objects), in Scripture order: chapter, verse, thread's first date, comment,
    block. `status` keeps open threads, resolved ones, or both. No-change and
    historical proposals are not queued; unreadable ones are, so a person sees
    them."""
    if status not in FILTERS:
        raise ReviewError(f"status must be one of {list(FILTERS)}")
    items: list[tuple[tuple[int, int, str, int, int], dict[str, Any]]] = []
    for thread in threads:
        if getattr(thread, "kind", "note") != "note" or thread.ref is None:
            continue
        if status == FILTER_UNRESOLVED and thread.resolved:
            continue
        if status == FILTER_RESOLVED and not thread.resolved:
            continue
        proposals = thread_proposals(thread.id, thread.comments)
        outstanding = [p for p in proposals if p.outstanding]
        for proposal in outstanding:
            key = (int(thread.ref.chapter), _verse_number(thread.ref.verse), thread.comments[0].date,
                   proposal.commentIndex, proposal.block)
            items.append((key, {
                "proposalId": proposal.proposalId, "threadId": thread.id,
                "book": thread.ref.book, "chapter": str(thread.ref.chapter), "verse": str(thread.ref.verse),
                "verseRef": thread.verse_ref, "threadResolved": thread.resolved,
                "selectedText": thread.selected_text,
                "contextBefore": thread.comments[0].context_before, "contextAfter": thread.comments[0].context_after,
                "proposal": proposal.to_json(),
                "threadOutstanding": len(outstanding),
            }))
    items.sort(key=lambda pair: pair[0])
    return [item for _, item in items]


class ReviewStore:
    """Decisions and queue state of one book, written as `identity`."""

    def __init__(self, workbench: WorkbenchRepository, identity: WorkbenchIdentity, book_id: str):
        self.workbench = workbench
        self.identity = identity
        self.book_id = book_id

    # -- decisions ---------------------------------------------------------------

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
        self.workbench._write(
            DECISIONS, self._decision_id(proposal_id), project_id=self.identity.project_id, book_id=self.book_id,
            payload=payload, actor_id=self.identity.actor_id, device_id=self.identity.device_id,
            expected_revision=None, op=f"decision:{payload.get('decision')}",
            extra_columns={"proposal_id": proposal_id, "thread_id": str(payload.get("threadId") or ""),
                           "decision": str(payload.get("decision") or ""),
                           "verified": 1 if payload.get("verified") else 0},
        )
        return self.decision(proposal_id)  # type: ignore[return-value]

    # -- state -------------------------------------------------------------------

    def _state_id(self) -> str:
        return natural_row_id(self.identity.project_id, self.book_id, self.identity.actor_id, "paratext_review_queue")

    def state(self) -> dict[str, Any]:
        found = self._row_payload(self.workbench.get(STATE, self._state_id()))
        return found or {"status": FILTER_UNRESOLVED, "position": "", "drafts": {}, "sessionStartedAt": ""}

    def save_state(self, patch: dict[str, Any]) -> dict[str, Any]:
        current = self.state()
        current.pop("revision", None)
        current.pop("updatedAt", None)
        merged = {**current, **{k: v for k, v in patch.items() if k in ("status", "position", "drafts", "sessionStartedAt")}}
        if "drafts" in patch and isinstance(patch["drafts"], dict):
            drafts = {k: v for k, v in patch["drafts"].items() if isinstance(v, dict) and (
                str(v.get("replacement") or "").strip() or str(v.get("comment") or "").strip())}
            merged["drafts"] = drafts
        self.workbench._write(
            STATE, self._state_id(), project_id=self.identity.project_id, book_id=self.book_id,
            payload=merged, actor_id=self.identity.actor_id, device_id=self.identity.device_id,
            expected_revision=None, op="queue_state",
        )
        return self.state()


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------

def thread_completion(items_in_thread: list[dict[str, Any]], decisions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Whether every outstanding proposal of a thread has a terminal
    decision, so the reviewer may be offered "Resolve in Paratext". An
    unreadable proposal, a deferred one, or an apply that was not verified
    keeps the thread open."""
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
    return {"complete": not blocking and bool(items_in_thread), "blocking": blocking}


def apply_proposal(
    *, item: dict[str, Any], replacement: str, raw_verse: str,
    edit: Callable[[str, str, str, str], dict[str, Any]], read_back: Callable[[str, str], str],
    confirm_delete: bool = False,
) -> dict[str, Any]:
    """Apply one proposal to Bridge's copy of the verse through `edit`
    (chapter, verse, new_raw, expected_old_raw) and verify by reading the
    verse again. Returns the decision payload fragment. Raises ReviewError
    with the reason when it must not happen."""
    proposal = item["proposal"]
    route, operation, region = proposal.get("route"), proposal.get("operation"), proposal.get("region")
    if route not in (ROUTE_LITERAL, ROUTE_REVIEW):
        raise ReviewError(f"A proposal routed \"{route}\" cannot be applied here; it is review-only.")
    if region != REGION_BODY:
        raise ReviewError(f"The proposal targets the {region}, not the verse body; it is review-only here.")
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
    location = locate(raw_verse, original, context_before=item.get("contextBefore", ""),
                      context_after=item.get("contextAfter", ""))
    if not location.ok:
        raise ReviewError(location.reason)
    match = location.chosen
    assert match is not None
    before_plain = lift_verse(raw_verse).plain
    new_raw = replaced_raw(raw_verse, match, replacement)
    result = edit(item["chapter"], item["verse"], new_raw, raw_verse)
    saved_raw = read_back(item["chapter"], item["verse"])
    saved_plain = lift_verse(saved_raw).plain
    # The writer trims an ordinary edit; the read-back is compared trimmed
    # the same way, and must hold the replacement where the span was.
    verified = saved_raw == new_raw.strip() and saved_plain[match.start:match.start + len(replacement)] == replacement
    return {
        "original": original, "replacement": replacement,
        "span": {"plainStart": match.start, "plainEnd": match.end, "rawStart": match.raw_start, "rawEnd": match.raw_end},
        "before": {"raw": raw_verse, "plain": before_plain},
        "after": {"raw": saved_raw, "plain": saved_plain},
        "verified": verified,
        "journalTransactionId": str(result.get("journalTransactionId") or ""),
        "unverifiedReason": "" if verified else "The saved verse does not read as the apply intended; treat this edit as unverified.",
    }


def revert_latest(
    store: ReviewStore, *, read_back: Callable[[str, str], str],
    edit: Callable[[str, str, str, str], dict[str, Any]], username: str,
) -> dict[str, Any]:
    """Revert the latest verified apply in this book, only while the verse
    still equals its saved post-image."""
    applied = [d for d in store.decisions() if d.get("decision") == APPLIED and d.get("verified")]
    if not applied:
        raise ReviewError("There is no verified applied correction in this book to revert.")
    latest = max(applied, key=lambda d: str(d.get("decidedAt") or ""))
    current = read_back(latest["chapter"], latest["verse"])
    after_raw = str((latest.get("after") or {}).get("raw") or "")
    before_raw = str((latest.get("before") or {}).get("raw") or "")
    if current != after_raw:
        raise ReviewError(
            f"{latest['verseRef']} no longer reads as the correction left it (someone changed it since); "
            "the revert is refused so that change is not lost. Current text: "
            f"“{lift_verse(current).plain}”")
    result = edit(latest["chapter"], latest["verse"], before_raw, after_raw)
    restored = read_back(latest["chapter"], latest["verse"])
    payload = dict(latest)
    payload.pop("revision", None)
    payload.pop("updatedAt", None)
    payload.update({
        "decision": REVERTED, "revertedAt": _now(), "revertedBy": username,
        "revertVerified": restored == before_raw,
        "revertJournalTransactionId": str(result.get("journalTransactionId") or ""),
    })
    return store.write_decision(payload)


# ---------------------------------------------------------------------------
# Evidence: CSV and the HTML session report
# ---------------------------------------------------------------------------

CSV_COLUMNS = ("reference", "book", "chapter", "verse", "threadId", "proposalId", "pass", "category", "decision",
               "verified", "original", "replacement", "comment", "reviewer", "decidedAt", "threadResolved")


def _csv_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    if text.startswith(_FORMULA_START):
        return "'" + text
    return text


def decisions_csv(decisions: Iterable[dict[str, Any]]) -> str:
    """UTF-8 text (the writer adds the BOM) with spreadsheet-safe cells:
    quotes and newlines are quoted by the csv module, and a cell that would
    read as a formula is prefixed with an apostrophe."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for d in sorted(decisions, key=lambda x: (int(x.get("chapter") or 0), _verse_number(x.get("verse") or ""),
                                              str(x.get("decidedAt") or ""))):
        writer.writerow([_csv_cell(d.get(column)) for column in CSV_COLUMNS[:9]] + [
            "yes" if d.get("verified") else "no" if d.get("decision") == APPLIED else "",
            _csv_cell(d.get("original")), _csv_cell(d.get("replacement")), _csv_cell(d.get("comment")),
            _csv_cell(d.get("reviewer")), _csv_cell(d.get("decidedAt")),
            "yes" if d.get("threadResolved") else "no",
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


def session_report_html(*, project_name: str, book: str, reviewer: str, decisions: list[dict[str, Any]],
                        since: str, generated_at: str) -> str:
    """A self-contained, offline HTML report of one session's decisions.
    Every note and verse string is escaped. An applied decision is labelled
    verified only when its saved text was read back; a rejected one shows the
    text unchanged; a manual one shows what was observed, not who edited it."""
    rows = []
    for d in sorted(decisions, key=lambda x: (int(x.get("chapter") or 0), _verse_number(x.get("verse") or ""),
                                              str(x.get("decidedAt") or ""))):
        decision = str(d.get("decision") or "")
        before = (d.get("before") or {}).get("plain") or (d.get("observed") or {}).get("plain") or ""
        after = (d.get("after") or {}).get("plain") or ""
        if decision == APPLIED:
            label = "Applied · verified" if d.get("verified") else "Applied · NOT verified"
            snapshot = (f"<div class=\"snap\"><b>Before</b> {_highlight(before, d.get('span'), d.get('original', ''), 'was')}</div>"
                        f"<div class=\"snap\"><b>After</b> {_highlight(after, d.get('span'), d.get('replacement', ''), 'now')}</div>")
        elif decision == REVERTED:
            label = "Reverted" + ("" if d.get("revertVerified") else " · NOT verified")
            snapshot = f"<div class=\"snap\"><b>Restored</b> {html.escape(before)}</div>"
        elif decision == REJECTED:
            label = "Rejected · text unchanged"
            snapshot = f"<div class=\"snap\"><b>Text</b> {html.escape(before)}</div>"
        elif decision == MANUAL:
            label = "Completed manually / no change · observed, not authored by Bridge"
            snapshot = f"<div class=\"snap\"><b>Observed</b> {html.escape(before)}</div>"
        else:
            label = "Left for later"
            snapshot = ""
        if not before and decision != DEFERRED:
            snapshot = "<div class=\"snap muted\">No snapshot was recorded for this decision.</div>"
        rows.append(
            f"<article class=\"d {html.escape(decision)}\" data-decision=\"{html.escape(decision)}\">"
            f"<h3>{html.escape(str(d.get('verseRef') or ''))} <small>{html.escape(label)}</small></h3>"
            f"<p class=\"meta\">{html.escape(str(d.get('category') or ''))} · {html.escape(str(d.get('pass') or ''))}"
            f" · thread {html.escape(str(d.get('threadId') or ''))} · proposal {html.escape(str(d.get('proposalId') or ''))}"
            f" · {html.escape(str(d.get('reviewer') or ''))} · {html.escape(str(d.get('decidedAt') or ''))} UTC"
            f" · Paratext thread {'resolved' if d.get('threadResolved') else 'open'}</p>"
            f"<p><b>Original</b> {html.escape(str(d.get('original') or ''))}<br><b>Replacement</b> {html.escape(str(d.get('replacement') or ''))}</p>"
            f"{snapshot}"
            f"<p class=\"comment\"><b>Comment</b> {html.escape(str(d.get('comment') or ''))}</p>"
            f"</article>")
    body = "\n".join(rows) or "<p class=\"muted\">No decisions in this session.</p>"
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
<p class="meta">Reviewer {html.escape(reviewer)} · session since {html.escape(since or 'start')} UTC · generated {html.escape(generated_at)} UTC · {len(rows)} decision{'' if len(rows) == 1 else 's'}</p>
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


def write_session_report(folder: str | Path, html_text: str, *, stamp: str | None = None) -> Path:
    """Write the report atomically into `folder` as report-<stamp>.html, so
    an interrupted write never leaves a half file behind the latest name."""
    target_dir = Path(folder)
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = stamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = target_dir / f"report-{stamp}.html"
    temporary = target.with_suffix(".html.tmp")
    temporary.write_text(html_text, encoding="utf-8")
    temporary.replace(target)
    return target


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
