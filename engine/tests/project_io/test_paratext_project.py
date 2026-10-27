"""The read-only Paratext 9 folder reader (#354), against synthetic folders."""

from __future__ import annotations

import builtins
import hashlib
import io
import json
import os
from pathlib import Path
from xml.etree import ElementTree

import pytest

from tc_ai_bridge import paratext_project as pp
from tc_ai_bridge.versification import SCHEMAS
from tests.support.paratext_fixture import (
    DEFAULT_GUID,
    build_paratext_project,
    simple_book,
    write_notes_file,
)


def _tree_digest(folder: Path) -> dict[str, str]:
    return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


# --------------------------------------------------------------------------- canon


def test_canon_positions_match_paratext():
    assert len(pp.PARATEXT_CANON) == 123
    assert len(set(pp.PARATEXT_CANON)) == 123
    assert pp.PARATEXT_CANON[0] == "GEN"
    assert pp.PARATEXT_CANON[38] == "MAL"
    assert pp.PARATEXT_CANON[39] == "MAT"
    assert pp.PARATEXT_CANON[65] == "REV"
    # 1-based bits 107 and 109 are INT and GLO (verified on a real project).
    assert pp.PARATEXT_CANON[106] == "INT"
    assert pp.PARATEXT_CANON[108] == "GLO"
    assert pp.PERIPHERAL_CODES <= set(pp.PARATEXT_CANON)


def test_versification_names_are_bridge_schemas():
    assert set(pp.VERSIFICATION_NAMES.values()) == set(SCHEMAS)
    assert pp.VERSIFICATION_NAMES[4] == "eng"


@pytest.mark.parametrize(("raw", "code", "script", "region"), [
    ("ta:::", "ta", "", ""),
    ("bhd:Deva:IN:", "bhd", "Deva", "IN"),
    ("xx:::", "xx", "", ""),
    ("xxx:Latn::", "xxx", "Latn", ""),
    ("ory", "ory", "", ""),
    ("", "", "", ""),
    ("abcd:::", "", "", ""),
    ("TA:::", "ta", "", ""),
])
def test_parse_language_iso(raw, code, script, region):
    parsed = pp.parse_language_iso(raw)
    assert (parsed.code, parsed.script, parsed.region) == (code, script, region)
    assert parsed.raw == raw


# --------------------------------------------------------------------------- settings


def test_detect_paratext_folder(tmp_path):
    folder = build_paratext_project(tmp_path)
    assert pp.detect_paratext_folder(folder) == folder
    assert pp.detect_paratext_folder(folder / "57TITTSTP.SFM") == folder
    other = tmp_path / "plain"
    other.mkdir()
    (other / "Settings.xml").write_text("<Settings/>", encoding="utf-8")
    assert pp.detect_paratext_folder(other) is None
    assert pp.detect_paratext_folder(tmp_path / "missing") is None


def test_read_settings_fields(tmp_path):
    folder = build_paratext_project(tmp_path, books_present_extra=("LUK",))
    settings = pp.read_settings(folder)
    assert settings is not None
    assert settings.name == "TSTP"
    assert settings.full_name == "Synthetic Test Project"
    assert settings.language_name == "Tamil"
    assert settings.language_code == "ta"
    assert settings.guid == DEFAULT_GUID
    assert settings.encoding == "65001"
    assert (settings.versification, settings.versification_name) == (4, "eng")
    assert settings.naming == pp.Naming("", "TSTP.SFM", "41MAT")
    assert settings.books_present == {"TIT", "PHM", "LUK"}
    assert settings.normalization == "NFC"
    assert settings.left_to_right is None
    assert settings.stylesheet == "usfm.sty"
    assert settings.quotes == {"Quotes": "<< >>", "InnerQuotes": "< >"}
    assert settings.repeatable_words == ("very", "so")
    assert settings.non_repeatable_words == ("the",)
    assert settings.valid_characters == "a b c"
    assert settings.invalid_characters == "~"
    assert settings.biblical_terms_list == "Major::BiblicalTerms.xml"
    assert settings.sha256 == hashlib.sha256((folder / "Settings.xml").read_bytes()).hexdigest()
    assert settings.warnings == ()


@pytest.mark.parametrize("naming", ["element", "attribute", "both"])
def test_naming_in_either_form(tmp_path, naming):
    folder = build_paratext_project(tmp_path, naming=naming, post="X.SFM")
    assert pp.read_settings(folder).naming == pp.Naming("", "X.SFM", "41MAT")


def test_attribute_naming_wins_over_elements(tmp_path):
    folder = build_paratext_project(tmp_path, naming="attribute", post="A.SFM",
                                    settings_extra={"FileNamePostPart": "E.SFM"})
    assert pp.read_settings(folder).naming.post_part == "A.SFM"


def test_wrong_length_books_present_is_ignored_with_a_warning(tmp_path):
    folder = build_paratext_project(tmp_path)
    path = folder / "Settings.xml"
    text = path.read_text(encoding="utf-8-sig")
    start = text.index("<BooksPresent>") + len("<BooksPresent>")
    end = text.index("</BooksPresent>")
    path.write_text(text[:start] + "1" * 66 + text[end:], encoding="utf-8")
    settings = pp.read_settings(folder)
    assert settings.books_present == frozenset()
    assert any("BooksPresent" in warning for warning in settings.warnings)


def test_read_settings_without_scripture_text_root(tmp_path):
    (tmp_path / "Settings.xml").write_text("<Other/>", encoding="utf-8")
    assert pp.read_settings(tmp_path) is None
    assert pp.read_settings(tmp_path / "nowhere") is None


@pytest.mark.parametrize(("iso", "language_id"), [
    ("ta:::", "tam"), ("sa:::", "san"), ("bhd:Deva:IN:", "bhd"), ("qq:::", ""), ("ory", "ory"),
])
def test_language_fields(tmp_path, iso, language_id):
    folder = build_paratext_project(tmp_path, language_iso=iso, language="Somelang",
                                    settings_extra={"LeftToRight": "F"})
    fields = pp.language_fields(pp.read_settings(folder))
    assert fields == {"languageId": language_id, "languageName": "Somelang", "languageDirection": "rtl"}


def test_link_block(tmp_path):
    folder = build_paratext_project(tmp_path, books_present_extra=("MAT",))
    settings = pp.read_settings(folder)
    block = pp.link_block(folder, settings, linked_at="2026-10-22T00:00:00+00:00")
    assert block == {
        "schemaVersion": 1, "guid": DEFAULT_GUID, "folder": str(folder), "name": "TSTP",
        "fullName": "Synthetic Test Project", "versification": "eng",
        "naming": {"prePart": "", "postPart": "TSTP.SFM", "bookNameForm": "41MAT"},
        "booksPresent": ["MAT", "TIT", "PHM"], "settingsSha256": settings.sha256,
        "linkedAt": "2026-10-22T00:00:00+00:00",
    }
    json.dumps(block)


# --------------------------------------------------------------------------- scan


def test_scan_skips_backups_and_peripherals_with_reasons(tmp_path):
    folder = build_paratext_project(tmp_path, regex_backups=2, bak=True,
                                    peripherals={"INT": "\\id INT\n\\ip Introduction only.\n"})
    scan = pp.scripture_candidates(folder, pp.read_settings(folder))
    assert [(code, path.name) for code, path in scan.files] == [("TIT", "57TITTSTP.SFM"), ("PHM", "58PHMTSTP.SFM")]
    reasons = {path.name: reason for path, reason in scan.skipped}
    assert set(reasons) == {"RegExBackup1.sfm", "RegExBackup2.sfm", "A7INTTSTP.SFM"}
    assert "RegExBackup" in reasons["RegExBackup1.sfm"]
    assert "peripheral" in reasons["A7INTTSTP.SFM"]
    assert all(not path.name.endswith(".BAK") for _, path in scan.files)
    assert scan.warnings == []


def test_scan_bak_matching_the_pattern_is_skipped(tmp_path):
    # Only reachable when the pattern has no extension of its own.
    folder = build_paratext_project(tmp_path, pre="TS", post="", form="41MAT")
    (folder / "TS57TIT.BAK").write_text(simple_book("TIT"), encoding="utf-8")
    scan = pp.scripture_candidates(folder, pp.read_settings(folder))
    assert "TS57TIT.BAK" in {p.name for p, _ in scan.skipped}
    assert [code for code, _ in scan.files] == ["TIT", "PHM"]


def test_scan_compares_books_present(tmp_path):
    folder = build_paratext_project(tmp_path, books_present=("TIT", "LUK"))
    scan = pp.scripture_candidates(folder, pp.read_settings(folder))
    assert [code for code, _ in scan.files] == ["TIT", "PHM"]
    assert scan.warnings == [
        "LUK is marked present in Settings.xml but has no book file.",
        "PHM has a book file but is not marked present in Settings.xml.",
    ]


def test_scan_skips_a_file_with_no_chapter_marker(tmp_path):
    folder = build_paratext_project(tmp_path, books={"TIT": simple_book("TIT"), "PHM": "\\id PHM\n\\p no chapters\n"})
    scan = pp.scripture_candidates(folder, pp.read_settings(folder))
    assert [code for code, _ in scan.files] == ["TIT"]
    assert [(p.name, r) for p, r in scan.skipped] == [("58PHMTSTP.SFM", "no \\c chapter marker")]


def test_scan_reads_the_id_line_when_the_form_has_no_book_code(tmp_path):
    folder = build_paratext_project(tmp_path, form="41", post="-T.SFM")
    assert sorted(p.name for p in folder.glob("*.SFM")) == ["57-T.SFM", "58-T.SFM"]
    scan = pp.scripture_candidates(folder, pp.read_settings(folder))
    assert [code for code, _ in scan.files] == ["TIT", "PHM"]


def test_scan_never_descends_into_subfolders(tmp_path):
    folder = build_paratext_project(tmp_path)
    for sub in ("PrintDraft", ".hg", "shared"):
        (folder / sub).mkdir()
        (folder / sub / "41MATTSTP.SFM").write_text(simple_book("MAT"), encoding="utf-8")
    scan = pp.scripture_candidates(folder, pp.read_settings(folder))
    assert [code for code, _ in scan.files] == ["TIT", "PHM"]


def test_scan_with_no_match_warns_for_fallback(tmp_path):
    folder = build_paratext_project(tmp_path, books={})
    scan = pp.scripture_candidates(folder, pp.read_settings(folder))
    assert scan.files == []
    assert scan.warnings == ["No book files match the project's naming pattern."]


def test_scan_without_a_naming_pattern_matches_nothing(tmp_path):
    folder = build_paratext_project(tmp_path, naming="none")
    scan = pp.scripture_candidates(folder, pp.read_settings(folder))
    assert (scan.files, scan.skipped) == ([], [])
    assert scan.warnings == ["Settings.xml names no book file pattern."]


def test_scan_second_file_for_a_book_is_skipped(tmp_path):
    folder = build_paratext_project(tmp_path, form="41", post="-T.SFM")
    (folder / "99-T.SFM").write_text(simple_book("TIT"), encoding="utf-8")
    scan = pp.scripture_candidates(folder, pp.read_settings(folder))
    assert [code for code, _ in scan.files] == ["TIT", "PHM"]
    assert [p.name for p, _ in scan.skipped] == ["99-T.SFM"]


# --------------------------------------------------------------------------- refs


@pytest.mark.parametrize(("value", "expected"), [
    ("MAT 4:4", ("MAT", 4, "4", "4")),
    ("JDG 1:0", ("JDG", 1, "0", "0")),
    ("GEN 1:1-3", ("GEN", 1, "1", "1-3")),
    ("1SA 3:4a", ("1SA", 3, "4", "4a")),
    ("mat 4:4/4", ("MAT", 4, "4", "4")),
    ("XYZ 1:1", None),
    ("MAT 4", None),
    ("", None),
    (None, None),
])
def test_parse_ref(value, expected):
    parsed = pp.parse_ref(value)
    assert (tuple(parsed) if parsed else None) == expected


def test_ref_from_bbbcccvvv():
    assert tuple(pp.ref_from_bbbcccvvv(40004004)) == ("MAT", 4, "4", "4")
    assert tuple(pp.ref_from_bbbcccvvv("1001001")) == ("GEN", 1, "1", "1")
    assert pp.ref_from_bbbcccvvv(999001001) is None
    assert pp.ref_from_bbbcccvvv("x") is None


# --------------------------------------------------------------------------- small files


def test_book_names_comment_tags_and_users(tmp_path):
    folder = build_paratext_project(
        tmp_path,
        book_names={"TIT": ("Ti", "Titus", "The Letter to Titus")},
        comment_tags={"1": "To Do", "3": "Accuracy"},
        users=[{"name": "User A", "role": "Administrator", "first": True, "all_books": True},
               {"name": "User B", "role": "Translator", "books": ["TIT"]}],
    )
    assert pp.read_book_names(folder) == {"TIT": {"abbr": "Ti", "short": "Titus", "long": "The Letter to Titus"}}
    assert pp.read_comment_tags(folder) == {
        "1": {"name": "To Do", "icon": "01flag1", "creatorResolve": False},
        "3": {"name": "Accuracy", "icon": "01flag1", "creatorResolve": False},
    }
    assert pp.read_user_access(folder) == [
        {"userName": "User A", "role": "Administrator", "firstUser": True, "unregistered": False,
         "allBooks": True, "books": []},
        {"userName": "User B", "role": "Translator", "firstUser": False, "unregistered": False,
         "allBooks": False, "books": ["TIT"]},
    ]
    empty = build_paratext_project(tmp_path, "EMPTY")
    assert (pp.read_book_names(empty), pp.read_comment_tags(empty), pp.read_user_access(empty)) == ({}, {}, [])


# --------------------------------------------------------------------------- notes

NOTES = {
    "User A": [
        {"thread": "t1", "verse_ref": "TIT 1:2", "date": "2026-01-01T10:00:00.1234567+05:30",
         "selected_text": "word", "status": "todo", "contents": ["First **bold** para", "Second para"],
         "assigned_user": "User B", "tags_added": ["1"]},
        {"thread": "t2", "verse_ref": "TIT 1:2", "date": "2026-01-02T10:00:00+05:30",
         "status": "deleted", "contents": "resolved in Paratext"},
        {"thread": "BT_λόγος", "verse_ref": "TIT 1:1", "date": "2026-01-03T10:00:00+05:30",
         "status": "todo", "contents": "term note", "hidden": True},
        {"thread": "t4", "verse_ref": "PHM 1:1-3", "date": "2026-01-04T10:00:00+05:30",
         "type": "conflict", "status": "todo", "contents": "conflict"},
    ],
    "User B": [
        # A reply in another user's file, earlier in the file but later in time.
        {"thread": "t1", "verse_ref": "TIT 1:2", "date": "2026-01-01T06:00:00+00:00",
         "status": "", "contents": "reply", "reply_to_user": "User A",
         "tags_added": ["3"], "tags_removed": ["1"], "assigned_user": ""},
        {"thread": "t5", "verse_ref": "TIT 1:2", "date": "2026-01-05T10:00:00+05:30",
         "status": "todo", "contents": "open"},
        {"thread": "t5", "verse_ref": "TIT 1:2", "date": "2026-01-06T10:00:00+05:30",
         "status": "done", "contents": "resolved"},
    ],
}


def test_iter_comments_reads_every_child(tmp_path):
    folder = build_paratext_project(tmp_path, notes={"User A": NOTES["User A"][:1]})
    [comment] = list(pp.iter_comments(folder / "Notes_User A.xml"))
    assert comment.thread == "t1"
    assert comment.user == "User A"
    assert comment.verse_ref == "TIT 1:2"
    assert comment.selected_text == "word"
    assert comment.status == "todo"
    assert comment.assigned_user == "User B"
    assert comment.contents == "First bold para\nSecond para"
    assert comment.tags_added == ("1",)
    assert comment.file == "Notes_User A.xml"
    assert comment.hidden is False


def test_iter_comments_inline_markup_and_absent_elements(tmp_path):
    write_notes_file(tmp_path, "U", [{"thread": "x", "verse_ref": "TIT 1:1", "date": "2026-01-01T00:00:00Z",
                                      "contents": "one **two** three"}])
    [comment] = list(pp.iter_comments(tmp_path / "Notes_U.xml"))
    assert comment.contents == "one two three"
    assert comment.assigned_user is None
    assert comment.tags_removed == ()


def test_iter_comments_ignores_a_notes_11_document():
    raw = b'<?xml version="1.0"?><notes version="1.1"><thread id="a"><comment/></thread></notes>'
    assert list(pp.iter_comments(raw)) == []
    assert pp.comment_list_root(raw) == "notes"


def test_iter_comments_on_malformed_xml_raises():
    with pytest.raises(ElementTree.ParseError):
        list(pp.iter_comments(b"<CommentList><Comment Thread='a'>"))


def test_build_notes_index_merges_users_and_folds_status(tmp_path):
    folder = build_paratext_project(tmp_path, notes=NOTES)
    (folder / "Notes_AI_Suggestion.xml").write_text('<notes version="1.1"/>', encoding="utf-8")
    index = pp.build_notes_index(folder)

    assert set(index.threads) == {"t1", "t2", "BT_λόγος", "t4", "t5"}
    assert index.skipped_files == {"Notes_AI_Suggestion.xml": "not a <CommentList> notes file"}
    assert set(index.files) == {"Notes_User A.xml", "Notes_User B.xml", "Notes_AI_Suggestion.xml"}

    t1 = index.threads["t1"]
    # 06:00 UTC is 11:30 +05:30, after User A's 10:00 +05:30 comment.
    assert [c.user for c in t1.comments] == ["User A", "User B"]
    assert t1.status == "todo"                      # an empty Status leaves it unchanged
    assert t1.assigned_user == ""                   # explicitly unassigned by the reply
    assert t1.tags == ("3",)                        # 1 added then removed, 3 added
    assert t1.users == ("User A", "User B")
    assert t1.kind == "note"
    assert t1.selected_text == "word"
    assert index.threads["t2"].resolved             # Paratext writes a resolve as "deleted"
    assert index.threads["BT_λόγος"].kind == "biblicalTerm"
    assert index.threads["BT_λόγος"].hidden
    assert index.threads["t4"].kind == "conflict"
    assert index.threads["t4"].ref.verse == "1"
    assert index.threads["t5"].resolved

    assert index.by_ref["TIT"]["1"]["2"] == ["t1", "t2", "t5"]
    assert index.counts == {
        "TIT": {"1": {"1": {"open": 1, "total": 1}, "2": {"open": 1, "total": 3}}},
        "PHM": {"1": {"1": {"open": 1, "total": 1}}},
    }
    assert [t.id for t in index.threads_for("TIT", 1, "2")] == ["t1", "t2", "t5"]
    assert [t.id for t in index.threads_for("tit", "1")] == ["BT_λόγος", "t1", "t2", "t5"]
    assert index.unanchored == []
    summary = t1.summary_json()
    assert summary["commentCount"] == 2 and summary["lastUser"] == "User B"
    json.dumps(summary, ensure_ascii=False)


def test_notes_index_json_round_trip(tmp_path):
    folder = build_paratext_project(tmp_path, notes=NOTES)
    index = pp.build_notes_index(folder)
    back = pp.NotesIndex.from_json(json.loads(json.dumps(index.to_json(), ensure_ascii=False)))
    assert back.counts == index.counts
    assert back.by_ref == index.by_ref
    assert back.files == index.files
    assert back.fingerprint == index.fingerprint
    assert {tid: t.comments for tid, t in back.threads.items()} == {tid: t.comments for tid, t in index.threads.items()}
    with pytest.raises(ValueError):
        pp.NotesIndex.from_json({"schemaVersion": 99})


def test_build_notes_index_reuses_unchanged_files(tmp_path, monkeypatch):
    folder = build_paratext_project(tmp_path, notes=NOTES)
    first = pp.build_notes_index(folder)
    read: list[str] = []
    real = pp.snapshot_bytes

    def counting(path, **kwargs):
        read.append(path.name)
        return real(path, **kwargs)

    monkeypatch.setattr(pp, "snapshot_bytes", counting)
    write_notes_file(folder, "User B", NOTES["User B"][:1] + [
        {"thread": "t6", "verse_ref": "PHM 1:2", "date": "2026-02-01T00:00:00Z", "status": "todo", "contents": "new"}])
    os.utime(folder / "Notes_User B.xml", ns=(1, 1))
    second = pp.build_notes_index(folder, previous=first)
    assert read == ["Notes_User B.xml"]
    assert "t6" in second.threads and "t5" not in second.threads
    assert [c.user for c in second.threads["t1"].comments] == ["User A", "User B"]


def test_snapshot_retries_when_the_file_changes_mid_read(tmp_path, monkeypatch):
    path = tmp_path / "Notes_U.xml"
    path.write_bytes(b"<CommentList/>")
    real = pp.file_signature
    calls = {"n": 0}

    def flaky(p):
        calls["n"] += 1
        signature = real(p)
        # The second stat of the first attempt sees a different file.
        return (signature[0], signature[1] + 1) if calls["n"] == 2 else signature

    monkeypatch.setattr(pp, "file_signature", flaky)
    raw, signature, root = pp.snapshot_bytes(path, delay=0, check=pp.comment_list_root)
    assert raw == b"<CommentList/>" and root == "CommentList"
    assert calls["n"] == 4


def test_snapshot_retries_a_parse_error_then_succeeds(tmp_path):
    path = tmp_path / "Notes_U.xml"
    path.write_bytes(b"<CommentList><Comment")      # Paratext mid-save
    attempts = []

    def check(raw):
        attempts.append(raw)
        if len(attempts) == 1:
            path.write_bytes(b"<CommentList/>")
        return pp._parse_notes_bytes(raw, "Notes_U.xml")

    raw, _, comments = pp.snapshot_bytes(path, delay=0, check=check)
    assert comments == [] and raw == b"<CommentList/>" and len(attempts) == 2


def test_snapshot_gives_up_after_the_retries(tmp_path):
    path = tmp_path / "Notes_U.xml"
    path.write_bytes(b"<CommentList><Comment")
    with pytest.raises(pp.ParatextReadError):
        pp.snapshot_bytes(path, delay=0, check=lambda raw: pp._parse_notes_bytes(raw, "x"))


def test_reader_memoizes_and_keeps_a_stale_parse(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "_SNAPSHOT_DELAY", 0)
    folder = build_paratext_project(tmp_path, notes=NOTES, book_names={"TIT": ("Ti", "Titus", "Titus")})
    reader = pp.ParatextFolderReader(folder)
    settings = reader.settings()
    assert reader.settings() is settings
    index = reader.notes_index()
    assert reader.notes_index() is index
    assert reader.book_names()["TIT"]["short"] == "Titus"

    broken = folder / "Notes_User B.xml"
    broken.write_bytes(b"<CommentList><Comment")
    stale = reader.notes_index()
    assert "t5" in stale.threads                    # the previous comments are kept
    assert stale.stale_files == ["Notes_User B.xml"]
    assert reader.status()["notes"]["stale"] is True

    write_notes_file(folder, "User B", NOTES["User B"])
    fresh = reader.notes_index()
    assert fresh.stale_files == [] and reader.status()["notes"]["stale"] is False

    (folder / "Settings.xml").write_bytes(b"<ScriptureText><Name>")
    assert reader.settings() is settings
    assert reader.status()["settings"]["stale"] is True


# --------------------------------------------------------------------------- read-only contract


def test_no_function_writes_into_the_folder(tmp_path, monkeypatch):
    folder = build_paratext_project(
        tmp_path, notes=NOTES, regex_backups=1, bak=True, peripherals={"GLO": "\\id GLO\n\\p x\n"},
        book_names={"TIT": ("Ti", "Titus", "Titus")}, comment_tags={"1": "To Do"},
        users=[{"name": "User A"}],
    )
    before = _tree_digest(folder)
    real_open = builtins.open
    real_os_open = os.open

    def guarded_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in "wax+"):
            raise AssertionError(f"opened {file} for writing")
        return real_open(file, mode, *args, **kwargs)

    def guarded_os_open(path, flags, *args, **kwargs):
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC):
            raise AssertionError(f"os.open {path} for writing")
        return real_os_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(io, "open", guarded_open)
    monkeypatch.setattr(os, "open", guarded_os_open)

    settings = pp.read_settings(folder)
    pp.detect_paratext_folder(folder)
    pp.scripture_candidates(folder, settings)
    pp.link_block(folder, settings)
    pp.read_book_names(folder)
    pp.read_comment_tags(folder)
    pp.read_user_access(folder)
    index = pp.build_notes_index(folder)
    list(pp.iter_comments(folder / "Notes_User A.xml"))
    reader = pp.ParatextFolderReader(folder)
    reader.settings(), reader.notes_index(), reader.book_names(), reader.comment_tags(), reader.user_access()
    assert index.threads

    monkeypatch.undo()
    assert _tree_digest(folder) == before
