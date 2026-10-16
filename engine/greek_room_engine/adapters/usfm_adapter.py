"""
USFM structural checker adapter.

Wraps the vendored Greek Room USFM checker (engine/vendor/greekroom-usfm/,
see NOTICE.md there for provenance/license/pinned commit) as a subprocess,
not an import — that tool is a 4,000-line CLI/report generator, not a
library, and isn't published on PyPI at all (unlike Wildebeest). See
docs/BUILD_LOG.md for the full investigation of why this is
vendored rather than a normal dependency.

Unlike WildebeestAdapter, this operates on a WHOLE BOOK at once, not a
single verse — duplicate/missing verse numbers, unclosed markers spanning
lines, and chapter-level structure are inherently whole-file concerns. The
caller (bridge_service.py) runs this once per book and caches the result,
rather than once per verse.runChecks call, since each run spawns a Python
subprocess loading a real Unicode/tag database — far too slow to repeat
per verse.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from .base import CheckAdapter
from ..models.finding import QaFinding, FindingCategory, Severity

VENDOR_ROOT = Path(__file__).resolve().parent.parent.parent / "vendor" / "greekroom-usfm"
CHECKER_SCRIPT = VENDOR_ROOT / "usfm_check.py"
CHECKER_OVERRIDE_ENV = "BRIDGE_USFM_CHECKER"
CHECKER_BINARY_NAME = "bridge-usfm-checker"


class UsfmCheckerError(RuntimeError):
    """The structural checker could not complete reliably.

    A failed checker is deliberately not represented as an empty finding
    list: empty means the book was checked and found clean.
    """


class UsfmCheckerCancelled(UsfmCheckerError):
    """The caller cancelled a running structural-check subprocess."""


def _frozen_checker_candidates() -> list[Path]:
    executable = Path(sys.executable).resolve()
    extension = ".exe" if os.name == "nt" else ""
    candidates = [executable.with_name(f"{CHECKER_BINARY_NAME}{extension}")]

    # Tauri's build output strips the target triple, but developers may run
    # the target-suffixed source artifact in src-tauri/binaries directly.
    if executable.name.startswith("bridge-engine"):
        suffix = executable.name[len("bridge-engine"):]
        candidates.append(executable.with_name(f"{CHECKER_BINARY_NAME}{suffix}"))
    return list(dict.fromkeys(candidates))


def _checker_command() -> list[str] | None:
    """Resolve the checker command without ever re-invoking bridge-engine."""
    override = os.getenv(CHECKER_OVERRIDE_ENV, "").strip()
    if override:
        path = Path(override).expanduser().resolve()
        return [str(path)] if path.is_file() else None

    if getattr(sys, "frozen", False):
        for candidate in _frozen_checker_candidates():
            if candidate.is_file():
                return [str(candidate)]
        return None

    # Source mode uses the active Python interpreter. Ensure the vendored
    # CLI's only third-party runtime dependency is actually importable.
    if CHECKER_SCRIPT.is_file() and find_spec("regex") is not None:
        return [sys.executable, str(CHECKER_SCRIPT)]
    return None


def _bounded_detail(value: str, limit: int = 600) -> str:
    """Return the useful final diagnostic, not an entire Python traceback."""
    lines = [line.strip() for line in (value or "").splitlines() if line.strip()]
    if not lines:
        return "no diagnostic output"
    useful = next(
        (line for line in reversed(lines) if not line.startswith(("Traceback ", "File "))),
        lines[-1],
    )
    return useful[-limit:]

_SEVERITY_MAP = {
    "severe errors": Severity.HIGH,
    "errors": Severity.HIGH,
    "auto-repairable errors": Severity.MEDIUM,
    "warnings": Severity.LOW,
}

# Three location-reference shapes the real tool's .txt report actually uses
# (verified against real output, not guessed — see docs/BUILD_LOG.md):
#   "TIT 2:2: <line text>"                        -> book, chapter, verse given
#   "book.usfm l.7 (TIT 1): Duplicate verse ... 1" -> book, chapter given, no verse
#   "book.usfm (TIT 1): Missing verse: 2"          -> book, chapter given, no verse
_LOC_WITH_VERSE_RE = re.compile(r"^(?P<book>[A-Z1-9]{2,4}) (?P<chapter>\d+):(?P<verse>\S+?):\s*(?P<detail>.*)$")
_LOC_WITH_LINE_RE = re.compile(r"^\S+\.[Uu][Ss][Ff][Mm] l\.\d+ \((?P<book>[A-Z1-9]{2,4}) (?P<chapter>\d+)\):\s*(?P<detail>.*)$")
_LOC_FILE_ONLY_RE = re.compile(r"^\S+\.[Uu][Ss][Ff][Mm] \((?P<book>[A-Z1-9]{2,4}) (?P<chapter>\d+)\):\s*(?P<detail>.*)$")
_LABELED_COUNT_RE = re.compile(r"^(?P<label>[A-Za-z][^()]*?)\s*\((?P<count>\d+)\)\s*$")
_TRAILING_NUMBER_RE = re.compile(r"(\d+)\s*$")
_VERSE_MENTION_RE = re.compile(r"\bverse:?\s*(\d+)\b", re.IGNORECASE)
# A file-and-line instance whose detail is the verse line itself, e.g.
# "\v 5a five a" under "Verse number includes letter" (#303): the verse is
# the marker's own reference, segment letter or bridge included.
_DETAIL_VERSE_MARKER_RE = re.compile(r"^\\v\s+(\d+[a-z]?(?:-\d+[a-z]?)?)(?=\s|$)")
_LEADING_NUMBER_RE = re.compile(r"^(\d+)")


def _verse_number(ref: str) -> int:
    """The first number of a verse reference: "5a" -> 5, "3-4" -> 3, "" -> 0."""
    match = _LEADING_NUMBER_RE.match(ref)
    return int(match.group(1)) if match else 0


def _slugify(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_") or "issue"


def _parse_report(text: str) -> list[dict[str, Any]]:
    """Parse usfm_check.py's indented .txt report into structured issues.

    There's no machine-readable output to parse instead: the tool's -j/--json
    CLI flag is accepted but never actually used anywhere in its own code
    (verified by reading the vendored source — dead code upstream, not a
    version mismatch on our end). The .txt report's indentation depth to
    reach an actual issue instance varies by category (3 or 4 levels), so
    this tracks an indentation stack rather than assuming a fixed depth.

    An instance line can itself end in a count -- "LUK 18:14: <verse> (2)",
    the same problem twice in one verse -- so a line that matches a location
    shape is an instance before it is ever tried as a header. Before #283 it
    was taken for a header, its verse text became the subcategory (and so the
    check type) of every later instance in the group, and it was itself lost.
    `legacy_subcategory` is what that parse said, so a decision recorded under
    the old check type can be carried to the new id once (#273's rule).
    """
    issues: list[dict[str, Any]] = []
    stack: list[tuple[int, str]] = []
    legacy_stack: list[tuple[int, str]] = []

    def push(target: list[tuple[int, str]], indent: int, label: str) -> None:
        while target and target[-1][0] >= indent:
            target.pop()
        target.append((indent, label))

    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()

        labeled = _LABELED_COUNT_RE.match(stripped)
        is_instance = bool(_LOC_WITH_VERSE_RE.match(stripped) or _LOC_WITH_LINE_RE.match(stripped)
                           or _LOC_FILE_ONLY_RE.match(stripped))
        if labeled:
            push(legacy_stack, indent, labeled.group("label").strip())
            if not is_instance:
                push(stack, indent, labeled.group("label").strip())
                continue

        severity_label = stack[0][1].lower() if stack else ""
        severity = _SEVERITY_MAP.get(severity_label, Severity.MEDIUM)
        category = stack[1][1] if len(stack) > 1 else ""
        subcategory = stack[-1][1] if stack else "USFM issue"
        # The line the old parse took for a header was never a finding then,
        # so it has no earlier id to carry.
        legacy_subcategory = subcategory if labeled else (legacy_stack[-1][1] if legacy_stack else "USFM issue")

        match = _LOC_WITH_VERSE_RE.match(stripped)
        if match:
            issues.append({
                "book": match.group("book"), "chapter": match.group("chapter"),
                "verse": match.group("verse"), "detail": match.group("detail"),
                "severity": severity, "category": category, "subcategory": subcategory,
                "legacy_subcategory": legacy_subcategory,
            })
            continue

        match = _LOC_WITH_LINE_RE.match(stripped)
        if match:
            detail = match.group("detail")
            verse_match = (_DETAIL_VERSE_MARKER_RE.match(detail) or _TRAILING_NUMBER_RE.search(subcategory)
                           or _TRAILING_NUMBER_RE.search(detail))
            issues.append({
                "book": match.group("book"), "chapter": match.group("chapter"),
                "verse": verse_match.group(1) if verse_match else "",
                "detail": detail, "severity": severity, "category": category, "subcategory": subcategory,
                "legacy_subcategory": legacy_subcategory,
            })
            continue

        match = _LOC_FILE_ONLY_RE.match(stripped)
        if match:
            detail = match.group("detail")
            verse_match = _VERSE_MENTION_RE.search(detail)
            issues.append({
                "book": match.group("book"), "chapter": match.group("chapter"),
                "verse": verse_match.group(1) if verse_match else "",
                "detail": detail, "severity": severity, "category": category, "subcategory": subcategory,
                "legacy_subcategory": legacy_subcategory,
            })
            continue

    return issues


class UsfmAdapter(CheckAdapter):
    engine_name = "usfm"

    def is_available(self) -> bool:
        return _checker_command() is not None

    def using_real_engine(self) -> bool:
        return self.is_available()

    def version(self) -> str:
        return "vendored-18ddcf0"  # pinned commit short SHA, see vendor/greekroom-usfm/NOTICE.md

    def check_verse(self, *, project_id: str, lang_code: str, ref: str,
                     text: str, params: dict[str, Any]) -> list[QaFinding]:
        # Not used: this adapter is whole-book, invoked directly via
        # check_book() from bridge_service.py, not through GreekRoomEngine's
        # per-verse dispatch. Present only to satisfy the CheckAdapter
        # interface (is_available() gates it out of the normal per-verse
        # loop, since it isn't registered as "usfm" in that loop's checks).
        return []

    def check_book(
        self, *, project_id: str, book_id: str, usfm_text: str,
        cancel_event: threading.Event | None = None,
    ) -> list[QaFinding]:
        command = _checker_command()
        if command is None:
            mode = "frozen helper" if getattr(sys, "frozen", False) else "source checker"
            raise UsfmCheckerError(f"USFM structural checker unavailable ({mode} not found or incomplete)")
        book_upper = book_id.upper()
        with tempfile.TemporaryDirectory(prefix="bridge-usfm-check-") as tmp:
            tmp_path = Path(tmp)
            source_path = tmp_path / f"{book_upper}.usfm"
            source_path.write_text(usfm_text, encoding="utf-8")
            report_path = tmp_path / "report.txt"
            html_path = tmp_path / "report.html"
            extract_path = tmp_path / "extract.jsonl"

            args = [*command, str(source_path), "-o", str(report_path),
                    "-x", str(html_path), "-e", str(extract_path)]
            env = {
                **os.environ,
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
                "PYTHONPATH": os.pathsep.join(filter(None, [
                    str(VENDOR_ROOT), os.environ.get("PYTHONPATH", ""),
                ])),
            }
            try:
                completed = self._run_checker(
                    args, cwd=tmp_path, env=env, cancel_event=cancel_event,
                )
            except OSError as exc:
                raise UsfmCheckerError(f"USFM structural checker could not start: {exc}") from exc

            if completed.returncode != 0:
                raise UsfmCheckerError(
                    f"USFM structural checker exited with code {completed.returncode}: "
                    f"{_bounded_detail(completed.stderr)}"
                )

            if not report_path.is_file():
                raise UsfmCheckerError(
                    "USFM structural checker exited successfully but produced no report: "
                    f"{_bounded_detail(completed.stderr)}"
                )
            try:
                report_text = report_path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                raise UsfmCheckerError(f"USFM structural checker report could not be read: {exc}") from exc

        issues = _parse_report(report_text)
        findings: list[QaFinding] = []
        for issue in issues:
            if issue["book"] != book_upper:
                continue
            chapter = issue["chapter"]
            verse = issue["verse"] or "0"
            # "5a" or "3-4" keeps its exact reference for anchoring (#303);
            # `verse` is its first number, as everywhere else (gotcha 12).
            verse_ref = "" if verse.isdigit() else verse
            subcategory = issue["subcategory"]
            detail = issue["detail"]
            # The upstream report's detail line often just restates the
            # subcategory label ("Duplicate verse number: Duplicate verse
            # number 1") — only prefix it when detail adds something new.
            explanation = detail if subcategory.lower() in detail.lower() else f"{subcategory}: {detail}"
            finding = QaFinding(
                project_id=project_id,
                book=book_id,
                chapter=int(chapter) if chapter.isdigit() else 0,
                verse=_verse_number(verse),
                verse_ref=verse_ref,
                original_text="",
                engine=self.engine_name,
                check_type=f"usfm.{_slugify(subcategory)}",
                category=FindingCategory.STRUCTURE,
                severity=issue["severity"],
                confidence=0.8,
                explanation=explanation.strip(": "),
                engine_version=self.version(),
            )
            if issue["legacy_subcategory"] != subcategory:
                # The check type this finding had before #283; the dispatcher
                # derives the old id from it to carry a decision once.
                finding._legacy_check_type = f"usfm.{_slugify(issue['legacy_subcategory'])}"  # type: ignore[attr-defined]
            findings.append(finding)
        return findings

    @staticmethod
    def _run_checker(
        args: list[str], *, cwd: Path, env: dict[str, str],
        cancel_event: threading.Event | None,
    ) -> subprocess.CompletedProcess[str]:
        if cancel_event is None:
            try:
                return subprocess.run(
                    args, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=120, check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise UsfmCheckerError("USFM structural checker timed out after 120 seconds") from exc

        process = subprocess.Popen(
            args, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
        )
        deadline = time.monotonic() + 120
        while process.poll() is None:
            if cancel_event.wait(timeout=0.05):
                process.terminate()
                try:
                    process.communicate(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate(timeout=3)
                raise UsfmCheckerCancelled("USFM structural checker was cancelled")
            if time.monotonic() >= deadline:
                process.terminate()
                try:
                    process.communicate(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate(timeout=3)
                raise UsfmCheckerError("USFM structural checker timed out after 120 seconds")

        stdout, stderr = process.communicate()
        return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
