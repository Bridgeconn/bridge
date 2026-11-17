"""A local rule for translationWords checks, in shadow mode only (#501).

Some translationWords checks may not need a model: the word aligned to the
source term in this verse is already a rendering the project uses for that
term. This module works out what such a rule WOULD decide and nothing more.
It reads the project; it never writes to it, never changes a request, never
skips a call and never applies a selection. Its result is stored beside the
AI review as a diagnostic (`localTwShadow`) so the two can be compared.

Letting the rule take a check away from the AI, or recording its answer as a
check result, changes who decides a check. That is a change to the auto-apply
behaviour, needs an entry in `docs/DECISIONS.md` first, and is deliberately not
something this module can do: there is no mode but `shadow`, and nothing here
returns anything a caller could apply.

The rule, exactly (#501, "Nothing else qualifies"):

1. The check is a translationWords check that is not invalidated.
2. Every word of its source quote is found among the verse's aligned source
   words, by word and occurrence. A word that repeats in the verse without the
   check saying which occurrence is meant does not qualify.
3. Each of those source words sits in an alignment group that has target
   words, and those groups hold no other source word (no partial match: a
   group that also renders a neighbouring source word is not a rendering of
   this term alone).
4. The target words of those groups are, as a set of words, exactly the
   selection of another check of the same term in this project that is not a
   Nothing-to-Select and not invalidated. The check's own stored selection is
   never counted, so a re-review cannot agree with itself.
"""
from __future__ import annotations

import unicodedata
from collections import Counter
from typing import Any, Callable

MODE = 'shadow'
RULE_VERSION = 1
# References listed for a matched rendering, for the comparison.
_MATCH_REFERENCES_MAX = 8


def _norm(word: Any) -> str:
    return unicodedata.normalize('NFC', str(word or '')).strip()


def _quote_words(context: dict[str, Any]) -> list[tuple[str, int | None]]:
    """The quote as `(word, occurrence or None)`. translationCore stores a
    quote either as one string with one occurrence for the phrase, or as a
    list of words that each carry their own occurrence."""
    quote = context.get('quote')
    if isinstance(quote, list) and quote:
        words: list[tuple[str, int | None]] = []
        for item in quote:
            if isinstance(item, dict) and _norm(item.get('word')) and _norm(item.get('word')) != '&':
                try:
                    occurrence: int | None = int(item.get('occurrence'))
                except (TypeError, ValueError):
                    occurrence = None
                words.append((_norm(item.get('word')), occurrence))
        return words
    text = _norm(context.get('quoteString') if context.get('quoteString') is not None else quote)
    parts = [p for p in text.split() if p and p != '&']
    if len(parts) == 1:
        try:
            return [(parts[0], int(context.get('occurrence') or 1))]
        except (TypeError, ValueError):
            return [(parts[0], 1)]
    # A phrase: the check's occurrence counts the phrase, not each word.
    return [(p, None) for p in parts]


def _selection_texts(selections: Any) -> list[str]:
    texts: list[str] = []
    if isinstance(selections, list):
        for item in selections:
            if isinstance(item, dict) and _norm(item.get('text')):
                texts.append(_norm(item.get('text')))
            elif isinstance(item, str) and _norm(item):
                texts.append(_norm(item))
    return texts


def _term_renderings(
    project: Any, group_id: str, own: tuple[str, str, str],
    accept_reference: Callable[[str, str], bool] | None = None,
) -> list[dict[str, Any]]:
    """Every other check of the term that has a selection: `{reference, texts}`.
    `accept_reference(chapter, verse)` narrows which verses count."""
    out: list[dict[str, Any]] = []
    for entry in project._load_index_tool('translationWords'):
        context = entry.get('contextId', {}) if isinstance(entry, dict) else {}
        if str(context.get('groupId')) != group_id:
            continue
        reference = context.get('reference', {}) if isinstance(context.get('reference'), dict) else {}
        key = (str(reference.get('chapter')), str(reference.get('verse')), str(context.get('checkId')))
        if key == own:
            continue
        if accept_reference is not None and not accept_reference(key[0], key[1]):
            continue
        if entry.get('nothingToSelect') or entry.get('invalidated'):
            continue
        texts = _selection_texts(entry.get('selections'))
        if texts:
            out.append({'reference': f'{key[0]}:{key[1]}', 'texts': texts})
    return out


def shadow_check(
    project: Any, chapter: str, verse: str, entry: dict[str, Any], alignment: Any,
    accept_reference: Callable[[str, str], bool] | None = None,
) -> dict[str, Any]:
    """What the rule would decide for one check. `wouldPass` is true only
    when every condition in the module docstring holds; otherwise `reason`
    says which one did not."""
    context = entry.get('contextId', {}) if isinstance(entry.get('contextId'), dict) else {}
    group_id = str(context.get('groupId') or '')
    check_id = str(context.get('checkId') or '')
    row: dict[str, Any] = {
        'checkId': check_id, 'groupId': group_id,
        'sourceQuote': str(context.get('quoteString') or ''),
        'wouldPass': False, 'reason': '', 'alignedTargetWords': [],
        'matchedRendering': None, 'matchingRenderings': 0, 'matchingReferences': [],
        'renderingsConsidered': 0,
    }

    def stop(reason: str) -> dict[str, Any]:
        row['reason'] = reason
        return row

    if entry.get('invalidated'):
        return stop('check is invalidated')
    words = _quote_words(context)
    if not words:
        return stop('check has no source quote')

    groups = list(alignment.alignments)
    top = [(index, token) for index, group in enumerate(groups) for token in group.top_words]
    used_groups: list[int] = []
    quote_signatures: set[str] = set()
    for word, occurrence in words:
        matches = [(index, token) for index, token in top if _norm(token.word) == word]
        if occurrence is not None:
            matches = [(index, token) for index, token in matches if int(token.occurrence or 1) == occurrence]
        if not matches:
            return stop('source quote is not among the verse\'s aligned source words')
        if len(matches) > 1:
            return stop('a quoted source word repeats in the verse and the check does not say which')
        index, token = matches[0]
        quote_signatures.add(token.signature)
        if index not in used_groups:
            used_groups.append(index)

    aligned: list[str] = []
    for index in used_groups:
        group = groups[index]
        if not group.bottom_words:
            return stop('source quote is not aligned to any target word')
        if any(token.signature not in quote_signatures for token in group.top_words):
            return stop('the alignment group also holds another source word (partial match)')
        aligned.extend(_norm(token.word) for token in group.bottom_words)
    row['alignedTargetWords'] = aligned

    renderings = _term_renderings(project, group_id, (str(chapter), str(verse), check_id), accept_reference)
    row['renderingsConsidered'] = len(renderings)
    if not renderings:
        return stop('the project has no other rendering of this term yet')
    wanted = Counter(aligned)
    matching = [r for r in renderings if Counter(r['texts']) == wanted]
    if not matching:
        return stop('the aligned words are not a rendering the project already uses for this term')
    row['wouldPass'] = True
    row['matchedRendering'] = matching[0]['texts']
    row['matchingRenderings'] = len(matching)
    row['matchingReferences'] = [r['reference'] for r in matching[:_MATCH_REFERENCES_MAX]]
    return row


def shadow_tw_decisions(
    project: Any, chapter: str, verse: str, alignment: Any,
    accept_reference: Callable[[str, str], bool] | None = None,
) -> dict[str, Any]:
    """The shadow record for one verse: one row per translationWords check.

    `alignment` is the verse's stored alignment, not one an AI call filled in:
    a rule that ran instead of the AI would have nothing else. Never raises;
    a failure is recorded as `error` so it cannot cost a verse its review.

    `accept_reference(chapter, verse)` limits which verses' selections count
    as renderings. The review passes none (every other check of the term
    counts); `scripts/compare_local_tw_shadow.py` uses it to ask what the rule
    would have found on a first run, when only earlier verses had selections.
    """
    record: dict[str, Any] = {'mode': MODE, 'ruleVersion': RULE_VERSION, 'twChecks': 0, 'wouldPass': 0, 'checks': []}
    try:
        for entry in project.checks_for_verse(chapter, verse):
            context = entry.get('contextId', {}) if isinstance(entry, dict) else {}
            if str(context.get('tool')) != 'translationWords':
                continue
            record['checks'].append(
                shadow_check(project, str(chapter), str(verse), entry, alignment, accept_reference)
            )
        record['twChecks'] = len(record['checks'])
        record['wouldPass'] = sum(1 for row in record['checks'] if row['wouldPass'])
    except Exception as exc:  # a diagnostic must never fail the review it sits beside
        record['error'] = f'{type(exc).__name__}: {exc}'
    return record
