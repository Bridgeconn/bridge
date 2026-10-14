"""The book stages of a Language QA pass are reused while what they read is
unchanged (#271): a pass after a decision or an idle refresh re-runs none of
them, a verse edit re-runs structure for its own chapter only, and a heading
edit leaves the stages that never read headings alone. Whatever is reused, the
findings are the ones a cold pass finds."""
from __future__ import annotations

import json

from tc_ai_bridge.language_packs import indic_qa_adapter
from tc_ai_bridge.language_qa_jobs import LanguageQaManager
from tests.support.language_qa import project_at, wait

CHAPTER_1 = {
    "1": "ஆதியிலே தேவன் வானத்தையும் பூமியையும் படைத்தார்.",
    "2": "பூமியானது ஒழுங்கின்மையும் வெறுமையுமாக இருந்தது; ஆழத்தின்மேல் இருள் இருந்தது.",
}
CHAPTER_2 = {
    "1": "இப்படியே வானமும் பூமியும் அவைகளின் சர்வசேனையும் உண்டாக்கி முடிந்தது.",
    "2": "தேவன் தாம் செய்த தம்முடைய கிரியையை ஏழாம் நாளிலே முடித்து \\f + \\fr 2:2 \\ft ஓய்ந்திருந்தார்.\\f*",
}
# Stages that read neither headings nor anything a verse edit changes besides text.
NOT_HEADINGS = ("lqa.book.note_callers", "lqa.book.xrefs", "lqa.book.header", "lqa.book.learned", "lqa.book.names")


def _project(tmp_path):
    project = project_at(tmp_path, verses=CHAPTER_1, book="gen")
    (project.book_dir / "2.json").write_text(json.dumps(CHAPTER_2, ensure_ascii=False), encoding="utf-8")
    (project.book_dir / "1.headings.json").write_text(
        json.dumps({"1": [{"tag": "s", "text": "உலகத்தின் படைப்பு"}]}, ensure_ascii=False), encoding="utf-8")
    return project


def _again(manager, chapter="1"):
    manager.invalidate(chapter)
    return wait(manager)


def _book_stages(status):
    return {name: entry for name, entry in status["timings"].items()
            if (name.startswith("lqa.book.") or name == "lqa.indicqa.book")
            and name not in {"lqa.book.settle", "lqa.book.layer_dedupe", "lqa.book.layer_dropped_as_duplicate"}}


def _ids(status):
    return sorted(json.dumps(f, sort_keys=True, ensure_ascii=False) for f in status["findings"])


def _cold(project):
    manager = LanguageQaManager(debounce=0, yield_seconds=0)
    manager.bind(project)
    try:
        return wait(manager)
    finally:
        manager.unbind()


def test_a_pass_with_nothing_changed_reruns_no_book_stage(tmp_path):
    project = _project(tmp_path)
    manager = LanguageQaManager(debounce=0, yield_seconds=0)
    manager.bind(project)
    try:
        first = wait(manager)
        stages = _book_stages(first)
        assert all("cached" not in entry for entry in stages.values())
        assert {"lqa.book.headings", "lqa.book.structure", "lqa.book.note_callers"} <= set(stages)
        assert "lqa.indicqa.build_book" in first["timings"]  # the ta-irv layer ran (its own steps)
        again = _again(manager)
    finally:
        manager.unbind()
    reused = _book_stages(again)
    # The layer's run is timed by its own steps; reused, it shows as one entry.
    assert set(reused) == set(stages) | {"lqa.indicqa.book"}
    assert "lqa.indicqa.build_book" not in again["timings"]
    for name, entry in reused.items():
        assert entry["calls"] == 0 and entry["cached"] >= 1, (name, entry)
    assert reused["lqa.book.structure"]["cached"] == 2  # one per chapter
    assert _ids(again) == _ids(first)


def test_a_verse_edit_reruns_structure_for_its_chapter_only_and_matches_a_cold_pass(tmp_path):
    project = _project(tmp_path)
    manager = LanguageQaManager(debounce=0, yield_seconds=0)
    manager.bind(project)
    try:
        wait(manager)
        edited = {**CHAPTER_2, "1": CHAPTER_2["1"] + " “"}  # an opening quote nothing closes
        (project.book_dir / "2.json").write_text(json.dumps(edited, ensure_ascii=False), encoding="utf-8")
        after = _again(manager, "2")
    finally:
        manager.unbind()
    stages = _book_stages(after)
    assert stages["lqa.book.structure"]["calls"] == 1 and stages["lqa.book.structure"]["cached"] == 1
    assert stages["lqa.book.note_callers"]["calls"] == 1  # it reads the text, so it ran again
    assert after["scannedVerses"] == 1
    assert any(f["rule"] == "punctuation.unbalanced-quote" and f["chapter"] == "2" for f in after["findings"])
    assert _ids(after) == _ids(_cold(project))


def test_a_heading_edit_leaves_the_stages_that_never_read_headings_alone(tmp_path):
    project = _project(tmp_path)
    manager = LanguageQaManager(debounce=0, yield_seconds=0)
    manager.bind(project)
    try:
        wait(manager)
        (project.book_dir / "1.headings.json").write_text(
            json.dumps({"1": [{"tag": "s", "text": "உலகத்தின் படைப்பு."}]}, ensure_ascii=False), encoding="utf-8")
        after = _again(manager)
    finally:
        manager.unbind()
    stages = _book_stages(after)
    assert stages["lqa.book.headings"]["calls"] == 1
    assert stages["lqa.book.structure"]["calls"] == 1 and stages["lqa.book.structure"]["cached"] == 1
    for name in NOT_HEADINGS:
        if name in stages:
            assert stages[name]["calls"] == 0 and stages[name]["cached"] == 1, (name, stages[name])
    assert any(f["rule"] == "heading.trailing-punctuation" for f in after["findings"])
    assert _ids(after) == _ids(_cold(project))


def test_a_rebind_starts_with_no_reused_stage(tmp_path):
    project = _project(tmp_path)
    manager = LanguageQaManager(debounce=0, yield_seconds=0)
    manager.bind(project)
    try:
        wait(manager)
        manager.bind(project)
        rebound = wait(manager)
    finally:
        manager.unbind()
    assert all("cached" not in entry for entry in _book_stages(rebound).values())


def test_the_layer_runs_again_when_its_checker_is_no_longer_resident(tmp_path):
    """Book words reads the resident checker, so a reused layer result is only
    taken while that checker still holds this book (another book or pack
    checked in between replaces it)."""
    project = _project(tmp_path)
    manager = LanguageQaManager(debounce=0, yield_seconds=0)
    manager.bind(project)
    try:
        wait(manager)
        indic_qa_adapter.release()
        after = _again(manager)
        words = manager.book_words()
    finally:
        manager.unbind()
    assert "lqa.indicqa.build_book" in after["timings"] and "lqa.indicqa.book" not in after["timings"]
    assert words["ready"] is True
