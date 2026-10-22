"""Read-only reader for a Paratext 9 project folder (#354).

Everything Bridge learns from a Paratext project comes through here: the
settings, which files are books, the small lookup files, and the Project Notes.
It is read-only by contract. No function in this module opens a file for
writing, and none descends into ``.hg`` -- a Paratext folder is a live
Mercurial working copy, and Send/Receive commits whatever is on disk.

USFM is read by ``usfm_parser``/``usfm_verse`` only (CLAUDE.md gotcha 14). The
one exception this module takes is the one that gotcha allows: it reads a
book file's ``\\id`` line to name the file when the naming pattern does not,
and checks that a ``\\c`` line exists. It parses nothing else of the text.

Notes are ``Notes_<User>.xml`` files in Paratext desktop's ``<CommentList>``
form, one per team member; a reply by another user lives in that user's file
under the same ``Thread`` id, so threads are merged across files. A file is
read as bytes between two stats (Paratext may be writing it) and parsed with
``iterparse``, clearing each ``Comment`` as it ends: one real notes file is
over 40 MB.
"""

from __future__ import annotations

import hashlib
import io
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, NamedTuple
from xml.etree import ElementTree

from .iso639 import ISO_639_1_TO_3
from .usfm_parser import UsfmParseError, decode_usfm_text

# Paratext's canon, in its own order (SIL.Scripture Canon.AllBookIds). The
# BooksPresent bit string in Settings.xml is indexed by this list.
PARATEXT_CANON: tuple[str, ...] = (
    "GEN", "EXO", "LEV", "NUM", "DEU", "JOS", "JDG", "RUT", "1SA", "2SA",
    "1KI", "2KI", "1CH", "2CH", "EZR", "NEH", "EST", "JOB", "PSA", "PRO",
    "ECC", "SNG", "ISA", "JER", "LAM", "EZK", "DAN", "HOS", "JOL", "AMO",
    "OBA", "JON", "MIC", "NAM", "HAB", "ZEP", "HAG", "ZEC", "MAL",
    "MAT", "MRK", "LUK", "JHN", "ACT", "ROM", "1CO", "2CO", "GAL", "EPH",
    "PHP", "COL", "1TH", "2TH", "1TI", "2TI", "TIT", "PHM", "HEB", "JAS",
    "1PE", "2PE", "1JN", "2JN", "3JN", "JUD", "REV",
    "TOB", "JDT", "ESG", "WIS", "SIR", "BAR", "LJE", "S3Y", "SUS", "BEL",
    "1MA", "2MA", "3MA", "4MA", "1ES", "2ES", "MAN", "PS2", "ODA", "PSS",
    "JSA", "JDB", "TBS", "SST", "DNT", "BLT",
    "XXA", "XXB", "XXC", "XXD", "XXE", "XXF", "XXG",
    "FRT", "BAK", "OTH", "3ES", "EZA", "5EZ", "6EZ",
    "INT", "CNC", "GLO", "TDX", "NDX",
    "DAG", "PS3", "2BA", "LBA", "JUB", "ENO", "1MQ", "2MQ", "3MQ", "REP", "4BA", "LAO",
)
_CANON_INDEX = {code: index for index, code in enumerate(PARATEXT_CANON)}

# Books that are not Scripture text: front/back matter, introductions,
# concordance, glossary, indexes and the extra-material slots.
PERIPHERAL_CODES = frozenset({
    "FRT", "BAK", "OTH", "INT", "CNC", "GLO", "TDX", "NDX",
    "XXA", "XXB", "XXC", "XXD", "XXE", "XXF", "XXG",
})

# Settings.xml <Versification> (Paratext's ScrVersType) to the schema names in
# versification.SCHEMAS.
VERSIFICATION_NAMES: dict[int, str] = {1: "org", 2: "lxx", 3: "vul", 4: "eng", 5: "rsc", 6: "rso"}

SCRIPTURE_SUFFIXES = (".sfm", ".usfm", ".ptx", ".txt")
_SNAPSHOT_RETRIES = 3
_SNAPSHOT_DELAY = 0.2


class ParatextReadError(RuntimeError):
    """A Paratext file could not be read into a stable, parseable snapshot."""


# ---------------------------------------------------------------------------
# Snapshots: bytes read between two equal stats
# ---------------------------------------------------------------------------

Signature = tuple[int, int]  # (size, mtime_ns)


def file_signature(path: Path) -> Signature | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return (stat.st_size, stat.st_mtime_ns)


def snapshot_bytes(path: Path, *, retries: int | None = None, delay: float | None = None,
                   check: Callable[[bytes], Any] | None = None) -> tuple[bytes, Signature, Any]:
    """The bytes of ``path``, read between two stats that agree.

    Paratext may be saving the file while Bridge reads it. When the stats
    differ, or ``check`` (a parser) raises on the bytes, the read is retried up
    to ``retries`` more times, ``delay`` seconds apart. Returns the bytes, their
    signature and ``check``'s result; raises :class:`ParatextReadError` when no
    attempt was stable."""
    retries = _SNAPSHOT_RETRIES if retries is None else retries
    delay = _SNAPSHOT_DELAY if delay is None else delay
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        if attempt:
            time.sleep(delay)
        before = file_signature(path)
        if before is None:
            raise ParatextReadError(f"{path.name} does not exist.")
        try:
            with open(path, "rb") as handle:
                raw = handle.read()
        except OSError as exc:
            last_error = exc
            continue
        if file_signature(path) != before or len(raw) != before[0]:
            last_error = ParatextReadError(f"{path.name} changed while it was being read.")
            continue
        try:
            parsed = check(raw) if check is not None else None
        except (ElementTree.ParseError, ValueError, ParatextReadError) as exc:
            last_error = exc
            continue
        return raw, before, parsed
    raise ParatextReadError(f"{path.name} could not be read: {last_error}")


def _xml_root(raw: bytes) -> ElementTree.Element:
    return ElementTree.fromstring(raw)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


# ---------------------------------------------------------------------------
# Settings.xml
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LanguageIso:
    raw: str
    code: str
    script: str
    region: str
    variant: str


def parse_language_iso(raw: str | None) -> LanguageIso:
    """Split Paratext's ``<LanguageIsoCode>`` (``code:script:region:variant``).

    ``code`` is the first part lower-cased when it is two or three ASCII
    letters, else ``""``: ``ta:::`` -> ``ta``, ``bhd:Deva:IN:`` -> ``bhd``,
    ``ory`` -> ``ory``. A two-letter code stays two letters here;
    :func:`language_fields` is where it becomes ISO 639-3."""
    value = (raw or "").strip()
    parts = (value.split(":") + ["", "", "", ""])[:4]
    code = parts[0].strip().lower()
    if not (2 <= len(code) <= 3 and code.isascii() and code.isalpha()):
        code = ""
    return LanguageIso(raw=value, code=code, script=parts[1].strip(), region=parts[2].strip(),
                       variant=parts[3].strip())


@dataclass(frozen=True)
class Naming:
    pre_part: str
    post_part: str
    book_name_form: str

    def to_json(self) -> dict[str, str]:
        return {"prePart": self.pre_part, "postPart": self.post_part, "bookNameForm": self.book_name_form}


@dataclass(frozen=True)
class ParatextSettings:
    folder: Path
    name: str
    full_name: str
    language_name: str
    language_iso: LanguageIso
    guid: str
    encoding: str
    versification: int | None
    versification_name: str
    naming: Naming
    books_present: frozenset[str]
    normalization: str
    left_to_right: bool | None
    stylesheet: str
    valid_characters: str
    invalid_characters: str
    valid_punctuation: str
    invalid_punctuation: str
    quotes: dict[str, str]
    repeatable_words: tuple[str, ...]
    non_repeatable_words: tuple[str, ...]
    biblical_terms_list: str
    sha256: str
    warnings: tuple[str, ...] = ()

    @property
    def language_code(self) -> str:
        return self.language_iso.code


def detect_paratext_folder(source: str | Path) -> Path | None:
    """``source`` itself, or the folder holding it, when that folder has a
    ``Settings.xml`` whose root is ``<ScriptureText>``; else None."""
    path = Path(source)
    for candidate in ((path,) if path.is_dir() else ()) + (path.parent,):
        settings = candidate / "Settings.xml"
        if not settings.is_file():
            continue
        try:
            raw, _, root = snapshot_bytes(settings, retries=1, check=_xml_root)
        except ParatextReadError:
            continue
        if _local(root.tag) == "ScriptureText":
            return candidate
    return None


_QUOTE_KEYS = ("Quotes", "InnerQuotes", "InnerInnerQuotes", "Continuer", "InnerContinuer",
               "InnerInnerContinuer")


def _settings_from_bytes(folder: Path, raw: bytes, root: ElementTree.Element) -> ParatextSettings:
    if _local(root.tag) != "ScriptureText":
        raise ParatextReadError("Settings.xml root is not <ScriptureText>.")
    values: dict[str, str] = {}
    naming_attrs: dict[str, str] | None = None
    for child in root:
        tag = _local(child.tag)
        if tag == "Naming":
            naming_attrs = dict(child.attrib)
            continue
        # The first occurrence wins, as Paratext writes each element once.
        values.setdefault(tag, child.text or "")

    def text(name: str) -> str:
        return values.get(name, "").strip()

    warnings: list[str] = []
    if naming_attrs is not None:
        naming = Naming(naming_attrs.get("PrePart", ""), naming_attrs.get("PostPart", ""),
                        naming_attrs.get("BookNameForm", ""))
    else:
        naming = Naming(text("FileNamePrePart"), text("FileNamePostPart"), text("FileNameBookNameForm"))

    bits = text("BooksPresent")
    books_present: frozenset[str] = frozenset()
    if bits:
        if len(bits) != len(PARATEXT_CANON) or set(bits) - {"0", "1"}:
            warnings.append(f"BooksPresent has {len(bits)} characters, not {len(PARATEXT_CANON)}; ignored.")
        else:
            books_present = frozenset(code for code, bit in zip(PARATEXT_CANON, bits) if bit == "1")

    versification: int | None
    try:
        versification = int(text("Versification")) if text("Versification") else None
    except ValueError:
        versification = None
        warnings.append(f"Versification {text('Versification')!r} is not a number.")

    ltr_raw = text("LeftToRight").lower()
    left_to_right = True if ltr_raw in {"t", "true"} else False if ltr_raw in {"f", "false"} else None

    return ParatextSettings(
        folder=folder,
        name=text("Name"),
        full_name=text("FullName"),
        language_name=text("Language"),
        language_iso=parse_language_iso(values.get("LanguageIsoCode")),
        guid=text("Guid"),
        encoding=text("Encoding"),
        versification=versification,
        versification_name=VERSIFICATION_NAMES.get(versification or 0, ""),
        naming=naming,
        books_present=books_present,
        normalization=text("NormalizationForm"),
        left_to_right=left_to_right,
        stylesheet=text("StyleSheet"),
        valid_characters=values.get("ValidCharacters", ""),
        invalid_characters=values.get("InvalidCharacters", ""),
        valid_punctuation=values.get("ValidPunctuation", ""),
        invalid_punctuation=values.get("InvalidPunctuation", ""),
        quotes={key: values[key] for key in _QUOTE_KEYS if values.get(key)},
        repeatable_words=tuple(text("RepeatableWords").split()),
        non_repeatable_words=tuple(text("NonRepeatableWords").split()),
        biblical_terms_list=text("BiblicalTermsListSetting"),
        sha256=hashlib.sha256(raw).hexdigest(),
        warnings=tuple(warnings),
    )


def read_settings(folder: str | Path) -> ParatextSettings | None:
    """The parsed ``Settings.xml`` of a Paratext folder, or None when there is
    none or it is not a ``<ScriptureText>`` document."""
    folder = Path(folder)
    path = folder / "Settings.xml"
    if not path.is_file():
        return None
    try:
        raw, _, root = snapshot_bytes(path, check=_xml_root)
        return _settings_from_bytes(folder, raw, root)
    except ParatextReadError:
        return None


def language_fields(settings: ParatextSettings) -> dict[str, str]:
    """Import metadata from the settings: ``languageId`` as ISO 639-3 (a
    two-letter code mapped through the import screen's own table, #308; an
    unknown code is "" so the reviewer picks), ``languageName`` from
    ``<Language>``, ``languageDirection`` from ``<LeftToRight>`` when set."""
    code = settings.language_iso.code
    language_id = ISO_639_1_TO_3.get(code, "") if len(code) == 2 else code
    direction = "" if settings.left_to_right is None else ("ltr" if settings.left_to_right else "rtl")
    return {"languageId": language_id, "languageName": settings.language_name, "languageDirection": direction}


def link_block(folder: str | Path, settings: ParatextSettings, *, linked_at: str | None = None) -> dict[str, Any]:
    """The ``paratext`` block an import records on each book of a collection."""
    return {
        "schemaVersion": 1,
        "guid": settings.guid,
        "folder": str(Path(folder)),
        "name": settings.name,
        "fullName": settings.full_name,
        "versification": settings.versification_name or None,
        "naming": settings.naming.to_json(),
        "booksPresent": sorted(settings.books_present, key=lambda code: _CANON_INDEX[code]),
        "settingsSha256": settings.sha256,
        "linkedAt": linked_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------------------
# Which files are books
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScriptureScan:
    files: list[tuple[str, Path]]                 # (book code, path), canon order
    skipped: list[tuple[Path, str]]               # (path, reason)
    warnings: list[str]


def _decoded_head(path: Path) -> str:
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
        return decode_usfm_text(raw, path.name)
    except (OSError, UsfmParseError):
        return ""


def _id_code(text: str) -> str:
    """The book code on the ``\\id`` line (the only USFM this module reads)."""
    for line in text.lstrip("\ufeff").split("\n", 20)[:20]:
        stripped = line.strip()
        if stripped.startswith("\\id ") or stripped.startswith("\\id\t"):
            parts = stripped[3:].split()
            return parts[0].upper() if parts else ""
    return ""


def _has_chapter_line(text: str) -> bool:
    return any(line.lstrip().startswith(("\\c ", "\\c\t")) for line in text.split("\n"))


def _code_from_name(name: str, naming: Naming) -> str:
    form = naming.book_name_form
    position = form.upper().find("MAT")
    if position < 0:
        return ""
    middle = name[len(naming.pre_part):len(name) - len(naming.post_part)]
    if len(middle) != len(form):
        return ""
    return middle[position:position + 3].upper()


def _matches_naming(name: str, naming: Naming) -> bool:
    lower = name.lower()
    return (lower.startswith(naming.pre_part.lower()) and lower.endswith(naming.post_part.lower())
            and len(name) > len(naming.pre_part) + len(naming.post_part))


def scripture_candidates(folder: str | Path, settings: ParatextSettings) -> ScriptureScan:
    """The book files of a Paratext folder, read from its naming pattern.

    Only the folder itself is listed (never ``PrintDraft/``, ``shared/`` or
    ``.hg``). Paratext's own ``RegExBackupN.sfm``, ``*.BAK`` copies, peripheral
    books (INT, GLO, FRT, ...) and files without a ``\\c`` are skipped with a
    reason, never an error. An empty result carries a warning so the caller
    can fall back to its own scan."""
    folder = Path(folder)
    naming = settings.naming
    files: dict[str, Path] = {}
    skipped: list[tuple[Path, str]] = []
    warnings: list[str] = []
    for path in sorted((p for p in folder.iterdir() if p.is_file()), key=lambda p: p.name.lower()):
        name = path.name
        lower = name.lower()
        if lower.startswith("regexbackup"):
            if lower.endswith(SCRIPTURE_SUFFIXES):
                skipped.append((path, "Paratext find-and-replace backup (RegExBackup)"))
            continue
        if not _matches_naming(name, naming):
            continue
        if lower.endswith(".bak"):
            skipped.append((path, "Paratext backup copy (.BAK)"))
            continue
        code = _code_from_name(name, naming)
        if code in PERIPHERAL_CODES:
            skipped.append((path, f"peripheral book {code}, not Scripture text"))
            continue
        text = _decoded_head(path)
        if not code:
            code = _id_code(text)
        if not code:
            skipped.append((path, "no book code in the file name or the \\id line"))
            continue
        if code in PERIPHERAL_CODES:
            skipped.append((path, f"peripheral book {code}, not Scripture text"))
            continue
        if code not in _CANON_INDEX:
            skipped.append((path, f"unknown book code {code}"))
            continue
        if not text:
            skipped.append((path, "not UTF-8 or UTF-16 USFM text"))
            continue
        if not _has_chapter_line(text):
            skipped.append((path, "no \\c chapter marker"))
            continue
        if code in files:
            skipped.append((path, f"second file for {code} (kept {files[code].name})"))
            continue
        files[code] = path
    if settings.books_present:
        for code in sorted(settings.books_present - set(files) - PERIPHERAL_CODES, key=_CANON_INDEX.get):
            warnings.append(f"{code} is marked present in Settings.xml but has no book file.")
        for code in sorted(set(files) - settings.books_present, key=_CANON_INDEX.get):
            warnings.append(f"{code} has a book file but is not marked present in Settings.xml.")
    if not files:
        warnings.append("No book files match the project's naming pattern.")
    ordered = sorted(files.items(), key=lambda item: _CANON_INDEX[item[0]])
    return ScriptureScan(files=ordered, skipped=skipped, warnings=warnings)


# ---------------------------------------------------------------------------
# References
# ---------------------------------------------------------------------------

class ParatextRef(NamedTuple):
    book: str
    chapter: int
    verse: str          # the anchor: first numeric component ("1" for "1-3")
    verse_text: str     # the verse part as written ("1-3", "4a")

    def __str__(self) -> str:
        return f"{self.book} {self.chapter}:{self.verse_text}"


_REF_RE = re.compile(r"^\s*([0-9A-Z]{3})\s+(\d+):(\d+)([^/\s]*)(?:/\d+)?\s*$", re.IGNORECASE)


def parse_ref(value: str | None) -> ParatextRef | None:
    """``MAT 4:4``, ``JDG 1:0``, ``GEN 1:1-3`` (a trailing ``/4`` versification
    tag is dropped). None when it is not a reference."""
    match = _REF_RE.match(value or "")
    if not match:
        return None
    book = match.group(1).upper()
    if book not in _CANON_INDEX:
        return None
    verse = str(int(match.group(3)))
    return ParatextRef(book, int(match.group(2)), verse, verse + match.group(4))


def ref_from_bbbcccvvv(value: int | str) -> ParatextRef | None:
    """A ``BBBCCCVVV`` integer reference (book number in Paratext canon order)."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    book, rest = divmod(number, 1_000_000)
    chapter, verse = divmod(rest, 1000)
    if not 1 <= book <= len(PARATEXT_CANON):
        return None
    return ParatextRef(PARATEXT_CANON[book - 1], chapter, str(verse), str(verse))


# ---------------------------------------------------------------------------
# Small lookup files
# ---------------------------------------------------------------------------

def _read_root(path: Path, expected: str) -> ElementTree.Element | None:
    if not path.is_file():
        return None
    try:
        _, _, root = snapshot_bytes(path, check=_xml_root)
    except ParatextReadError:
        return None
    return root if _local(root.tag) == expected else None


def read_book_names(folder: str | Path) -> dict[str, dict[str, str]]:
    """``BookNames.xml``: {code: {abbr, short, long}}."""
    root = _read_root(Path(folder) / "BookNames.xml", "BookNames")
    if root is None:
        return {}
    return {
        book.get("code", "").upper(): {key: book.get(key, "") for key in ("abbr", "short", "long")}
        for book in root.iter("book") if book.get("code")
    }


def read_comment_tags(folder: str | Path) -> dict[str, dict[str, Any]]:
    """``CommentTags.xml``: {id: {name, icon, creatorResolve}}."""
    root = _read_root(Path(folder) / "CommentTags.xml", "TagList")
    if root is None:
        return {}
    return {
        tag.get("Id", ""): {"name": tag.get("Name", ""), "icon": tag.get("Icon", ""),
                            "creatorResolve": tag.get("CreatorResolve", "").lower() == "true"}
        for tag in root.iter("Tag") if tag.get("Id")
    }


def read_user_access(folder: str | Path) -> list[dict[str, Any]]:
    """``ProjectUserAccess.xml``: one entry per project member."""
    root = _read_root(Path(folder) / "ProjectUserAccess.xml", "ProjectUserAccess")
    if root is None:
        return []
    users = []
    for user in root.iter("User"):
        books = user.find("Books")
        users.append({
            "userName": user.get("UserName", ""),
            "role": (user.findtext("Role") or "").strip(),
            "firstUser": user.get("FirstUser", "").lower() == "true",
            "unregistered": user.get("UnregisteredUser", "").lower() == "true",
            "allBooks": (user.findtext("AllBooks") or "").strip().lower() == "true",
            "books": [b.get("Id", "").upper() for b in books if b.get("Id")] if books is not None else [],
        })
    return users


# ---------------------------------------------------------------------------
# Project Notes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NoteComment:
    thread: str
    user: str
    verse_ref: str
    language: str
    date: str
    file: str
    order: int
    selected_text: str = ""
    start_position: int = 0
    context_before: str = ""
    context_after: str = ""
    status: str = ""
    type: str = ""
    conflict_type: str = ""
    verse: str = ""
    assigned_user: str | None = None    # None: element absent; "": unassigned
    reply_to_user: str = ""
    hidden: bool = False
    contents: str = ""
    tags_added: tuple[str, ...] = ()
    tags_removed: tuple[str, ...] = ()
    biblical_term_id: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "thread": self.thread, "user": self.user, "verseRef": self.verse_ref, "language": self.language,
            "date": self.date, "file": self.file, "order": self.order, "selectedText": self.selected_text,
            "startPosition": self.start_position, "contextBefore": self.context_before,
            "contextAfter": self.context_after, "status": self.status, "type": self.type,
            "conflictType": self.conflict_type, "verse": self.verse, "assignedUser": self.assigned_user,
            "replyToUser": self.reply_to_user, "hidden": self.hidden, "contents": self.contents,
            "tagsAdded": list(self.tags_added), "tagsRemoved": list(self.tags_removed),
            "biblicalTermId": self.biblical_term_id,
        }

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> "NoteComment":
        return cls(
            thread=value["thread"], user=value["user"], verse_ref=value["verseRef"], language=value["language"],
            date=value["date"], file=value["file"], order=value["order"], selected_text=value["selectedText"],
            start_position=value["startPosition"], context_before=value["contextBefore"],
            context_after=value["contextAfter"], status=value["status"], type=value["type"],
            conflict_type=value["conflictType"], verse=value["verse"], assigned_user=value["assignedUser"],
            reply_to_user=value["replyToUser"], hidden=value["hidden"], contents=value["contents"],
            tags_added=tuple(value["tagsAdded"]), tags_removed=tuple(value["tagsRemoved"]),
            biblical_term_id=value["biblicalTermId"],
        )


def _flatten_contents(element: ElementTree.Element | None) -> str:
    """``<Contents>`` as plain text: one line per ``<p>``, inline markup
    (``<bold>``, ``<span>``, ...) reduced to its text."""
    if element is None:
        return ""
    lines: list[str] = []
    buffer: list[str] = [element.text or ""]
    for child in element:
        if _local(child.tag) == "p":
            lines.append("".join(buffer))
            lines.append("".join(child.itertext()))
            buffer = [child.tail or ""]
        else:
            buffer.append("".join(child.itertext()))
            buffer.append(child.tail or "")
    lines.append("".join(buffer))
    return "\n".join(line.strip() for line in lines if line.strip())


def _tag_ids(element: ElementTree.Element | None) -> tuple[str, ...]:
    if element is None or not (element.text or "").strip():
        return ()
    return tuple(part.strip() for part in element.text.split(",") if part.strip())


def _comment_from_element(element: ElementTree.Element, file: str, order: int) -> NoteComment:
    def text(tag: str) -> str:
        return element.findtext(tag) or ""

    assigned = element.find("AssignedUser")
    try:
        start = int(text("StartPosition").strip() or 0)
    except ValueError:
        start = 0
    return NoteComment(
        thread=element.get("Thread", ""), user=element.get("User", ""), verse_ref=element.get("VerseRef", ""),
        language=element.get("Language", ""), date=element.get("Date", ""), file=file, order=order,
        selected_text=text("SelectedText"), start_position=start, context_before=text("ContextBefore"),
        context_after=text("ContextAfter"), status=text("Status").strip(), type=text("Type").strip(),
        conflict_type=text("ConflictType").strip(), verse=text("Verse"),
        assigned_user=None if assigned is None else (assigned.text or "").strip(),
        reply_to_user=text("ReplyToUser").strip(),
        hidden=text("HideInTextWindow").strip().lower() == "true",
        contents=_flatten_contents(element.find("Contents")),
        tags_added=_tag_ids(element.find("TagAdded")), tags_removed=_tag_ids(element.find("TagRemoved")),
        biblical_term_id=text("BiblicalTermId").strip(),
    )


def iter_comments(source: str | Path | bytes, *, file: str = "") -> Iterator[NoteComment]:
    """Every ``<Comment>`` of a ``<CommentList>`` notes file, in file order.

    ``source`` is a path or the file's bytes. Parsed with ``iterparse``; each
    comment is cleared once read. A document whose root is not
    ``<CommentList>`` (Bridge's own Notes 1.1 companion file, for one) yields
    nothing. Raises ``ElementTree.ParseError`` on malformed XML."""
    if isinstance(source, bytes):
        stream: Any = io.BytesIO(source)
        name = file
    else:
        stream = open(Path(source), "rb")
        name = file or Path(source).name
    try:
        root: ElementTree.Element | None = None
        order = 0
        for event, element in ElementTree.iterparse(stream, events=("start", "end")):
            if root is None:
                root = element
                if _local(root.tag) != "CommentList":
                    return
                continue
            if event == "end" and element.tag == "Comment":
                yield _comment_from_element(element, name, order)
                order += 1
                element.clear()
    finally:
        stream.close()


def comment_list_root(raw: bytes) -> str:
    """The root tag of a notes file, read from its first start event."""
    for _, element in ElementTree.iterparse(io.BytesIO(raw), events=("start",)):
        return _local(element.tag)
    return ""


def _date_key(value: str) -> float:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return float("inf")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


@dataclass
class NoteThread:
    id: str
    kind: str                       # note | conflict | biblicalTerm
    ref: ParatextRef | None
    verse_ref: str
    selected_text: str
    comments: list[NoteComment]
    status: str                     # last non-empty comment Status ("" = never set)
    assigned_user: str
    tags: tuple[str, ...]
    hidden: bool
    users: tuple[str, ...]

    @property
    def deleted(self) -> bool:
        return self.status == "deleted"

    @property
    def resolved(self) -> bool:
        return self.status == "done"

    def summary_json(self) -> dict[str, Any]:
        first, last = self.comments[0], self.comments[-1]
        return {
            "id": self.id, "kind": self.kind, "verseRef": self.verse_ref,
            "book": self.ref.book if self.ref else "", "chapter": self.ref.chapter if self.ref else None,
            "verse": self.ref.verse if self.ref else "", "selectedText": self.selected_text,
            "status": self.status, "deleted": self.deleted, "resolved": self.resolved,
            "assignedUser": self.assigned_user, "tags": list(self.tags), "hidden": self.hidden,
            "users": list(self.users), "commentCount": len(self.comments),
            "firstDate": first.date, "lastDate": last.date, "lastUser": last.user,
            "firstContents": first.contents,
        }


def _fold_thread(thread_id: str, comments: list[NoteComment]) -> NoteThread:
    comments.sort(key=lambda c: (_date_key(c.date), c.file, c.order))
    first = comments[0]
    status = ""
    assigned = ""
    hidden = first.hidden
    tags: list[str] = []
    users: list[str] = []
    conflict = False
    for comment in comments:
        if comment.status:
            status = comment.status
        if comment.assigned_user is not None:
            assigned = comment.assigned_user
        hidden = comment.hidden
        for tag in comment.tags_added:
            if tag not in tags:
                tags.append(tag)
        for tag in comment.tags_removed:
            if tag in tags:
                tags.remove(tag)
        if comment.user and comment.user not in users:
            users.append(comment.user)
        conflict = conflict or comment.type == "conflict"
    kind = "biblicalTerm" if thread_id.startswith("BT_") else "conflict" if conflict else "note"
    return NoteThread(
        id=thread_id, kind=kind, ref=parse_ref(first.verse_ref), verse_ref=first.verse_ref,
        selected_text=first.selected_text, comments=comments, status=status, assigned_user=assigned,
        tags=tuple(tags), hidden=hidden, users=tuple(users),
    )


@dataclass
class NotesIndex:
    threads: dict[str, NoteThread]
    files: dict[str, tuple[int, int, str]]          # name -> (size, mtime_ns, sha256)
    skipped_files: dict[str, str] = field(default_factory=dict)   # name -> reason
    by_ref: dict[str, dict[str, dict[str, list[str]]]] = field(default_factory=dict)
    counts: dict[str, dict[str, dict[str, dict[str, int]]]] = field(default_factory=dict)
    unanchored: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)          # name -> parse seconds
    stale_files: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.by_ref and self.threads:
            self._index()

    def _index(self) -> None:
        self.by_ref, self.counts, self.unanchored = {}, {}, []
        for thread in sorted(self.threads.values(), key=lambda t: (_date_key(t.comments[0].date), t.id)):
            if thread.ref is None:
                self.unanchored.append(thread.id)
                continue
            book, chapter, verse = thread.ref.book, str(thread.ref.chapter), thread.ref.verse
            self.by_ref.setdefault(book, {}).setdefault(chapter, {}).setdefault(verse, []).append(thread.id)
            if thread.deleted:
                continue
            cell = self.counts.setdefault(book, {}).setdefault(chapter, {}).setdefault(verse, {"open": 0, "total": 0})
            cell["total"] += 1
            if not thread.resolved:
                cell["open"] += 1

    def threads_for(self, book: str, chapter: int | str, verse: str | None = None, *,
                    include_deleted: bool = False) -> list[NoteThread]:
        chapters = self.by_ref.get(book.upper(), {}).get(str(chapter), {})
        verses = [str(verse)] if verse is not None else sorted(chapters, key=lambda v: int(v) if v.isdigit() else 0)
        found = [self.threads[tid] for v in verses for tid in chapters.get(v, [])]
        return found if include_deleted else [t for t in found if not t.deleted]

    @property
    def fingerprint(self) -> str:
        return files_fingerprint({name: (size, mtime) for name, (size, mtime, _) in self.files.items()})

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "files": {name: list(value) for name, value in self.files.items()},
            "skippedFiles": dict(self.skipped_files),
            "comments": [c.to_json() for t in self.threads.values() for c in t.comments],
        }

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> "NotesIndex":
        if value.get("schemaVersion") != 1:
            raise ValueError("Unsupported notes index schema.")
        grouped: dict[str, list[NoteComment]] = {}
        for item in value["comments"]:
            comment = NoteComment.from_json(item)
            grouped.setdefault(comment.thread, []).append(comment)
        return cls(
            threads={tid: _fold_thread(tid, comments) for tid, comments in grouped.items()},
            files={name: (int(v[0]), int(v[1]), str(v[2])) for name, v in value["files"].items()},
            skipped_files=dict(value.get("skippedFiles", {})),
        )


def files_fingerprint(signatures: dict[str, Signature]) -> str:
    """A digest of (name, size, mtime_ns) over a set of files."""
    digest = hashlib.sha256()
    for name in sorted(signatures):
        size, mtime = signatures[name]
        digest.update(f"{name}\0{size}\0{mtime}\n".encode("utf-8"))
    return digest.hexdigest()


def notes_files(folder: str | Path) -> list[Path]:
    """The ``Notes_*.xml`` files of a project folder (not ``*.BAK``)."""
    return sorted((p for p in Path(folder).glob("Notes_*.xml") if p.is_file()), key=lambda p: p.name.lower())


def notes_signatures(folder: str | Path) -> dict[str, Signature]:
    out = {}
    for path in notes_files(folder):
        signature = file_signature(path)
        if signature is not None:
            out[path.name] = signature
    return out


def _parse_notes_bytes(raw: bytes, name: str) -> list[NoteComment] | None:
    if comment_list_root(raw) != "CommentList":
        return None
    return list(iter_comments(raw, file=name))


def build_notes_index(folder: str | Path, *, previous: NotesIndex | None = None) -> NotesIndex:
    """Every Paratext note thread of the project, merged across user files.

    A file whose (size, mtime) matches ``previous`` reuses its comments; the
    rest are read as stable snapshots. A file that cannot be read stably keeps
    its comments from ``previous`` and is listed in ``stale_files``."""
    folder = Path(folder)
    previous_comments: dict[str, list[NoteComment]] = {}
    if previous is not None:
        for thread in previous.threads.values():
            for comment in thread.comments:
                previous_comments.setdefault(comment.file, []).append(comment)
    by_thread: dict[str, list[NoteComment]] = {}
    files: dict[str, tuple[int, int, str]] = {}
    skipped: dict[str, str] = {}
    timings: dict[str, float] = {}
    stale: list[str] = []
    for path in notes_files(folder):
        name = path.name
        signature = file_signature(path)
        old = previous.files.get(name) if previous is not None else None
        started = time.perf_counter()
        if previous is not None and old is not None and signature == old[:2]:
            comments = previous_comments.get(name, [])
            files[name] = old
            if name in previous.skipped_files:
                skipped[name] = previous.skipped_files[name]
        else:
            try:
                raw, signature, comments = snapshot_bytes(path, check=lambda b, n=name: _parse_notes_bytes(b, n))
            except ParatextReadError as exc:
                if old is not None:
                    stale.append(name)
                    files[name] = old
                    comments = previous_comments.get(name, [])
                else:
                    skipped[name] = str(exc)
                    continue
            else:
                files[name] = (signature[0], signature[1], hashlib.sha256(raw).hexdigest())
                if comments is None:
                    skipped[name] = "not a <CommentList> notes file"
                    comments = []
        timings[name] = time.perf_counter() - started
        for comment in comments:
            if comment.thread:
                by_thread.setdefault(comment.thread, []).append(comment)
    threads = {tid: _fold_thread(tid, comments) for tid, comments in by_thread.items()}
    return NotesIndex(threads=threads, files=files, skipped_files=skipped, timings=timings, stale_files=stale)


# ---------------------------------------------------------------------------
# A folder reader that memoizes on file signatures
# ---------------------------------------------------------------------------

class ParatextFolderReader:
    """Memoized read access to one Paratext folder.

    Each accessor re-reads its file only when its (size, mtime_ns) changed.
    When a changed file cannot be read stably (Paratext mid-save, or a parse
    error), the previous parse is kept and marked stale in :meth:`status`."""

    def __init__(self, folder: str | Path) -> None:
        self.folder = Path(folder)
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[Any, Any]] = {}
        self._stale: dict[str, str] = {}

    def _memo(self, key: str, signature: Any, build: Callable[[], Any]) -> Any:
        with self._lock:
            cached = self._cache.get(key)
        if cached is not None and cached[0] == signature:
            return cached[1]
        try:
            value = build()
        except ParatextReadError as exc:
            if cached is None:
                raise
            with self._lock:
                self._stale[key] = str(exc)
            return cached[1]
        with self._lock:
            self._cache[key] = (signature, value)
            self._stale.pop(key, None)
        return value

    def settings(self) -> ParatextSettings | None:
        path = self.folder / "Settings.xml"

        def build() -> ParatextSettings | None:
            if not path.is_file():
                return None
            raw, _, root = snapshot_bytes(path, check=_xml_root)
            return _settings_from_bytes(self.folder, raw, root)

        return self._memo("settings", file_signature(path), build)

    def book_names(self) -> dict[str, dict[str, str]]:
        return self._memo("bookNames", file_signature(self.folder / "BookNames.xml"),
                          lambda: read_book_names(self.folder))

    def comment_tags(self) -> dict[str, dict[str, Any]]:
        return self._memo("commentTags", file_signature(self.folder / "CommentTags.xml"),
                          lambda: read_comment_tags(self.folder))

    def user_access(self) -> list[dict[str, Any]]:
        return self._memo("userAccess", file_signature(self.folder / "ProjectUserAccess.xml"),
                          lambda: read_user_access(self.folder))

    def notes_index(self) -> NotesIndex:
        fingerprint = files_fingerprint(notes_signatures(self.folder))
        with self._lock:
            cached = self._cache.get("notes")
        if cached is not None and cached[0] == fingerprint:
            return cached[1]
        index = build_notes_index(self.folder, previous=cached[1] if cached is not None else None)
        with self._lock:
            # A stale file kept its previous comments; caching under no
            # fingerprint makes the next call try that file again.
            self._cache["notes"] = (None if index.stale_files else fingerprint, index)
            if index.stale_files:
                self._stale["notes"] = ", ".join(index.stale_files)
            else:
                self._stale.pop("notes", None)
        return index

    def status(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {key: {"stale": key in self._stale, "error": self._stale.get(key, "")}
                    for key in self._cache}
