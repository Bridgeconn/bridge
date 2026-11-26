"""Publishing-level proofreading of a book, with the bundled toolkit (#505).

The toolkit (`engine/proofreading_toolkit/`, Benz's `bible-qa-universal`) was
written as a Claude skill: a model reads each book against a reference Bible,
and the toolkit's own command-line tools produce the leads it starts from,
answer its questions about the whole translation, verify that every finding's
words really stand in the text, and write the workbook, the CSV and the
Paratext notes. Bridge keeps all of that and replaces only the session: this
module does the steps of `SKILL.md` section 2 itself and asks whatever reader
it is handed (`ask`, in practice Bridge's own AI client on an API key or a
ChatGPT sign-in) for the findings.

What this module is careful about:

* **The tools only ever see staged copies.** A run has a folder under Bridge's
  data folder; the text is written into it and the tools are pointed at it by
  `config.json`. They read USFM with their own regular expressions, which is
  allowed nowhere else in Bridge (CLAUDE.md gotcha 14; the exception is in
  docs/DECISIONS.md, 2026-11-25). This module does not parse USFM at all.
* **Nothing a model wrote is executed.** The toolkit's `build.py` loads a
  book's findings by executing `rows_<book>.py`. The reader returns findings as
  data against a strict schema; `write_rows_file` writes the file itself, each
  value through `repr()`.
* **A finding is kept only if the toolkit can place it.** `build.py` locates
  every `Original` character for character in the verse, the heading, the
  footnote or the introduction. What it cannot place is dropped and counted,
  never reported.
* **Nothing is written to a project here.** The outcome is rows and counts;
  storing them is the caller's business.

No Bridge engine state is touched: the tool runner, the reader and the
cancellation check are all passed in, so the whole procedure runs under test
with a scripted reader and the real tools.
"""
from __future__ import annotations

import ast
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

# Bump when what a run would produce for the same text changes (the prompt, the
# procedure, the row shape), so a recorded run of an older pipeline is not
# treated as current.
PIPELINE_VERSION = 1
TOOLKIT_NAME = "bible-qa-universal"

# The 66 books the toolkit knows (`tools/project.py` ORDER). A book outside
# this list cannot be put in its queue.
TOOLKIT_BOOKS: tuple[str, ...] = tuple(
    "GEN EXO LEV NUM DEU JOS JDG RUT 1SA 2SA 1KI 2KI 1CH 2CH EZR NEH EST JOB PSA PRO ECC SNG ISA JER LAM "
    "EZK DAN HOS JOL AMO OBA JON MIC NAM HAB ZEP HAG ZEC MAL MAT MRK LUK JHN ACT ROM 1CO 2CO GAL EPH PHP COL "
    "1TH 2TH 1TI 2TI TIT PHM HEB JAS 1PE 2PE 1JN 2JN 3JN JUD REV".split()
)

# SKILL.md section 4: "Issue types (use these strings)".
ISSUE_TYPES: tuple[str, ...] = (
    "Sandhi / word-joining", "Source comparison", "Punctuation", "Textual-basis review", "Grammar",
    "Footnote / cross-reference", "USFM marker", "Name consistency", "Possible missed source word",
    "Confirmed typo", "Possible typo", "Plural agreement", "Case/object marker", "Theological consistency",
    "Reviewer decision", "Addition - not in source", "Harmonization", "Heading", "Numbers", "Verse boundary",
    "Factual", "Style",
)
SEVERITIES: tuple[str, ...] = ("High", "Medium", "Low")
CONFIDENCES: tuple[str, ...] = ("High", "Medium", "Low", "Reviewer decision")
DECISIONS: tuple[str, ...] = ("No", "Review", "Yes")
EVIDENCE_CHECKS: tuple[str, ...] = ("none", "count", "nearby")

# The columns of the toolkit's `<BOOK>_QA_Issues.csv`, by position: the header
# names two of them after the language and the reference, so they are not
# matched by name.
CSV_FIELDS: tuple[str, ...] = (
    "book", "chapter", "verse", "issueType", "category", "severity", "confidence", "original", "suggested",
    "explanation", "referenceNote", "decisionNeeded", "status", "location", "anchor",
)

# About three chapters at a time (SKILL.md section 2), fewer when they are long.
CHUNK_CHAPTERS = 3
CHUNK_CHARS = 16000
LEADS_CHARS = 24000
INTRO_CHARS = 16000
NEARBY_PER_CHUNK = 12
BUILD_ROUNDS = 4
TOOL_TIMEOUT_SECONDS = 600
PARATEXT_DATA_FILES: tuple[str, ...] = (
    "Settings.xml", "BookNames.xml", "SpellingStatus.xml", "ProjectBiblicalTerms.xml", "TermRenderings.xml",
)


class ProofreadingError(RuntimeError):
    pass


class ProofreadingCancelled(ProofreadingError):
    """The run was cancelled between two steps. Nothing of the book in flight
    is kept as a result; its finished chunks stay in the checkpoint."""


# -- the toolkit, as files ----------------------------------------------------

def toolkit_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "proofreading_toolkit"
    return Path(__file__).resolve().parent.parent / "proofreading_toolkit"


def toolkit_fingerprint() -> str:
    """A short hash of every toolkit file, so a recorded run says which copy
    of the toolkit produced it and a changed toolkit re-reads a book."""
    digest = hashlib.sha256()
    root = toolkit_root()
    for path in sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def tool_command(tool: str, args: Iterable[str]) -> list[str]:
    """The frozen exe re-invokes itself with --proofread-tool; from source it
    is `python proofread_tool_main.py` (see that module)."""
    arguments = [str(a) for a in args]
    if getattr(sys, "frozen", False):
        return [sys.executable, "--proofread-tool", tool, *arguments]
    runner = Path(__file__).resolve().parent.parent / "proofread_tool_main.py"
    return [sys.executable, str(runner), tool, *arguments]


@dataclass(frozen=True)
class ToolResult:
    tool: str
    code: int
    out: str
    err: str

    @property
    def ok(self) -> bool:
        return self.code == 0


class ToolRunner:
    """Runs one toolkit tool per call, each in its own process, against one
    run's `config.json`. Output is read as UTF-8 (the runner sets it)."""

    def __init__(self, config: Path, timeout: float = TOOL_TIMEOUT_SECONDS) -> None:
        self.config = Path(config)
        self.timeout = timeout
        self.calls = 0

    def __call__(self, tool: str, *args: Any, env: dict[str, str] | None = None) -> ToolResult:
        environment = {**os.environ, "QA_CONFIG": str(self.config), "PYTHONUTF8": "1",
                       "PYTHONIOENCODING": "utf-8", **(env or {})}
        self.calls += 1
        try:
            done = subprocess.run(
                tool_command(tool, args), stdin=subprocess.DEVNULL, capture_output=True,
                timeout=self.timeout, env=environment, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as exc:
            raise ProofreadingError(f"The proofreading tool '{tool}' did not finish in {int(self.timeout)} s.") from exc
        except OSError as exc:
            raise ProofreadingError(f"The proofreading tool '{tool}' could not be started: {exc}") from exc
        return ToolResult(tool, done.returncode, done.stdout.decode("utf-8", "replace"),
                          done.stderr.decode("utf-8", "replace"))


def require(result: ToolResult) -> str:
    """The tool's output, or a ProofreadingError carrying what it said."""
    if not result.ok:
        said = (result.err or result.out).strip().splitlines()
        raise ProofreadingError(f"The proofreading tool '{result.tool}' failed: {said[-1] if said else result.code}")
    return result.out


# -- a run's folder -----------------------------------------------------------

@dataclass(frozen=True)
class RunPaths:
    root: Path

    @property
    def target(self) -> Path:
        return self.root / "stage" / "target"

    @property
    def reference(self) -> Path:
        return self.root / "stage" / "reference"

    @property
    def work(self) -> Path:
        return self.root / "work"

    @property
    def rows(self) -> Path:
        return self.work / "rows"

    @property
    def output(self) -> Path:
        return self.root / "output"

    @property
    def config(self) -> Path:
        return self.root / "config.json"

    def prepare(self) -> None:
        """Empty staging folders; the work and output folders are kept, so the
        cumulative notes file, the run report and each book's checkpoint
        survive from one run to the next."""
        for folder in (self.target, self.reference):
            if folder.exists():
                shutil.rmtree(folder)
            folder.mkdir(parents=True, exist_ok=True)
        for folder in (self.rows, self.output):
            folder.mkdir(parents=True, exist_ok=True)

    def checkpoint(self, book: str) -> Path:
        return self.work / f"checkpoint_{book.lower()}.json"

    def book_output(self, book: str) -> Path:
        return self.output / book.upper()


def run_folder_name(key: str) -> str:
    """A folder name for a project key (a collection or project id)."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "-", str(key or "")).strip("-.")
    return cleaned[:80] or hashlib.sha1(str(key).encode("utf-8")).hexdigest()[:20]


def language_tag(code: Any) -> str:
    """A language code as the toolkit may be handed it: letters, digits and
    hyphens only. `tools/project.py` joins it into a folder path to pick a
    profile, and `deliver.py` writes it raw into an XML attribute of every
    Paratext note; a manifest's `target_language.id` is free text."""
    return re.sub(r"[^A-Za-z0-9-]", "", str(code or ""))[:35]


def notes_user_name(name: Any) -> str:
    """The name the toolkit's notes are written under. `deliver.py` puts it
    in an XML attribute without escaping a double quote, and `merge_notes.py`
    makes it part of a file name (`Notes_<name>.xml`), so the characters
    neither can hold are taken out. Bridge's display names are free text."""
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', " ", str(name or ""))
    return " ".join(cleaned.split()).strip(" .")[:80] or "Bridge"


def plain_label(value: Any, fallback: str = "") -> str:
    """A name the toolkit prints at the start of a cell: the workbook's title
    line begins with the language name, and the CSV's headers carry it and the
    reference's name. One that begins with `=`, `+`, `-` or `@` would make
    that cell a formula, so those leading characters are dropped. Both names
    are free text (a manifest field, a folder's name)."""
    text = " ".join(str(value or "").split()).lstrip("=+-@ ")
    return text or fallback


def write_config(paths: RunPaths, *, project_name: str, language_code: str, language_label: str,
                 reference_name: str, notes_user: str, model: str, prices: dict[str, float]) -> None:
    """The toolkit's `config.json` (templates/config.example.json), pointing
    every tool at this run's staged copies and nowhere else."""
    language_code = language_tag(language_code)
    notes_user = notes_user_name(notes_user)
    config = {
        "project_name": plain_label(project_name),
        "target_dir": paths.target.as_posix(),
        "reference_dir": paths.reference.as_posix(),
        "reference_name": plain_label(reference_name, "Reference"),
        # A named language picks profiles/<code>; "auto" lets the toolkit read
        # a staged Settings.xml, then the script of the text.
        "language": language_code or "auto",
        "language_label": plain_label(language_label),
        "notes_user": notes_user or "Bridge",
        "notes_language_tag": language_code or "",
        "output_dir": paths.output.as_posix(),
        "work_dir": paths.work.as_posix(),
        "model": model,
        "price_per_million_tokens_usd": {
            "input": float(prices.get("input", 0.0)), "cache_write": float(prices.get("input", 0.0)),
            "cache_read": float(prices.get("cached_input", 0.0)), "output": float(prices.get("output", 0.0)),
        },
    }
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.config.write_text(json.dumps(config, ensure_ascii=False, indent=1), encoding="utf-8")


def stage_book(paths: RunPaths, book: str, usfm: str) -> Path:
    """One book's text, as the toolkit will read it. Written as given: no
    newline translation, so what `build.py` locates is what Bridge exported."""
    path = paths.target / f"{book.upper()}.usfm"
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(usfm)
    return path


def stage_paratext_data(folder: Path | None, paths: RunPaths) -> list[str]:
    """Copies of the linked Paratext project's team data, for the tools that
    read it (`sweep` the wrong-word list and book names, `terms` and `nearby`
    the key-term renderings). Read-only towards Paratext; missing files are
    simply not there, and each tool says so itself."""
    if folder is None or not folder.is_dir():
        return []
    staged: list[str] = []
    for name in PARATEXT_DATA_FILES:
        source = folder / name
        if source.is_file():
            try:
                shutil.copyfile(source, paths.target / name)
                staged.append(name)
            except OSError:
                continue
    return staged


def _verse_order(value: str) -> tuple[int, str]:
    digits = "".join(ch for ch in str(value).split("-")[0] if ch.isdigit())
    return (int(digits) if digits else 0, str(value))


def stage_reference(folder: str | Path, paths: RunPaths) -> dict[str, Any]:
    """The reference Bible, as USFM files the toolkit finds by their `\\id`
    line. A folder of USFM/SFM files is copied as it is, so the tools can count
    its headings, poetry lines and footnotes. A `verses.tsv` reference holds
    plain verse text only, so it is written out as minimal USFM: the reference
    comparisons work, and those three counts read 0 for it."""
    from .language_packs.reference_text import _load_tsv, _source_files, detect

    source = Path(folder)
    kind = detect(source)
    if kind is None:
        return {"kind": "", "files": 0, "error": "The reference folder holds no USFM/SFM files and no verses.tsv."}
    files = 0
    if kind == "usfm":
        for file in _source_files(source, "usfm"):
            shutil.copyfile(file, paths.reference / file.name)
            files += 1
    else:
        for book, chapters in _load_tsv(source).items():
            lines = [f"\\id {book}"]
            for chapter in sorted(chapters, key=_verse_order):
                lines.append(f"\\c {chapter}")
                lines.append("\\p")
                for verse in sorted(chapters[chapter], key=_verse_order):
                    lines.append(f"\\v {verse} {' '.join(str(chapters[chapter][verse]).split())}")
            (paths.reference / f"{book}.usfm").write_text("\n".join(lines) + "\n", encoding="utf-8")
            files += 1
    return {"kind": kind, "files": files, "error": "" if files else "The reference folder has no readable book."}


def file_hash(*paths: Path) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes() if path.is_file() else b"\0missing")
    return digest.hexdigest()


# -- what the reader is told --------------------------------------------------

def _skill_sections(text: str, numbers: tuple[int, ...]) -> str:
    """The numbered `## N.` sections of SKILL.md, verbatim. If the headings
    are not found (a later copy renumbered them) the whole file is returned:
    more than needed, never less."""
    parts = re.split(r"(?m)^(?=## )", text)
    wanted = [p.strip() for p in parts if any(p.startswith(f"## {n}.") for n in numbers)]
    return "\n\n".join(wanted) if len(wanted) == len(numbers) else text.strip()


def load_profile(language_code: str) -> dict[str, Any]:
    """`profiles/<code>/profile.json`, else the generic one: the same choice
    `tools/project.py` makes, so the reader is told the rules the tools use."""
    root = toolkit_root() / "profiles"
    code = (language_tag(language_code) or "generic").split("-")[0].lower() or "generic"
    folder = root / code
    if not (folder / "profile.json").is_file():
        folder = root / "generic"
    profile = json.loads((folder / "profile.json").read_text(encoding="utf-8"))
    profile["_profile"] = folder.name
    return profile


def instructions(*, language_label: str, reference_name: str, profile: dict[str, Any]) -> str:
    """The reader's standing instructions: the same for every chunk of every
    book of a run, so a provider's prefix cache can hold them."""
    root = toolkit_root()
    skill = (root / "SKILL.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    checklist = (root / "guides" / "checklist-meaning-and-theology.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    language = language_label or "the target language"
    reviewed = profile.get("_profile") != "generic" and "DRAFT" not in str(profile.get("status") or "").upper()
    rules = profile.get("rules") if isinstance(profile.get("rules"), dict) else {}
    lines = [
        f"You are the proofreader in a publishing-level proofreading check of a Bible translation in {language}, "
        f"read against a reference Bible ({reference_name or 'the reference'}). Every finding you report is a "
        "proposal for human review. You never change the text.",
        "",
        "# How you work here",
        "A program runs the checking toolkit around you. For each book it gives you: the LEADS the toolkit's "
        "scripted tools produced (leads are not findings: check each one against the text before you report it, "
        "and list in `rejected` the ones you checked and found correct or house style), the book's INTRODUCTION "
        "with the first chapters, and then a few chapters of the TRANSLATION followed by the same chapters of the "
        "REFERENCE. Read every verse you are given against the reference and report every finding in those "
        "chapters, Low ones included. Report nothing outside the chapters (and the introduction) you were given.",
        "",
        "# Each row",
        "- `chapter` is the chapter number, or \"Intro\" for the introduction. `verse` is the verse number as it "
        "stands in the translation (\"\" for the introduction).",
        "- `original` is copied character for character from the translation you were given: the exact words the "
        "finding is about, as few as identify it, never the whole verse, never the verse number, never words from "
        "two verses. A row whose `original` cannot be found in that verse is discarded. For a heading, `original` "
        "starts with \"\\s \" followed by the heading's words.",
        "- `suggested` is clean target-language text only, or \"\" when the item is a decision for the team.",
        "- `explanation` is plain English with the evidence and the effect. `reference_note` is a short phrase "
        "from the reference Bible with its verse.",
        "- `issue_type` is one of the listed strings. `priority_category` is a one-word class such as Typo, "
        "Source, Punctuation, Grammar, Heading, Marker, Name, Number, Theology, Style.",
        "- `evidence_check`: \"count\" for a spelling or word-division finding (the program counts `original` and "
        "`suggested` across the whole translation before it is reported; a form common across the translation is "
        "house style); \"nearby\" before anything is reported as missing (an omission, a possible missed source "
        "word, a missing clause or name, a verse boundary), with `evidence_find` set to the target-language word "
        "or words you expected to see, or \"\"; otherwise \"none\" with `evidence_find` \"\".",
        "",
        "# The toolkit's checks and row rules (SKILL.md)",
        _skill_sections(skill, (4, 5)),
        "",
        "# " + checklist.lstrip("# ").strip(),
        "",
        f"# Language profile: {profile.get('name') or profile.get('_profile')}",
        f"Status: {profile.get('status') or ''}",
    ]
    if rules and "how_to_fill" not in rules and "TO_FILL" not in rules:
        lines.append("Rules of the profile:")
        lines.append(json.dumps(rules, ensure_ascii=False, indent=1))
    if not reviewed:
        lines.append(
            "No profile reviewed by a native linguist exists for this language. Apply what you know of its "
            "spelling, grammar and agreement, case or particles, word division, register, punctuation and "
            "quotation, numbers and names. A row that rests only on such an unreviewed rule is Confidence Medium "
            "with decision Review.")
    figures = profile.get("figures_of_speech")
    if isinstance(figures, list) and figures:
        lines.append("Figures of speech to watch: " + "; ".join(str(f) for f in figures))
    return "\n".join(lines)


VERDICT_INSTRUCTIONS = (
    "You reported the rows below with a request for evidence, and the program ran the toolkit's tools. Decide each "
    "row again on that evidence, following the toolkit's rules.\n"
    "- A counted spelling or word-division form: a form common across the whole translation is house style; do "
    "not report it (keep = false, and say why). Keep a form that is clearly the minority against a dominant one, "
    "and put the counts in the explanation.\n"
    "- A row that would report something as missing: read the window for the sense, not only the words. A "
    "paraphrase, a pronoun, a merged or re-ordered clause carries the meaning too. in-verse (the meaning is there "
    "in other words): no finding. found_another_verse or split_across_verses: not an omission; keep it only as a "
    "Verse boundary row (Low or Medium) when the move changes the sense or breaks the verse numbering. not_found "
    "in the window or the chapter: keep it as missing and say in the explanation which verses were searched. A "
    "short verse next to a long one (x0.7 / x1.4) means content moved, not lost.\n"
    "Return one verdict for every row index you were given."
)


def rows_schema() -> dict[str, Any]:
    text = {"type": "string"}
    row = {
        "chapter": text, "verse": text,
        "issue_type": {"type": "string", "enum": list(ISSUE_TYPES)},
        "priority_category": text,
        "severity": {"type": "string", "enum": list(SEVERITIES)},
        "confidence": {"type": "string", "enum": list(CONFIDENCES)},
        "original": text, "suggested": text, "explanation": text, "reference_note": text,
        "decision_needed": {"type": "string", "enum": list(DECISIONS)},
        "evidence_check": {"type": "string", "enum": list(EVIDENCE_CHECKS)},
        "evidence_find": text,
    }
    return {
        "type": "object", "additionalProperties": False, "required": ["rows", "rejected"],
        "properties": {
            "rows": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": list(row), "properties": row}},
            "rejected": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["lead", "why"],
                "properties": {"lead": text, "why": text}}},
        },
    }


def verdicts_schema() -> dict[str, Any]:
    verdict = {
        "index": {"type": "integer"}, "keep": {"type": "boolean"},
        "issue_type": {"type": "string", "enum": list(ISSUE_TYPES)},
        "severity": {"type": "string", "enum": list(SEVERITIES)},
        "confidence": {"type": "string", "enum": list(CONFIDENCES)},
        "explanation": {"type": "string"}, "why": {"type": "string"},
    }
    return {
        "type": "object", "additionalProperties": False, "required": ["verdicts"],
        "properties": {"verdicts": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": list(verdict), "properties": verdict}}},
    }


# -- the reading plan ---------------------------------------------------------

def plan_chunks(chapter_sizes: dict[int, int], *, max_chapters: int = CHUNK_CHAPTERS,
                max_chars: int = CHUNK_CHARS) -> list[list[int]]:
    """Consecutive chapters grouped about three at a time, fewer when they are
    long: a chunk closes at `max_chapters`, or before the chapter that would
    take it past `max_chars`. A chapter longer than that is a chunk alone."""
    chunks: list[list[int]] = []
    current: list[int] = []
    size = 0
    for chapter in sorted(chapter_sizes):
        length = int(chapter_sizes[chapter] or 0)
        if current and (len(current) >= max_chapters or size + length > max_chars or chapter != current[-1] + 1):
            chunks.append(current)
            current, size = [], 0
        current.append(chapter)
        size += length
    if current:
        chunks.append(current)
    return chunks


def chunk_key(chunk: list[int]) -> str:
    return f"{chunk[0]}-{chunk[-1]}"


_REFERENCE_LINE = re.compile(r"^(\d+:\S+) R: (.*)$")


def reference_lines(both_output: str) -> str:
    """The reference half of `dump.py BOOK both C`: one `c:v text` line a verse."""
    out = []
    for line in both_output.splitlines():
        match = _REFERENCE_LINE.match(line)
        if match and match.group(2).strip() not in ("", "?"):
            out.append(f"{match.group(1)} {match.group(2).strip()}")
    return "\n".join(out)


def _clip(text: str, limit: int, what: str) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + f"\n[... {what} cut at {limit} characters ...]"


def book_block(book: str, leads: dict[str, str]) -> str:
    """The part of every request of a book that does not change from chunk to
    chunk: placed first, so it extends the cached prefix."""
    parts = [f"BOOK: {book}", "", "== LEADS FROM THE TOOLKIT'S TOOLS (the whole book; leads are not findings)"]
    for tool in ("sweep", "numchk", "terms"):
        said = leads.get(tool, "").strip()
        if said:
            parts.append(f"-- {tool}.py")
            parts.append(_clip(said, LEADS_CHARS, f"{tool} leads"))
    return "\n".join(parts)


def chunk_block(chunk: list[int], *, target: str, reference: str, reference_name: str, intro: str = "") -> str:
    span = f"chapter {chunk[0]}" if len(chunk) == 1 else f"chapters {chunk[0]} to {chunk[-1]}"
    parts: list[str] = []
    if intro.strip():
        parts += ["== INTRODUCTION (report its findings with chapter \"Intro\" and verse \"\")",
                  _clip(intro, INTRO_CHARS, "introduction"), ""]
    parts += [f"== TRANSLATION, {span} (each verse begins with its number; headings and footnotes as written)",
              target.strip(), ""]
    if reference.strip():
        parts += [f"== REFERENCE ({reference_name or 'reference'}), {span}", reference.strip()]
    else:
        parts += ["== REFERENCE", "No reference text is available for this book. Report only what the translation "
                  "itself shows; make no source-comparison finding."]
    return "\n".join(parts)


# -- rows ---------------------------------------------------------------------

def _one_line(value: Any) -> str:
    return " ".join(str(value or "").split())


def normalize_row(raw: Any, allowed_chapters: set[int] | None = None) -> dict[str, Any] | None:
    """One finding as the reader returned it, checked and tidied, or None when
    it cannot be a row. The schema already constrains the enumerated fields;
    this is for a provider that ignored it."""
    if not isinstance(raw, dict):
        return None
    original = _one_line(raw.get("original"))
    if not original:
        return None
    chapter_text = _one_line(raw.get("chapter"))
    if chapter_text.lower() in ("intro", "introduction"):
        chapter: Any = "Intro"
        verse: Any = ""
    else:
        if not chapter_text.isdigit():
            return None
        chapter = int(chapter_text)
        if allowed_chapters is not None and chapter not in allowed_chapters:
            return None
        verse_text = _one_line(raw.get("verse"))
        if not verse_text:
            return None
        verse = int(verse_text) if verse_text.isdigit() else verse_text

    def choice(key: str, allowed: tuple[str, ...], default: str) -> str:
        value = _one_line(raw.get(key))
        for option in allowed:
            if option.lower() == value.lower():
                return option
        return default

    check = choice("evidence_check", EVIDENCE_CHECKS, "none")
    return {
        "chapter": chapter, "verse": verse,
        "issueType": choice("issue_type", ISSUE_TYPES, "Reviewer decision"),
        "category": _one_line(raw.get("priority_category")) or "Review",
        "severity": choice("severity", SEVERITIES, "Low"),
        "confidence": choice("confidence", CONFIDENCES, "Medium"),
        "original": original,
        "suggested": _one_line(raw.get("suggested")),
        "explanation": _one_line(raw.get("explanation")),
        "referenceNote": _one_line(raw.get("reference_note")),
        "decisionNeeded": choice("decision_needed", DECISIONS, "Review"),
        "check": check,
        "find": _one_line(raw.get("evidence_find")) if check == "nearby" else "",
    }


def row_tuple(row: dict[str, Any]) -> tuple[Any, ...]:
    """The eleven fields of one `R(...)` call (templates/rows_template.py)."""
    return (row["chapter"], row["verse"], row["issueType"], row["category"], row["severity"], row["confidence"],
            row["original"], row["suggested"], row["explanation"], row["referenceNote"], row["decisionNeeded"])


def write_rows_file(path: Path, rows: list[dict[str, Any]], rejected: list[tuple[str, str]],
                    reviewed: str) -> None:
    """`rows_<book>.py`, the file `build.py` loads by executing it. Bridge
    writes every value through `repr()`: the file is data in Python's own
    notation, and nothing a model wrote is ever run."""
    lines = [
        "# Written by Bridge from findings its AI reader returned as data (tc_ai_bridge/proofreading.py).",
        "# Every value is a literal. Do not edit by hand: the next run overwrites it.",
        "ROWS = [",
    ]
    lines += [f"    {row_tuple(row)!r}," for row in rows]
    lines += ["]", "TYPE_NOTES = {}", f"REVIEWED = {reviewed!r}", "REJECTED = ["]
    lines += [f"    {(str(lead), str(why))!r}," for lead, why in rejected]
    lines += ["]", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    # A compiled copy of an earlier version of this file must not be loaded in
    # its place (see proofread_tool_main: same second, same length).
    shutil.rmtree(path.parent / "__pycache__", ignore_errors=True)
    path.write_text("\n".join(lines), encoding="utf-8")


_FAIL_COUNT = re.compile(r"'fail': (\d+)")


def build_failures(output: str, rows: list[dict[str, Any]]) -> tuple[int, list[int]]:
    """(the failure count `build.py` printed, the indexes of our rows it could
    not place). A failed row is recognised by the exact line the tool prints
    for it (`FAIL <chapter> <verse> <first 60 characters>`), not by parsing."""
    said = set(line.rstrip("\r") for line in output.splitlines() if line.startswith("FAIL "))
    failed = [i for i, row in enumerate(rows)
              if f"FAIL {row['chapter']} {row['verse']} {str(row['original'])[:60]}" in said]
    match = None
    for match in _FAIL_COUNT.finditer(output):
        pass
    return (int(match.group(1)) if match else (len(said) if said else -1)), failed


_SEVERITY_RANK = {"High": 0, "Medium": 1, "Low": 2}


def build_overlaps(output: str, rows: list[dict[str, Any]]) -> list[int]:
    """Indexes of our rows to drop so no two pins overlap in one verse.
    `build.py` prints `OVERLAP ((chapter, verse), <30 chars>, <30 chars>)` for
    a pair; an automatic row (double spaces, a minority spelling) is not among
    ours and wins, as SKILL.md says, and of two of ours the less severe goes."""
    drop: set[int] = set()
    for line in output.splitlines():
        if not line.startswith("OVERLAP "):
            continue
        try:
            (chapter, verse), first, second = ast.literal_eval(line[len("OVERLAP "):].strip())
        except (ValueError, SyntaxError, TypeError):
            continue
        ours: list[int] = []
        for selected in (first, second):
            wanted = _one_line(selected)
            for index, row in enumerate(rows):
                if index in drop or index in ours or str(row["chapter"]) != str(chapter):
                    continue
                if str(row["verse"]).split("-")[0] != str(verse).split("-")[0]:
                    continue
                words = _one_line(row["original"])
                if wanted and (words.startswith(wanted) or wanted.startswith(words)):
                    ours.append(index)
                    break
        if len(ours) == 1:
            drop.add(ours[0])
        elif len(ours) == 2:
            drop.add(max(ours, key=lambda i: (_SEVERITY_RANK.get(rows[i]["severity"], 3), len(rows[i]["original"]))))
    return sorted(drop)


def read_issues_csv(path: Path) -> list[dict[str, str]]:
    """The findings of one book as `deliver.py` wrote them: located, in
    reading order, automatic rows included."""
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        table = list(csv.reader(handle))
    return [dict(zip(CSV_FIELDS, line + [""] * (len(CSV_FIELDS) - len(line)))) for line in table[1:] if line]


def finding_id(book: str, row: dict[str, Any], occurrence: int) -> str:
    """Stable across runs for the same finding on the same words (gotcha 3):
    a note or a decision keyed to it must survive the book being read again."""
    key = "|".join([book.upper(), str(row.get("chapter", "")), str(row.get("verse", "")),
                    str(row.get("issueType", "")), str(row.get("original", "")), str(occurrence)])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]


def stored_rows(book: str, rows: list[dict[str, str]]) -> dict[str, list[dict[str, Any]]]:
    """chapter key ("intro" or the number) -> the rows Bridge keeps."""
    seen: dict[str, int] = {}
    by_chapter: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        chapter = str(row.get("chapter") or "").strip()
        key = "intro" if chapter.lower() == "intro" else chapter
        identity = "|".join([key, str(row.get("verse", "")), str(row.get("issueType", "")), str(row.get("original", ""))])
        occurrence = seen.get(identity, 0)
        seen[identity] = occurrence + 1
        by_chapter.setdefault(key, []).append({
            "id": finding_id(book, row, occurrence), "book": book.upper(), "chapter": chapter,
            "verse": str(row.get("verse") or ""), "issueType": str(row.get("issueType") or ""),
            "category": str(row.get("category") or ""), "severity": str(row.get("severity") or ""),
            "confidence": str(row.get("confidence") or ""), "original": str(row.get("original") or ""),
            "suggested": str(row.get("suggested") or ""), "explanation": str(row.get("explanation") or ""),
            "referenceNote": str(row.get("referenceNote") or ""),
            "decisionNeeded": str(row.get("decisionNeeded") or ""), "location": str(row.get("location") or ""),
            "anchor": str(row.get("anchor") or ""),
        })
    return by_chapter


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_severity = {name: 0 for name in SEVERITIES}
    by_type: dict[str, int] = {}
    for row in rows:
        severity = str(row.get("severity") or "")
        if severity in by_severity:
            by_severity[severity] += 1
        issue = str(row.get("issueType") or "Other")
        by_type[issue] = by_type.get(issue, 0) + 1
    return {"findings": len(rows), "bySeverity": by_severity, "byIssueType": dict(sorted(by_type.items()))}


# -- the estimate shown before a run ------------------------------------------

def estimate_tokens(text: bytes | str) -> int:
    """About four ASCII characters a token and about two tokens for every
    other character: the rule `ai_client.estimate_input_tokens` uses for the
    scripts Bridge works in. An estimate, and shown as one."""
    data = text if isinstance(text, str) else text.decode("utf-8", "replace")
    ascii_count = sum(1 for ch in data if ord(ch) < 128)
    return ascii_count // 4 + (len(data) - ascii_count) * 2 + 1


# Chapters per book, for the estimate only (the run itself asks the project).
_CHAPTER_COUNTS = dict(zip(TOOLKIT_BOOKS, (
    50, 40, 27, 36, 34, 24, 21, 4, 31, 24, 22, 25, 29, 36, 10, 13, 10, 42, 150, 31, 12, 8, 66, 52, 5,
    48, 12, 14, 3, 9, 1, 4, 7, 3, 3, 3, 2, 14, 4, 28, 16, 24, 21, 28, 16, 16, 13, 6, 6, 4, 4,
    5, 3, 6, 4, 3, 1, 13, 5, 5, 3, 5, 1, 1, 1, 22,
)))


def estimate_book(book: str, target_chars: int, target_tokens: int, reference_tokens: int,
                  standing_tokens: int) -> dict[str, int]:
    """Requests and tokens one book would take: its text and the reference
    once, the standing instructions and the leads with every request, and a
    second request for about a third of the chunks (the evidence round)."""
    by_chapters = -(-_CHAPTER_COUNTS.get(book.upper(), 1) // CHUNK_CHAPTERS)
    chunks = max(1, by_chapters, -(-int(target_chars) // CHUNK_CHARS))
    requests = chunks + max(1, chunks // 3)
    input_tokens = target_tokens + reference_tokens + requests * standing_tokens
    output_tokens = max(800, target_tokens // 6) + requests * 300
    return {"requests": requests, "inputTokens": input_tokens, "outputTokens": output_tokens,
            "cachedInputTokens": max(0, (requests - 1) * standing_tokens)}


# -- one book -----------------------------------------------------------------

Ask = Callable[[str, dict[str, Any], str, str], dict[str, Any]]


@dataclass
class BookOutcome:
    book: str
    rows: list[dict[str, str]] = field(default_factory=list)
    chunks: int = 0
    reported: int = 0          # rows the reader returned, before evidence and placing
    rejected: int = 0          # leads and rows set aside (house style, found nearby, ...)
    unplaced: int = 0          # rows build.py could not locate, dropped
    overlapping: int = 0       # rows dropped because their pin overlapped another
    notes: list[str] = field(default_factory=list)


def _load_checkpoint(path: Path, content_hash: str) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("hash") != content_hash or data.get("pipeline") != PIPELINE_VERSION:
        return {}
    chunks = data.get("chunks")
    return chunks if isinstance(chunks, dict) else {}


def _save_checkpoint(path: Path, content_hash: str, chunks: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"hash": content_hash, "pipeline": PIPELINE_VERSION, "chunks": chunks},
                                    ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


UNCHECKED_NOTES = {
    "count": "Not checked against house style: the whole-translation count of both forms could not be run.",
    "nearby": "Not checked against the neighbouring verses: the search for the meaning in them could not be run.",
}


def _mark_unchecked(row: dict[str, Any]) -> None:
    """A finding whose evidence check did not happen: say so in its
    explanation, and never leave it as a confident row nobody need look at."""
    if row.get("confidence") == "High":
        row["confidence"] = "Medium"
    if row.get("decisionNeeded") == "No":
        row["decisionNeeded"] = "Review"
    note = UNCHECKED_NOTES.get(str(row.get("check")), "")
    if note and note not in str(row.get("explanation") or ""):
        row["explanation"] = f"{row.get('explanation') or ''} {note}".strip()


def mostly_empty(verse_texts: Iterable[str]) -> bool:
    """More than half of a book's verses have no text. Such a book is not
    read: there is little to proofread, and the toolkit's `sweep.py` divides
    by the median length ratio, which is zero for it (see NOTICE.md)."""
    texts = [str(text or "").strip() for text in verse_texts]
    return not texts or sum(1 for text in texts if not text) * 2 > len(texts)


FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def spreadsheet_safe(value: Any) -> str:
    """A cell a spreadsheet will show as text: one that would be read as a
    formula is prefixed with an apostrophe, the rule Bridge's Paratext review
    export already follows (`paratext_review._csv_cell`). A finding's words
    come from a model or from the text, and either may begin with `=`."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_START) else text


def guard_delivered_files(folder: Path, book: str) -> list[str]:
    """Make one book's delivered CSV and workbook safe to open, and say which
    of the two had to be rewritten. `deliver.py` writes cells as they come: in
    the CSV a cell beginning with `=`, `+`, `-` or `@` is a formula to a
    spreadsheet, and in the workbook `openpyxl` stores one beginning with `=`
    as a formula. The toolkit's file is left as shared; Bridge rewrites what
    it delivered. The CSV gets the apostrophe prefix. In the workbook the cell
    keeps its words and becomes text; the Summary sheet's own formulas (the
    counts) are left alone. Bridge reads the findings from the CSV before
    this runs, so its stored rows carry no prefix."""
    rewritten: list[str] = []
    issues = folder / f"{book.upper()}_QA_Issues.csv"
    if issues.is_file():
        with issues.open(encoding="utf-8-sig", newline="") as handle:
            table = list(csv.reader(handle))
        if any(cell.startswith(FORMULA_START) for line in table for cell in line):
            with issues.open("w", encoding="utf-8-sig", newline="") as handle:
                csv.writer(handle).writerows([spreadsheet_safe(cell) for cell in line] for line in table)
            rewritten.append(issues.name)
    workbook = folder / f"{book.upper()}_QA_Report.xlsx"
    if workbook.is_file():
        from openpyxl import load_workbook  # only here: the engine never needs it otherwise

        loaded = load_workbook(workbook)
        changed = False
        for sheet in loaded.worksheets:
            if sheet.title == "Summary":
                continue
            for line in sheet.iter_rows():
                for cell in line:
                    if cell.data_type == "f":
                        cell.data_type = "s"
                        changed = True
        if changed:
            loaded.save(workbook)
            rewritten.append(workbook.name)
        loaded.close()
    return rewritten


def _read_chunk(book: str, chunk: list[int], *, tools: ToolRunner, ask: Ask, standing: str, block: str,
                reference_name: str, has_reference: bool, intro: str,
                cancelled: Callable[[], bool]) -> dict[str, Any]:
    """One chunk: the text, the reader's rows, the evidence the toolkit's
    tools give for the doubtful ones, and the reader's second look at those."""
    target = require(tools("dump", book, chunk[0], chunk[-1]))
    # `dump.py` ends a range at the next chapter line only when that line is
    # exactly `\c N` and a newline. Where it is not (a trailing space, say) the
    # tool prints from the first chapter to the end of the book, and every
    # request of the book would then carry most of the book. More chapter
    # lines than chapters asked for is that case: stop, and say why, rather
    # than pay for it. This counts the tool's own output; it parses nothing.
    if target.count("\\c ") > len(chunk):
        raise ProofreadingError(
            f"{book}: the toolkit could not cut chapters {chunk[0]} to {chunk[-1]} out of this book (its chapter "
            "lines are not in the form the toolkit expects), so the book was not sent.")
    reference = ""
    if has_reference:
        reference = "\n".join(reference_lines(require(tools("dump", book, "both", chapter))) for chapter in chunk)
    answer = ask("proofreading_rows", rows_schema(), standing,
                 block + "\n\n" + chunk_block(chunk, target=target, reference=reference,
                                              reference_name=reference_name, intro=intro))
    allowed = set(chunk)
    rows = [row for row in (normalize_row(raw, allowed) for raw in (answer.get("rows") or [])) if row is not None]
    if not intro.strip():
        rows = [row for row in rows if row["chapter"] != "Intro"]
    rejected = [[_one_line(item.get("lead")), _one_line(item.get("why"))]
                for item in (answer.get("rejected") or []) if isinstance(item, dict) and _one_line(item.get("lead"))]
    reported = len(rows)

    doubtful = [i for i, row in enumerate(rows) if row["check"] != "none"]
    nearby = [i for i in doubtful if rows[i]["check"] == "nearby" and rows[i]["chapter"] != "Intro" and has_reference]
    counted = [i for i in doubtful if rows[i]["check"] == "count"]
    evidence: dict[int, str] = {}
    decided: set[int] = set()
    dropped: set[int] = set()
    if counted and not cancelled():
        # One call for every counted form of the chunk. `q.py c` takes
        # patterns, so each form is escaped to be counted as written.
        forms: list[str] = []
        for i in counted:
            for form in (rows[i]["original"], rows[i]["suggested"]):
                if form and form not in forms:
                    forms.append(form)
        said = tools("q", "c", *[re.escape(form) for form in forms])
        counts: dict[str, str] = {}
        if said.ok:
            pieces = said.out.strip().split(" | ")
            if len(pieces) == len(forms):
                for form, piece in zip(forms, pieces):
                    counts[form] = piece.rsplit(": ", 1)[-1]
        for i in counted:
            row = rows[i]
            if row["original"] in counts:
                line = f"`{row['original']}` occurs {counts[row['original']]} times (whole translation / New Testament)"
                if row["suggested"] and row["suggested"] in counts:
                    line += f"; `{row['suggested']}` occurs {counts[row['suggested']]} times"
                evidence[i] = line + "."
    for i in nearby[:NEARBY_PER_CHUNK]:
        if cancelled():
            break
        row = rows[i]
        arguments: list[Any] = [book, f"{row['chapter']}:{str(row['verse']).split('-')[0]}", "--window", 3]
        if row["find"]:
            arguments += ["--find", re.escape(row["find"])]
        said = tools("nearby", *arguments)
        if said.ok:
            evidence[i] = said.out.strip()
    if evidence and not cancelled():
        listing = []
        for i in sorted(evidence):
            row = rows[i]
            listing.append(
                f"ROW {i}: {book} {row['chapter']}:{row['verse']} | {row['issueType']} | {row['severity']} | "
                f"original `{row['original']}` | suggested `{row['suggested']}`\n"
                f"your explanation: {row['explanation']}\nEVIDENCE:\n{evidence[i]}")
        verdicts = ask("proofreading_verdicts", verdicts_schema(), standing + "\n\n" + VERDICT_INSTRUCTIONS,
                       block + "\n\n== ROWS AWAITING A DECISION\n\n" + "\n\n".join(listing))
        for verdict in verdicts.get("verdicts") or []:
            if not isinstance(verdict, dict):
                continue
            try:
                index = int(verdict.get("index"))
            except (TypeError, ValueError):
                continue
            if index not in evidence:
                continue
            decided.add(index)
            row = rows[index]
            if verdict.get("keep") is False:
                dropped.add(index)
                rejected.append([f"{row['chapter']}:{row['verse']} {row['original']}",
                                 _one_line(verdict.get("why")) or "Set aside on the toolkit's evidence."])
                continue
            for key, allowed_values, field_name in (("issue_type", ISSUE_TYPES, "issueType"),
                                                    ("severity", SEVERITIES, "severity"),
                                                    ("confidence", CONFIDENCES, "confidence")):
                value = _one_line(verdict.get(key))
                if value in allowed_values:
                    row[field_name] = value
            explanation = _one_line(verdict.get("explanation"))
            if explanation:
                row["explanation"] = explanation
    # A row that asked for evidence and was never decided on it is still the
    # reader's first impression: the count or the search could not be run (the
    # tool failed, the book has no reference, the chunk asked for more searches
    # than are run), or the second answer left it out. SKILL.md says not to
    # report such a row unchecked, and dropping it would hide what the reader
    # saw, so it is kept and says so: never High confidence, always for review.
    for index in doubtful:
        if index not in decided and index not in dropped:
            _mark_unchecked(rows[index])
    rows = [row for i, row in enumerate(rows) if i not in dropped]
    return {"rows": rows, "rejected": rejected, "reported": reported}


def proofread_book(
    book: str, chapter_sizes: dict[int, int], *, paths: RunPaths, tools: ToolRunner, ask: Ask,
    language_label: str, reference_name: str, language_code: str, has_reference: bool, content_hash: str,
    base_offset: int = 0,
    cancelled: Callable[[], bool] = lambda: False,
    report: Callable[[str, int, int], None] = lambda stage, done, total: None,
) -> BookOutcome:
    """SKILL.md section 2, steps 2 to 6, for one book that is already staged.

    Leads, the whole book read chunk by chunk against the reference, the
    findings file, `build.py` until nothing fails, then `deliver.py` and
    `merge_notes.py`. A chunk that was read stays in the book's checkpoint, so
    a run stopped by a cancel or by a plan's limit does not pay for it twice.
    Raises `ProofreadingCancelled` at a step boundary after a cancel."""
    book = book.upper()
    outcome = BookOutcome(book=book)
    chunks = plan_chunks(chapter_sizes)
    total = len(chunks)
    outcome.chunks = total

    def stop() -> None:
        if cancelled():
            raise ProofreadingCancelled("Proofreading was cancelled.")

    report("Running the toolkit's checks", 0, total)
    # `sweep.py` can die part-way: its comparison with the reference divides
    # by the median length ratio and indexes the list of ratios, and neither is
    # guarded (NOTICE.md). What it printed before that is still leads, so the
    # book is read with those and says so, rather than not read at all.
    swept = tools("sweep", book)
    leads: dict[str, str] = {"sweep": swept.out}
    if not swept.ok:
        why = ((swept.err or "").strip().splitlines() or [f"exit code {swept.code}"])[-1]
        outcome.notes.append(f"The toolkit's sweep stopped early ({why}); the book was read with the leads it had "
                             "printed by then.")
    if has_reference:
        numbers = tools("numchk", book)
        leads["numchk"] = numbers.out if numbers.ok else ""
        if not numbers.ok:
            outcome.notes.append("The number check did not run for this book.")
    terms = tools("terms", book)
    if terms.ok:
        leads["terms"] = terms.out
    else:
        outcome.notes.append("Key terms: " + ((terms.err or terms.out).strip().splitlines() or ["not checked"])[-1])
    stop()
    intro = tools("dump", book, "intro")
    intro_text = intro.out if intro.ok else ""
    profile = load_profile(language_code)
    standing = instructions(language_label=language_label, reference_name=reference_name, profile=profile)
    block = book_block(book, leads)

    done = _load_checkpoint(paths.checkpoint(book), content_hash)
    for number, chunk in enumerate(chunks):
        stop()
        key = chunk_key(chunk)
        if key not in done:
            span = f"chapter {chunk[0]}" if len(chunk) == 1 else f"chapters {chunk[0]} to {chunk[-1]}"
            report(f"Reading {span}", number, total)
            done[key] = _read_chunk(
                book, chunk, tools=tools, ask=ask, standing=standing, block=block, reference_name=reference_name,
                has_reference=has_reference, intro=intro_text if number == 0 else "", cancelled=cancelled)
            stop()  # a chunk cut short by a cancel is not a finished chunk
            _save_checkpoint(paths.checkpoint(book), content_hash, done)
        report(f"Read {key}", number + 1, total)

    rows: list[dict[str, Any]] = []
    rejected: list[tuple[str, str]] = []
    for chunk in chunks:
        part = done.get(chunk_key(chunk)) or {}
        rows += [row for row in part.get("rows") or [] if isinstance(row, dict)]
        rejected += [(str(lead), str(why)) for lead, why in part.get("rejected") or []]
        outcome.reported += int(part.get("reported") or 0)

    report("Verifying every finding against the text", total, total)
    rows_path = paths.rows / f"rows_{book.lower()}.py"
    reviewed = ("whole book, every verse read against the reference, and the introduction" if has_reference
                else "whole book and the introduction; no reference text was available for this book")
    for _round in range(BUILD_ROUNDS):
        stop()
        write_rows_file(rows_path, rows, rejected, reviewed)
        built = require(tools("build", book))
        fail_count, failed = build_failures(built, rows)
        overlapping = [] if failed else build_overlaps(built, rows)
        if fail_count == 0 and not overlapping:
            break
        if fail_count < 0:
            raise ProofreadingError(f"{book}: the toolkit's verification step printed no result, so nothing was "
                                    "delivered for this book.")
        if fail_count != 0 and not failed:
            raise ProofreadingError(f"{book}: the toolkit could not place {fail_count} finding(s) and they could "
                                    "not be told apart, so nothing was delivered for this book.")
        for index in failed:
            row = rows[index]
            rejected.append((f"{row['chapter']}:{row['verse']} {row['original']}",
                             "The quoted words were not found in that place, so the finding was not reported."))
        for index in overlapping:
            row = rows[index]
            rejected.append((f"{row['chapter']}:{row['verse']} {row['original']}",
                             "It overlapped another finding on the same words; the other one was kept."))
        outcome.unplaced += len(failed)
        outcome.overlapping += len(overlapping)
        gone = set(failed) | set(overlapping)
        rows = [row for i, row in enumerate(rows) if i not in gone]
    else:
        raise ProofreadingError(f"{book}: the findings still did not verify after {BUILD_ROUNDS} rounds.")

    stop()
    report("Writing the workbook and the notes", total, total)
    require(tools("deliver", book, env={"PT_BASE_OFFSET": str(int(base_offset))}))
    merged = tools("merge_notes")
    if not merged.ok:
        outcome.notes.append("The cumulative notes file was not rebuilt.")
    outcome.rejected = len(rejected)
    # Read first, then make the files safe to open: the stored rows are the
    # findings as delivered, without a spreadsheet's apostrophe.
    outcome.rows = read_issues_csv(paths.book_output(book) / f"{book}_QA_Issues.csv")
    try:
        guard_delivered_files(paths.book_output(book), book)
    except Exception as exc:  # the findings are safe in Bridge; say the files were left as written
        outcome.notes.append(f"The delivered CSV and workbook could not be checked for formula cells ({exc}).")
    return outcome
