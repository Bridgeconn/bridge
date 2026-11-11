from __future__ import annotations

import json, re
from pathlib import Path
from typing import Any

SECRET_PATTERNS=[re.compile(r'\bsk-[A-Za-z0-9_-]{12,}\b'),re.compile(r'Authorization\s*:\s*Bearer\s+\S+',re.I)]

def redact_text(text:str)->str:
    out=str(text)
    for p in SECRET_PATTERNS: out=p.sub('[REDACTED]',out)
    return out

def sanitize_for_log(value:Any)->str:
    try:text=json.dumps(value,ensure_ascii=False) if not isinstance(value,str) else value
    except Exception:text=str(value)
    return redact_text(text)

def scan_tree_for_secrets(root:Path)->list[str]:
    findings=[]
    for p in Path(root).rglob('*'):
        if not p.is_file() or '__pycache__' in p.parts or p.suffix.lower() in ('.png','.jpg','.jpeg','.ico','.zip','.exe','.dll','.pyc','.pyo'): continue
        try:text=p.read_text('utf-8',errors='ignore')
        except Exception:continue
        if any(rx.search(text) for rx in SECRET_PATTERNS): findings.append(str(p))
    return findings

# The only keys a reviewer-history record may carry into a request (#470).
# Mirrors `ai_client.REVIEWER_DECISION_FIELDS` / `PROJECT_RENDERING_FIELDS`;
# kept here too so the manifest judges the payload it is handed, not the code
# that was supposed to have projected it.
_REVIEWER_RECORD_KEYS = frozenset({
    'reference', 'tool', 'groupId', 'checkId', 'decision', 'selectionText',
    'source_quote', 'selections', 'nothingToSelect', 'invalidated',
})


def _reviewer_records(fields: dict[str, Any]) -> list[Any]:
    records: list[Any] = list(fields.get('project_reviewer_decisions') or [])
    for check in fields.get('translationCore_checks') or []:
        if isinstance(check, dict):
            records.extend(check.get('approved_project_renderings') or [])
    return records


def contains_reviewer_identity(fields: dict[str, Any]) -> bool:
    """True when any reviewer-history record in the payload carries a key
    outside the projected shape: a name, a note, a timestamp, a device, a
    model, an evidence path. Judged on the records themselves, so a future
    field that slips past the projection is reported rather than assumed away."""
    for record in _reviewer_records(fields):
        if not isinstance(record, dict):
            return True
        if set(record) - _REVIEWER_RECORD_KEYS:
            return True
    return False


def ai_payload_manifest(reference:str,fields:dict[str,Any])->dict[str,Any]:
    """Human-readable privacy manifest; actual content stays local unless listed."""
    return {
        'reference': reference,
        'sentFields': sorted(fields.keys()),
        'containsScripture': bool(fields.get('tamil_verse') or fields.get('target_verse') or fields.get('currentTarget') or fields.get('targetPassageContext')),
        'containsOriginalLanguage': bool(fields.get('hebrew_topWords') or fields.get('source_topWords') or fields.get('hebrew') or fields.get('sourceSemanticUnits')),
        'containsTranslationHelps': bool(fields.get('translationCore_checks') or fields.get('evidence_catalog') or fields.get('resourceEvidence')),
        'containsReviewerIdentity': contains_reviewer_identity(fields),
        'unrelatedProjectFilesSent': False,
    }
