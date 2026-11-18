"""Several verses of a chapter in one review request (#502, design in #474).

Today's review sends one verse per request. This module sends a window of
verses with one evidence catalog they share, splits the single answer back
into one stored review per verse, and degrades to smaller windows when a
request fails. It is used only when the "verses per request" setting is above
one, or one of the two options below is on; with the defaults the job runs
`OpenAIResponsesClient.prepare_verse_review` exactly as before and nothing
here is called.

What stays per verse, as today: the fingerprint taken before the verse's first
call, the semantic mapping and the gap-fill alignment (each verse's own
requests, sent before its window), the selection gate, the reviewer-noise
gates, the semantic policy, the stored review and its usage. What a window
shares: the instructions, the answer schema, one reasoning run and one
evidence catalog.

Two options on top of the window size:

- `whole_chapter`: no verse limit; a window closes at a check-count or
  input-size cap, preferably at a section heading.
- `chapter_context`: every request of the chapter starts with the same block
  (language context, the reviewer decisions as they stood when the job
  started, and every article the chapter's checks cite, each once), so a
  provider's prefix cache can serve it. The check count then lives in the
  per-window part of the input, never in the instructions or the schema,
  because a number ahead of the shared block would end the shared prefix.

Known differences from the single-verse run, which is why the default is one:
a verse does not see a rendering applied from an earlier verse of the same
window, and with `chapter_context` it does not see a reviewer decision made
after the job started.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

from .ai_client import (
    AIError, AIUsage, OpenAIResponsesClient, REVIEW_INSTRUCTIONS_STATIC, build_verse_evidence,
    frozen_reviewer_decisions, review_check_schema, review_issue_schema, review_project_tail,
    review_prompt_cache_key, usage_dict,
)
from .ai_review_payload import ReviewPayloadOptions, sent_language_context, sent_mapping_states, sent_token
from .alignment_engine import apply_proposal, make_inventory, validate_preparation_proposal
from .cache_engine import dependency_snapshot
from .models import AICheckReview, QAIssue, VerseAlignment
from .plugins import PluginRegistry
from .security import ai_payload_manifest
from .local_tw_pass import shadow_tw_decisions
from .semantic_mapping_bridge import prepare_semantic_mappings_for_review
from .usfm import strip_usfm

# #474: a window is 4 verses by default and 6 at most; 24 checks or 60,000
# characters of serialised verse blocks close it early.
WINDOW_MAX_VERSES = 6
WINDOW_MAX_CHECKS = 24
WINDOW_MAX_INPUT_CHARS = 60_000
# Whole-chapter requests. Provisional: one answer holding this many rows has
# not been tried against a provider's output limit (#502, known risks).
CHAPTER_MAX_CHECKS = 100
CHAPTER_MAX_INPUT_CHARS = 240_000
# #474: 90 s plus 40 s a verse, capped. Never below the client's own timeout,
# so a one-verse window waits as long as a single-verse review does today.
WINDOW_TIMEOUT_BASE = 90.0
WINDOW_TIMEOUT_PER_VERSE = 40.0
WINDOW_TIMEOUT_CAP = 300.0
CHAPTER_TIMEOUT_CAP = 900.0

WINDOW_SCHEMA_NAME = 'tc_window_review'

WINDOW_RULES = (
    ' WINDOW RULES: this request holds one or more verses of one chapter in verses[]. Review each verse on its own, '
    'exactly as the rules above describe for a single verse; where they say the current verse, read the row\'s own verse. '
    'Every check_reviews row and every qa_issues row must carry the reference of its verse exactly as supplied, and '
    'summaries must hold one row per verse. A check belongs to the verse that lists it; never move a check to another verse. '
    'Token IDs are verse-scoped (verse|id): selection_ids of a row may use only target_bottomWords IDs of that row\'s own verse. '
    'evidence_catalog is shared by all verses of the request and may hold items no check of this request cites; '
    'a check\'s evidence_ids name its own items. semantic_mapping_check_states is one list for the request; '
    'each row names its check by checkId.'
)


@dataclass(frozen=True)
class WindowSettings:
    """`AppSettings.ai_review` as the window review reads it. The defaults are
    today's behaviour: one verse per request, no shared context."""

    verses_per_request: int = 1
    whole_chapter: bool = False
    chapter_context: bool = False

    @classmethod
    def from_settings(cls, value: Any) -> 'WindowSettings':
        data = value if isinstance(value, dict) else {}
        try:
            size = int(data.get('versesPerRequest', 1) or 1)
        except (TypeError, ValueError):
            size = 1
        return cls(
            verses_per_request=max(1, min(WINDOW_MAX_VERSES, size)),
            whole_chapter=bool(data.get('wholeChapter', False)),
            chapter_context=bool(data.get('chapterContext', False)),
        )

    @property
    def windowed(self) -> bool:
        """False for the defaults, which run the single-verse review as before."""
        return self.verses_per_request > 1 or self.whole_chapter or self.chapter_context

    @property
    def max_verses(self) -> int | None:
        return None if self.whole_chapter else self.verses_per_request

    @property
    def max_checks(self) -> int:
        return CHAPTER_MAX_CHECKS if self.whole_chapter else WINDOW_MAX_CHECKS

    @property
    def max_input_chars(self) -> int:
        return CHAPTER_MAX_INPUT_CHARS if self.whole_chapter else WINDOW_MAX_INPUT_CHARS


def window_timeout(client_timeout: float, verse_count: int, whole_chapter: bool = False) -> float:
    cap = CHAPTER_TIMEOUT_CAP if whole_chapter else WINDOW_TIMEOUT_CAP
    budget = min(cap, WINDOW_TIMEOUT_BASE + WINDOW_TIMEOUT_PER_VERSE * max(1, int(verse_count)))
    return max(float(client_timeout), budget)


def verse_number(verse: str) -> int | None:
    """The first numeric component of a verse label (`3`, `3-4`, `3a`)."""
    digits = ''
    for ch in str(verse):
        if ch.isdigit():
            digits += ch
        elif digits:
            break
    return int(digits) if digits else None


def heading_between(previous: str, current: str, heading_verses: Iterable[str]) -> bool:
    """Whether a section starts after `previous` and at or before `current`.
    A heading is keyed by the verse it introduces (#180)."""
    lo, hi = verse_number(previous), verse_number(current)
    for heading in heading_verses:
        if str(heading) == str(current):
            return True
        n = verse_number(heading)
        if n is not None and lo is not None and hi is not None and lo < n <= hi:
            return True
    return False


def window_accepts(
    *, settings: WindowSettings, verse_count: int, checks: int, chars: int,
    add_checks: int, chars_with: int, crosses_heading: bool,
) -> bool:
    """Whether one more verse may join a non-empty window.

    `checks` / `chars` are the window's now, `add_checks` the verse's checks
    and `chars_with` the window's size with the verse in it. A verse that
    alone exceeds a cap is never asked here: it opens its own window.

    A section heading always closes a window of a fixed size (#474). In
    whole-chapter mode the caps close a window, and a heading closes one that
    is already half full by either cap, so a chapter too large for one request
    is cut at its headings where it has them.
    """
    if settings.max_verses is not None and verse_count + 1 > settings.max_verses:
        return False
    if checks + add_checks > settings.max_checks or chars_with > settings.max_input_chars:
        return False
    if crosses_heading:
        if not settings.whole_chapter:
            return False
        if checks * 2 >= settings.max_checks or chars * 2 >= settings.max_input_chars:
            return False
    return True


def plan_windows(
    verses: Sequence[str], *, settings: WindowSettings, heading_verses: Iterable[str] = (),
    checks: dict[str, int] | None = None, chars: dict[str, int] | None = None,
) -> list[list[str]]:
    """Cut a job's verses into windows: contiguous in the job's order, closed
    by `window_accepts`. The session forms windows as it goes, because a
    verse's size is known only once its own preparation calls have returned;
    this is the same rule over sizes known up front."""
    checks = checks or {}
    chars = chars or {}
    headings = [str(h) for h in heading_verses]
    windows: list[list[str]] = []
    current: list[str] = []
    for verse in verses:
        if current:
            now_chars = sum(chars.get(v, 0) for v in current)
            if not window_accepts(
                settings=settings, verse_count=len(current),
                checks=sum(checks.get(v, 0) for v in current), chars=now_chars,
                add_checks=checks.get(verse, 0), chars_with=now_chars + chars.get(verse, 0),
                crosses_heading=heading_between(current[-1], verse, headings),
            ):
                windows.append(current)
                current = []
        current.append(verse)
    if current:
        windows.append(current)
    return windows


_EVIDENCE_PREFIX = {
    'translationWords': 'tw', 'translationAcademy': 'ta', 'translationWordsLinks': 'twl',
    'translationNote': 'tn', 'originalQuote': 'quote', 'referenceBible': 'ref',
}
# Articles: the same item whichever verse cites it.
_SHARED_EVIDENCE_KINDS = frozenset({'translationWords', 'translationAcademy', 'translationWordsLinks'})


class EvidenceIds:
    """Content ids for one chapter's evidence (#474 section 2): `tw:god`,
    `ta:figs-metaphor`, `twl:god`, and verse-scoped ids for a verse's own
    items. One id always names one text: an item whose text differs from the
    first one seen under its id (an article cut by the per-verse evidence
    budget) gets the id with a short content hash."""

    def __init__(self) -> None:
        self._content: dict[str, str] = {}
        self.full: dict[str, dict[str, Any]] = {}

    def for_verse(self, chapter: str, verse: str) -> Callable[[int, dict[str, Any]], str]:
        def make(n: int, item: dict[str, Any]) -> str:
            kind = str(item.get('kind') or '')
            identifier = str(item.get('identifier') or '')
            prefix = _EVIDENCE_PREFIX.get(kind, 'ev')
            if kind in _SHARED_EVIDENCE_KINDS and identifier:
                base = f'{prefix}:{identifier}'
            else:
                base = f'{prefix}:{chapter}:{verse}:{identifier or n}'
            digest = hashlib.sha1(
                json.dumps([kind, item.get('title'), item.get('content')], ensure_ascii=False).encode('utf-8')
            ).hexdigest()
            eid = base
            if self._content.setdefault(base, digest) != digest:
                eid = f'{base}#{digest[:8]}'
                self._content.setdefault(eid, digest)
            self.full[eid] = item
            return eid
        return make


@dataclass
class PreparedVerse:
    """One verse ready to join a window: its own calls are done, its block is
    built, and nothing has been written."""

    chapter: str
    verse: str
    reference: str
    start_fingerprint: str
    alignment: VerseAlignment
    review_alignment: VerseAlignment
    proposal: dict[str, Any] | None
    semantic_mapping_pack: dict[str, Any] | None
    inventory: Any
    language: Any
    resource_provenance: dict[str, Any]
    evidence_catalog: dict[str, dict[str, Any]]
    sent_catalog: dict[str, dict[str, Any]]
    check_inputs: list[dict[str, Any]]
    block: dict[str, Any]
    block_chars: int
    # The Stage 3 states of the verse's passage, as sent. Verses of one
    # passage hold the same rows, so a request lists them once for the window.
    mapping_states: list[Any] = field(default_factory=list)
    mapping_unresolved: list[Any] = field(default_factory=list)
    # #501: the shadow record, stored beside the review and used for nothing.
    local_tw_shadow: dict[str, Any] = field(default_factory=dict)
    usage: AIUsage = field(default_factory=AIUsage)
    cost: float = 0.0
    usage_recorded: bool = False

    @property
    def check_count(self) -> int:
        return len(self.check_inputs)


def scoped_id(verse: str, token_id: str) -> str:
    return f'{verse}|{token_id}'


def build_verse_block(prepared_parts: dict[str, Any]) -> dict[str, Any]:
    """The per-verse part of a window request. Token ids carry the verse, so a
    selection id names its verse and can only be validated against it."""
    verse = prepared_parts['verse']
    inv = prepared_parts['inventory']
    alignment = prepared_parts['alignment']
    top = [dict(sent_token(tid, t, source=True), id=scoped_id(verse, tid)) for tid, t in inv.top_ids.items()]
    bottom = [dict(sent_token(tid, t, source=False), id=scoped_id(verse, tid)) for tid, t in inv.bottom_ids.items()]
    groups = []
    for group in alignment.alignments:
        groups.append({
            'source_ids': [
                scoped_id(verse, inv.top_sig_to_id[x.signature]) for x in group.top_words
                if x.signature in inv.top_sig_to_id
            ],
            'target_ids': [
                scoped_id(verse, inv.bottom_sig_to_id[x.signature]) for x in group.bottom_words
                if x.signature in inv.bottom_sig_to_id
            ],
        })
    return {
        'reference': prepared_parts['reference'],
        'target_verse': strip_usfm(prepared_parts['target_text']),
        'source_topWords': top,
        'target_bottomWords': bottom,
        'current_alignment_groups': groups,
        'translationCore_checks': prepared_parts['check_inputs'],
    }


def merged_mapping_states(window: Sequence['PreparedVerse']) -> tuple[list[Any], list[Any]]:
    """The window's Stage 3 states and unresolved rows, each row once, in
    verse order. A passage's rows are the same for every verse in it."""
    states: list[Any] = []
    unresolved: list[Any] = []
    for prepared in window:
        for row in prepared.mapping_states:
            if row not in states:
                states.append(row)
        for row in prepared.mapping_unresolved:
            if row not in unresolved:
                unresolved.append(row)
    return states, unresolved


def window_review_instructions(language: Any, check_count: int, verse_count: int, count_in_input: bool) -> str:
    """The single-verse instructions' static block, the window rules (static
    too), the project tail, then the count."""
    count_sentence = (
        'THIS REQUEST: the input field expected_check_reviews states how many input checks there are across all '
        'verses; return exactly that many check_reviews rows.'
        if count_in_input else
        f'THIS REQUEST: {check_count} input checks across {verse_count} verse(s) require exactly {check_count} '
        'check_reviews rows.'
    )
    return REVIEW_INSTRUCTIONS_STATIC + WINDOW_RULES + review_project_tail(language) + count_sentence


def window_review_schema(check_count: int, count_in_input: bool) -> dict[str, Any]:
    """One answer for the window: every row names its verse. JSON Schema can
    pin the total row count but not a count per verse, so the per-verse count
    is enforced by the parser, as the missing-row path does today."""
    rows: dict[str, Any] = {'type': 'array', 'items': review_check_schema(with_reference=True)}
    if not count_in_input:
        rows['minItems'] = check_count
        rows['maxItems'] = check_count
    summary = {
        'type': 'object', 'additionalProperties': False,
        'properties': {'reference': {'type': 'string'}, 'summary': {'type': 'string'}},
        'required': ['reference', 'summary'],
    }
    return {
        'type': 'object', 'additionalProperties': False,
        'properties': {
            'summaries': {'type': 'array', 'items': summary},
            'check_reviews': rows,
            'qa_issues': {'type': 'array', 'items': review_issue_schema(with_reference=True)},
        },
        'required': ['summaries', 'check_reviews', 'qa_issues'],
    }


def _norm_reference(value: Any) -> str:
    return ' '.join(str(value or '').split()).casefold()


def split_window_answer(result: dict[str, Any], window: Sequence[PreparedVerse]) -> dict[str, dict[str, Any]]:
    """Group a window answer's rows by verse: `{verse: {check_reviews,
    qa_issues, summary}}`, with `selection_ids` back in each verse's own
    inventory ids. A row naming a verse that is not in the window makes the
    whole answer unusable (AIError): it cannot be attributed."""
    by_reference = {_norm_reference(p.reference): p for p in window}
    out: dict[str, dict[str, Any]] = {
        p.verse: {'check_reviews': [], 'qa_issues': [], 'summary': ''} for p in window
    }
    for key in ('check_reviews', 'qa_issues'):
        rows = result.get(key, [])
        if not isinstance(rows, list):
            raise AIError(f'AI window review returned no {key} list.')
        for row in rows:
            if not isinstance(row, dict):
                raise AIError(f'AI window review returned a malformed {key} row.')
            prepared = by_reference.get(_norm_reference(row.get('reference')))
            if prepared is None:
                raise AIError(
                    f'AI window review returned a row for a verse that is not in the request: {row.get("reference")!r}.'
                )
            item = {k: v for k, v in row.items() if k != 'reference'}
            if key == 'check_reviews':
                prefix = f'{prepared.verse}|'
                # An id of another verse keeps its prefix, is unknown to this
                # verse's inventory, and fails this verse alone in the parser.
                item['selection_ids'] = [
                    str(x)[len(prefix):] if str(x).startswith(prefix) else str(x)
                    for x in (item.get('selection_ids') or [])
                ]
            out[prepared.verse][key].append(item)
    for row in result.get('summaries', []) if isinstance(result.get('summaries'), list) else []:
        if isinstance(row, dict):
            prepared = by_reference.get(_norm_reference(row.get('reference')))
            if prepared is not None:
                out[prepared.verse]['summary'] = str(row.get('summary') or '')
    return out


def apportion_usage(
    usage: AIUsage, cost: float, weights: Sequence[int],
) -> list[tuple[AIUsage, float]]:
    """Split one request's usage across its verses by weight (each verse's
    share of the request's verse blocks). Token counts are split in whole
    numbers that sum to the request's own; the request counts as one call for
    every verse that took part in it. The per-verse figures are estimates; the
    request's own usage is kept exact on each stored review's `batch`."""
    clean = [max(0, int(w)) for w in weights]
    if not sum(clean):
        clean = [1] * len(clean)
    shares = [w / sum(clean) for w in clean]
    out: list[tuple[AIUsage, float]] = []
    spent = {'input': 0, 'output': 0, 'total': 0, 'cached': 0}
    for index, share in enumerate(shares):
        last = index == len(shares) - 1
        parts = {}
        for key, whole in (('input', usage.input_tokens), ('output', usage.output_tokens),
                           ('total', usage.total_tokens), ('cached', usage.cached_input_tokens)):
            value = int(whole) - spent[key] if last else int(int(whole) * share)
            spent[key] += value
            parts[key] = value
        out.append((
            AIUsage(parts['input'], parts['output'], parts['total'], parts['cached'],
                    calls=int(usage.calls), unanswered_calls=int(usage.unanswered_calls)),
            float(cost) * share,
        ))
    return out


def window_privacy_manifest(label: str, input_obj: dict[str, Any]) -> dict[str, Any]:
    """`ai_payload_manifest` over a window request: the same questions asked of
    the same fields, which a window nests under `verses`."""
    verses = [v for v in input_obj.get('verses', []) if isinstance(v, dict)]
    flat: dict[str, Any] = {k: v for k, v in input_obj.items() if k != 'verses'}
    for key in ('target_verse', 'source_topWords', 'target_bottomWords', 'current_alignment_groups',
                'translationCore_checks'):
        values = [v.get(key) for v in verses if v.get(key)]
        if not values:
            continue
        flat[key] = ' '.join(values) if key == 'target_verse' else [x for value in values for x in value]
    manifest = ai_payload_manifest(label, flat)
    manifest['sentFields'] = sorted(set(manifest['sentFields']) | {'verses', 'reference'})
    manifest['verses'] = [str(v.get('reference') or '') for v in verses]
    return manifest


class WindowReviewSession:
    """Review a chapter's verses in windows.

    The reporter receives every outcome and owns everything that touches the
    project beyond the stored review itself:

    - `begin(verse)` before a verse's first call; may raise to fail the verse.
    - `stage(verse, percent, text)` progress of the verse being prepared.
    - `window(verses)` the window about to be sent.
    - `done(verse, prepared, reviews, issues, summary, meta)` the verse's
      review is stored; the caller applies selections and so on.
    - `failed(verse, error, usage, cost)` the verse failed, with what it spent.
    - `cancelled(verse)` the verse was prepared and never sent.
    """

    def __init__(
        self, client: OpenAIResponsesClient, project: Any, chapter: str, verses: Sequence[str],
        settings: WindowSettings, *, knowledge_base: Any = None,
    ) -> None:
        from .knowledge_base import TranslationHelpsKnowledgeBase

        self.client = client
        self.project = project
        self.chapter = str(chapter)
        self.verses = [str(v) for v in verses]
        self.settings = settings
        self.options: ReviewPayloadOptions = client.review_options
        self.knowledge_base = knowledge_base
        self.kb = knowledge_base or TranslationHelpsKnowledgeBase(project)
        self.ids = EvidenceIds()
        self.count_in_input = bool(self.options.count_in_input or settings.chapter_context)
        try:
            self.heading_verses = [str(v) for v in project.chapter_headings(self.chapter)]
        except Exception:
            self.heading_verses = []
        self.decisions: list[dict[str, Any]] | None = None
        self.chapter_catalog: dict[str, dict[str, Any]] | None = None
        self.windows_sent: list[dict[str, Any]] = []

    # -- preparation ---------------------------------------------------------

    def _evidence(self, verse: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        pack = self.kb.evidence_pack_for_verse(self.chapter, verse, max_chars=42000)
        full, sent, checks = build_verse_evidence(
            pack, self.kb, self.options, evidence_id=self.ids.for_verse(self.chapter, verse),
        )
        return pack, full, sent, checks

    def _build_chapter_context(self) -> None:
        """Freeze the decisions and collect every article the job's verses
        cite, each once, in verse order. Local reads only."""
        self.decisions = frozen_reviewer_decisions(self.project)
        catalog: dict[str, dict[str, Any]] = {}
        for verse in self.verses:
            try:
                _, _, sent, _ = self._evidence(verse)
            except Exception:
                continue  # the verse fails in its own preparation, with its own message
            for eid, item in sent.items():
                catalog.setdefault(eid, item)
        self.chapter_catalog = catalog

    def prepare(self, verse: str, progress: Callable[[int, str], None] | None = None) -> PreparedVerse:
        """The verse's own calls, as `prepare_verse_review` makes them (the
        semantic mapping, then the gap-fill alignment when words are
        unaligned), and its block. Nothing is written."""
        client, project, chapter = self.client, self.project, self.chapter
        start_fingerprint = project.review_input_fingerprint(chapter, verse)
        mark = client.usage_mark()
        try:
            if progress: progress(5, 'Preparing verse review')
            alignment = project.load_verse_alignment(chapter, verse)
            local_tw_shadow = shadow_tw_decisions(project, chapter, verse, alignment)
            if progress: progress(7, 'Mapping source meanings across target passage')
            mapping = prepare_semantic_mappings_for_review(
                project=project, client=client, chapter=chapter, verse=verse,
            )
            needs_alignment = bool(alignment.word_bank) or any(
                g.top_words and not g.bottom_words for g in alignment.alignments
            )
            proposal: dict[str, Any] | None = None
            review_alignment = alignment
            if needs_alignment:
                if progress: progress(12, 'AI preparing incomplete alignment')
                proposal = client.propose_alignment(
                    project, chapter, verse, alignment, mode='gap_fill', semantic_mapping_pack=mapping,
                )
                validate_preparation_proposal(alignment, proposal)
                review_alignment = apply_proposal(alignment, proposal)
                if progress: progress(38, 'Alignment proposal validated locally')
            elif progress:
                progress(38, 'Existing alignment ready')
            if project.review_input_fingerprint(chapter, verse) != start_fingerprint:
                raise AIError('Verse/project data changed while AI was preparing alignment; stale result was discarded.')
            if progress: progress(48, 'Building verse evidence package')
            target_text = project.target_verse_text(chapter, verse)
            language = PluginRegistry().detect_project(project, review_alignment, target_text)
            inventory = make_inventory(review_alignment)
            pack, full, sent, checks = self._evidence(verse)
            reference = f'{project.book_id} {chapter}:{verse}'
            block = build_verse_block({
                'verse': verse, 'reference': reference, 'inventory': inventory, 'alignment': review_alignment,
                'semantic_mapping_pack': mapping, 'target_text': target_text, 'check_inputs': checks,
            })
            states, unresolved = sent_mapping_states(mapping)
            if progress: progress(58, 'Waiting for the rest of the window')
        except Exception as exc:
            usage, cost = client.usage_since(mark)
            exc.spent_usage = usage  # type: ignore[attr-defined]
            exc.spent_cost = cost  # type: ignore[attr-defined]
            raise
        usage, cost = client.usage_since(mark)
        return PreparedVerse(
            chapter=chapter, verse=verse, reference=reference, start_fingerprint=start_fingerprint,
            alignment=alignment, review_alignment=review_alignment, proposal=proposal,
            semantic_mapping_pack=mapping, inventory=inventory, language=language,
            resource_provenance=pack.get('resource_provenance', {}), evidence_catalog=full,
            sent_catalog=sent, check_inputs=checks, block=block,
            block_chars=len(json.dumps(block, ensure_ascii=False)), usage=usage, cost=cost,
            mapping_states=states, mapping_unresolved=unresolved, local_tw_shadow=local_tw_shadow,
        )

    # -- window formation ----------------------------------------------------

    def _window_chars(self, window: Sequence[PreparedVerse]) -> int:
        """Characters of the request that belong to the window: its verse
        blocks, and its own catalog unless the chapter's is shared."""
        total = sum(p.block_chars for p in window)
        total += len(json.dumps(merged_mapping_states(window), ensure_ascii=False))
        if self.chapter_catalog is None:
            catalog: dict[str, dict[str, Any]] = {}
            for p in window:
                for eid, item in p.sent_catalog.items():
                    catalog.setdefault(eid, item)
            total += len(json.dumps(catalog, ensure_ascii=False))
        return total

    def fits(self, window: Sequence[PreparedVerse], prepared: PreparedVerse) -> bool:
        return window_accepts(
            settings=self.settings, verse_count=len(window),
            checks=sum(p.check_count for p in window), chars=self._window_chars(window),
            add_checks=prepared.check_count, chars_with=self._window_chars([*window, prepared]),
            crosses_heading=heading_between(window[-1].verse, prepared.verse, self.heading_verses),
        )

    # -- the request ---------------------------------------------------------

    def build_request(self, window: Sequence[PreparedVerse]) -> tuple[str, dict[str, Any], dict[str, Any]]:
        """`(instructions, input object, schema)` for one window. Key order is
        the serialised order: what is the same for every request of the
        chapter first, the window's verses last."""
        language = window[0].language
        check_count = sum(p.check_count for p in window)
        if self.chapter_catalog is not None:
            catalog = self.chapter_catalog
        else:
            catalog = {}
            for p in window:
                for eid, item in p.sent_catalog.items():
                    catalog.setdefault(eid, item)
        input_obj: dict[str, Any] = {
            'language_context': sent_language_context(language),
            'project_reviewer_decisions': (
                self.decisions if self.decisions is not None else frozen_reviewer_decisions(self.project)
            ),
            'evidence_catalog': catalog,
            'verses': [p.block for p in window],
        }
        input_obj['semantic_mapping_check_states'], input_obj['semantic_mapping_unresolved'] = (
            merged_mapping_states(window)
        )
        if self.count_in_input:
            input_obj['expected_check_reviews'] = check_count
        instructions = window_review_instructions(language, check_count, len(window), self.count_in_input)
        return instructions, input_obj, window_review_schema(check_count, self.count_in_input)

    # -- running -------------------------------------------------------------

    def run(self, reporter: Any, cancel_event: Any) -> None:
        if self.settings.chapter_context:
            self._build_chapter_context()
        current: list[PreparedVerse] = []
        for verse in self.verses:
            if cancel_event.is_set():
                break
            try:
                reporter.begin(verse)
                prepared = self.prepare(verse, lambda percent, text, v=verse: reporter.stage(v, percent, text))
            except Exception as exc:
                reporter.failed(
                    verse, exc, getattr(exc, 'spent_usage', AIUsage()), float(getattr(exc, 'spent_cost', 0.0)),
                )
                continue
            if current and not self.fits(current, prepared):
                self._send(current, reporter, cancel_event)
                current = []
            current.append(prepared)
        if current:
            self._send(current, reporter, cancel_event)

    def _send(self, window: Sequence[PreparedVerse], reporter: Any, cancel_event: Any, attempt: int = 0) -> None:
        """Send one window. A request that fails as a whole (transport,
        timeout, an HTTP error, an answer that is not the schema or cannot be
        attributed) is retried once at half the size and then verse by verse
        (#474 section 4); a one-verse window that fails is a failed verse."""
        if cancel_event.is_set():
            for p in window:
                reporter.cancelled(p.verse)
            return
        client = self.client
        reporter.window([p.verse for p in window])
        window_id = uuid.uuid4().hex[:12]
        mark = client.usage_mark()
        instructions, input_obj, schema = self.build_request(window)
        label = (
            f'{window[0].reference}' if len(window) == 1
            else f'{window[0].reference}-{window[-1].verse}'
        )
        manifest = window_privacy_manifest(label, input_obj)
        client.last_privacy_manifest = manifest
        try:
            result = client._post_structured(
                instructions, json.dumps(input_obj, ensure_ascii=False), WINDOW_SCHEMA_NAME, schema,
                prompt_cache_key=review_prompt_cache_key(self.project),
                timeout=window_timeout(client.timeout, len(window), self.settings.whole_chapter),
            )
            rows = split_window_answer(result, window)
            error: Exception | None = None
        except Exception as exc:
            rows, error = {}, exc
        usage, cost = client.usage_since(mark)
        weights = [p.block_chars for p in window]
        shares = apportion_usage(usage, cost, weights)
        for p, (share_usage, share_cost) in zip(window, shares):
            p.usage = p.usage + share_usage
            p.cost += share_cost
        self.windows_sent.append({
            'windowId': window_id, 'verses': [p.verse for p in window], 'attempt': attempt,
            'ok': error is None, 'usage': usage_dict(usage),
        })
        if error is not None:
            if len(window) == 1:
                reporter.failed(window[0].verse, error, window[0].usage, window[0].cost)
            elif attempt == 0:
                middle = (len(window) + 1) // 2
                self._send(window[:middle], reporter, cancel_event, 1)
                self._send(window[middle:], reporter, cancel_event, 1)
            else:
                for p in window:
                    self._send([p], reporter, cancel_event, 2)
            return
        total_weight = sum(weights) or 1
        for p in window:
            batch = {
                'windowId': window_id, 'verses': [x.verse for x in window], 'attempt': attempt,
                'chapterContext': self.chapter_catalog is not None,
                'share': round(p.block_chars / total_weight, 6),
                'windowUsage': usage_dict(usage), 'windowEstimatedCostUSD': cost,
            }
            try:
                verse_rows = rows[p.verse]
                reviews, issues, suppressed, summary = client.parse_review_rows(
                    self.project, p.chapter, p.verse, inventory=p.inventory, check_inputs=p.check_inputs,
                    evidence_catalog=self.ids.full, result=verse_rows,
                    semantic_mapping_pack=p.semantic_mapping_pack,
                )
                meta = self._record(p, reviews, issues, suppressed, summary, manifest, batch)
            except Exception as exc:
                reporter.failed(p.verse, exc, p.usage, p.cost)
                continue
            reporter.done(p.verse, p, reviews, issues, summary, meta)

    def _record(
        self, p: PreparedVerse, reviews: list[AICheckReview], issues: list[QAIssue],
        suppressed: list[QAIssue], summary: str, manifest: dict[str, Any], batch: dict[str, Any],
    ) -> dict[str, Any]:
        """Store one verse's review, with its own fingerprint, exactly as the
        single-verse review stores it, plus `batch`."""
        project, client = self.project, self.client
        if project.review_input_fingerprint(p.chapter, p.verse) != p.start_fingerprint:
            raise AIError('Verse/project data changed while AI was working; stale AI review was discarded.')
        usage = usage_dict(p.usage)
        saved = project.record_ai_review_result(p.chapter, p.verse, {
            'summary': summary,
            'model': client.model,
            'reasoningEffort': client._effective_reasoning_effort(),
            'estimatedCostUSD': p.cost,
            'dependencySnapshot': dependency_snapshot(project, p.chapter, p.verse, self.knowledge_base, client.model),
            'resourceProvenance': p.resource_provenance,
            'privacyManifest': manifest,
            'usage': usage,
            'alignmentProposal': p.proposal,
            'alignmentWasAIProposed': p.proposal is not None,
            'reviewedAlignment': p.review_alignment.to_dict(),
            'checkReviews': [x.to_dict() for x in reviews],
            'qaIssues': [x.to_dict() for x in issues],
            'semanticMapping': p.semantic_mapping_pack,
            'localTwShadow': p.local_tw_shadow,
            'batch': batch,
        })
        return {
            'resource_provenance': p.resource_provenance, 'saved_to': str(saved),
            'evidence_catalog': p.evidence_catalog, 'model': client.model,
            'reasoning_effort': client._effective_reasoning_effort(),
            'estimated_cost_usd': p.cost, 'usage': usage, 'privacy_manifest': manifest,
            'language_context': p.language.to_dict(), 'suppressed_qa_count': len(suppressed),
            'semantic_mapping': p.semantic_mapping_pack,
            'alignment_was_ai_proposed': p.proposal is not None,
            'total_tokens_for_prepare': p.usage.total_tokens, 'batch': batch,
        }
