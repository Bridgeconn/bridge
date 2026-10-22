"""The open project's Paratext session (#356).

One per engine, attached by ``project.open`` and replaced only when the
Paratext Guid changes, so moving between books of one collection keeps the
reader (and, from #357, the notes index) it already has. It holds the
resolved link and a memoizing ``ParatextFolderReader`` when the link is
``linked``; in any other state every reader answers "no Paratext data" and
the state string says why. The RPC handlers in ``bridge_service`` stay thin
and call into this.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from tc_ai_bridge.paratext_link import LINKED, LinkResolution
from tc_ai_bridge.paratext_project import PARATEXT_CANON, ParatextFolderReader, notes_users

# Paratext files a later QA input may read (#353, deferred); linkStatus only
# says whether each exists.
_DATA_FILES = {
    "bookNames": ("BookNames.xml",),
    "commentTags": ("CommentTags.xml",),
    "userAccess": ("ProjectUserAccess.xml",),
    "termRenderings": ("TermRenderings.xml",),
    "errorDenials": ("ErrorDenials.xml",),
    "spellingStatus": ("SpellingStatus.xml",),
    "checkingStatus": ("CheckingStatus.xml",),
    "progress": ("ProjectProgress.xml",),
}


class ParatextSession:
    def __init__(self, resolution: LinkResolution, cache_root: Path) -> None:
        self.cache_root = Path(cache_root)
        self._lock = threading.Lock()
        self.resolution = resolution
        self.reader: ParatextFolderReader | None = None
        self._attach_reader()

    @property
    def guid(self) -> str:
        return self.resolution.guid

    @property
    def linked(self) -> bool:
        return self.resolution.state == LINKED

    def _attach_reader(self) -> None:
        folder = self.resolution.folder if self.linked else None
        if folder is None:
            self.reader = None
        elif self.reader is None or self.reader.folder != folder:
            self.reader = ParatextFolderReader(folder)

    def update(self, resolution: LinkResolution) -> None:
        """A fresh resolution for the same Guid (another book of the
        collection, or a relink): the reader is kept when the folder is."""
        with self._lock:
            self.resolution = resolution
            self._attach_reader()

    def refresh(self, resolution: LinkResolution) -> None:
        """Drop every memo and take a fresh resolution."""
        with self._lock:
            self.resolution = resolution
            self.reader = None
            self._attach_reader()

    def book_names(self) -> dict[str, dict[str, str]]:
        reader = self.reader
        return reader.book_names() if reader is not None else {}

    def link_status(self) -> dict[str, Any]:
        resolution = self.resolution
        link = resolution.link or {}
        settings = resolution.settings
        folder = resolution.folder
        status: dict[str, Any] = {
            "state": resolution.state,
            "folder": str(folder) if folder else "",
            "guid": resolution.guid,
            "name": settings.name if settings else str(link.get("name") or ""),
            "fullName": settings.full_name if settings else str(link.get("fullName") or ""),
            "versification": (settings.versification_name if settings else link.get("versification")) or None,
            "encoding": settings.encoding if settings else "",
            "booksPresent": (sorted(settings.books_present, key=PARATEXT_CANON.index) if settings
                             else list(link.get("booksPresent") or [])),
            "linkedAt": str(link.get("linkedAt") or ""),
            "files": {"notes": {"count": 0, "users": []}, **{key: False for key in _DATA_FILES}},
        }
        if resolution.candidate is not None:
            status["candidate"] = str(resolution.candidate)
        if self.linked and folder is not None:
            users = notes_users(folder)
            status["files"]["notes"] = {"count": len(users), "users": users}
            for key, names in _DATA_FILES.items():
                status["files"][key] = any((folder / name).is_file() for name in names)
            if self.reader is not None:
                status["readerStatus"] = self.reader.status()
        return status
