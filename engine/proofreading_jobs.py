"""The proofreading run: chosen books of a collection, one after another (#505).

Same shape as `collection_jobs.py`: one active run, a worker thread, JSON-native
snapshots. The manager owns ordering, pause, cancel, timing and the stop on a
provider that will take no more requests; the engine supplies the callables
that do the work, so this module never opens a project, runs a tool or calls a
model:

- `prepare(report)` stages the text and returns what to do with each book:
  `{bookId: {"skip": reason}}` for one that is not read (unchanged since its
  recorded run, or not a book the toolkit knows), `{}` for the rest;
- `run_book(book, cancelled, report)` reads one book end to end and returns
  its summary (`findings`, `bySeverity`, `usage`, ...);
- `record_run(entry)` persists a finished book, so a later run can skip it;
- `finish()` rebuilds the run report once the books are done;
- `halt()` answers why nothing more should be sent (a ChatGPT plan's limit, a
  lapsed sign-in), or "".

Pause takes effect between books. Cancel stops the book in flight at its next
step, and a cancelled or halted book records nothing: its finished chunks stay
in the toolkit's work folder, so the next run resumes it without asking the
reader for them again.
"""
from __future__ import annotations

import copy
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

TERMINAL_STATES = {"succeeded", "failed", "cancelled"}


class ProofreadingJobError(RuntimeError):
    pass


class ProofreadingJobConflict(ProofreadingJobError):
    pass


class BookCancelled(Exception):
    """Raised by `run_book` when it stopped because the run was cancelled."""


class RunHalted(Exception):
    """Raised by `run_book` when the provider will accept nothing more for
    now. The message is what the reviewer is shown."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ProofreadingJobSpec:
    collection_path: str
    books: tuple[dict[str, Any], ...]      # {bookId, bookName, path}, in run order
    reference: str = ""                    # the reference Bible's name, for the snapshot
    force: bool = False


Prepare = Callable[[Callable[[str], None]], dict[str, dict[str, Any]]]
RunBook = Callable[[dict[str, Any], Callable[[], bool], Callable[[str, int, int], None]], dict[str, Any]]
RecordRun = Callable[[dict[str, Any]], None]

_ZERO_USAGE = {"calls": 0, "inputTokens": 0, "outputTokens": 0, "cachedInputTokens": 0, "totalTokens": 0,
               "estimatedCostUSD": 0.0}


def add_usage(total: dict[str, Any], usage: dict[str, Any] | None) -> None:
    for key in _ZERO_USAGE:
        value = (usage or {}).get(key, 0) or 0
        total[key] = round(float(total.get(key, 0)) + float(value), 6) if key == "estimatedCostUSD" \
            else int(total.get(key, 0)) + int(value)


class _ProofreadingJob:
    def __init__(self, spec: ProofreadingJobSpec) -> None:
        self.id = f"prj-{uuid.uuid4().hex[:12]}"
        self.spec = spec
        self.state = "queued"
        self.paused = False
        self.stage = "Queued"
        self.current_book: Optional[str] = None
        self.books: list[dict[str, Any]] = [
            {"bookId": str(b.get("bookId") or ""), "bookName": str(b.get("bookName") or ""),
             "path": str(b.get("path") or ""), "state": "pending", "elapsedSeconds": None,
             "findings": 0, "bySeverity": {}, "chunksDone": 0, "chunksTotal": 0, "usage": dict(_ZERO_USAGE),
             "error": None, "note": None, "completedAt": None}
            for b in spec.books
        ]
        self.usage: dict[str, Any] = dict(_ZERO_USAGE)
        self.error: Optional[str] = None
        self.halted = False
        self.created_at = _now()
        self.finished_at: Optional[str] = None
        self.started_monotonic = time.monotonic()
        self.cancel_event = threading.Event()
        self.resume_event = threading.Event()
        self.resume_event.set()
        self.lock = threading.RLock()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            done = [b for b in self.books if b["state"] in {"done", "skipped", "failed"}]
            timed = [b["elapsedSeconds"] for b in self.books if b["state"] == "done" and b["elapsedSeconds"]]
            remaining = sum(1 for b in self.books if b["state"] in {"pending", "running"})
            # The estimate uses measured books only: skipped ones took no time.
            estimate = round(sum(timed) / len(timed) * remaining, 1) if timed and remaining else None
            return {
                "jobId": self.id, "state": self.state, "paused": self.paused, "stage": self.stage,
                "halted": self.halted,
                "collectionPath": self.spec.collection_path, "reference": self.spec.reference,
                "totalBooks": len(self.books), "completedBooks": len(done),
                "percent": round(100 * len(done) / len(self.books)) if self.books else 100,
                "currentBook": self.current_book,
                "books": copy.deepcopy(self.books),
                "findings": sum(int(b["findings"] or 0) for b in self.books if b["state"] in {"done", "skipped"}),
                "usage": dict(self.usage),
                "elapsedSeconds": round(time.monotonic() - self.started_monotonic, 1),
                "estimatedRemainingSeconds": estimate,
                "error": self.error, "createdAt": self.created_at, "finishedAt": self.finished_at,
            }


class ProofreadingJobManager:
    """One active proofreading run; completed snapshots are kept for status."""

    def __init__(self) -> None:
        self._jobs: dict[str, _ProofreadingJob] = {}
        self._active_id: Optional[str] = None
        self._lock = threading.RLock()

    def active(self) -> bool:
        with self._lock:
            job = self._jobs.get(self._active_id or "")
            return job is not None and job.state not in TERMINAL_STATES

    def start(self, spec: ProofreadingJobSpec, *, prepare: Prepare, run_book: RunBook, record_run: RecordRun,
              finish: Optional[Callable[[], None]] = None,
              halt: Optional[Callable[[], str]] = None) -> dict[str, Any]:
        with self._lock:
            if self.active():
                raise ProofreadingJobConflict("A proofreading run is already in progress.")
            job = _ProofreadingJob(spec)
            self._jobs[job.id] = job
            self._active_id = job.id
        threading.Thread(
            target=self._run, args=(job, prepare, run_book, record_run, finish, halt),
            name=f"bridge-proofreading-{job.id[-8:]}", daemon=True,
        ).start()
        return job.snapshot()

    def _job(self, job_id: str = "") -> _ProofreadingJob:
        with self._lock:
            job = self._jobs.get(job_id or self._active_id or "")
        if job is None:
            raise ProofreadingJobError(f"Unknown proofreading run '{job_id}'.")
        return job

    def status(self, job_id: str = "") -> dict[str, Any]:
        return self._job(job_id).snapshot()

    def pause(self, paused: bool, job_id: str = "") -> dict[str, Any]:
        job = self._job(job_id)
        with job.lock:
            if job.state not in TERMINAL_STATES:
                job.paused = paused
                (job.resume_event.clear if paused else job.resume_event.set)()
        return job.snapshot()

    def cancel(self, job_id: str = "") -> dict[str, Any]:
        job = self._job(job_id)
        with job.lock:
            if job.state not in TERMINAL_STATES:
                job.cancel_event.set()
                job.resume_event.set()  # a paused run wakes up to stop
                job.state = "cancelling"
                job.stage = "Cancelling after the current step"
        return job.snapshot()

    def _run(self, job: _ProofreadingJob, prepare: Prepare, run_book: RunBook, record_run: RecordRun,
             finish: Optional[Callable[[], None]], halt: Optional[Callable[[], str]]) -> None:
        with job.lock:
            job.state = "running"
            job.stage = "Preparing the text"
        try:
            def say(stage: str) -> None:
                with job.lock:
                    if job.state == "running":
                        job.stage = stage

            plan = prepare(say)
            read_any = False
            for index, book in enumerate(job.spec.books):
                job.resume_event.wait()
                if job.cancel_event.is_set():
                    return self._finish(job, "cancelled")
                row = job.books[index]
                planned = plan.get(row["bookId"]) or {}
                if planned.get("skip"):
                    previous = planned.get("previous") or {}
                    with job.lock:
                        row.update(state="skipped", note=str(planned["skip"]),
                                   findings=int(previous.get("findings") or 0),
                                   bySeverity=dict(previous.get("bySeverity") or {}),
                                   completedAt=previous.get("completedAt"))
                    continue
                reason = halt() if halt is not None else ""
                if reason:
                    return self._halt(job, reason)
                with job.lock:
                    row["state"] = "running"
                    job.current_book = row["bookId"]
                    job.stage = f"Starting {row['bookName'] or row['bookId'].upper()}"
                started = time.monotonic()

                def report(stage: str, done: int, total: int, _row: dict[str, Any] = row) -> None:
                    with job.lock:
                        _row["chunksDone"], _row["chunksTotal"] = int(done), int(total)
                        if job.state == "running":
                            job.stage = stage

                try:
                    result = run_book(book, job.cancel_event.is_set, report)
                except BookCancelled:
                    with job.lock:
                        row["state"] = "pending"  # nothing recorded: the next run resumes it
                    return self._finish(job, "cancelled")
                except RunHalted as exc:
                    with job.lock:
                        row["state"] = "pending"
                        add_usage(job.usage, getattr(exc, "usage", None))
                    return self._halt(job, str(exc))
                except Exception as exc:  # one book must not abort the run
                    if job.cancel_event.is_set():
                        with job.lock:
                            row["state"] = "pending"
                        return self._finish(job, "cancelled")
                    with job.lock:
                        row.update(state="failed", error=str(exc),
                                   elapsedSeconds=round(time.monotonic() - started, 2))
                        add_usage(job.usage, getattr(exc, "usage", None))
                    read_any = True
                    continue
                read_any = True
                elapsed = round(time.monotonic() - started, 2)
                entry = {**result, "bookId": row["bookId"], "state": "done", "completedAt": _now(),
                         "elapsedSeconds": elapsed}
                with job.lock:
                    row.update(state="done", elapsedSeconds=elapsed, completedAt=entry["completedAt"],
                               findings=int(result.get("findings") or 0),
                               bySeverity=dict(result.get("bySeverity") or {}),
                               usage={**_ZERO_USAGE, **(result.get("usage") or {})},
                               note="; ".join(result.get("notes") or []) or None)
                    add_usage(job.usage, result.get("usage"))
                try:
                    record_run(entry)
                except Exception as exc:
                    with job.lock:
                        row["error"] = f"The book was read but its run was not recorded: {exc}"
            with job.lock:
                job.current_book = None
            if finish is not None and read_any and not job.cancel_event.is_set():
                with job.lock:
                    job.stage = "Writing the run report"
                try:
                    finish()
                except Exception:  # the findings are already stored; the workbook is a convenience
                    pass
            if job.cancel_event.is_set():
                return self._finish(job, "cancelled")
            failed = [b for b in job.books if b["state"] == "failed"]
            self._finish(job, "failed" if failed else "succeeded",
                         f"{len(failed)} book(s) could not be read." if failed else None)
        except Exception as exc:
            self._finish(job, "failed", str(exc))

    @staticmethod
    def _halt(job: _ProofreadingJob, reason: str) -> None:
        with job.lock:
            job.halted = True
        ProofreadingJobManager._finish(job, "failed", reason)

    @staticmethod
    def _finish(job: _ProofreadingJob, state: str, error: Optional[str] = None) -> None:
        with job.lock:
            job.state = state
            job.error = error
            job.current_book = None
            job.stage = {"succeeded": "Complete", "cancelled": "Cancelled"}.get(state, "Stopped")
            job.finished_at = _now()
