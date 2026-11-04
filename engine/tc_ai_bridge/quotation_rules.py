"""Offline, book-wide quotation QA (#456).

Reference punctuation supplies review evidence, never target insertion offsets.
Rules are pack-independent settings, replicated to all collection roots (including
lazy books) through the existing settings writer. No Scripture is written here.
"""
from __future__ import annotations

import copy
import json
import threading
import unicodedata
from pathlib import Path
from typing import Any, Callable

from .language_qa import RULE_VERSION, lift_inline_usfm, rule_fields, stable_finding_id, text_hash

VERSION = 1
_REFERENCE_LOCK = threading.Lock()
_REFERENCES: dict[tuple, Any] = {}
RELATIVE_PATH = Path('.apps/translationCoreAI/language-packs/common/overrides.json')
DEFAULTS = {
    'version': VERSION, 'enabled': True, 'referenceEnabled': True,
    'target': {'pairs': [{'open': '“', 'close': '”'}, {'open': '‘', 'close': '’'}],
               'continuation': 'repeat-opening'},
    'reference': {'pairs': [{'open': '“', 'close': '”'}, {'open': '‘', 'close': '’'}],
                  'continuation': 'repeat-opening'},
}


def validate(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != set(DEFAULTS):
        raise ValueError('Quotation rules require version, enabled, referenceEnabled, target and reference.')
    if type(raw['version']) is not int or raw['version'] != VERSION:
        raise ValueError('Unsupported quotation rules version.')
    for key in ('enabled', 'referenceEnabled'):
        if not isinstance(raw[key], bool):
            raise ValueError(f'{key} must be true or false.')
    for name in ('target', 'reference'):
        style = raw[name]
        if not isinstance(style, dict) or set(style) != {'pairs', 'continuation'}:
            raise ValueError(f'{name} requires pairs and continuation.')
        if style['continuation'] not in ('none', 'repeat-opening'):
            raise ValueError(f'{name}.continuation must be none or repeat-opening.')
        pairs = style['pairs']
        if not isinstance(pairs, list) or not 1 <= len(pairs) <= 4:
            raise ValueError(f'{name}: supply one to four pairs, in outer-to-inner order.')
        seen: list[str] = []
        for pair in pairs:
            if not isinstance(pair, dict) or set(pair) != {'open', 'close'}:
                raise ValueError(f'{name}: each pair needs open and close.')
            marks = [pair['open'], pair['close']]
            for mark in marks:
                if (not isinstance(mark, str) or not 1 <= len(mark) <= 4
                        or any(c.isspace() or c.isalnum() or c == '\\'
                               or unicodedata.category(c).startswith(('C', 'M')) for c in mark)):
                    raise ValueError(f'{name}: quotation marks must be 1–4 punctuation characters.')
            unique = list(dict.fromkeys(marks))
            if any(a.startswith(b) or b.startswith(a) for a in unique for b in seen):
                raise ValueError(f'{name}: quotation pairs overlap or reuse a mark.')
            if len(unique) == 2 and (unique[0].startswith(unique[1]) or unique[1].startswith(unique[0])):
                raise ValueError(f'{name}: opening and closing marks overlap.')
            seen.extend(unique)
    return copy.deepcopy(raw)


def load(root: str | Path) -> dict[str, Any]:
    path = Path(root) / RELATIVE_PATH
    document = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if not isinstance(document, dict):
        raise ValueError('Common rule overrides must be an object.')
    return validate(document['quotations']) if 'quotations' in document else copy.deepcopy(DEFAULTS)


def reference_holder(folder: str, label: str, cache: Path) -> Any:
    """Share one loader with the Reference panel, including its disk-cache write.
    A changed source fingerprint gives both consumers a fresh holder."""
    from .language_packs.reference_text import ReferenceHolder
    from .language_packs.reference_text import detect, fingerprint
    kind = detect(folder)
    key = (fingerprint(folder, kind) if kind else str(Path(folder).resolve()), label, str(cache))
    with _REFERENCE_LOCK:
        holder = _REFERENCES.get(key)
        if holder is None:
            holder = ReferenceHolder(folder, label, cache)
            if len(_REFERENCES) >= 4:
                _REFERENCES.pop(next(iter(_REFERENCES)))
            _REFERENCES[key] = holder
    return holder


def reference_source(folder: str, label: str, cache: Path, proceed: Callable[[], bool]) -> tuple[Any, str]:
    """Load on the QA worker, never the request thread."""
    holder = reference_holder(folder, label, cache)
    while proceed():
        text, error = holder.wait(.05)
        if text is not None or error:
            return text, f'Reference quotation comparison unavailable: {error}' if error else ''
    return None, 'Reference quotation comparison interrupted.'


def _order(value: str) -> tuple[int, str]:
    digits = ''.join(c for c in value.split('-')[0] if c.isdigit())
    return int(digits) if digits else 0, value


def _word(c: str) -> bool:
    return c.isalnum() or unicodedata.category(c).startswith('M')


def _rows(chapters: dict[str, dict[str, Any]]) -> list[tuple[str, str, str, Any]]:
    rows = []
    for chapter in sorted(chapters, key=_order):
        for verse in sorted(chapters[chapter], key=_order):
            raw = chapters[chapter][verse]
            if isinstance(raw, str) and verse[:1].isdigit():
                lifted, _ = lift_inline_usfm(raw)
                rows.append((chapter, verse, raw, lifted))
    return rows


def _scan(rows: list, style: dict, proceed: Callable[[], bool]) -> tuple[list, list, set, list]:
    """errors, complete outer spans, verses with quotation evidence, limitations.

    Stack entries retain chapter/verse and raw spans. Only explicit paragraph
    starts and verse-leading marks count as continuation positions. Importers
    can omit the paragraph marker before a verse, and reference TSV is plain
    text. This permissive convention is explicit and can be disabled.
    """
    pairs = style['pairs']
    opens = {p['open']: i for i, p in enumerate(pairs)}
    closes = {p['close']: i for i, p in enumerate(pairs)}
    marks = sorted(set(opens) | set(closes), key=len, reverse=True)
    stack: list = []
    errors, spans, occupied, notes = [], [], set(), []
    for row_index, (chapter, verse, raw, lifted) in enumerate(rows):
        if not proceed():
            return [], [], set(), ['Quotation check interrupted.']
        if lifted is None:
            notes.append(f'Quotation text could not be read at {chapter}:{verse}.')
            continue
        text = lifted.visible
        if stack:
            occupied.add(row_index)
        at = 0
        while at < len(text):
            mark = next((m for m in marks if text.startswith(m, at)), None)
            if mark is None:
                at += 1
                continue
            end = at + len(mark)
            # Single quotes inside a word are apostrophes, including Indic
            # combining marks. Their use is independent of quotation nesting.
            if mark in ("'", '’', '‘') and at and end < len(text) and _word(text[at - 1]) and _word(text[end]):
                at = end
                continue
            # A trailing apostrophe (e.g. Jesus’ disciples) must not make a
            # whole reference book look unbalanced. When an inner quotation
            # actually is open, its matching closer still takes precedence.
            if (mark in ("'", '’') and at and _word(text[at - 1])
                    and (end == len(text) or not _word(text[end]))
                    and not (stack and closes.get(mark) == stack[-1][0])):
                at = end
                continue
            occupied.add(row_index)
            start_raw, end_raw = lifted.raw_index[at], lifted.raw_index[end - 1] + 1
            event = (row_index, chapter, verse, raw, start_raw, end_raw, mark)
            opener = opens.get(mark)
            closer = closes.get(mark)
            paragraph = not text[:at].strip() or (at > 0 and text[:at].rstrip(' \t').endswith('\n'))
            if stack and paragraph and style['continuation'] == 'repeat-opening':
                # A continued nested quotation may repeat the entire active
                # chain (e.g. “ ‘), or just its innermost opener. Check this
                # before symmetric straight marks would otherwise close it.
                cursor = at
                for level, _ in stack:
                    repeated = pairs[level]['open']
                    while cursor < len(text) and text[cursor] in ' \t':
                        cursor += 1
                    if not text.startswith(repeated, cursor):
                        break
                    cursor += len(repeated)
                else:
                    at = cursor
                    continue
                if mark == pairs[stack[-1][0]]['open']:
                    at = end
                    continue
            if stack and closer == stack[-1][0]:
                _, opening = stack.pop()
                if not stack:
                    spans.append((opening, event))
            elif opener is not None:
                expected = len(stack) % len(pairs)
                if opener != expected:
                    errors.append((event, f'Unexpected opening {mark}; expected {pairs[expected]["open"]} at this nesting level.'))
                stack.append((opener, event))
            else:
                errors.append((event, f'Closing {mark} has no matching opening {pairs[closer]["open"]} in this book.'))
            at = end
    for level, event in stack:
        errors.append((event, f'Opening {event[-1]} has no closing {pairs[level]["close"]} later in this book.'))
    return errors, spans, occupied, notes


def quotation_findings(book: str, chapters: dict, config: dict | None = None, *,
                       reference: Any = None, reference_note: str = '',
                       proceed: Callable[[], bool] = lambda: True) -> tuple[list[dict], list[str]]:
    rules = validate(config) if config is not None else copy.deepcopy(DEFAULTS)
    if not rules['enabled']:
        return [], []
    rows = _rows(chapters)
    errors, _, occupied, notes = _scan(rows, rules['target'], proceed)
    findings: list[dict] = []

    def add(rule: str, event: tuple, message: str, identity: str = '') -> dict:
        _, chapter, verse, raw, start, end, _ = event
        original = raw[start:end]
        finding = {
            'id': stable_finding_id(book, chapter, verse, rule, identity or f'{original}@{start}', 1),
            'book': book, 'chapter': chapter, 'verse': verse, 'rule': rule, 'severity': 'medium',
            'start': start, 'end': end, 'originalText': original, 'message': message,
            'textHash': text_hash(raw), 'ruleVersion': RULE_VERSION, 'status': 'review-needed',
            **rule_fields(rule, []),
        }
        stamp = text_hash(json.dumps(rules['target'] if rule == 'punctuation.unbalanced-quote'
                                    else rules, sort_keys=True, ensure_ascii=False))[:12]
        finding['packVersion'] = f'{RULE_VERSION}-quotes-{stamp}'
        finding['ruleVersion'] = finding['packVersion']
        findings.append(finding)
        return finding

    grouped: dict[tuple, tuple[tuple, list[str]]] = {}
    for event, message in errors:
        key = (event[1], event[2], event[4], event[5])
        if key not in grouped:
            grouped[key] = (event, [])
        grouped[key][1].append(message)
    for event, messages in grouped.values():
        add('punctuation.unbalanced-quote', event, ' '.join(dict.fromkeys(messages)))
    if not rules['referenceEnabled']:
        return findings, notes
    if reference is None:
        return findings, notes + [reference_note or 'Reference quotation comparison unavailable: choose a local reference Bible in Settings → Language QA.']
    ref_rows = _rows(reference.verses.get(book.upper(), {}))
    if not ref_rows:
        return findings, notes + [f'Reference quotation comparison unavailable: {reference.label} has no {book.upper()} text.']
    ref_errors, spans, _, ref_notes = _scan(ref_rows, rules['reference'], proceed)
    if ref_errors or ref_notes:
        return findings, notes + [f'Reference quotation comparison skipped: {reference.label} has unbalanced/unsupported quotation text; check its quotation rules.']
    if not spans:
        return findings, notes + [f'Reference quotation comparison: {reference.label} has no complete quotations under the configured reference rules; coverage is unverified.']
    target_keys = {(c, v): i for i, (c, v, _, _) in enumerate(rows)}
    for opening, closing in spans:
        if not proceed():
            break
        corresponding = ref_rows[opening[0]:closing[0] + 1]
        keys = [(r[0], r[1]) for r in corresponding]
        label = f'{book.upper()} {opening[1]}:{opening[2]}–{closing[1]}:{closing[2]}'
        # Require exact reference keys, not numeric coercion of bridges or
        # segments. An uncertain mapping is a limitation, never a clean pass.
        if any(k not in target_keys or rows[target_keys[k]][3] is None
               or not rows[target_keys[k]][3].visible.strip() for k in keys):
            notes.append(f'Reference quotation comparison skipped at {label}: missing or ambiguous target verse correspondence.')
            continue
        indices = [target_keys[k] for k in keys]
        if indices != list(range(indices[0], indices[-1] + 1)):
            notes.append(f'Reference quotation comparison skipped at {label}: differing verse segmentation.')
            continue
        if any(i in occupied for i in indices):
            continue
        c, v, raw, lifted = rows[indices[0]]
        # Highlight existing visible content, not an invented insertion point.
        start, end = lifted.raw_index[0], lifted.raw_index[-1] + 1
        event = (indices[0], c, v, raw, start, end, '')
        f = add('quotation.reference-missing', event,
                f'Possible missing quotation marks: {reference.label} quotes {label}, but the corresponding target passage has no quotation marks under its configured rules. Review the passage; indirect speech or different boundaries may be intentional.', label)
        f['referenceEvidence'] = {'label': reference.label, 'path': reference.path, 'range': label,
                                  'openingText': opening[3], 'closingText': closing[3]}
        evidence_version = text_hash(json.dumps(f['referenceEvidence'], sort_keys=True, ensure_ascii=False))[:12]
        f['packVersion'] += f'-{evidence_version}'
        f['ruleVersion'] = f['packVersion']
    return findings, notes
