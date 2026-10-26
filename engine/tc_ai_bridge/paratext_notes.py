"""Paratext's own Project Notes file shape, as Paratext writes it.

``Notes_<User>.xml`` in a Paratext project folder is a ``<CommentList>`` of
``<Comment>`` elements whose children come in a fixed order. Bridge reads those
files (``paratext_project.py``, #357) and never writes them: Paratext
write-back goes through the companion plugin only (#358, DECISIONS
2026-10-26). What stays here is that order and a validator for a file in it,
which the tests' synthetic Paratext folders are built against.

The companion "Notes 1.1" file (``paratextNotes/Notes_AI_Suggestion.xml``) and
its writer and converters were removed on 2026-10-26 (#358, decision 5): it was
the Paratext Data Access web API's format, Paratext desktop never read it, and
it could not carry a reply or a resolve.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


class ParatextNoteError(RuntimeError):
    pass


COMMENT_CHILD_ORDER = (
    'SelectedText', 'StartPosition', 'ContextBefore', 'ContextAfter',
    'Status', 'Type', 'ConflictType', 'Verse',
    'AssignedUser', 'ReplyToUser', 'HideInTextWindow', 'Contents',
    'TagAdded', 'TagRemoved',
)
REQUIRED_COMMENT_ATTRS = ('Thread', 'User', 'VerseRef', 'Language', 'Date')
REQUIRED_COMMENT_CHILDREN = (
    'SelectedText', 'StartPosition', 'ContextBefore', 'ContextAfter',
    'Status', 'Type', 'ConflictType', 'Verse', 'HideInTextWindow',
)


def validate_comment_list(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    root = ET.parse(p).getroot()
    if root.tag != 'CommentList':
        raise ParatextNoteError('Expected <CommentList>.')
    comments = list(root.findall('Comment'))
    for c in comments:
        for attr in REQUIRED_COMMENT_ATTRS:
            if attr not in c.attrib:
                raise ParatextNoteError(f'Comment attribute {attr} is required.')
        for tag in REQUIRED_COMMENT_CHILDREN:
            if c.find(tag) is None:
                raise ParatextNoteError(f'Comment element <{tag}> is required.')
        int(c.findtext('StartPosition') or '0')
        child_names = [x.tag for x in c]
        order = {name: i for i, name in enumerate(COMMENT_CHILD_ORDER)}
        seen = [order[x] for x in child_names if x in order]
        if seen != sorted(seen):
            raise ParatextNoteError('Comment child elements are not in Paratext export order.')
    return {'format': 'CommentList', 'comments': len(comments), 'path': str(p)}
