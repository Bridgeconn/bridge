from __future__ import annotations

from collections import Counter
from pathlib import Path

from . import check_timing
from .models import QAIssue, VerseAlignment
from .tc_project import TranslationCoreProject
from .plugins import PluginRegistry, ProjectLanguageContext
from .usfm import strip_usfm, whitespace_tokens
from .usfm_verse import balance_message, redundant_style_reopens, unbalanced_markers


def alignment_integrity_checks(verse: VerseAlignment, target_text: str = '', target_name: str = 'Tamil', source_name: str = 'Hebrew') -> list[QAIssue]:
    issues: list[QAIssue] = []
    top = verse.all_top(); aligned_bottom = verse.aligned_bottom(); bank = verse.word_bank
    top_counts = Counter(x.signature for x in top)
    bottom_counts = Counter(x.signature for x in aligned_bottom)
    bank_counts = Counter(x.signature for x in bank)
    for sig, n in top_counts.items():
        if n > 1:
            # group_id: the token, so two duplicated tokens never share a
            # finding id and the count is not part of it (#273).
            issues.append(QAIssue('ALIGN_DUP_TOP', 'critical', f'{source_name} token aligned more than once', f'The same topWord identity appears in {n} alignment groups.', group_id=sig))
    for sig, n in bottom_counts.items():
        if n > 1:
            issues.append(QAIssue('ALIGN_DUP_BOTTOM', 'critical', f'{target_name} token aligned more than once', f'The same bottomWord identity appears in {n} alignment groups.', group_id=sig))
    overlap = set(bottom_counts) & set(bank_counts)
    if overlap:
        issues.append(QAIssue('ALIGN_BANK_OVERLAP', 'critical', f'{target_name} token both aligned and in wordBank', f'{len(overlap)} {target_name} token(s) are represented in both places.'))
    empty_bottom = sum(1 for g in verse.alignments if g.top_words and not g.bottom_words)
    if empty_bottom:
        issues.append(QAIssue('ALIGN_UNALIGNED_TOP', 'high', f'Unaligned {source_name} source tokens', f'{empty_bottom} alignment group(s) have topWords but no bottomWords.'))
    if bank:
        issues.append(QAIssue('ALIGN_UNALIGNED_BOTTOM', 'medium', f'Unaligned {target_name} target tokens', f'{len(bank)} {target_name} bottomWord token(s) remain in wordBank.'))
    for token in top + aligned_bottom + bank:
        if token.occurrence < 1 or token.occurrences < 1 or token.occurrence > token.occurrences:
            issues.append(QAIssue('ALIGN_OCCURRENCE', 'critical', 'Invalid occurrence metadata', f'{token.word}: occurrence {token.occurrence}, occurrences {token.occurrences}'))
    if target_text:
        plain = strip_usfm(target_text)
        missing = [t.word for t in aligned_bottom + bank if t.word and t.word not in plain]
        if missing:
            sample = ', '.join(missing[:8])
            issues.append(QAIssue('ALIGN_TARGET_MISMATCH', 'high', f'Alignment token not found in current {target_name} verse', f'{len(missing)} token(s) do not occur verbatim in the current verse text. Examples: {sample}. This may indicate stale alignmentData after a verse edit.'))
    return issues


def target_editorial_checks(text: str, language: ProjectLanguageContext | None = None) -> list[QAIssue]:
    # Repeated spaces and zero-width/BOM characters were checked here too
    # ({TA|LANG}_DOUBLE_SPACE, {TA|LANG}_HIDDEN_CHAR) until #234. Language QA
    # owns them now (spacing.extra, unicode.invisible): it runs for every pack,
    # is cached per verse, draws inline and offers the fix, and one character
    # no longer makes three findings with three decisions. The codes stay known
    # to _categorize_qaissue for findings recorded before.
    issues: list[QAIssue] = []
    prefix = 'TA' if (language is None or language.target_id == 'ta') else 'LANG'
    tokens = whitespace_tokens(text)
    for a, b in zip(tokens, tokens[1:]):
        if a == b:
            issues.append(QAIssue(f'{prefix}_REPEAT_WORD', 'medium', 'Consecutive repeated word', f'“{a}” occurs twice consecutively. Verify that the repetition is intentional.'))
            break
    return issues


_TOOL_GROUP = {'translationNotes': 'tN', 'translationWords': 'tW'}


def translationcore_check_issues(project: TranslationCoreProject, chapter: str, verse: str,
                                 groups: frozenset[str] = frozenset({'tN', 'tW', 'alignment'})) -> list[QAIssue]:
    """`groups` (#251): tN and tW pick their own tool's items; any other tool's
    items, comments and edit history come with either; Word Alignment's
    invalid state is the alignment group's."""
    issues: list[QAIssue] = []
    tc = bool(groups & {'tN', 'tW'})
    if not tc and 'alignment' not in groups:
        return issues
    checks = project.checks_for_verse(chapter, verse) if tc else []
    # The verse's selections, invalidations, comments and verse edits, read
    # once: every check's staleness is answered from them (#240).
    states = project.check_state_for_verse(chapter, verse) if tc else {}
    for entry in checks:
        ctx = entry.get('contextId', {})
        tool = str(ctx.get('tool', 'translationCore'))
        if _TOOL_GROUP.get(tool, 'tc') not in groups | {'tc'}:
            continue
        group = str(ctx.get('groupId', ''))
        check_id = str(ctx.get('checkId', ''))
        selection = entry.get('selections', False)
        nothing = bool(entry.get('nothingToSelect', False))
        invalid = bool(entry.get('invalidated', False))
        stale = project.check_staleness(chapter, verse, check_id, tool, group, state=states) == 'stale'
        if invalid or stale:
            reason = 'invalidated' if invalid else 'stale after a later Scripture edit'
            issues.append(QAIssue('TC_INVALIDATED' if invalid else 'TC_STALE_AFTER_EDIT', 'high', f'{tool}: recheck required', f'{group} / {check_id} is {reason}.', 'translationCore', check_id, group))
        elif selection is False and not nothing:
            sev = 'medium' if tool == 'translationNotes' else 'high'
            note = str(ctx.get('occurrenceNote', '') or '')
            issues.append(QAIssue('TC_PENDING', sev, f'{tool}: unchecked item', note or f'{group} / {check_id} has no selection yet.', 'translationCore', check_id, group))
    if 'alignment' in groups and project.word_alignment_state(chapter, verse) == 'invalid':
        issues.append(QAIssue('WA_INVALID', 'high', 'Word Alignment recheck required', 'translationCore marks Word Alignment invalid after a target-text edit.', 'translationCore'))
    if states.get('comments'):
        issues.append(QAIssue('TC_COMMENTS', 'info', 'Reviewer comments present', f'{len(states["comments"])} translationCore comment(s) exist for this verse.', 'translationCore'))
    if states.get('verseEdits'):
        issues.append(QAIssue('TC_VERSE_EDITS', 'info', 'Verse edit history present', f'{len(states["verseEdits"])} translationCore verse edit record(s) exist.', 'translationCore'))
    return issues


def usfm_checks(project: TranslationCoreProject, chapter: str, verse: str) -> list[QAIssue]:
    text = project.target_verse_text(chapter, verse)
    # group_id: the marker, not the counts in the message (#273).
    issues = [QAIssue('USFM_BALANCE', 'high', 'USFM marker imbalance', balance_message(marker, opens, closes),
                      'local', group_id=marker) for marker, opens, closes in unbalanced_markers(text)]
    # A character style closed and reopened with nothing between (#203): the
    # space inside the reopened marker is syntax, so readers glue the words
    # (`lepers\wj*\wj in` reads "lepersin"). The fix is mechanical and offered
    # as a one-click replacement; nothing is changed without the reviewer.
    for ordinal, fix in enumerate(redundant_style_reopens(text), start=1):
        before = text[max(0, fix.start - 12):fix.start]
        after = text[fix.end:fix.end + 12]
        shown = (before + "·" + after).replace("\n", " ")
        issues.append(QAIssue(
            'USFM_REDUNDANT_MARKER', 'medium',
            f'\\{fix.marker} closed and reopened with nothing between',
            f'Readers join the words on either side ("{shown}"); merging the two runs keeps the text as written.',
            'local', group_id=f'{fix.marker}#{ordinal}',
            start_offset=fix.start, end_offset=fix.end,
            original_text=fix.original, suggested_replacement=fix.replacement,
        ))
    return issues


def versification_checks(project: TranslationCoreProject, chapter: str, verse: str) -> list[QAIssue]:
    """#352: a source verse that lands in no target verse under the book's
    recorded versification (UGNT 3JN 1:15 against a 14-verse 3 John) is
    raised on the nearest target verse as "source verse not in target
    versification", with the source words, so it is visible from there and
    the reviewer decides. Never merged into a neighbour by guess; the target
    text is not changed. Severity medium: a thing to look at, not an error in
    the text, so it does not block the advisory gate (#337)."""
    from .source_verse_map import UNPLACED_CHECK_ID, UNPLACED_CODE, schema_from_manifest, unplaced_for_project
    issues: list[QAIssue] = []
    schema = schema_from_manifest(getattr(project, 'manifest', None))
    for item in unplaced_for_project(project):
        if (str(item.get('nearestChapter')), str(item.get('nearestVerse'))) != (str(chapter), str(verse)):
            continue
        source_ref = f"{item['sourceChapter']}:{item['sourceVerse']}"
        words = list(item.get('words') or [])
        shown = ' '.join(words[:8]) + (' …' if len(words) > 8 else '')
        issues.append(QAIssue(
            code=UNPLACED_CODE, severity='medium',
            title=f'Source verse {source_ref} is not in the target versification',
            detail=(f'The original-language text has {source_ref} ({len(words)} words: {shown}), but under the '
                    f'"{schema}" versification no verse of this book receives it, so its words cannot be aligned or '
                    f'checked here. {chapter}:{verse} is the nearest target verse. The target text was not changed.'),
            source='versification', check_id=UNPLACED_CHECK_ID, group_id=source_ref,
        ))
    return issues


LOCAL_QA_GROUPS = frozenset({'tN', 'tW', 'alignment', 'text'})


def run_local_qa(project: TranslationCoreProject, chapter: str, verse: str, alignment: VerseAlignment,
                 groups: frozenset[str] | set[str] | None = None) -> list[QAIssue]:
    """The verse's Bridge-side checks, only the `groups` asked for (#251):
    tN, tW (translationCore items), alignment (integrity and Word Alignment
    state) and text (USFM markers, repeated words). None runs all four."""
    groups = LOCAL_QA_GROUPS if groups is None else frozenset(groups) & LOCAL_QA_GROUPS
    timings = check_timing.current()
    with timings.step("local.read_text"):
        text = project.target_verse_text(chapter, verse)
    issues = []
    language = None
    if groups & {'alignment', 'text'}:
        with timings.step("local.detect_language"):
            language = PluginRegistry().detect_project(project, alignment, text)
    if 'alignment' in groups:
        with timings.step("local.alignment_integrity"):
            issues += alignment_integrity_checks(alignment, text, language.target_name, language.source_name)
        with timings.step("local.versification"):
            issues += versification_checks(project, chapter, verse)
    if groups & {'tN', 'tW', 'alignment'}:
        with timings.step("local.tc_checks"):
            issues += translationcore_check_issues(project, chapter, verse, groups)
    if 'text' in groups:
        with timings.step("local.editorial"):
            issues += target_editorial_checks(text, language)
        with timings.step("local.usfm"):
            issues += usfm_checks(project, chapter, verse)
    order = {'critical': 0, 'high': 1, 'medium': 2, 'editorial': 3, 'info': 4}
    return sorted(issues, key=lambda x: (order.get(x.severity, 9), x.title))
