"""The open project's Paratext session (#356, #357).

One per engine, attached by ``project.open`` and replaced only when the
Paratext Guid changes, so moving between books of one collection keeps the
reader and the notes index it already has. It holds the resolved link and a
memoizing ``ParatextFolderReader`` when the link is ``linked``; in any other
state every reader answers "no Paratext data" and the state string says why.
The RPC handlers in ``bridge_service`` stay thin and call into this.

The notes index (#357) is built on a daemon thread, never on the dispatcher:
``ensure_notes_index`` stats the ``Notes_*.xml`` files (a fingerprint over
name, size and mtime) on every notes request and starts a rebuild when they
changed. Until the first build is done the RPCs answer ``state: "building"``;
while a rebuild runs they answer from the previous index as ``"stale"``.

The index is cached in ``<cache_root>/<guid>/notes-<fingerprint>.jsonl.gz``
(``%LOCALAPPDATA%\\Bridge\\data\\paratext-cache``, beside ``reference-cache``):
derived data, rebuilt when the fingerprint differs, older files for the guid
deleted. It is gzip JSON lines -- a header, then one compact row per comment
-- read a line at a time, so loading it never holds the GIL for one long
``json.loads`` (the indic-qa snapshot lesson, 2026-10-22). Nothing is ever
written into the Paratext folder.
"""

from __future__ import annotations

import dataclasses
import gzip
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tc_ai_bridge.paratext_link import LINKED, LinkResolution
from tc_ai_bridge.paratext_project import (
    PARATEXT_CANON,
    NoteComment,
    NotesIndex,
    NoteThread,
    ParatextFolderReader,
    _fold_thread,
    build_notes_index,
    files_fingerprint,
    notes_signatures,
    notes_users,
)

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

INDEX_UNAVAILABLE = "unavailable"
INDEX_BUILDING = "building"
INDEX_READY = "ready"
INDEX_STALE = "stale"
INDEX_ERROR = "error"

DEFAULT_KINDS = ("note", "conflict")
_EXCERPT = 160
_CACHE_SCHEMA = 1
_COMMENT_FIELDS = tuple(f.name for f in dataclasses.fields(NoteComment))
_TUPLE_FIELDS = {"tags_added", "tags_removed"}


# ---------------------------------------------------------------------------
# The notes cache
# ---------------------------------------------------------------------------

def _cache_dir(cache_root: Path, guid: str) -> Path:
    return cache_root / re.sub(r"[^0-9A-Za-z]", "", guid)[:64]


def write_notes_cache(cache_root: Path, guid: str, fingerprint: str, index: NotesIndex) -> Path:
    folder = _cache_dir(cache_root, guid)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"notes-{fingerprint}.jsonl.gz"
    temporary = target.with_suffix(".tmp")
    header = {"schemaVersion": _CACHE_SCHEMA, "guid": guid, "fingerprint": fingerprint,
              "files": {name: list(value) for name, value in index.files.items()},
              "skippedFiles": index.skipped_files}
    with gzip.open(temporary, "wt", encoding="utf-8", compresslevel=3) as handle:
        handle.write(json.dumps(header, ensure_ascii=False) + "\n")
        for thread in index.threads.values():
            for comment in thread.comments:
                row = [getattr(comment, name) for name in _COMMENT_FIELDS]
                handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    os.replace(temporary, target)
    for old in folder.glob("notes-*"):
        if old != target:
            try:
                old.unlink()
            except OSError:
                pass
    return target


def read_notes_cache(cache_root: Path, guid: str, fingerprint: str) -> NotesIndex | None:
    path = _cache_dir(cache_root, guid) / f"notes-{fingerprint}.jsonl.gz"
    if not path.is_file():
        return None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            header = json.loads(handle.readline())
            if header.get("schemaVersion") != _CACHE_SCHEMA or header.get("fingerprint") != fingerprint:
                return None
            grouped: dict[str, list[NoteComment]] = {}
            for line in handle:
                values = dict(zip(_COMMENT_FIELDS, json.loads(line)))
                for name in _TUPLE_FIELDS:
                    values[name] = tuple(values[name])
                comment = NoteComment(**values)
                grouped.setdefault(comment.thread, []).append(comment)
    except (OSError, ValueError, TypeError, EOFError):
        return None
    return NotesIndex(
        threads={tid: _fold_thread(tid, comments) for tid, comments in grouped.items()},
        files={name: (int(v[0]), int(v[1]), str(v[2])) for name, v in header["files"].items()},
        skipped_files=dict(header.get("skippedFiles") or {}),
    )


# ---------------------------------------------------------------------------
# Wire shapes
# ---------------------------------------------------------------------------

def _verse_anchors(verse: str) -> list[str]:
    """``"3"`` -> [3]; a bridge ``"3-5"`` -> [3, 4, 5]; ``"4a"`` -> [4]."""
    match = re.match(r"^\s*(\d+)[a-z]?(?:\s*-\s*(\d+)[a-z]?)?", str(verse))
    if not match:
        return []
    first = int(match.group(1))
    last = int(match.group(2) or first)
    return [str(v) for v in range(first, max(first, last) + 1)][:200]


class ParatextSession:
    def __init__(self, resolution: LinkResolution, cache_root: Path) -> None:
        self.cache_root = Path(cache_root)
        self._lock = threading.Lock()
        self.resolution = resolution
        self.reader: ParatextFolderReader | None = None
        self._attach_reader()
        self._index: NotesIndex | None = None
        self._index_fingerprint: str | None = None
        self._index_error = ""
        self._built_at = ""
        self._build_seconds: float | None = None
        self._built_from = ""            # "cache" | "files"
        self._build_thread: threading.Thread | None = None

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
        """Drop every memo and take a fresh resolution. The notes index is
        kept: its fingerprint decides whether it is rebuilt."""
        with self._lock:
            self.resolution = resolution
            self.reader = None
            self._attach_reader()
        self.ensure_notes_index()

    def book_names(self) -> dict[str, dict[str, str]]:
        reader = self.reader
        return reader.book_names() if reader is not None else {}

    # -- the notes index ----------------------------------------------------

    def ensure_notes_index(self) -> None:
        """Start a build on a daemon thread when there is no index for the
        current notes files. Returns at once; never parses on the caller."""
        if not self.linked or self.resolution.folder is None:
            return
        folder = self.resolution.folder
        fingerprint = files_fingerprint(notes_signatures(folder))
        with self._lock:
            if self._build_thread is not None and self._build_thread.is_alive():
                return
            if self._index is not None and self._index_fingerprint == fingerprint:
                return
            if self._index_error and self._index_fingerprint == fingerprint:
                return                      # the same files failed already
            thread = threading.Thread(
                target=self._build_notes_index, args=(folder, self.guid, fingerprint, self._index),
                name="paratext-notes-index", daemon=True,
            )
            self._build_thread = thread
        thread.start()

    def wait_for_notes_index(self, timeout: float | None = None) -> str:
        """For tests and scripts: wait for a running build."""
        thread = self._build_thread
        if thread is not None:
            thread.join(timeout)
        return self.notes_index_status()["state"]

    def _build_notes_index(self, folder: Path, guid: str, fingerprint: str, previous: NotesIndex | None) -> None:
        started = time.perf_counter()
        source = "files"
        try:
            index = read_notes_cache(self.cache_root, guid, fingerprint) if previous is None else None
            if index is not None:
                source = "cache"
            else:
                index = build_notes_index(folder, previous=previous)
                try:
                    write_notes_cache(self.cache_root, guid, fingerprint, index)
                except OSError:
                    pass                    # a cache that cannot be written is only slower next time
        except Exception as exc:  # noqa: BLE001 -- reported on linkStatus, never raised
            with self._lock:
                self._index_error = f"{type(exc).__name__}: {exc}"
                self._index_fingerprint = fingerprint
            return
        elapsed = time.perf_counter() - started
        with self._lock:
            self._index = index
            self._index_fingerprint = fingerprint
            self._index_error = ""
            self._built_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self._build_seconds = round(elapsed, 3)
            self._built_from = source

    def notes_index_status(self) -> dict[str, Any]:
        with self._lock:
            index = self._index
            building = self._build_thread is not None and self._build_thread.is_alive()
            error = self._index_error
            status: dict[str, Any] = {
                "threads": len(index.threads) if index is not None else 0,
                "builtAt": self._built_at, "buildSeconds": self._build_seconds,
                "source": self._built_from, "error": error,
            }
        if not self.linked:
            state = INDEX_UNAVAILABLE
        elif index is None:
            state = INDEX_BUILDING if building or not error else INDEX_ERROR
        elif building or error or index.stale_files:
            state = INDEX_STALE
        else:
            state = INDEX_READY
        status["state"] = state
        if index is not None and index.stale_files:
            status["staleFiles"] = list(index.stale_files)
        return status

    def _index_for_request(self) -> tuple[NotesIndex | None, str]:
        self.ensure_notes_index()
        status = self.notes_index_status()
        return (self._index if self.linked else None), status["state"]

    def _tags(self, ids: tuple[str, ...]) -> list[dict[str, str]]:
        names = self.reader.comment_tags() if self.reader is not None else {}
        return [{"id": tag, "name": str(names.get(tag, {}).get("name") or "")} for tag in ids]

    def _summary(self, thread: NoteThread) -> dict[str, Any]:
        first, last = thread.comments[0], thread.comments[-1]
        excerpt = first.contents.split("\n", 1)[0]
        return {
            "id": thread.id, "kind": thread.kind, "status": thread.status or "todo",
            "resolved": thread.resolved, "verseRef": thread.verse_ref,
            "verse": thread.ref.verse if thread.ref else "",
            "users": list(thread.users), "firstDate": first.date, "lastDate": last.date, "lastUser": last.user,
            "excerpt": excerpt[:_EXCERPT] + ("…" if len(excerpt) > _EXCERPT else ""),
            "selectedText": thread.selected_text, "assignedUser": thread.assigned_user,
            "tags": self._tags(thread.tags), "hidden": thread.hidden, "commentCount": len(thread.comments),
        }

    def _full(self, thread: NoteThread) -> dict[str, Any]:
        first = thread.comments[0]
        value = self._summary(thread)
        value.update({
            "contextBefore": first.context_before, "contextAfter": first.context_after,
            "comments": [{
                "user": c.user, "date": c.date, "contents": c.contents, "status": c.status, "type": c.type,
                "assignedUser": c.assigned_user, "replyToUser": c.reply_to_user, "language": c.language,
                "tagsAdded": self._tags(c.tags_added), "tagsRemoved": self._tags(c.tags_removed),
            } for c in thread.comments],
        })
        return value

    def notes_for_chapter(self, book: str, chapter: str, *, include_resolved: bool = False,
                          kinds: list[str] | tuple[str, ...] | None = None) -> dict[str, Any]:
        index, state = self._index_for_request()
        wanted = set(kinds or DEFAULT_KINDS)
        verses: dict[str, list[dict[str, Any]]] = {}
        counts: dict[str, dict[str, int]] = {}
        if index is not None:
            for thread in index.threads_for(book, chapter):
                if thread.kind not in wanted or thread.ref is None:
                    continue
                cell = counts.setdefault(thread.ref.verse, {"open": 0, "resolved": 0})
                cell["resolved" if thread.resolved else "open"] += 1
                if thread.resolved and not include_resolved:
                    continue
                verses.setdefault(thread.ref.verse, []).append(self._summary(thread))
        return {"state": state, "book": book.upper(), "chapter": str(chapter), "verses": verses, "counts": counts}

    def notes_for_verse(self, book: str, chapter: str, verse: str) -> dict[str, Any]:
        index, state = self._index_for_request()
        threads: list[dict[str, Any]] = []
        if index is not None:
            for anchor in _verse_anchors(verse):
                threads.extend(self._full(t) for t in index.threads_for(book, chapter, anchor))
        return {"state": state, "book": book.upper(), "chapter": str(chapter), "verse": str(verse),
                "threads": threads}

    def note_thread(self, thread_id: str) -> dict[str, Any]:
        index, state = self._index_for_request()
        thread = index.threads.get(thread_id) if index is not None else None
        return {"state": state, "thread": self._full(thread) if thread is not None else None}

    # -- #358: what write-back needs from the index ------------------------------

    def index_ready(self) -> bool:
        """True only when the index matches the notes files on disk now: the
        outbox sends nothing while a footer could be missed."""
        if not self.linked:
            return False
        self.ensure_notes_index()
        return self.notes_index_status()["state"] == INDEX_READY

    def find_bridge_ref(self, message_id: str) -> dict[str, Any] | None:
        """The thread and comment carrying ``[Bridge ref <message_id>]``, from
        the index as it stands; None when absent or there is no index."""
        if not message_id:
            return None
        with self._lock:
            index = self._index
        if index is None or not self.linked:
            return None
        needle = f"[Bridge ref {message_id}]"
        for thread in index.threads.values():
            for comment in thread.comments:
                if needle in (comment.contents or ""):
                    return {"threadId": thread.id, "user": comment.user, "date": comment.date,
                            "resolved": thread.resolved, "verseRef": thread.verse_ref}
        return None

    def thread_key(self, thread_id: str) -> dict[str, Any] | None:
        """What connector 0.8.0 finds a thread by -- its verse, selected text and
        first comment -- with the book and chapter it is in. None when the
        index has no such thread."""
        with self._lock:
            index = self._index
        thread = index.threads.get(thread_id) if index is not None else None
        if thread is None or thread.ref is None or not thread.comments:
            return None
        first = thread.comments[0]
        return {
            "book": thread.ref.book, "chapter": str(thread.ref.chapter),
            "key": {"verse_ref": thread.verse_ref, "offset": -1, "selected_text": thread.selected_text,
                    "first_author": first.user, "first_created": first.date},
        }

    # -- linkStatus -----------------------------------------------------------

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
            self.ensure_notes_index()
        status["notesIndex"] = self.notes_index_status()
        return status
