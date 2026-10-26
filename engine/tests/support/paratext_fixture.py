"""A synthetic Paratext 9 project folder for tests (#354).

Writes the element shapes Paratext 9.5 writes -- ``Settings.xml`` with either
or both naming forms, book files named by the pattern, ``RegExBackupN.sfm``
and ``*.BAK`` traps, peripheral books, and ``Notes_<User>.xml`` files in
``<CommentList>`` form with children in Paratext's order -- from synthetic
text only. Nothing here is copied from a real project.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET

from tc_ai_bridge.paratext_notes import COMMENT_CHILD_ORDER
from tc_ai_bridge.paratext_project import PARATEXT_CANON

# Paratext's file-name book numbers: 01-39 OT, 41-67 NT, A*/B* peripherals.
_PERIPHERAL_NUMBERS = {"FRT": "A0", "BAK": "A1", "OTH": "A2", "INT": "A7", "CNC": "A8", "GLO": "A9",
                       "TDX": "B0", "NDX": "B1"}

DEFAULT_GUID = "5e1f0c2a9b8d7e6f5a4b3c2d1e0f9a8b7c6d5e4f"


def book_number(code: str) -> str:
    if code in _PERIPHERAL_NUMBERS:
        return _PERIPHERAL_NUMBERS[code]
    index = PARATEXT_CANON.index(code)
    return f"{index + 1:02d}" if index < 39 else f"{index + 2:02d}" if index < 66 else f"{index + 2}"


def simple_book(code: str, chapters: int = 1, verses: int = 2, word: str = "synthetic") -> str:
    lines = [f"\\id {code} Synthetic test book", f"\\h {code.title()}"]
    for chapter in range(1, chapters + 1):
        lines.append(f"\\c {chapter}")
        lines.append("\\p")
        for verse in range(1, verses + 1):
            lines.append(f"\\v {verse} {word} {code} {chapter}:{verse}.")
    return "\n".join(lines) + "\n"


def _text(parent: ET.Element, tag: str, value: Any) -> ET.Element:
    element = ET.SubElement(parent, tag)
    if value is not None and value != "":
        element.text = str(value)
    return element


def _write_xml(path: Path, root: ET.Element, *, bom: bool = True) -> None:
    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode")
    prefix = "﻿" if bom else ""
    path.write_text(prefix + '<?xml version="1.0" encoding="utf-8"?>\n' + body + "\n", encoding="utf-8")


def settings_xml(*, name: str, full_name: str, language: str, language_iso: str, guid: str,
                 naming: str, pre: str, post: str, form: str, books_present: Iterable[str],
                 versification: int = 4, extra: dict[str, str] | None = None) -> ET.Element:
    root = ET.Element("ScriptureText")
    present = set(books_present)
    fields = [
        ("Name", name), ("FullName", full_name), ("Encoding", "65001"), ("Language", language),
        ("LanguageIsoCode", language_iso), ("Guid", guid), ("Versification", str(versification)),
        ("StyleSheet", "usfm.sty"), ("NormalizationForm", "NFC"),
        ("BooksPresent", "".join("1" if code in present else "0" for code in PARATEXT_CANON)),
        ("Quotes", "<< >>"), ("InnerQuotes", "< >"),
        ("ValidCharacters", "a b c"), ("InvalidCharacters", "~"),
        ("ValidPunctuation", "._ ,_"), ("InvalidPunctuation", "_."),
        ("RepeatableWords", "very so"), ("NonRepeatableWords", "the"),
        ("BiblicalTermsListSetting", "Major::BiblicalTerms.xml"),
    ]
    if naming in ("element", "both"):
        fields += [("FileNamePrePart", pre), ("FileNamePostPart", post), ("FileNameBookNameForm", form)]
    for key, value in fields + list((extra or {}).items()):
        _text(root, key, value)
    if naming in ("attribute", "both"):
        ET.SubElement(root, "Naming", {"PrePart": pre, "PostPart": post, "BookNameForm": form})
    return root


def comment_element(user: str, spec: dict[str, Any]) -> ET.Element:
    """One ``<Comment>``. ``spec`` keys: thread, verse_ref, date (required);
    selected_text, start_position, context_before, context_after, status, type,
    conflict_type, verse, assigned_user, reply_to_user, hidden, contents (str or
    list of paragraph strings, ``**x**`` becomes ``<bold>x</bold>``),
    tags_added, tags_removed, language, user."""
    comment = ET.Element("Comment", {
        "Thread": spec["thread"], "User": spec.get("user", user), "VerseRef": spec["verse_ref"],
        "Language": spec.get("language", "ta"), "Date": spec["date"],
    })
    values = {
        "SelectedText": spec.get("selected_text", ""), "StartPosition": spec.get("start_position", 0),
        "ContextBefore": spec.get("context_before", ""), "ContextAfter": spec.get("context_after", ""),
        "Status": spec.get("status", ""), "Type": spec.get("type", ""),
        "ConflictType": spec.get("conflict_type", ""), "Verse": spec.get("verse", ""),
        "ReplyToUser": spec.get("reply_to_user", ""),
        "HideInTextWindow": "true" if spec.get("hidden") else "false",
    }
    for tag in COMMENT_CHILD_ORDER:
        if tag in values:
            _text(comment, tag, values[tag])
        elif tag == "AssignedUser" and "assigned_user" in spec:
            _text(comment, tag, spec["assigned_user"])
        elif tag == "Contents" and "contents" in spec:
            _contents(comment, spec["contents"])
        elif tag == "TagAdded" and spec.get("tags_added"):
            _text(comment, tag, ",".join(spec["tags_added"]))
        elif tag == "TagRemoved" and spec.get("tags_removed"):
            _text(comment, tag, ",".join(spec["tags_removed"]))
    return comment


def _inline(parent: ET.Element, text: str) -> None:
    parts = text.split("**")
    parent.text = parts[0]
    last: ET.Element | None = None
    for index, part in enumerate(parts[1:], start=1):
        if index % 2:
            last = ET.SubElement(parent, "bold")
            last.text = part
        elif last is not None:
            last.tail = part


def _contents(comment: ET.Element, value: str | list[str]) -> None:
    contents = ET.SubElement(comment, "Contents")
    if isinstance(value, str):
        _inline(contents, value)
        return
    for paragraph in value:
        _inline(ET.SubElement(contents, "p"), paragraph)


def write_notes_file(folder: Path, user: str, comments: list[dict[str, Any]]) -> Path:
    root = ET.Element("CommentList")
    for spec in comments:
        root.append(comment_element(user, spec))
    path = folder / f"Notes_{user}.xml"
    _write_xml(path, root)
    return path


def build_paratext_project(
    root: Path,
    name: str = "TSTP",
    *,
    books: dict[str, str] | None = None,
    peripherals: dict[str, str] | None = None,
    naming: str = "both",
    pre: str = "",
    post: str | None = None,
    form: str = "41MAT",
    books_present_extra: Iterable[str] = (),
    books_present: Iterable[str] | None = None,
    regex_backups: int = 0,
    bak: bool = False,
    language: str = "Tamil",
    language_iso: str = "ta:::",
    guid: str = DEFAULT_GUID,
    full_name: str = "Synthetic Test Project",
    versification: int = 4,
    settings_extra: dict[str, str] | None = None,
    notes: dict[str, list[dict[str, Any]]] | None = None,
    book_names: dict[str, tuple[str, str, str]] | None = None,
    comment_tags: dict[str, str] | None = None,
    users: list[dict[str, Any]] | None = None,
) -> Path:
    """A Paratext-shaped folder ``root/name``. ``books`` maps a code to its
    USFM (default: TIT and PHM); ``books_present`` defaults to the books and
    peripherals plus ``books_present_extra``."""
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    books = {"TIT": simple_book("TIT"), "PHM": simple_book("PHM")} if books is None else books
    peripherals = peripherals or {}
    post = f"{name}.SFM" if post is None else post

    def file_name(code: str) -> str:
        middle = form.replace("41", book_number(code)).replace("MAT", code)
        return f"{pre}{middle}{post}"

    for code, text in {**books, **peripherals}.items():
        path = folder / file_name(code)
        path.write_text(text, encoding="utf-8")
        if bak:
            (folder / (path.name + ".BAK")).write_text(text, encoding="utf-8")
    first = next(iter(books), "TIT")
    for number in range(1, regex_backups + 1):
        # Paratext writes these as UTF-16 and they start with a real \id line.
        (folder / f"RegExBackup{number}.sfm").write_text(f"\\id {first}\n\\c 1\n", encoding="utf-16")
    present = set(books) | set(peripherals) | set(books_present_extra) if books_present is None else set(books_present)
    _write_xml(folder / "Settings.xml", settings_xml(
        name=name, full_name=full_name, language=language, language_iso=language_iso, guid=guid,
        naming=naming, pre=pre, post=post, form=form, books_present=present, versification=versification,
        extra=settings_extra,
    ))
    for user, comments in (notes or {}).items():
        write_notes_file(folder, user, comments)
    if book_names:
        names = ET.Element("BookNames")
        for code, (abbr, short, long) in book_names.items():
            ET.SubElement(names, "book", {"code": code, "abbr": abbr, "short": short, "long": long})
        _write_xml(folder / "BookNames.xml", names)
    if comment_tags:
        tags = ET.Element("TagList")
        for tag_id, tag_name in comment_tags.items():
            ET.SubElement(tags, "Tag", {"Id": tag_id, "Name": tag_name, "Icon": "01flag1", "CreatorResolve": "false"})
        _text(tags, "LastUsedID", max(comment_tags, key=int))
        _write_xml(folder / "CommentTags.xml", tags)
    if users:
        access = ET.Element("ProjectUserAccess", {"PeerSharing": "true"})
        for user in users:
            element = ET.SubElement(access, "User", {
                "UserName": user["name"], "FirstUser": "true" if user.get("first") else "false",
                "UnregisteredUser": "false",
            })
            _text(element, "Role", user.get("role", "Translator"))
            _text(element, "AllBooks", "true" if user.get("all_books") else "false")
            books_el = ET.SubElement(element, "Books")
            for code in user.get("books", ()):
                ET.SubElement(books_el, "Book", {"Id": code})
        _write_xml(folder / "ProjectUserAccess.xml", access)
    return folder
