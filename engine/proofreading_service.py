"""The proofreading run as the engine offers it: `proofreading.*` (#505).

`BridgeEngine` owns one `ProofreadingService` and hands every `proofreading.*`
request to it. Kept out of `bridge_service.py` on purpose: that file is what
every service test imports, and this is a feature with its own job, its own
tools and its own report.

Three modules sit under this one. `tc_ai_bridge/proofreading.py` is the
procedure for one book (the toolkit's tools around a reader);
`proofreading_jobs.py` is the run (order, pause, cancel, the stop on a plan's
limit); `proofread_tool_main.py` is how a tool is started. This module is what
knows the engine: which books, which reference Bible, which AI client, where
the findings are kept.

What a run touches:

- it **reads** each chosen book's current text (the same source-preserving
  USFM an export writes) and the reference folder, into staged copies under
  `<data>/proofreading/<project>/`;
- it **writes** the findings to each book's workbench (`proofreading_results`,
  v13), the per-book run to `.bridge/collection.json` `proofreadRuns[]`, and
  the toolkit's own files (workbook, CSV, Paratext notes file, run report) to
  that run folder;
- it **never** writes Scripture, alignment, findings or a decision, and it
  sends nothing to Paratext.

The reader is whatever Settings > AI provider is set to, through
`BridgeEngine._ai_client`: an API key or a ChatGPT sign-in. Nothing here runs
unless a reviewer starts it, and nothing on the import, open or check path
touches it.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from pathlib import Path
from typing import Any

import proofreading_jobs as jobs
from tc_ai_bridge import proofreading as toolkit
from tc_ai_bridge.ai_client import AIError, AIPlanLimitError, usage_dict
from tc_ai_bridge.language_packs.reference_text import _source_files, detect, fingerprint
from tc_ai_bridge.language_qa_xrefs import source_of
from tc_ai_bridge.model_router import DEFAULT_PRICES, estimate_cost
from tc_ai_bridge.paratext_link import resolve as resolve_paratext_link
from tc_ai_bridge.project_import import (
    PROOFREAD_RUNS_KEY, collection_projects, collection_qa_runs, materialize_lazy_project, record_collection_qa_run,
)
from tc_ai_bridge.qa_report import write_report_rows
from tc_ai_bridge.tc_project import ProjectError, TranslationCoreProject, peek_proofreading_results
from tc_ai_bridge.usfm_verse import plain_text

# One request reads up to three chapters with the reference beside them and
# may reason for a while before answering.
ASK_TIMEOUT_SECONDS = 900.0

EXPORT_COLUMNS: list[dict[str, str]] = [
    {"key": "book", "label": "Book"}, {"key": "chapter", "label": "Chapter"}, {"key": "verse", "label": "Verse"},
    {"key": "issueType", "label": "Issue type"}, {"key": "category", "label": "Category"},
    {"key": "severity", "label": "Severity"}, {"key": "confidence", "label": "Confidence"},
    {"key": "original", "label": "Original"}, {"key": "suggested", "label": "Suggested correction"},
    {"key": "explanation", "label": "Explanation"}, {"key": "referenceNote", "label": "Reference note"},
    {"key": "decisionNeeded", "label": "Reviewer decision needed"}, {"key": "location", "label": "Location"},
]

_NO_REFERENCE_LINE = re.compile(r"^Target books with no reference file:\s*(.*)$", re.MULTILINE)


def _canon_order(book: dict[str, Any]) -> tuple[int, str]:
    code = str(book.get("bookId") or "").upper()
    known = toolkit.TOOLKIT_BOOKS
    return (known.index(code) if code in known else len(known), code)


class ProofreadingService:
    def __init__(self, engine: Any) -> None:
        self.engine = engine
        self.jobs = jobs.ProofreadingJobManager()

    # -- what the open project gives ------------------------------------------

    def _books(self) -> list[dict[str, Any]]:
        """Every book of the open collection (or the open book alone), in the
        toolkit's canonical order, which is the order its queue hands them out."""
        engine = self.engine
        root = str(engine.project.path)
        siblings = collection_projects(root) or [{
            "path": root, "bookId": engine.project.book_id, "bookName": engine.project.summary.book_name,
            "lazy": False,
        }]
        books = [
            {"path": str(entry.get("path") or ""), "bookId": str(entry.get("bookId") or ""),
             "bookName": str(entry.get("bookName") or ""), "lazy": bool(entry.get("lazy"))}
            for entry in siblings if Path(str(entry.get("path") or "")).is_dir() and entry.get("bookId")
        ]
        return sorted(books, key=_canon_order)

    def _key(self) -> str:
        engine = self.engine
        return str(getattr(engine, "_reference_key", "") or "") or hashlib.sha1(
            str(Path(engine.project.path).resolve().parent).encode("utf-8")).hexdigest()[:20]

    def _paths(self) -> toolkit.RunPaths:
        return toolkit.RunPaths(self.engine.settings.path.parent / "proofreading" / toolkit.run_folder_name(self._key()))

    def _reference(self) -> dict[str, str]:
        """The reference Bible a run would compare against: the folder chosen
        for proofreading, else the folder a reviewer chose as the project's
        reference Bible (#289). The text a Language QA pack bundles (the Tamil
        Old Version) is not offered: it is there for quotation marks and
        related words, and nobody chose it as a text to proofread against."""
        engine = self.engine
        chosen = engine.settings.proofreading_references.get(self._key())
        if chosen:
            folder, label, origin = chosen, Path(chosen).name or chosen, "proofreading"
        else:
            choice = engine._reference_choice()
            if choice is None or choice[2] != "project":
                return {"path": "", "label": "", "origin": "none", "kind": "", "files": "0",
                        "error": "No reference Bible is chosen."}
            folder, label, origin = choice
        try:
            kind = detect(folder)
            files = len(_source_files(Path(folder), kind)) if kind else 0
        except OSError as exc:
            return {"path": folder, "label": label, "origin": origin, "kind": "", "files": "0",
                    "error": f"The reference folder cannot be read: {exc}"}
        error = "" if kind and files else "The folder holds no USFM/SFM files and no verses.tsv."
        if not Path(folder).is_dir():
            error = "The folder is not on this computer."
        return {"path": folder, "label": label, "origin": origin, "kind": kind or "", "files": str(files),
                "error": error}

    def _language(self) -> tuple[str, str]:
        target = self.engine.project.manifest.get("target_language", {})
        if not isinstance(target, dict):
            return "", ""
        return str(target.get("id") or ""), str(target.get("name") or target.get("id") or "")

    def _busy_with_checks(self) -> bool:
        engine = self.engine
        return bool(engine._check_jobs.active() or engine._collection_jobs.active())

    # -- proofreading.preflight -----------------------------------------------

    def preflight(self) -> dict[str, Any]:
        """Everything the start dialog shows before anything is sent: whether
        the AI can be used, the reference Bible, each book and its last run,
        and an estimate worked out offline from the size of the text."""
        engine = self.engine
        engine._require_project()
        code, label = self._language()
        profile = toolkit.load_profile(code)
        reference = self._reference()
        runs = collection_qa_runs(str(engine.project.path), PROOFREAD_RUNS_KEY)
        model, _effort = engine.settings.ai_task_choice("review")
        plan = engine._uses_chatgpt_plan()
        standing = toolkit.estimate_tokens(toolkit.instructions(
            language_label=label, reference_name=reference["label"], profile=profile)) + 1500

        sizes: dict[str, tuple[int, int]] = {}
        for book in self._books():
            source = source_of(Path(book["path"]))
            try:
                text = source.read_text(encoding="utf-8-sig", errors="replace") if source else ""
            except OSError:
                text = ""
            sizes[book["bookId"]] = (len(text), toolkit.estimate_tokens(text))
        reference_tokens = 0
        if not reference["error"]:
            try:
                files = _source_files(Path(reference["path"]), reference["kind"])
                # A verses.tsv carries six columns besides the text; a USFM
                # folder is nearly all text. Bytes over four is close for both.
                reference_tokens = sum(f.stat().st_size for f in files) // 4
            except OSError:
                reference_tokens = 0
        all_tokens = sum(tokens for _chars, tokens in sizes.values()) or 1

        books: list[dict[str, Any]] = []
        for book in self._books():
            chars, tokens = sizes[book["bookId"]]
            supported = book["bookId"].upper() in toolkit.TOOLKIT_BOOKS
            share = reference_tokens * tokens // all_tokens
            estimate = toolkit.estimate_book(book["bookId"], chars, tokens, share, standing)
            try:
                cost = 0.0 if plan else estimate_cost(model, estimate["inputTokens"], estimate["outputTokens"],
                                                      estimate["cachedInputTokens"])
            except Exception:
                cost = 0.0
            previous = runs.get(book["bookId"])
            books.append({
                "bookId": book["bookId"], "bookName": book["bookName"], "path": book["path"],
                "supported": supported,
                "estimate": {**estimate, "estimatedCostUSD": round(cost, 4)},
                "previous": {key: previous.get(key) for key in (
                    "completedAt", "findings", "bySeverity", "reference", "model")} if previous else None,
            })
        return {
            "aiReady": engine._ai_ready(), "planUsage": plan, "model": model,
            "haltReason": engine._ai_halt_reason(),
            "reference": reference,
            "language": {"code": code, "label": label},
            "profile": {"name": str(profile.get("name") or profile.get("_profile")),
                        "code": str(profile.get("_profile")), "status": str(profile.get("status") or "")},
            "toolkit": {"name": toolkit.TOOLKIT_NAME, "fingerprint": toolkit.toolkit_fingerprint(),
                        "pipeline": toolkit.PIPELINE_VERSION},
            "paratextLinked": resolve_paratext_link(engine.project.path).linked,
            "books": books,
            "running": self.jobs.active(), "checkRunning": self._busy_with_checks(),
        }

    # -- proofreading.setReference --------------------------------------------

    def set_reference(self, folder: Any) -> dict[str, str]:
        engine = self.engine
        engine._require_project()
        if folder is not None and not isinstance(folder, str):
            raise ProjectError("folder must be a path or null")
        folder = (folder or "").strip()
        if folder:
            if not Path(folder).is_dir():
                raise ProjectError(f"{folder}: no such folder on this computer")
            folder = str(Path(folder))
        engine.settings.set_proofreading_reference(self._key(), folder or None)
        return self._reference()

    # -- proofreading.start ---------------------------------------------------

    def start(self, book_ids: Any = None, force: bool = False) -> dict[str, Any]:
        engine = self.engine
        engine._require_project()
        if self._busy_with_checks():
            raise jobs.ProofreadingJobConflict("Wait for the running check to finish.")
        if book_ids is not None and not (isinstance(book_ids, list) and all(isinstance(b, str) for b in book_ids)):
            raise ProjectError("books must be a list of book ids")
        everything = self._books()
        if book_ids:
            wanted = {b.lower() for b in book_ids}
            unknown = wanted - {b["bookId"].lower() for b in everything}
            if unknown:
                raise ProjectError(f"Not a book of this project: {', '.join(sorted(unknown))}")
            selected = [b for b in everything if b["bookId"].lower() in wanted]
        else:
            selected = list(everything)
        if not selected:
            raise ProjectError("Choose at least one book to proofread.")
        reference = self._reference()
        if reference["error"]:
            raise ProjectError(f"Choose a reference Bible before proofreading. {reference['error']}")
        try:
            client = engine._ai_client("review")
        except AIError as exc:
            raise ProjectError(str(exc)) from exc

        code, label = self._language()
        model, _effort = engine.settings.ai_task_choice("review")
        plan = engine._uses_chatgpt_plan()
        link = resolve_paratext_link(engine.project.path)
        run = _Run(
            service=self, client=client, paths=self._paths(), collection_path=str(engine.project.path),
            everything=everything, selected=selected, reference=reference, language=(code, label),
            model=model, provider="chatgpt" if plan else "api",
            prices={} if plan else dict(DEFAULT_PRICES.get(model) or DEFAULT_PRICES["gpt-5.6-sol"]),
            notes_user=str(engine.settings.reviewer_name or "Bridge"),
            project_name=str(Path(engine.project.path).name),
            paratext_folder=link.folder if link.linked else None,
            previous=collection_qa_runs(str(engine.project.path), PROOFREAD_RUNS_KEY),
            force=bool(force), cache_key=f"proofreading:{self._key()}",
        )
        spec = jobs.ProofreadingJobSpec(
            collection_path=run.collection_path, reference=reference["label"], force=bool(force),
            books=tuple({"bookId": b["bookId"], "bookName": b["bookName"], "path": b["path"]} for b in selected),
        )
        return self.jobs.start(
            spec, prepare=run.prepare, run_book=run.run_book, record_run=run.record, finish=run.finish,
            halt=engine._ai_halt_reason,
        )

    # -- proofreading.status / pause / cancel ----------------------------------

    def status(self, job_id: str = "") -> dict[str, Any]:
        """The run's snapshot; with no run in this session, an idle one built
        from the recorded `proofreadRuns[]`, so the bar shows each book's last
        run after a restart."""
        try:
            return self.jobs.status(job_id)
        except jobs.ProofreadingJobError:
            if job_id:
                raise
        engine = self.engine
        engine._require_project()
        runs = collection_qa_runs(str(engine.project.path), PROOFREAD_RUNS_KEY)
        books = []
        for book in self._books():
            run = runs.get(book["bookId"]) or {}
            done = run.get("state") == "done"
            books.append({
                "bookId": book["bookId"], "bookName": book["bookName"], "path": book["path"],
                "state": "done" if done else "pending", "elapsedSeconds": run.get("elapsedSeconds"),
                "findings": int(run.get("findings") or 0), "bySeverity": dict(run.get("bySeverity") or {}),
                "chunksDone": 0, "chunksTotal": 0, "usage": dict(run.get("usage") or {}),
                "error": None, "note": None, "completedAt": run.get("completedAt"),
            })
        finished = [b for b in books if b["state"] == "done"]
        return {
            "jobId": "", "state": "idle", "paused": False, "stage": "", "halted": False,
            "collectionPath": str(engine.project.path), "reference": "",
            "totalBooks": len(books), "completedBooks": len(finished),
            "percent": round(100 * len(finished) / len(books)) if books else 0,
            "currentBook": None, "books": books, "findings": sum(b["findings"] for b in finished),
            "usage": {}, "elapsedSeconds": 0, "estimatedRemainingSeconds": None,
            "error": None, "createdAt": None, "finishedAt": None,
        }

    def pause(self, paused: bool, job_id: str = "") -> dict[str, Any]:
        return self.jobs.pause(paused, job_id)

    def cancel(self, job_id: str = "") -> dict[str, Any]:
        return self.jobs.cancel(job_id)

    # -- proofreading.report / rows / export -----------------------------------

    def report(self) -> dict[str, Any]:
        """Each book's last run and the totals, from `proofreadRuns[]` alone:
        no book is opened and no row is read, so it answers at once for a whole
        Bible. The rows themselves are asked for a book at a time."""
        engine = self.engine
        engine._require_project()
        runs = collection_qa_runs(str(engine.project.path), PROOFREAD_RUNS_KEY)
        books: list[dict[str, Any]] = []
        severity = {name: 0 for name in toolkit.SEVERITIES}
        by_type: dict[str, int] = {}
        usage: dict[str, Any] = {}
        for book in self._books():
            run = runs.get(book["bookId"])
            if not run or run.get("state") != "done":
                books.append({"bookId": book["bookId"], "bookName": book["bookName"], "state": "notRun"})
                continue
            for name in severity:
                severity[name] += int((run.get("bySeverity") or {}).get(name) or 0)
            for issue, count in (run.get("byIssueType") or {}).items():
                by_type[str(issue)] = by_type.get(str(issue), 0) + int(count or 0)
            jobs.add_usage(usage, run.get("usage"))
            books.append({"bookName": book["bookName"], **{key: run.get(key) for key in (
                "bookId", "state", "completedAt", "findings", "bySeverity", "byIssueType", "reference", "model",
                "provider", "chunks", "reported", "rejected", "unplaced", "overlapping", "notes", "usage",
                "elapsedSeconds", "hasReference")}})
        paths = self._paths()
        files = {name: str(path) for name, path in (
            ("runReport", paths.output / "QA_Run_Report.xlsx"),
            ("runSummary", paths.output / "RUN_REPORT.md"),
        ) if path.is_file()}
        notes = sorted(paths.output.glob("Notes_*.xml")) if paths.output.is_dir() else []
        if notes:
            files["paratextNotes"] = str(notes[0])
        done = [b for b in books if b.get("state") == "done"]
        return {
            "books": books, "booksRead": len(done), "totalBooks": len(books),
            "findings": sum(int(b.get("findings") or 0) for b in done),
            "bySeverity": severity, "byIssueType": dict(sorted(by_type.items(), key=lambda kv: (-kv[1], kv[0]))),
            "usage": usage, "outputFolder": str(paths.output) if paths.output.is_dir() else "", "files": files,
            "note": "Every row is a proposal from an AI reading, verified to stand in the text, awaiting human "
                    "review. No Scripture was changed.",
        }

    def _book_path(self, book_id: str) -> str:
        for book in self._books():
            if book["bookId"].lower() == str(book_id).lower():
                return book["path"]
        raise ProjectError(f"Not a book of this project: {book_id}")

    def rows(self, book_id: str) -> dict[str, Any]:
        self.engine._require_project()
        path = self._book_path(book_id)
        rows = peek_proofreading_results(path)
        files = {}
        folder = self._paths().book_output(book_id)
        for name, file in (("workbook", folder / f"{book_id.upper()}_QA_Report.xlsx"),
                           ("csv", folder / f"{book_id.upper()}_QA_Issues.csv")):
            if file.is_file():
                files[name] = str(file)
        return {"bookId": book_id, "rows": rows, "files": files}

    def export(self, output_path: str, fmt: str = "csv", book_ids: Any = None) -> dict[str, Any]:
        """The stored findings of the chosen books (all that have any, when
        none are named) as one CSV or TSV, UTF-8 with a BOM."""
        self.engine._require_project()
        if not str(output_path or "").strip():
            raise ProjectError("outputPath is required.")
        wanted = {str(b).lower() for b in book_ids} if isinstance(book_ids, list) and book_ids else None
        rows: list[dict[str, Any]] = []
        for book in self._books():
            if wanted is not None and book["bookId"].lower() not in wanted:
                continue
            rows.extend(peek_proofreading_results(book["path"]))
        # A finding's words come from a model or from the text: a cell that a
        # spreadsheet would read as a formula is written as text.
        keys = [column["key"] for column in EXPORT_COLUMNS]
        rows = [{key: toolkit.spreadsheet_safe(row.get(key)) for key in keys} for row in rows]
        try:
            return write_report_rows(output_path, fmt, rows, EXPORT_COLUMNS)
        except (OSError, ValueError) as exc:
            raise ProjectError(str(exc)) from exc


class _Run:
    """One run's fixed inputs and its three callables. Everything it needs from
    the engine is read when the run starts, on the request thread; the worker
    thread then touches only this object, its own project objects and the AI
    client."""

    def __init__(self, *, service: ProofreadingService, client: Any, paths: toolkit.RunPaths,
                 collection_path: str, everything: list[dict[str, Any]], selected: list[dict[str, Any]],
                 reference: dict[str, str], language: tuple[str, str], model: str, provider: str,
                 prices: dict[str, float], notes_user: str, project_name: str, paratext_folder: Path | None,
                 previous: dict[str, dict[str, Any]], force: bool, cache_key: str) -> None:
        self.service, self.client, self.paths = service, client, paths
        self.collection_path, self.everything, self.selected = collection_path, everything, selected
        self.reference, self.language = reference, language
        self.model, self.provider, self.prices = model, provider, prices
        self.notes_user, self.project_name, self.paratext_folder = notes_user, project_name, paratext_folder
        self.previous, self.force, self.cache_key = previous, force, cache_key
        self.tools = toolkit.ToolRunner(paths.config)
        self.hashes: dict[str, str] = {}
        self.offsets: dict[str, int] = {}
        self.no_reference: set[str] = set()
        self.toolkit_fingerprint = toolkit.toolkit_fingerprint()
        self._usage_lock = threading.Lock()

    def _project(self, path: str) -> TranslationCoreProject:
        engine = self.service.engine
        return TranslationCoreProject(Path(path), workspace=engine.workspace, reviewer_name=self.notes_user)

    # -- prepare: stage everything, decide what is read -------------------------

    def prepare(self, say: Any) -> dict[str, dict[str, Any]]:
        engine = self.service.engine
        paths = self.paths
        paths.prepare()
        say("Staging the reference Bible")
        staged = toolkit.stage_reference(self.reference["path"], paths)
        if staged["error"]:
            raise jobs.ProofreadingJobError(staged["error"])
        toolkit.stage_paratext_data(self.paratext_folder, paths)
        chosen = {b["bookId"] for b in self.selected}
        plan: dict[str, dict[str, Any]] = {}
        say("Staging the books")
        for book in self.everything:
            code = book["bookId"].upper()
            text = ""
            if book["bookId"] in chosen and code in toolkit.TOOLKIT_BOOKS:
                # A chosen book is read as it stands now: materialized first
                # (its findings are kept in its own workbench), then the same
                # source-preserving USFM an export writes.
                materialize_lazy_project(book["path"])
                text = engine._source_preserving_usfm(project=self._project(book["path"])) or ""
            if not text:
                # Every other book is staged as imported, without being opened:
                # it is there only for the whole-translation counts.
                source = source_of(Path(book["path"]))
                try:
                    text = source.read_text(encoding="utf-8-sig") if source else ""
                except (OSError, UnicodeDecodeError):
                    text = ""
            if text:
                toolkit.stage_book(paths, code, text)
            elif book["bookId"] in chosen:
                plan[book["bookId"]] = {"skip": "This book has no USFM text to read."}
        toolkit.write_config(
            paths, project_name=self.project_name, language_code=self.language[0], language_label=self.language[1],
            reference_name=self.reference["label"], notes_user=self.notes_user, model=self.model, prices=self.prices,
        )
        say("Checking the staged text")
        detected = toolkit.require(self.tools("detect_language"))
        missing = _NO_REFERENCE_LINE.search(detected)
        self.no_reference = set(missing.group(1).split()) if missing else set()
        reference_state = fingerprint(self.reference["path"], self.reference["kind"])
        to_run: list[str] = []
        for book in self.selected:
            book_id, code = book["bookId"], book["bookId"].upper()
            if book_id in plan:
                continue
            if code not in toolkit.TOOLKIT_BOOKS:
                plan[book_id] = {"skip": "Not one of the 66 books the proofreading toolkit knows."}
                continue
            digest = hashlib.sha256(json.dumps([
                toolkit.file_hash(paths.target / f"{code}.usfm"), reference_state, self.toolkit_fingerprint,
                toolkit.PIPELINE_VERSION, self.language[0],
            ]).encode("utf-8")).hexdigest()
            self.hashes[book_id] = digest
            previous = self.previous.get(book_id) or {}
            if not self.force and previous.get("state") == "done" and previous.get("contentHash") == digest:
                plan[book_id] = {"skip": "Unchanged since it was last proofread.", "previous": previous}
                continue
            if self.force:
                # "Read it again" means ask the reader again: without this the
                # book's checkpoint, which is for the same text, would answer.
                paths.checkpoint(code).unlink(missing_ok=True)
            to_run.append(code)
        if to_run:
            toolkit.require(self.tools("queue", "start", ",".join(to_run), "--new"))
        return plan

    # -- one book ----------------------------------------------------------------

    def run_book(self, book: dict[str, Any], cancelled: Any, report: Any) -> dict[str, Any]:
        engine = self.service.engine
        book_id, code = str(book["bookId"]), str(book["bookId"]).upper()
        project = self._project(str(book["path"]))
        sizes: dict[int, int] = {}
        verses: list[str] = []
        for chapter in project.chapters():
            if str(chapter).isdigit():
                texts = [str(text) for text in project.target_chapter(chapter).values()]
                sizes[int(chapter)] = sum(len(text) for text in texts)
                verses += [plain_text(text) for text in texts]
        unreadable = ("This book has no chapters to read." if not sizes
                      else "More than half of this book's verses have no text, so it was not read."
                      if toolkit.mostly_empty(verses) else "")
        if unreadable:
            # Before anything is sent, and before the toolkit's sweep, which
            # fails on such a book. Its queue is told, so the next book is the
            # one it hands out next.
            self.tools("queue", "skip", code, unreadable)
            raise toolkit.ProofreadingError(unreadable)
        offset = 3600
        queued = self.tools("queue", "next")
        handed = re.match(r"NEXT (\S+) (\d+)", queued.out.strip())
        if handed and handed.group(1) == code:
            offset = int(handed.group(2))
        client = self.client
        mark = client.usage_mark()

        def ask(name: str, schema: dict[str, Any], instructions: str, text: str) -> dict[str, Any]:
            last: Exception | None = None
            for _attempt in range(2):
                if cancelled():
                    raise toolkit.ProofreadingCancelled("Proofreading was cancelled.")
                reason = engine._ai_halt_reason()
                if reason:
                    raise AIPlanLimitError(reason)
                try:
                    return client.proofread(
                        instructions, text, name, schema, prompt_cache_key=self.cache_key,
                        timeout=ASK_TIMEOUT_SECONDS)
                except AIPlanLimitError:
                    raise
                except AIError as exc:  # one more try: a cut-off answer, a passing fault
                    last = exc
            raise last if last is not None else AIError("The AI did not answer.")

        def spent() -> dict[str, Any]:
            usage, cost = client.usage_since(mark)
            return {**usage_dict(usage), "estimatedCostUSD": round(float(cost), 6)}

        def settle() -> dict[str, Any]:
            usage = spent()
            if usage["calls"]:
                with self._usage_lock:
                    engine.settings.record_ai_usage(usage["totalTokens"], usage["estimatedCostUSD"])
            return usage

        try:
            outcome = toolkit.proofread_book(
                code, sizes, paths=self.paths, tools=self.tools, ask=ask,
                language_label=self.language[1], reference_name=self.reference["label"],
                language_code=self.language[0], has_reference=code not in self.no_reference,
                content_hash=self.hashes.get(book_id, ""), base_offset=offset, cancelled=cancelled, report=report,
            )
        except toolkit.ProofreadingCancelled as exc:
            settle()
            raise jobs.BookCancelled(str(exc)) from exc
        except AIPlanLimitError as exc:
            halted = jobs.RunHalted(str(exc))
            halted.usage = settle()  # type: ignore[attr-defined]
            raise halted from exc
        except Exception as exc:
            exc.usage = settle()  # type: ignore[attr-defined]
            self.tools("queue", "skip", code, "not finished:", str(exc)[:120])
            raise
        usage = settle()
        stored = toolkit.stored_rows(code, outcome.rows)
        rows = [row for chapter in stored.values() for row in chapter]
        summary = toolkit.summarize(rows)
        project.save_proofreading_results(stored, meta={
            "model": self.model, "provider": self.provider, "reference": self.reference["label"],
            "toolkit": self.toolkit_fingerprint, "pipeline": toolkit.PIPELINE_VERSION,
        })
        fresh = max(0, usage["inputTokens"] - usage["cachedInputTokens"])
        self.tools("queue", "done", code, "--usage",
                   f"{fresh},0,{usage['cachedInputTokens']},{usage['outputTokens']}")
        return {
            **summary, "contentHash": self.hashes.get(book_id, ""), "pipeline": toolkit.PIPELINE_VERSION,
            "toolkit": self.toolkit_fingerprint, "model": self.model, "provider": self.provider,
            "reference": self.reference["label"], "hasReference": code not in self.no_reference,
            "chunks": outcome.chunks, "reported": outcome.reported, "rejected": outcome.rejected,
            "unplaced": outcome.unplaced, "overlapping": outcome.overlapping, "notes": outcome.notes,
            "usage": usage,
        }

    def record(self, entry: dict[str, Any]) -> None:
        record_collection_qa_run(self.collection_path, entry, key=PROOFREAD_RUNS_KEY)

    def finish(self) -> None:
        self.tools("report")
