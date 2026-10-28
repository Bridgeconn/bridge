"""`alignment.window.aiPropose` (#214) through the protocol, on a project imported
cold from the unaligned Tamil IRV Philippians (`tests/support/cold_start.py`).

Every test injects a fake transport: no key, no network, no live model. What is
checked here is what Bridge sends, how it routes what comes back, that the ids it
returns round-trip into the two existing writers, and that proposing writes
nothing. The one measurement that needs a real model is the key-gated
`tests/ai/test_window_ai_alignment_live.py`.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bridge_service import BridgeEngine
from tc_ai_bridge.secret_store import AppSettings
from tests.support import cold_start
from tests.support.projects import call


def _response(body: dict) -> bytes:
    return json.dumps({
        "output_text": json.dumps(body, ensure_ascii=False),
        "usage": {"input_tokens": 1200, "output_tokens": 300, "total_tokens": 1500},
    }).encode("utf-8")


def transport_returning(body: dict, captured: list | None = None):
    def transport(url, headers, request_body, timeout):
        if captured is not None:
            captured.append(json.loads(request_body))
        return 200, _response(body)
    return transport


def _empty_reply() -> dict:
    return {"links": [], "implicit_source_ids": [], "target_only_ids": [], "review_notes": []}


def fresh_import(tmp_path_factory, name: str, variant: str = "swap34") -> Path:
    """Import one variant into its own temp root and return the project path."""
    root = tmp_path_factory.mktemp(name)
    sfm = cold_start.write_variant(root / "src", variant)
    engine = BridgeEngine(settings=AppSettings(path=root / "importer" / "settings.json"))
    return Path(cold_start.import_cold_project(call, engine, sfm, root / "projects")["path"])


@pytest.fixture(scope="module")
def swapped_project(tmp_path_factory) -> Path:
    """One import per module for the read-only tests: Philippians with Tamil 1:3
    and 1:4 exchanged. A test that writes takes its own `fresh_import`."""
    return fresh_import(tmp_path_factory, "cold-swap")


def open_engine(project: Path, tmp_path: Path, transport, api_key: str | None = "test-key") -> BridgeEngine:
    """A fresh engine per test with its own settings and workspace, opened on the
    shared import. The project's own workbench database is per project, so tests
    that write must not share a project -- none here do; proposing is read-only."""
    engine = BridgeEngine(
        settings=AppSettings(path=tmp_path / "settings.json"), ai_transport=transport,
    )
    if api_key:
        engine.settings.set_api_key(api_key, persist=False)
    opened = call(engine, "project.open", {"path": str(project)})
    assert opened["success"] is True, opened
    return engine


def window_propose(engine, verses):
    return call(engine, "alignment.window.aiPropose", {"chapter": "1", "verses": verses})


def _payload(captured: list) -> dict:
    """The structured input Bridge sent, out of the Responses envelope."""
    request = captured[-1]
    text = request["input"] if isinstance(request.get("input"), str) else json.dumps(request["input"])
    return json.loads(text)


def _handles(payload: dict, verse: str) -> tuple[dict[str, str], dict[str, str]]:
    """`{word: handle}` for one verse's source and target rows."""
    entry = next(v for v in payload["verses"] if v["verse"] == verse)
    return (
        {row["word"]: row["id"] for row in entry["source"]},
        {row["word"]: row["id"] for row in entry["target"]},
    )


def test_the_import_is_genuinely_cold(swapped_project):
    """Blank UGNT groups, full word bank, no completed verse: the state the
    corpus scorer and the #146 gap menu have nothing to say about."""
    data = json.loads(cold_start.alignment_chapter_bytes(swapped_project).decode("utf-8"))
    assert all(not group["bottomWords"] for group in data["3"]["alignments"])
    assert len(data["3"]["alignments"]) == 9      # Greek 1:3 has nine tokens
    assert len(data["4"]["alignments"]) == 13     # Greek 1:4 has thirteen
    assert data["3"]["wordBank"] and data["4"]["wordBank"]
    assert not (swapped_project / ".apps" / "translationCore" / "tools" / "wordAlignment" / "completed").exists()
    # The swap took: Tamil 1:3 now carries the words the IRV had in 1:4.
    moved = cold_start.moved_words("swap34")
    bank3 = [w["word"] for w in data["3"]["wordBank"]]
    assert all(word in bank3 for word in moved["3"])


def test_every_token_of_the_window_is_offered_in_reading_order_with_opaque_handles(swapped_project, tmp_path):
    captured: list = []
    engine = open_engine(swapped_project, tmp_path, transport_returning(_empty_reply(), captured))
    result = window_propose(engine, ["4", "3"])          # out of order on purpose
    assert result["success"] is True, result
    assert result["result"]["verses"] == ["3", "4"]       # chapter order, not request order
    payload = _payload(captured)
    assert payload["reference"] == "PHP 1:3-4"
    assert [v["verse"] for v in payload["verses"]] == ["3", "4"]
    sources3, targets3 = _handles(payload, "3")
    sources4, targets4 = _handles(payload, "4")
    assert len(sources3) == 9 and len(sources4) == 13
    assert result["result"]["window"] == {"sources": 22, "targets": len(targets3) + len(targets4)}
    # Opaque handles only: never Bridge's positional ids, never a token cap.
    flat = json.dumps(payload, ensure_ascii=False)
    assert "H001" not in flat and "T001" not in flat
    assert all(h.startswith("S") for h in sources3.values()) and all(h.startswith("T") for h in targets4.values())
    # The one thing a reviewer-facing model most needs: what the Greek word means.
    theos_row = next(row for row in payload["verses"][0]["source"] if row["word"] == "Θεῷ")
    assert theos_row["strong"] == "G23160" and theos_row.get("meaning")
    # And the translation itself, in order, so a moved clause is visible.
    assert payload["verses"][0]["translation"].startswith("நான் பண்ணுகிற")
    assert result["result"]["usage"]["totalTokens"] == 1500


def test_a_same_verse_pick_is_compiled_per_verse_and_applies_through_the_existing_writer(tmp_path, tmp_path_factory):
    """The same-verse case: Greek 1:4 ὑμῶν ("of you") and Tamil 1:4 உங்களுக்கு ("to
    you"). After the swap Tamil 1:4 carries the IRV's 1:3 clause, which also
    addresses "you", so the pair still shares a verse. Own import, because the
    apply at the end writes."""
    swapped_project = fresh_import(tmp_path_factory, "cold-swap-apply")
    captured: list = []
    probe = open_engine(swapped_project, tmp_path / "probe", transport_returning(_empty_reply(), captured))
    window_propose(probe, ["3", "4"])
    sources4, targets4 = _handles(_payload(captured), "4")
    reply = {
        **_empty_reply(),
        "links": [{
            "source_id": sources4["ὑμῶν"], "target_id": targets4["உங்களுக்கு"],
            "confidence": 0.4, "reason": "both address the readers",
        }],
    }
    engine = open_engine(swapped_project, tmp_path / "run", transport_returning(reply))
    result = window_propose(engine, ["3", "4"])["result"]
    assert result["crossVerseProposals"] == []
    [item] = result["verseProposals"]
    assert item["verse"] == "4" and item["edges"] == 1 and item["compiledGroups"] == 1
    compiled = [g for g in item["proposal"]["groups"] if g["origin"] == "ai_compiled"]
    assert len(compiled) == 1 and compiled[0]["confidence"] == 0.4   # below 0.72, still compiled
    # `expectedOriginal` is the alignment the proposal was compiled against ...
    current = call(engine, "alignment.get", {"chapter": "1", "verse": "4"})["result"]["alignment"]
    assert item["expectedOriginal"] == current
    # ... so the existing writer accepts it as one explicit, human-clicked save.
    applied = call(engine, "alignment.aiApplyProposal", {
        "chapter": "1", "verse": "4", "proposal": item["proposal"], "expectedOriginal": item["expectedOriginal"],
    })
    assert applied["success"] is True, applied
    # Positional ids renumber after a save (an aligned word leaves the word
    # bank), so the proof is by word: ὑμῶν and உங்களுக்கு now share a group.
    context = applied["result"]
    top_word = {t["id"]: t["word"] for t in context["topTokens"]}
    bottom_word = {t["id"]: t["word"] for t in context["bottomTokens"]}
    assert any(
        [top_word[i] for i in g["topIds"]] == ["ὑμῶν"] and [bottom_word[i] for i in g["bottomIds"]] == ["உங்களுக்கு"]
        for g in context["groups"]
    )
    assert context["status"] == "partial"


def test_a_cross_verse_pick_is_an_acceptable_proposal_whose_ids_round_trip_into_the_link_store(tmp_path, tmp_path_factory):
    """Own import: accepting writes a link, and the module-scoped project must
    stay untouched for the writes-nothing test."""
    project = fresh_import(tmp_path_factory, "cold-swap-link")

    captured: list = []
    probe = open_engine(project, tmp_path / "probe", transport_returning(_empty_reply(), captured))
    window_propose(probe, ["3", "4"])
    payload = _payload(captured)
    sources4, _ = _handles(payload, "4")
    _, targets3 = _handles(payload, "3")
    # Greek 1:4 δεήσει ("prayer") is realized, after the swap, by Tamil 1:3 விண்ணப்பத்திலும்.
    reply = {
        **_empty_reply(),
        "links": [{
            "source_id": sources4["δεήσει"], "target_id": targets3["விண்ணப்பத்திலும்"],
            "confidence": 0.93, "reason": "verse 3 carries “in every prayer”",
        }],
    }
    engine = open_engine(project, tmp_path / "run", transport_returning(reply))
    result = window_propose(engine, ["3", "4"])["result"]
    assert result["verseProposals"] == []
    [proposal] = result["crossVerseProposals"]
    assert proposal["status"] == "PROPOSED"
    assert proposal["autoLinkable"] is False and proposal["agreesWithCorpus"] is False
    assert proposal["source"]["verse"] == "4" and proposal["target"]["verse"] == "3"
    assert proposal["evidence"][0]["reason"].startswith("verse 3 carries")
    # The ids are this load's positional ids, exactly what Accept sends.
    linked = call(engine, "alignment.crossVerse.link", {
        "source": {"chapter": "1", "verse": "4", "topId": proposal["source"]["topId"]},
        "target": {"chapter": "1", "verse": "3", "bottomId": proposal["target"]["bottomId"]},
    })
    assert linked["success"] is True, linked
    assert linked["result"]["link"]["source"]["word"] == "δεήσει"
    assert linked["result"]["link"]["target"]["word"] == "விண்ணப்பத்திலும்"
    # A human Accept, not an automatic write: no "ai-auto" origin anywhere.
    assert linked["result"]["link"].get("origin", "") != "ai-auto"


def test_proposing_writes_nothing(swapped_project, tmp_path):
    captured: list = []
    probe = open_engine(swapped_project, tmp_path / "probe", transport_returning(_empty_reply(), captured))
    window_propose(probe, ["3", "4"])
    sources3, targets3 = _handles(_payload(captured), "3")
    sources4, targets4 = _handles(_payload(captured), "4")
    reply = {
        **_empty_reply(),
        "links": [
            {"source_id": sources4["ὑμῶν"], "target_id": targets4["உங்களுக்கு"], "confidence": 0.9, "reason": "a"},
            {"source_id": sources4["δεήσει"], "target_id": targets3["விண்ணப்பத்திலும்"], "confidence": 0.9, "reason": "b"},
        ],
        "implicit_source_ids": [sources3["τῷ"]],
    }
    before_alignment = cold_start.alignment_chapter_bytes(swapped_project)
    before_text = cold_start.target_chapter_bytes(swapped_project)
    engine = open_engine(swapped_project, tmp_path / "run", transport_returning(reply))
    links_before = engine.project.cross_verse_links.active_links()
    result = window_propose(engine, ["3", "4"])["result"]
    assert result["verseProposals"] and result["crossVerseProposals"]
    assert cold_start.alignment_chapter_bytes(swapped_project) == before_alignment
    assert cold_start.target_chapter_bytes(swapped_project) == before_text
    assert engine.project.cross_verse_links.active_links() == links_before


def test_an_invented_id_is_refused_rather_than_quietly_dropped(swapped_project, tmp_path):
    reply = {**_empty_reply(), "links": [{"source_id": "S999", "target_id": "T1", "confidence": 0.9, "reason": ""}]}
    engine = open_engine(swapped_project, tmp_path, transport_returning(reply))
    result = window_propose(engine, ["3", "4"])
    assert result["success"] is False
    assert "S999" in result["error"]["message"]


def test_no_api_key_is_a_supported_state_not_an_error(swapped_project, tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    engine = open_engine(swapped_project, tmp_path, transport_returning(_empty_reply()), api_key=None)
    result = window_propose(engine, ["3", "4"])
    assert result["success"] is True
    assert result["result"]["unavailable"]["reason"] == "no-api-key"
    assert result["result"]["verseProposals"] == [] and result["result"]["crossVerseProposals"] == []


def test_a_window_is_bounded_in_verses_not_tokens(swapped_project, tmp_path):
    calls: list = []
    engine = open_engine(swapped_project, tmp_path, transport_returning(_empty_reply(), calls))
    too_many = window_propose(engine, ["1", "2", "3", "4", "5", "6"])
    assert too_many["success"] is False and "at most 5" in too_many["error"]["message"]
    missing = window_propose(engine, ["3", "99"])
    assert missing["success"] is False and "1:99" in missing["error"]["message"]
    empty = window_propose(engine, [])
    assert empty["success"] is False
    assert calls == []   # none of these spent a request
    five = window_propose(engine, ["1", "2", "3", "4", "5"])
    assert five["success"] is True and five["result"]["window"]["sources"] > 40   # past the #146 cap, offered whole
