"""The one measurement that needs a real model (#214, #131, QA matrix D15).

Skipped unless `BRIDGE_LIVE_OPENAI_API_KEY` is set; never runs in CI. It sends
three windows of the cold Tamil IRV Philippians to the configured provider and
records how many of the words a variant moved were linked back to a source token
of the verse they came from, plus the token spend. The answer key is the
variant itself (`tests/support/cold_start.moved_words`), so no human judgement
is baked in.

Run it from `engine/` with:

    BRIDGE_LIVE_OPENAI_API_KEY=sk-... pytest tests/ai/test_window_ai_alignment_live.py -m live_ai -s

Optional: `BRIDGE_LIVE_AI_MODEL` (default: the client's own default) and
`BRIDGE_LIVE_AI_REPORT=<path>` to write the JSON report somewhere durable.

What is asserted is deliberately thin -- the request succeeded, the model was
consulted, and the full-swap window produced at least one cross-verse pick --
because the hit rate is the thing being *measured* for the first time, not a
number anyone can promise yet.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from bridge_service import BridgeEngine
from tc_ai_bridge.secret_store import AppSettings
from tests.support import cold_start
from tests.support.projects import call

pytestmark = pytest.mark.live_ai

KEY = os.environ.get("BRIDGE_LIVE_OPENAI_API_KEY", "").strip()

#: (variant, window) -- the natural case covers the IRV's own redistribution of
#: Philippians 1:3-6; the synthetic ones have a known answer.
CASES = [
    ("swap34", ["3", "4"]),
    ("spill34", ["3", "4"]),
    ("natural", ["3", "4", "5", "6"]),
]


def _engine(tmp_path: Path) -> BridgeEngine:
    engine = BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json"))
    engine.settings.set_api_key(KEY, persist=False)
    model = os.environ.get("BRIDGE_LIVE_AI_MODEL", "").strip()
    if model:
        engine.settings.model = model
    return engine


def _score(result: dict, variant: str, project: Path) -> dict:
    """How many moved words were linked cross-verse to the verse they came from."""
    moved = cold_start.moved_words(variant)
    cross = result.get("crossVerseProposals", [])
    hits: dict[str, int] = {}
    for now_in, words in moved.items():
        wanted = set(words)
        hits[now_in] = sum(
            1 for p in cross
            if p["target"]["verse"] == now_in and p["target"]["word"] in wanted and p["source"]["verse"] != now_in
        )
    same_verse_edges = result.get("edges", {}).get("sameVerse", 0)
    return {
        "movedWords": {verse: len(words) for verse, words in moved.items()},
        "movedWordsLinkedCrossVerse": hits,
        "crossVerseProposals": len(cross),
        "sameVerseEdges": same_verse_edges,
        "verseProposals": [
            {"verse": item["verse"], "compiledGroups": item["compiledGroups"], "edges": item["edges"]}
            for item in result.get("verseProposals", [])
        ],
        "reviewNotes": result.get("reviewNotes", []),
        "crossVersePicks": [
            {
                "from": f'{p["source"]["verse"]}:{p["source"]["word"]}',
                "to": f'{p["target"]["verse"]}:{p["target"]["word"]}',
                "confidence": p["confidence"],
                "reason": p["evidence"][0].get("reason", ""),
            }
            for p in cross
        ],
    }


@pytest.mark.skipif(not KEY, reason="BRIDGE_LIVE_OPENAI_API_KEY is not set; the live measurement is opt-in")
def test_live_window_alignment_on_the_cold_tamil_philippians(tmp_path):
    report: dict = {"model": "", "cases": {}}
    for variant, window in CASES:
        sfm = cold_start.write_variant(tmp_path / variant / "src", variant)
        importer = BridgeEngine(settings=AppSettings(path=tmp_path / variant / "importer" / "settings.json"))
        project = Path(cold_start.import_cold_project(call, importer, sfm, tmp_path / variant / "projects")["path"])
        engine = _engine(tmp_path / variant / "run")
        opened = call(engine, "project.open", {"path": str(project)})
        assert opened["success"] is True, opened
        report["model"] = engine.settings.model
        response = call(engine, "alignment.window.aiPropose", {"chapter": "1", "verses": window})
        assert response["success"] is True, response
        result = response["result"]
        assert result.get("modelConsulted") is True
        case = _score(result, variant, project)
        case["window"] = window
        case["usage"] = result.get("usage", {})
        report["cases"][variant] = case
        print(f"\n[live] {variant} {window}: {json.dumps(case, ensure_ascii=False, indent=2)}")

    out = os.environ.get("BRIDGE_LIVE_AI_REPORT", "").strip()
    if out:
        Path(out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[live] report written to {out}")

    # The full swap is the unambiguous case: every Greek word of 1:3 now lives
    # in Tamil 1:4 and vice versa. A model that finds none of them has not
    # understood the window at all.
    assert report["cases"]["swap34"]["crossVerseProposals"] >= 1
