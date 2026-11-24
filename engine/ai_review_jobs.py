"""Cancellable background jobs for evidence-grounded tN/tW AI review.

The worker is deliberately local to Bridge rather than using a provider's
remote background mode.  This keeps OpenAI-compatible providers working and
lets the sidecar remain responsive while a chapter or book is processed.
Cancellation is cooperative between verses and model calls; a request already
in flight is allowed to finish. Since #513 the worker looks at the cancel once
per verse, immediately before it stores that verse's review: seen there,
nothing is stored and the verse keeps the review it had. A verse the worker
reports as done was stored and finished, so the job keeps its result even when
the cancel arrived in between.
"""
from __future__ import annotations

import copy
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional


TERMINAL_STATES = {"succeeded", "failed", "cancelled"}


class AIReviewJobError(RuntimeError):
    pass


class AIReviewJobConflict(AIReviewJobError):
    pass


class AIReviewJobNotFound(AIReviewJobError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class AIReviewJobSpec:
    scope: str
    mode: str
    project_path: str
    chapters: tuple[str, ...]
    chapter_verses: dict[str, list[str]]
    skipped_current: int = 0
    resume_of: str = ""


class _AIReviewJob:
    def __init__(self, spec: AIReviewJobSpec) -> None:
        self.id = str(uuid.uuid4())
        self.spec = spec
        self.state = "queued"
        self.current_chapter: Optional[str] = None
        self.current_verse: Optional[str] = None
        self.current_stage = "Queued"
        self.current_verse_percent = 0
        # #502: the verses of the request in flight when several verses go in
        # one request; empty in the single-verse run.
        self.current_window: list[str] = []
        self.results: dict[str, dict[str, Any]] = {}
        self.latest_result_key: Optional[str] = None
        self.latest_result: Optional[dict[str, Any]] = None
        self.error: Optional[str] = None
        self.created_at = _now()
        self.finished_at: Optional[str] = None
        self.cancel_event = threading.Event()
        self.lock = threading.RLock()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            total = sum(len(values) for values in self.spec.chapter_verses.values())
            completed = sum(
                1 for item in self.results.values()
                if item.get("status") in {"succeeded", "failed"}
            )
            in_flight = self.current_verse_percent / 100 if self.current_verse else 0
            percent = 100 if self.state == "succeeded" else round(
                ((completed + in_flight) / total) * 100
            ) if total else 0
            compact_results = {
                key: {
                    "chapter": item.get("chapter"), "verse": item.get("verse"),
                    "status": item.get("status"), "error": item.get("error"),
                    "summary": item.get("summary", ""),
                    "appliedCount": len(item.get("appliedSelections") or []),
                    "skippedCount": len(item.get("skippedSelections") or []),
                    "usage": copy.deepcopy(item.get("usage") or {}),
                }
                for key, item in self.results.items()
            }
            return {
                "jobId": self.id,
                "scope": self.spec.scope,
                "mode": self.spec.mode,
                "projectPath": self.spec.project_path,
                "state": self.state,
                "chapters": list(self.spec.chapters),
                "chapterVerses": copy.deepcopy(self.spec.chapter_verses),
                "skippedCurrentVerses": self.spec.skipped_current,
                "resumeOf": self.spec.resume_of,
                "totalVerses": total,
                "completedVerses": completed,
                "failedVerses": sum(
                    1 for item in self.results.values() if item.get("status") == "failed"
                ),
                "percent": max(0, min(100, percent)),
                "currentChapter": self.current_chapter,
                "currentVerse": self.current_verse,
                "currentStage": self.current_stage,
                "currentWindow": list(self.current_window),
                "results": compact_results,
                # Only one full evidence bundle crosses the polling boundary.
                # Older full results live in the per-verse companion cache.
                "latestResult": (
                    {"key": self.latest_result_key, "result": copy.deepcopy(self.latest_result)}
                    if self.latest_result_key and self.latest_result is not None else None
                ),
                "error": self.error,
                "createdAt": self.created_at,
                "finishedAt": self.finished_at,
            }


Progress = Callable[[int, str], None]
RunVerse = Callable[[str, str, str, Progress, threading.Event], dict[str, Any]]
# #502: one chapter's verses reviewed in windows. The callable reports every
# verse's outcome through the `_JobReport` it is handed and returns when the
# chapter is done or the job is cancelled.
RunChapter = Callable[[str, list[str], str, "_JobReport", threading.Event], None]


def _verse_result(chapter: str, verse: str, payload: Optional[dict[str, Any]], error: Optional[str]) -> dict[str, Any]:
    """One verse's entry in a job's results, succeeded or failed: the shape
    the single-verse loop has always stored."""
    result: dict[str, Any] = {
        "summary": "", "checkReviews": [], "qaIssues": [],
        "alignmentProposal": None, "alignmentWasAIProposed": False,
        "appliedSelections": [], "skippedSelections": [], "usage": {},
    }
    if error is None:
        result.update(copy.deepcopy(payload or {}))
        result.update({"chapter": chapter, "verse": verse, "status": "succeeded", "error": None})
    else:
        result.update({"chapter": chapter, "verse": verse, "status": "failed", "error": str(error)})
    return result


class _JobReport:
    """What a window run tells its job (#502). Nothing here raises."""

    def __init__(self, job: "_AIReviewJob", chapter: str) -> None:
        self._job = job
        self._chapter = chapter

    def stage(self, verse: str, percent: int, stage: str) -> None:
        with self._job.lock:
            self._job.current_chapter = self._chapter
            self._job.current_verse = str(verse)
            self._job.current_verse_percent = max(0, min(100, int(percent)))
            self._job.current_stage = str(stage)

    def window(self, verses: list[str]) -> None:
        with self._job.lock:
            self._job.current_chapter = self._chapter
            self._job.current_window = [str(v) for v in verses]
            if verses:
                self._job.current_verse = str(verses[0])
                self._job.current_verse_percent = 64
                self._job.current_stage = "AI reviewing Notes, Words and whole verse"

    def result(self, verse: str, payload: Optional[dict[str, Any]] = None, error: Optional[str] = None) -> None:
        # After a cancel, an error is the cancellation and not a failed verse.
        # A payload is a verse that was stored and finished before the cancel
        # was seen (#513), and is kept, as in the single-verse loop.
        if error is not None and self._job.cancel_event.is_set():
            return
        key = f"{self._chapter}:{verse}"
        result = _verse_result(self._chapter, str(verse), payload, error)
        with self._job.lock:
            self._job.results[key] = result
            self._job.latest_result_key = key
            self._job.latest_result = result
            self._job.current_verse_percent = 0


class AIReviewJobManager:
    """Own one active AI pass and retain terminal jobs for retry/audit."""

    def __init__(self) -> None:
        self._jobs: dict[str, _AIReviewJob] = {}
        self._active_job_id: Optional[str] = None
        self._lock = threading.RLock()

    def start(
        self, spec: AIReviewJobSpec, *, run_verse: RunVerse, run_chapter: Optional[RunChapter] = None,
        halt: Optional[Callable[[], str]] = None,
    ) -> dict[str, Any]:
        """`run_chapter`, when given, replaces the per-verse loop for each
        chapter (#502); without it the job is the single-verse run.

        `halt` (#506) is asked before each verse or chapter. A non-empty
        answer ends the job there as failed with that message: the provider
        will accept nothing more for now (a ChatGPT plan's limit, a lapsed
        sign-in), so going on would only fail every remaining verse. Retry
        resumes from the verses that have no succeeded result."""
        if spec.mode not in {"basic", "advanced"}:
            raise AIReviewJobError("AI reviewer mode must be basic or advanced.")
        if spec.scope not in {"verse", "chapter", "book"}:
            raise AIReviewJobError("AI review scope must be verse, chapter, or book.")
        with self._lock:
            active = self._jobs.get(self._active_job_id or "")
            if active is not None and active.state not in TERMINAL_STATES:
                raise AIReviewJobConflict(f"AI review job {active.id} is already {active.state}.")
            job = _AIReviewJob(spec)
            self._jobs[job.id] = job
            self._active_job_id = job.id
        threading.Thread(
            target=self._run,
            args=(job, run_verse, run_chapter, halt),
            name=f"bridge-ai-review-{job.id[:8]}",
            daemon=True,
        ).start()
        return job.snapshot()

    def status(self, job_id: str = "") -> dict[str, Any]:
        with self._lock:
            resolved = job_id or self._active_job_id or ""
            job = self._jobs.get(resolved)
        if job is None:
            raise AIReviewJobNotFound(f"Unknown AI review job '{resolved}'.")
        return job.snapshot()

    def cancel(self, job_id: str = "") -> dict[str, Any]:
        with self._lock:
            resolved = job_id or self._active_job_id or ""
            job = self._jobs.get(resolved)
        if job is None:
            raise AIReviewJobNotFound(f"Unknown AI review job '{resolved}'.")
        with job.lock:
            if job.state not in TERMINAL_STATES:
                job.cancel_event.set()
                job.state = "cancelling"
                job.current_stage = "Cancelling after current AI request"
        return job.snapshot()

    def spec_for_retry(self, job_id: str) -> AIReviewJobSpec:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise AIReviewJobNotFound(f"Unknown AI review job '{job_id}'.")
        with job.lock:
            if job.state not in {"failed", "cancelled"}:
                raise AIReviewJobConflict("Only failed or cancelled AI review jobs can be retried.")
            remaining = {
                chapter: [
                    verse for verse in job.spec.chapter_verses.get(chapter, [])
                    if job.results.get(f"{chapter}:{verse}", {}).get("status") != "succeeded"
                ]
                for chapter in job.spec.chapters
            }
            return AIReviewJobSpec(
                scope=job.spec.scope,
                mode=job.spec.mode,
                project_path=job.spec.project_path,
                chapters=job.spec.chapters,
                chapter_verses=remaining,
                skipped_current=job.spec.skipped_current + sum(
                    1 for item in job.results.values() if item.get("status") == "succeeded"
                ),
                resume_of=job.id,
            )

    def _run(self, job: _AIReviewJob, run_verse: RunVerse, run_chapter: Optional[RunChapter] = None,
             halt: Optional[Callable[[], str]] = None) -> None:
        with job.lock:
            job.state = "running"
        try:
            for chapter in job.spec.chapters:
                if run_chapter is not None:
                    verses = list(job.spec.chapter_verses.get(chapter, []))
                    if not verses:
                        continue
                    if self._cancelled(job):
                        return
                    if self._halted(job, halt):
                        return
                    with job.lock:
                        job.current_chapter = chapter
                        job.current_verse = verses[0]
                        job.current_verse_percent = 0
                        job.current_stage = "Preparing AI review"
                    report = _JobReport(job, chapter)
                    run_chapter(chapter, verses, job.spec.mode, report, job.cancel_event)
                    if self._cancelled(job):
                        return
                    # Before the fill-in below: a chapter stopped by the
                    # provider leaves its unsent verses without a result, for
                    # Retry, not marked as failures of their own.
                    if self._halted(job, halt):
                        return
                    with job.lock:
                        job.current_window = []
                    # Every verse of the chapter has an outcome, whatever the
                    # window run reported.
                    for verse in verses:
                        if f"{chapter}:{verse}" not in job.results:
                            report.result(verse, error="AI review returned no result for this verse.")
                    continue
                for verse in job.spec.chapter_verses.get(chapter, []):
                    if self._cancelled(job):
                        return
                    if self._halted(job, halt):
                        return
                    key = f"{chapter}:{verse}"

                    def progress(percent: int, stage: str) -> None:
                        with job.lock:
                            job.current_verse_percent = max(0, min(100, int(percent)))
                            job.current_stage = str(stage)

                    with job.lock:
                        job.current_chapter = chapter
                        job.current_verse = verse
                        job.current_verse_percent = 0
                        job.current_stage = "Preparing AI review"
                    try:
                        payload = run_verse(chapter, verse, job.spec.mode, progress, job.cancel_event)
                        # #513: a payload means the verse's review was stored
                        # and finished. It is kept even if a cancel arrived
                        # meanwhile; the cancel takes effect before the next
                        # verse.
                        result = {
                            "summary": "", "checkReviews": [], "qaIssues": [],
                            "alignmentProposal": None, "alignmentWasAIProposed": False,
                            "appliedSelections": [], "skippedSelections": [], "usage": {},
                        }
                        result.update(copy.deepcopy(payload))
                        result.update({"chapter": chapter, "verse": verse, "status": "succeeded", "error": None})
                    except Exception as exc:  # one bad verse must not discard a chapter/book pass
                        # A cooperative worker notices cancellation after its
                        # provider request returns and raises instead of
                        # returning a payload. That is cancellation, not a
                        # failed verse; it stored nothing.
                        if self._cancelled(job):
                            return
                        result = {
                            "chapter": chapter, "verse": verse, "status": "failed",
                            "summary": "", "checkReviews": [], "qaIssues": [],
                            "alignmentProposal": None, "alignmentWasAIProposed": False,
                            "appliedSelections": [], "skippedSelections": [], "usage": {},
                            "error": str(exc),
                        }
                    with job.lock:
                        job.results[key] = result
                        job.latest_result_key = key
                        job.latest_result = result
                        job.current_verse_percent = 0

            if self._halted(job, halt):  # the last verse may be the one that met the limit
                return
            with job.lock:
                failed = [item for item in job.results.values() if item.get("status") == "failed"]
                job.state = "failed" if failed else "succeeded"
                job.error = f"{len(failed)} verse(s) failed AI review." if failed else None
                job.current_stage = "AI review failed" if failed else "Complete"
                job.current_chapter = None
                job.current_verse = None
                job.finished_at = _now()
        except Exception as exc:
            if self._cancelled(job):
                return
            with job.lock:
                job.state = "failed"
                job.error = str(exc)
                job.current_stage = "AI review failed"
                job.finished_at = _now()

    @staticmethod
    def _halted(job: _AIReviewJob, halt: Optional[Callable[[], str]]) -> bool:
        reason = halt() if halt is not None else ""
        if not reason:
            return False
        with job.lock:
            job.state = "failed"
            job.error = reason
            job.current_stage = "AI review stopped"
            job.current_chapter = None
            job.current_verse = None
            job.current_window = []
            job.current_verse_percent = 0
            job.finished_at = _now()
        return True

    @staticmethod
    def _cancelled(job: _AIReviewJob) -> bool:
        if not job.cancel_event.is_set():
            return False
        with job.lock:
            # #513: a cancel that arrives when every verse already has its
            # outcome has nothing left to stop. The job ends as what it is,
            # succeeded or failed, not as a cancelled job with all its work done.
            wanted = [
                f"{chapter}:{verse}"
                for chapter in job.spec.chapters
                for verse in job.spec.chapter_verses.get(chapter, [])
            ]
            if wanted and all(key in job.results for key in wanted):
                return False
            job.state = "cancelled"
            job.current_stage = "Cancelled"
            job.current_chapter = None
            job.current_verse = None
            job.current_window = []
            job.current_verse_percent = 0
            job.finished_at = _now()
        return True
