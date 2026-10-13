"""Background project import (#231).

Modeled on the report build (report_jobs.py) and deliberately its own lock
domain: importing must never be refused because a check or report job is
running, and the reviewer keeps the rest of Project Home while it runs. The
worker runs BridgeEngine's inspect / write / register sequence and never
touches BridgeEngine.project; opening the primary book afterwards is the
client's own project.open, on the dispatcher thread as always.

The snapshot is what the import screen draws: the phase, the book it is on
and, for the one book that is normalised eagerly, the chapter. A cancel sets
the event that project_import.import_source tests at every checkpoint; the
import then ends with ImportCancelled before anything is moved into the
destination root, so a cancelled job leaves nothing on disk.
"""
from __future__ import annotations

import copy
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from tc_ai_bridge.project_import import ImportCancelled

TERMINAL_STATES = {"succeeded", "failed", "cancelled"}

# What the import screen says for each phase. The engine owns the words so
# the sync RPC, the job and any script read the same ones.
PHASE_LABELS = {
    "queued": "Starting",
    "inspect": "Reading the source",
    "classify": "Checking for an existing copy",
    "copy": "Copying the project",
    "normalize": "Preparing {book}",
    "stage": "Copying {book}",
    "commit": "Moving into place",
    "register": "Registering",
}

# Share of the bar each phase owns, in order. The books phase is split evenly
# across the collection, and the eagerly normalised first book is split again
# across its chapters, so a 66-book Bible moves visibly from the first
# chapter of Genesis on.
_PHASE_SPANS = {
    "queued": (0, 0),
    "inspect": (0, 8),
    "classify": (8, 10),
    "copy": (10, 90),
    "normalize": (10, 90),
    "stage": (10, 90),
    "commit": (90, 95),
    "register": (95, 100),
}


class ImportJobError(RuntimeError):
    pass


class ImportJobConflict(ImportJobError):
    pass


class ImportJobNotFound(ImportJobError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# The worker body: given the progress sink and the cancel test, do the import
# and return its result (import_source's dict, with every book registered).
RunImport = Callable[[Callable[[dict[str, Any]], None], Callable[[], bool]], dict[str, Any]]


class _ImportJob:
    def __init__(self, source_path: str) -> None:
        self.id = str(uuid.uuid4())
        self.source_path = source_path
        self.state = "queued"
        self.phase = "queued"
        self.total_books = 0
        self.completed_books = 0
        self.current_book: Optional[str] = None
        self.chapter: Optional[int] = None
        self.chapter_count: Optional[int] = None
        self.percent = 0
        self.result: Optional[dict[str, Any]] = None
        self.error: Optional[str] = None
        self.created_at = _now()
        self.finished_at: Optional[str] = None
        self.cancel_event = threading.Event()
        self.lock = threading.RLock()

    def on_progress(self, event: dict[str, Any]) -> None:
        phase = str(event.get("phase") or self.phase)
        with self.lock:
            self.phase = phase
            if event.get("bookCount") is not None:
                self.total_books = int(event["bookCount"])
            if phase in {"normalize", "stage", "copy"}:
                if event.get("bookId") is not None:
                    self.current_book = str(event["bookId"])
                if event.get("bookIndex") is not None:
                    self.completed_books = int(event["bookIndex"])
                if event.get("chapter") is not None:
                    self.chapter = int(event["chapter"])
                    self.chapter_count = int(event.get("chapterCount") or 0) or None
                elif event.get("bookIndex") is not None:
                    self.chapter = None
                    self.chapter_count = None
            elif phase in {"commit", "register"}:
                self.completed_books = self.total_books
                self.current_book = None
                self.chapter = None
                self.chapter_count = None
            self.percent = self._percent()

    def _percent(self) -> int:
        start, end = _PHASE_SPANS.get(self.phase, (0, 0))
        span = end - start
        fraction = 0.0
        if self.phase in {"normalize", "stage", "copy"} and self.total_books:
            per_book = 1.0 / self.total_books
            fraction = self.completed_books * per_book
            if self.chapter and self.chapter_count:
                fraction += per_book * (self.chapter - 1) / self.chapter_count
        return max(0, min(100, int(start + span * fraction)))

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            label = PHASE_LABELS.get(self.phase, self.phase)
            if "{book}" in label:
                label = label.replace("{book}", (self.current_book or "book").upper())
            return {
                "jobId": self.id,
                "sourcePath": self.source_path,
                "state": self.state,
                "phase": self.phase,
                "phaseLabel": label,
                "totalBooks": self.total_books,
                "completedBooks": self.completed_books,
                "currentBook": self.current_book,
                "chapter": self.chapter,
                "chapterCount": self.chapter_count,
                "percent": 100 if self.state == "succeeded" else self.percent,
                "result": copy.deepcopy(self.result),
                "error": self.error,
                "createdAt": self.created_at,
                "finishedAt": self.finished_at,
            }


class ImportJobManager:
    """Owns one active import at a time; the last finished job stays
    pollable until the next one replaces it."""

    def __init__(self) -> None:
        self._jobs: dict[str, _ImportJob] = {}
        self._active_job_id: Optional[str] = None
        self._lock = threading.RLock()

    def active(self) -> bool:
        with self._lock:
            job = self._jobs.get(self._active_job_id or "")
            return job is not None and job.state not in TERMINAL_STATES

    def start(self, run: RunImport, *, source_path: str) -> dict[str, Any]:
        with self._lock:
            active = self._jobs.get(self._active_job_id or "")
            if active is not None and active.state not in TERMINAL_STATES:
                raise ImportJobConflict(f"Import {active.id} is already {active.state}.")
            job = _ImportJob(source_path)
            self._jobs[job.id] = job
            self._active_job_id = job.id
            for stale_id in [jid for jid in self._jobs if jid != job.id]:
                del self._jobs[stale_id]
        thread = threading.Thread(
            target=self._run, args=(job, run), name=f"bridge-import-{job.id[:8]}", daemon=True,
        )
        thread.start()
        return job.snapshot()

    def _resolve(self, job_id: str) -> _ImportJob:
        with self._lock:
            resolved_id = job_id or self._active_job_id or ""
            job = self._jobs.get(resolved_id)
        if job is None:
            raise ImportJobNotFound(f"Unknown import job '{resolved_id}'.")
        return job

    def status(self, job_id: str = "") -> dict[str, Any]:
        return self._resolve(job_id).snapshot()

    def cancel(self, job_id: str = "") -> dict[str, Any]:
        job = self._resolve(job_id)
        with job.lock:
            if job.state not in TERMINAL_STATES:
                job.cancel_event.set()
                job.state = "cancelling"
        return job.snapshot()

    @staticmethod
    def _run(job: _ImportJob, run: RunImport) -> None:
        with job.lock:
            if job.state == "queued":
                job.state = "running"
        try:
            result = run(job.on_progress, job.cancel_event.is_set)
        except ImportCancelled:
            with job.lock:
                job.state = "cancelled"
                job.finished_at = _now()
            return
        except Exception as exc:
            with job.lock:
                job.state = "failed"
                job.error = str(exc) or exc.__class__.__name__
                job.finished_at = _now()
            return
        with job.lock:
            job.result = result
            job.state = "succeeded"
            job.phase = "register"
            job.percent = 100
            job.completed_books = job.total_books or len(result.get("projects") or [])
            job.total_books = job.completed_books
            job.current_book = None
            job.finished_at = _now()
