"""#501: the local translationWords rule, in shadow mode only.

The rule says what it would have decided; it must not decide anything. These
tests pin the rule's four conditions and that computing it changes nothing on
disk and is read by nothing.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from tc_ai_bridge import local_tw_pass
from tc_ai_bridge.local_tw_pass import MODE, shadow_tw_decisions
from tc_ai_bridge.tc_project import TranslationCoreProject
from tests.support.paths import ENGINE_ROOT

GOD = "אֱלֹהִים"
SAID = "וַיֹּאמֶר"
LIGHT = "אוֹר"


def _top(word, occurrence=1, occurrences=1):
    return {"word": word, "strong": "H0000", "lemma": word, "morph": "He,N", "occurrence": occurrence,
            "occurrences": occurrences}


def _bottom(word, occurrence=1, occurrences=1):
    return {"word": word, "occurrence": occurrence, "occurrences": occurrences, "type": "bottomWord"}


def _tw(verse, check_id, quote, *, group="god", selections=False, occurrence=1, **extra):
    return {
        "contextId": {
            "reference": {"bookId": "gen", "chapter": "1", "verse": verse},
            "tool": "translationWords", "groupId": group, "checkId": check_id,
            "quoteString": quote, "occurrence": occurrence,
        },
        "selections": selections, "nothingToSelect": False, "invalidated": False, **extra,
    }


def _selected(*words):
    return [{"text": w, "occurrence": 1, "occurrences": 1} for w in words]


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")


@pytest.fixture
def genesis(tmp_path):
    """Four verses. 1:1 and 1:2 already have "परमेश्वर" selected for `god`;
    1:3 and 1:4 are the verses under test."""
    root = tmp_path / "data" / "projects" / "gen"
    _write(root / "manifest.json", {
        "project": {"id": "gen", "name": "Genesis"}, "target_language": {"id": "hi", "name": "Hindi"},
        "tc_version": "8", "tc_edit_version": "3.7.0",
    })
    _write(root / "gen" / "1.json", {
        "1": "आदि में परमेश्वर ने", "2": "परमेश्वर का आत्मा", "3": "तब परमेश्वर ने कहा उजियाला हो",
        "4": "और ईश्वर ने उजियाले को देखा",
    })
    _write(root / ".apps" / "translationCore" / "alignmentData" / "gen" / "1.json", {
        "1": {"alignments": [{"topWords": [_top(GOD)], "bottomWords": [_bottom("परमेश्वर")]}], "wordBank": []},
        "2": {"alignments": [{"topWords": [_top(GOD)], "bottomWords": [_bottom("परमेश्वर")]}], "wordBank": []},
        "3": {"alignments": [
            {"topWords": [_top(SAID)], "bottomWords": [_bottom("तब"), _bottom("कहा")]},
            {"topWords": [_top(GOD)], "bottomWords": [_bottom("परमेश्वर")]},
            {"topWords": [_top(LIGHT, 1, 2)], "bottomWords": [_bottom("उजियाला")]},
            {"topWords": [_top(LIGHT, 2, 2)], "bottomWords": []},
        ], "wordBank": [_bottom("ने"), _bottom("हो")]},
        "4": {"alignments": [
            {"topWords": [_top(GOD)], "bottomWords": [_bottom("ईश्वर")]},
        ], "wordBank": []},
    })
    index = root / ".apps" / "translationCore" / "index"
    _write(index / "translationWords" / "gen" / "god.json", [
        _tw("1", "g1", GOD, selections=_selected("परमेश्वर")),
        _tw("2", "g2", GOD, selections=_selected("परमेश्वर")),
        _tw("3", "g3", GOD),
        _tw("4", "g4", GOD),
    ])
    _write(index / "translationWords" / "gen" / "light.json", [
        _tw("3", "l1", LIGHT, group="light", occurrence=1),
        _tw("3", "l2", LIGHT, group="light", occurrence=2),
    ])
    _write(index / "translationNotes" / "gen" / "figs-metaphor.json", [{
        "contextId": {"reference": {"bookId": "gen", "chapter": "1", "verse": "3"},
                      "tool": "translationNotes", "groupId": "figs-metaphor", "checkId": "n1",
                      "quoteString": SAID, "occurrence": 1},
        "selections": False, "nothingToSelect": False, "invalidated": False,
    }])
    return root


def _shadow(root: Path, verse: str):
    project = TranslationCoreProject(root)
    record = shadow_tw_decisions(project, "1", verse, project.load_verse_alignment("1", verse))
    return record, {row["checkId"]: row for row in record["checks"]}


def test_a_term_aligned_to_a_rendering_the_project_already_uses_would_pass(genesis):
    record, rows = _shadow(genesis, "3")
    assert record["mode"] == MODE == "shadow" and "error" not in record
    god = rows["g3"]
    assert god["wouldPass"] is True and god["reason"] == ""
    assert god["alignedTargetWords"] == ["परमेश्वर"] and god["matchedRendering"] == ["परमेश्वर"]
    assert god["matchingRenderings"] == 2 and god["matchingReferences"] == ["1:1", "1:2"]
    assert god["renderingsConsidered"] == 2
    # translationWords only: the note on the same verse is not in the record.
    assert set(rows) == {"g3", "l1", "l2"}
    assert record["twChecks"] == 3 and record["wouldPass"] == 1


def test_nothing_else_qualifies(genesis):
    _, rows = _shadow(genesis, "3")
    # A term the project has never rendered before.
    assert rows["l1"]["wouldPass"] is False
    assert rows["l1"]["alignedTargetWords"] == ["उजियाला"]
    assert rows["l1"]["reason"] == "the project has no other rendering of this term yet"
    # A source word with no target word: unaligned, so not the rule's to take.
    assert rows["l2"]["wouldPass"] is False
    assert rows["l2"]["reason"] == "source quote is not aligned to any target word"
    # Aligned, but to a word the project has not used for the term.
    _, four = _shadow(genesis, "4")
    assert four["g4"]["wouldPass"] is False and four["g4"]["alignedTargetWords"] == ["ईश्वर"]
    assert four["g4"]["reason"] == "the aligned words are not a rendering the project already uses for this term"


def test_a_checks_own_selection_never_counts(genesis):
    # 1:1's check has "परमेश्वर" selected; the only other rendering is 1:2's.
    _, rows = _shadow(genesis, "1")
    assert rows["g1"]["wouldPass"] is True and rows["g1"]["matchingReferences"] == ["1:2"]
    # Take 1:2's away: 1:1 would then be agreeing with itself, and does not pass.
    path = genesis / ".apps" / "translationCore" / "index" / "translationWords" / "gen" / "god.json"
    entries = json.loads(path.read_text(encoding="utf-8"))
    entries[1]["selections"] = False
    path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    _, rows = _shadow(genesis, "1")
    assert rows["g1"]["wouldPass"] is False and rows["g1"]["renderingsConsidered"] == 0


def test_a_group_holding_another_source_word_is_a_partial_match(genesis):
    path = genesis / ".apps" / "translationCore" / "alignmentData" / "gen" / "1.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["3"]["alignments"][1]["topWords"].append(_top(SAID, 2, 2))  # God + another word in one group
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    _, rows = _shadow(genesis, "3")
    assert rows["g3"]["wouldPass"] is False
    assert rows["g3"]["reason"] == "the alignment group also holds another source word (partial match)"


def test_invalidated_and_nothing_to_select_records_are_not_renderings(genesis):
    path = genesis / ".apps" / "translationCore" / "index" / "translationWords" / "gen" / "god.json"
    entries = json.loads(path.read_text(encoding="utf-8"))
    entries[0]["invalidated"] = True
    entries[1]["nothingToSelect"] = True
    path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    _, rows = _shadow(genesis, "3")
    assert rows["g3"]["wouldPass"] is False and rows["g3"]["renderingsConsidered"] == 0
    # And an invalidated check is never the rule's.
    entries[2]["invalidated"] = True
    path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    _, rows = _shadow(genesis, "3")
    assert rows["g3"]["reason"] == "check is invalidated"


def test_a_phrase_with_a_repeated_word_does_not_qualify(genesis):
    path = genesis / ".apps" / "translationCore" / "index" / "translationWords" / "gen" / "light.json"
    entries = json.loads(path.read_text(encoding="utf-8"))
    entries[0]["contextId"]["quoteString"] = f"{SAID} {LIGHT}"  # אוֹר occurs twice; the phrase does not say which
    path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    _, rows = _shadow(genesis, "3")
    assert rows["l1"]["wouldPass"] is False
    assert rows["l1"]["reason"] == "a quoted source word repeats in the verse and the check does not say which"


def _tree(root: Path) -> dict[str, str]:
    """Every file under the project, by content, bar SQLite's own side files."""
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file() and not p.name.endswith(("-wal", "-shm"))
    }


def test_working_out_the_shadow_record_writes_nothing(genesis):
    project = TranslationCoreProject(genesis)
    alignment = project.load_verse_alignment("1", "3")
    project.checks_for_verse("1", "3")  # anything the project creates on first read exists before the snapshot
    before = _tree(genesis)
    for verse in ("1", "2", "3", "4"):
        shadow_tw_decisions(project, "1", verse, project.load_verse_alignment("1", verse))
    assert _tree(genesis) == before
    assert not (genesis / ".apps" / "translationCore" / "checkData").exists()
    assert alignment.to_dict() == project.load_verse_alignment("1", "3").to_dict()


def test_a_failure_is_recorded_and_never_raised(genesis):
    project = TranslationCoreProject(genesis)
    record = shadow_tw_decisions(project, "1", "3", None)  # no alignment object at all
    assert record["mode"] == "shadow" and "AttributeError" in record["error"]
    assert record["wouldPass"] == 0


def test_shadow_is_the_only_mode_and_the_record_is_read_by_nothing():
    """The step #501 leaves for a decision is skipping the AI or recording a
    local pass. Until docs/DECISIONS.md says otherwise there must be no code
    that could: the module calls no writer, and the stored record is only ever
    written, never read back."""
    source = (ENGINE_ROOT / "tc_ai_bridge" / "local_tw_pass.py").read_text(encoding="utf-8")
    assert local_tw_pass.MODE == "shadow"
    assert [m for m in re.findall(r"^MODE\s*=.*$", source, re.M)] == ["MODE = 'shadow'"]
    calls = set(re.findall(r"\.([A-Za-z_]+)\(", source))
    writers = {name for name in calls if name.startswith(("save", "record", "apply", "write", "_write", "mark", "set_"))}
    assert writers == set(), writers
    assert "open(" not in source and "write_text" not in source

    users: dict[str, list[str]] = {}
    for path in list(ENGINE_ROOT.glob("*.py")) + list((ENGINE_ROOT / "tc_ai_bridge").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        hits = [line.strip() for line in text.splitlines()
                if "localTwShadow" in line or "local_tw_shadow" in line or "shadow_tw_decisions" in line]
        if hits:
            users[path.name] = hits
    assert set(users) == {"ai_client.py", "ai_review_windows.py", "local_tw_pass.py"}
    for name in ("ai_client.py", "ai_review_windows.py"):
        for line in users[name]:
            # An import, the one call that computes it, a field that carries it, or the stored key.
            assert (
                line.startswith(("from .local_tw_pass import", "local_tw_shadow = shadow_tw_decisions(",
                                 "local_tw_shadow: dict[str, Any]", "'localTwShadow':"))
                or "local_tw_shadow=local_tw_shadow" in line
            ), (name, line)
