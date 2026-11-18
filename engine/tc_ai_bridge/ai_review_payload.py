"""What the AI review request carries, as distinct from what Bridge keeps (#500).

The verse review builds a full evidence pack locally and stores it with the
result. The request needs less: each fact once, and no field the instructions
never mention. The functions here produce the sent form; nothing here reads or
writes a project, and the local records (`resourceProvenance`, the full
evidence items a review cites, `languageContext`) are unchanged.

Two kinds of cut, kept apart on purpose:

- Duplication and unused fields. Always on. The model is asked the same thing
  about the same evidence; a fact it was sent twice is sent once.
- Evidence the model can read today and would no longer see (three sections of
  a translationWords article, the term's occurrence list, the example sections
  of a Translation Academy article). Behind `ReviewPayloadOptions`, all off by
  default, because whether a verdict depends on them has to be measured against
  a translator-judged run, not assumed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class ReviewPayloadOptions:
    """Switches for the review request. Every one defaults to today's request.

    `lean_*` remove evidence the model would otherwise read; `count_in_input`
    moves the verse's check count out of the instructions and the answer schema
    into the input, so both are identical for every verse of a project (the
    #500 prompt-cache hypothesis). With it on, the provider no longer enforces
    the row count; the parser's missing-row and duplicate checks still do.
    """

    lean_tw_articles: bool = False
    lean_twl_occurrences: bool = False
    lean_ta_examples: bool = False
    count_in_input: bool = False

    @classmethod
    def from_settings(cls, value: Any) -> 'ReviewPayloadOptions':
        """From `AppSettings.ai_review`: `leanEvidence` switches the three
        evidence cuts together, `countInInput` the cache experiment."""
        data = value if isinstance(value, dict) else {}
        lean = bool(data.get('leanEvidence', False))
        return cls(
            lean_tw_articles=lean, lean_twl_occurrences=lean, lean_ta_examples=lean,
            count_in_input=bool(data.get('countInInput', False)),
        )


# The only keys one evidence item carries into a request. `source_path` is a
# local folder path with the Windows user name in it, `sha256` / `version` /
# `provider` / `identifier` / `authoritative` are provenance Bridge keeps with
# the stored review and the model is never asked about.
SENT_EVIDENCE_FIELDS = ('kind', 'title', 'content')

# Evidence items that restate a field already on the check row: the source
# quote (`source_quote`) and the note text (`occurrenceNote`).
_RESTATED_EVIDENCE_KINDS = frozenset({'originalQuote', 'translationNote'})

_HEADING = re.compile(r'^(#{1,6})\s+(.*?)\s*$')

# translationWords: the Definition and Translation Suggestions are what a
# rendering is judged against; these three sections are cross-references.
TW_DROPPED_SECTIONS = ('bible references', 'examples from the bible stories', 'word data')
# Translation Academy: the description, the reasons and the strategies stay;
# the worked examples go.
TA_DROPPED_SECTION_PREFIXES = (
    'examples from', 'other examples from', 'examples of translation strategies applied',
    'translation strategies applied',
)


def _heading_title(line: str) -> tuple[int, str] | None:
    match = _HEADING.match(line)
    if not match:
        return None
    return len(match.group(1)), match.group(2).rstrip(':').strip().casefold()


def drop_markdown_sections(text: str, *, exact: Iterable[str] = (), prefixes: Iterable[str] = ()) -> str:
    """Remove whole sections from a markdown article: a heading whose title
    matches, and everything under it up to the next heading of the same or a
    higher level. Titles are compared case-insensitively without a trailing
    colon. Text outside the matched sections is returned verbatim."""
    exact_set = {str(x).casefold() for x in exact}
    prefix_list = tuple(str(x).casefold() for x in prefixes)
    kept: list[str] = []
    dropping_level = 0
    for line in str(text).split('\n'):
        heading = _heading_title(line)
        if heading is not None:
            level, title = heading
            if dropping_level and level > dropping_level:
                continue
            dropping_level = 0
            if title in exact_set or any(title.startswith(p) for p in prefix_list):
                dropping_level = level
                continue
        elif dropping_level:
            continue
        kept.append(line)
    return '\n'.join(kept).rstrip()


def sent_evidence_item(item: dict[str, Any], options: ReviewPayloadOptions) -> dict[str, Any]:
    """One catalog item as the request carries it."""
    kind = str(item.get('kind') or '')
    content = str(item.get('content') or '')
    if kind == 'translationWords' and options.lean_tw_articles:
        content = drop_markdown_sections(content, exact=TW_DROPPED_SECTIONS)
    elif kind == 'translationAcademy' and options.lean_ta_examples:
        content = drop_markdown_sections(content, prefixes=TA_DROPPED_SECTION_PREFIXES)
    return {'kind': kind, 'title': str(item.get('title') or ''), 'content': content}


def sent_check_evidence(
    evidence: list[tuple[str, dict[str, Any]]], options: ReviewPayloadOptions,
) -> list[str]:
    """The evidence ids of one check that go into the request, from its
    `(id, full item)` pairs in catalog order.

    An item that restates the check row is left out, unless that would leave
    the check with nothing to cite: a review with no cited evidence is never
    applied automatically, so a check keeps at least one citable item. The
    occurrence list is left out only under `lean_twl_occurrences`.
    """
    kept: list[str] = []
    restated: list[str] = []
    for eid, item in evidence:
        kind = str(item.get('kind') or '')
        if kind in _RESTATED_EVIDENCE_KINDS:
            restated.append(eid)
            continue
        if kind == 'translationWordsLinks' and options.lean_twl_occurrences:
            continue
        kept.append(eid)
    if not kept and restated:
        # Prefer the note (the last restated item) over the bare quote.
        kept = restated[-1:]
    return kept


def sent_language_context(language: Any) -> dict[str, Any]:
    """The language pair and the editorial categories. Fonts, text direction
    and the detection basis are display facts; `prompt_guidance` is already a
    sentence of the instructions."""
    return {
        'source': str(language.source_name), 'target': str(language.target_name),
        'qa_categories': list(language.qa_categories),
    }


def sent_token(token_id: str, token: Any, *, source: bool) -> dict[str, Any]:
    """One word of a verse. `occurrence` / `occurrences` are sent only for a
    word that occurs more than once; a word without them occurs once."""
    row: dict[str, Any] = {'id': token_id, 'word': token.word}
    if int(getattr(token, 'occurrences', 1) or 1) > 1:
        row['occurrence'] = token.occurrence
        row['occurrences'] = token.occurrences
    if source:
        row['strong'] = token.strong
        row['lemma'] = token.lemma
        row['morph'] = token.morph
    return row


def sent_alignment_groups(alignment: Any, inventory: Any) -> list[dict[str, Any]]:
    """The existing alignment as ids into the two word lists, which already
    carry each word's text, lemma, morphology and Strong's number."""
    groups: list[dict[str, Any]] = []
    for group in alignment.alignments:
        groups.append({
            'source_ids': [
                inventory.top_sig_to_id[x.signature] for x in group.top_words
                if x.signature in inventory.top_sig_to_id
            ],
            'target_ids': [
                inventory.bottom_sig_to_id[x.signature] for x in group.bottom_words
                if x.signature in inventory.bottom_sig_to_id
            ],
        })
    return groups


# Distinct source forms listed beside one rendering, and distinct renderings
# listed for one term.
RENDERING_SOURCE_QUOTES_MAX = 3
RENDERING_GROUPS_MAX = 10
# Keys of one grouped rendering; `security.ai_payload_manifest` reports any
# other key on a rendering record as reviewer identity.
RENDERING_GROUP_FIELDS = ('selections', 'count', 'source_quotes', 'nothingToSelect', 'invalidated')


def approved_rendering_groups(
    renderings: Iterable[dict[str, Any]], limit: int = RENDERING_GROUPS_MAX,
) -> list[dict[str, Any]]:
    """Group projected renderings (`ai_client.project_term_rendering`) of one
    term by what was selected, most used first.

    A project that renders a term the same way in 28 verses used to send 28
    rows differing only in the verse reference; it now sends one row with
    `count: 28`. Rows that differ in what was selected, or in whether the
    record is a Nothing-to-Select or an invalidated one, stay separate. Ties
    keep first-seen order, so the result is stable from verse to verse.
    """
    groups: dict[tuple[Any, ...], dict[str, Any]] = {}
    for record in renderings:
        selections = [str(x) for x in (record.get('selections') or [])]
        nothing = bool(record.get('nothingToSelect', False))
        invalidated = bool(record.get('invalidated', False))
        key = (tuple(selections), nothing, invalidated)
        group = groups.get(key)
        if group is None:
            group = groups[key] = {
                'selections': selections, 'count': 0, 'source_quotes': [],
                'nothingToSelect': nothing, 'invalidated': invalidated,
            }
        group['count'] += 1
        quote = str(record.get('source_quote') or '')
        if quote and quote not in group['source_quotes'] and len(group['source_quotes']) < RENDERING_SOURCE_QUOTES_MAX:
            group['source_quotes'].append(quote)
    ordered = sorted(groups.values(), key=lambda g: -int(g['count']))
    return ordered[:max(0, int(limit))]


def sent_mapping_states(pack: dict[str, Any] | None) -> tuple[list[Any], list[Any]]:
    """The Stage 3 mapping of a verse's passage as the request carries it:
    `(check states, unresolved rows)`.

    The pack states each located meaning twice, as a mapping row keyed by
    source unit and as a check state keyed by check, with the same target
    spans, relationships and meaning status. The check states go; the two
    facts only the mapping row held (the mapper's confidence and its one-line
    explanation) are carried onto the check state, so nothing the model could
    read is lost. An unresolved row that is already a check state, verbatim
    (an unresolved source anchor is listed in both), is not sent twice.
    """
    if not isinstance(pack, dict):
        return [], []
    by_unit = {
        str(row.get('source_unit_id')): row
        for row in pack.get('mappings', []) if isinstance(row, dict) and row.get('source_unit_id')
    }
    raw_states = list(pack.get('checkStates', []) or [])
    states: list[Any] = []
    for row in raw_states:
        if not isinstance(row, dict):
            states.append(row)
            continue
        sent = dict(row)
        mapping = by_unit.get(str(row.get('sourceUnitId') or ''))
        if mapping is not None:
            if mapping.get('confidence') is not None:
                sent['confidence'] = mapping.get('confidence')
            evidence = mapping.get('evidence')
            explanation = str(evidence.get('explanation') or '') if isinstance(evidence, dict) else ''
            if explanation:
                sent['explanation'] = explanation
        states.append(sent)
    unresolved = [row for row in (pack.get('unresolved', []) or []) if row not in raw_states]
    return states, unresolved
