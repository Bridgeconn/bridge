"""#412: one target-word drop must not re-read and re-decode its chapter once
per verse of every status scan.

A chapter Bridge has just written sits inside the cache's two-second distrust
window (`_racy`), and the save tail -- alignment context, completion re-check,
semantic digest, progress recount -- used to parse it again on every verse:
~90 parses per drop, 2-3 s on a 176-verse Hebrew chapter. Now a recently
written file is verified by digest rather than decoded, and the tail runs in
one `chapter_snapshot`, so the file is read once and parsed once per drop.
The external-edit detection the window exists for is kept: a rewrite inside
one timestamp tick, and a conflicting edit between two snapshots, are read."""
from __future__ import annotations

import json
import os
import time

import pytest

from bridge_service import BridgeEngine
from tc_ai_bridge import tc_project
from tests.support.alignment_books import context_id, unaligned_verse, write_alignment_book
from tests.support.projects import call

HEBREW = ["בְּרֵאשִׁית", "בָּרָא", "אֱלֹהִים", "אֵת", "הַשָּׁמַיִם", "וְאֵת", "הָאָרֶץ", "וְהָאָרֶץ", "הָיְתָה",
          "תֹהוּ", "וָבֹהוּ", "וְחֹשֶׁךְ", "עַל", "פְּנֵי", "תְהוֹם", "וְרוּחַ", "מְרַחֶפֶת", "הַמָּיִם",
          "וַיֹּאמֶר", "יְהִי", "אוֹר", "וַיַּרְא", "כִּי", "טוֹב", "וַיַּבְדֵּל"]
ENGLISH = ("in beginning created God the heavens and the earth and earth was formless and empty "
           "darkness over face deep spirit hovering waters said let light").split()


def _book(root, verse_count: int) -> None:
    sources = [(w, f"H{i:04d}") for i, w in enumerate(HEBREW, start=1)]
    write_alignment_book(root, "gen", {
        "1": {str(v): unaligned_verse(" ".join(ENGLISH), sources) for v in range(1, verse_count + 1)},
    }, lang_id="en")


@pytest.fixture
def reads(monkeypatch):
    """(bytes reads, JSON decodes) of alignment chapter 1 through the chapter
    cache, as two counters that the test resets between drops."""
    counts = {"read": 0, "parse": 0}
    real_parse = tc_project._parse_json_bytes
    real_read_bytes = tc_project.Path.read_bytes

    def counting_parse(path, raw):
        if path.parent.name == "gen" and path.parent.parent.name == "alignmentData":
            counts["parse"] += 1
        return real_parse(path, raw)

    def counting_read(self):
        if self.parent.name == "gen" and self.parent.parent.name == "alignmentData":
            counts["read"] += 1
        return real_read_bytes(self)

    monkeypatch.setattr(tc_project, "_parse_json_bytes", counting_parse)
    monkeypatch.setattr(tc_project.Path, "read_bytes", counting_read)
    return counts


def _drop(engine, verse: str, source: str, target: str) -> dict:
    context = call(engine, "alignment.get", {"chapter": "1", "verse": verse})["result"]
    result = call(engine, "alignment.realign", {
        "chapter": "1", "verse": verse,
        "topIds": [context_id(context, top_word=source)],
        "bottomIds": [context_id(context, bottom_word=target)],
        "expectedOriginal": context["alignment"],
    })
    assert result["success"] is True, result
    return result["result"]


@pytest.mark.parametrize("verse_count", [40, 176])
def test_a_drop_reads_and_parses_its_chapter_a_bounded_number_of_times(tmp_path, reads, verse_count):
    root = tmp_path / "gen"
    _book(root, verse_count)
    engine = BridgeEngine()
    assert call(engine, "project.open", {"path": str(root)})["success"] is True
    verse = str(verse_count // 2)
    # Alternate one target word between two source columns, as a tester does.
    for i in range(6):
        reads["read"] = reads["parse"] = 0
        source = HEBREW[0] if i % 2 == 0 else HEBREW[1]
        context = _drop(engine, verse, source, "God")
        group = next(g for g in context["alignment"]["alignments"] if g["topWords"][0]["word"] == source)
        assert [b["word"] for b in group["bottomWords"]] == ["God"]
        # Decodes: the context read before the drop, the writer's mutable
        # load, the atomic writer's validation of its temp file, its
        # read-back validation and the tail's one parse. Byte reads add the
        # digest verifications of a just-written file (one per snapshot) and
        # the semantic digest. Before #412 a drop decoded the chapter ~90
        # times at either size.
        assert reads["parse"] <= 6, (verse_count, i, reads)
        assert reads["read"] <= 10, (verse_count, i, reads)
    status = call(engine, "alignment.status", {"chapter": "1"})["result"]
    assert status["counts"]["partial"] == 1
    assert status["counts"]["untouched"] == verse_count - 1


def test_the_status_scan_of_a_fresh_chapter_decodes_it_once(tmp_path, reads):
    root = tmp_path / "gen"
    _book(root, 40)
    engine = BridgeEngine()
    assert call(engine, "project.open", {"path": str(root)})["success"] is True
    _drop(engine, "7", HEBREW[0], "God")
    reads["read"] = reads["parse"] = 0
    call(engine, "alignment.status", {"chapter": "1"})
    assert reads["parse"] == 0 and reads["read"] <= 1, reads  # digest-verified once, never decoded
    engine.project._forget_chapter_files()
    reads["read"] = reads["parse"] = 0
    call(engine, "alignment.status", {"chapter": "1"})
    assert reads["parse"] == 1 and reads["read"] == 1, reads


def test_an_edit_inside_one_timestamp_tick_is_still_read_by_digest(tmp_path):
    root = tmp_path / "gen"
    _book(root, 3)
    project = tc_project.TranslationCoreProject(root)
    path = project.chapter_path("1")
    now = time.time_ns()
    os.utime(path, ns=(now, now))
    assert project.load_verse_alignment("1", "1").word_bank[0].word == "in"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["1"]["wordBank"][0]["word"] = "IN"  # same byte length
    size = path.stat().st_size
    with path.open("w", encoding="utf-8") as fh:  # in place: same file id
        json.dump(data, fh, ensure_ascii=False)
    os.utime(path, ns=(now, now))
    assert path.stat().st_size == size
    assert project.load_verse_alignment("1", "1").word_bank[0].word == "IN"


def test_a_snapshot_trusts_a_file_only_within_itself(tmp_path, reads):
    root = tmp_path / "gen"
    _book(root, 3)
    project = tc_project.TranslationCoreProject(root)
    path = project.chapter_path("1")
    now = time.time_ns()
    os.utime(path, ns=(now, now))
    with project.chapter_snapshot():
        for _ in range(5):
            assert project.load_verse_alignment("1", "1").word_bank[0].word == "in"
            project.verses("1")
        assert reads["parse"] == 1 and reads["read"] == 1, reads
    # Another program rewrites the file inside the same tick, between two
    # of Bridge's scopes: the next scope verifies again and sees it.
    data = json.loads(path.read_text(encoding="utf-8"))
    data["1"]["wordBank"][0]["word"] = "IN"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    os.utime(path, ns=(now, now))
    with project.chapter_snapshot():
        assert project.load_verse_alignment("1", "1").word_bank[0].word == "IN"
        assert reads["parse"] == 2
    # And Bridge's own write ends the trust of the scope it happens in.
    with project.chapter_snapshot():
        current = project.load_verse_alignment("1", "2")
        project.save_verse_alignment("1", "2", current, expected_original=current.to_dict())
        before = reads["parse"]
        project.load_verse_alignment("1", "2")
        assert reads["parse"] == before + 1


def test_a_conflicting_edit_is_still_refused(tmp_path):
    root = tmp_path / "gen"
    _book(root, 3)
    engine = BridgeEngine()
    assert call(engine, "project.open", {"path": str(root)})["success"] is True
    context = call(engine, "alignment.get", {"chapter": "1", "verse": "1"})["result"]
    _drop(engine, "1", HEBREW[0], "God")  # the file changes after `context` was read
    stale = call(engine, "alignment.realign", {
        "chapter": "1", "verse": "1",
        "topIds": [context_id(context, top_word=HEBREW[1])],
        "bottomIds": [context_id(context, bottom_word="the")],
        "expectedOriginal": context["alignment"],
    })
    assert stale["success"] is False
    assert "changed on disk" in stale["error"]["message"]
