"""#352: a source verse the target versification has no verse for is raised as
a finding on the nearest target verse, through the ordinary local checks.

The issue's case: an English 3 John with 14 verses. UGNT has 1:15; it is never
merged into 1:14 by guess, the manifest records the versification, and
verse.runChecks / a check job raise "source verse not in target versification"
on 1:14 with a stable id the reviewer can decide."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bridge_service import BridgeEngine
from tc_ai_bridge import versification as vt
from tc_ai_bridge.project_import import import_source
from tests.support.projects import call, wait_for_job

pytestmark = pytest.mark.skipif(not vt.is_available(), reason="vendored versification data not present")

METADATA = {"languageId": "eng", "languageName": "English", "languageDirection": "ltr",
            "projectName": "3 John", "bibleName": "Test Bible"}


def _three_john(verse_count: int) -> str:
    lines = ["\\id 3JN", "\\h 3 John", "\\c 1", "\\p"]
    lines += [f"\\v {n} Verse {n} text." for n in range(1, verse_count + 1)]
    return "\n".join(lines) + "\n"


def _import(tmp_path: Path, verse_count: int) -> Path:
    source = tmp_path / f"65-3JN-{verse_count}.usfm"
    source.write_text(_three_john(verse_count), encoding="utf-8")
    return Path(import_source(source, tmp_path / f"projects{verse_count}", METADATA)["primaryProjectPath"])


def test_import_records_the_versification_and_the_unplaced_source_verse_without_merging(tmp_path):
    root = _import(tmp_path, 14)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    entry = manifest["bridge_versification"]
    assert entry["schema"] == "org" and entry["detected"] is False and "fit equally" in entry["reason"]
    provenance = json.loads((root / ".bridge" / "import.json").read_text(encoding="utf-8"))
    assert provenance["alignment"]["versification"] == "org"
    assert provenance["alignment"]["unplacedSourceVerses"] == [
        {"source": "1:15", "nearestTarget": "1:14", "wordCount": 11},
    ]
    alignment = json.loads((root / ".apps" / "translationCore" / "alignmentData" / "3jn" / "1.json").read_text(encoding="utf-8"))
    assert len(alignment["14"]["alignments"]) == 10  # UGNT 1:14 only; 1:15 is not merged in
    assert "15" not in alignment


def test_the_nearest_target_verse_carries_the_finding_with_a_stable_id(tmp_path):
    root = _import(tmp_path, 14)
    engine = BridgeEngine()
    assert call(engine, "project.open", {"path": str(root)})["success"]

    first = call(engine, "verse.runChecks", {"chapter": "1", "verse": "14", "checks": ["local"]})
    [finding] = [f for f in first["findings"] if f["check_type"] == "alignment.source_verse_unplaced"]
    assert finding["engine"] == "versification" and finding["severity"] == "medium"
    assert "Source verse 1:15 is not in the target versification" in finding["explanation"]
    assert "εἰρήνη" in finding["explanation"].lower() and "1:14 is the nearest target verse" in finding["explanation"]
    assert finding["status"] == "open"

    # Not on any other verse.
    other = call(engine, "verse.runChecks", {"chapter": "1", "verse": "13", "checks": ["local"]})
    assert not any(f["check_type"] == "alignment.source_verse_unplaced" for f in other["findings"])

    # The id is stable across runs (gotcha 3) and a decision survives a re-run (gotcha 4).
    assert call(engine, "verse.decide", {"chapter": "1", "verse": "14", "findingId": finding["id"],
                                         "status": "ignored", "comment": "The letter ends at 14 in English."})["success"]
    again = call(engine, "verse.runChecks", {"chapter": "1", "verse": "14", "checks": ["local"]})
    [same] = [f for f in again["findings"] if f["check_type"] == "alignment.source_verse_unplaced"]
    assert same["id"] == finding["id"] and same["status"] == "ignored"


def test_a_check_job_puts_the_finding_in_the_snapshot_and_a_15_verse_book_has_none(tmp_path):
    root = _import(tmp_path, 14)
    engine = BridgeEngine()
    assert call(engine, "project.open", {"path": str(root)})["success"]
    started = call(engine, "checks.start", {"scope": "book", "checks": ["local"]})["result"]
    assert wait_for_job(engine, started["jobId"], timeout=30)["state"] == "succeeded"
    snapshot = engine.project.load_check_findings_snapshot("1")
    assert any(f["check_type"] == "alignment.source_verse_unplaced" for f in snapshot.get("14", []))
    assert not any(f["check_type"] == "alignment.source_verse_unplaced"
                   for verse, findings in snapshot.items() if verse != "14" for f in findings)

    full = _import(tmp_path, 15)
    engine15 = BridgeEngine()
    assert call(engine15, "project.open", {"path": str(full)})["success"]
    provenance = json.loads((full / ".bridge" / "import.json").read_text(encoding="utf-8"))
    assert provenance["alignment"]["unplacedSourceVerses"] == []
    result = call(engine15, "verse.runChecks", {"chapter": "1", "verse": "15", "checks": ["local"]})
    assert not any(f["check_type"] == "alignment.source_verse_unplaced" for f in result["findings"])
