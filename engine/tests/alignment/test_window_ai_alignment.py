"""Unit tests for `window_ai_alignment` (#214): the window menu, the reply decoder
and the same-verse / cross-verse router, with hand-built alignments and no engine.

The protocol-level tests (fixture import, apply round-trip, writes-nothing) live in
`tests/service/test_window_ai_alignment_protocol.py`, per CLAUDE.md's rule that a
test driving an RPC belongs under `tests/service/`.
"""
from __future__ import annotations

import json

import pytest

from tc_ai_bridge import window_ai_alignment as window
from tc_ai_bridge.models import AlignmentGroup, TokenRef, VerseAlignment


def _top(word: str, strong: str, lemma: str = "") -> TokenRef:
    return TokenRef(word=word, strong=strong, lemma=lemma or word, morph="Gr,N,,,,,NMS,")


def _bottom(word: str) -> TokenRef:
    return TokenRef(word=word)


def _blank(tops: list[TokenRef], bottoms: list[TokenRef]) -> VerseAlignment:
    """A cold-start verse: every source token in its own empty group, every target
    word in the word bank -- exactly what a raw import produces."""
    return VerseAlignment([AlignmentGroup([t], []) for t in tops], list(bottoms))


THEOS, LOGOS, AGAPE = _top("θεός", "G23160"), _top("λόγος", "G30560"), _top("ἀγάπη", "G00260")
KADAVUL, VARTHAI, ANBU = _bottom("கடவுள்"), _bottom("வார்த்தை"), _bottom("அன்பு")


def _window():
    v3 = _blank([THEOS, LOGOS], [VARTHAI])
    v4 = _blank([AGAPE], [KADAVUL, ANBU])
    return [("3", v3, "வார்த்தை"), ("4", v4, "கடவுள் அன்பு")]


class TestBuildWindow:
    def test_every_token_is_offered_in_reading_order_with_opaque_handles(self):
        payload, sources, targets = window.build_window(
            _window(), reference="PHP 1:3-4", glosses={"G23160": "God"},
        )
        assert [v["verse"] for v in payload["verses"]] == ["3", "4"]
        assert [row["id"] for v in payload["verses"] for row in v["source"]] == ["S1", "S2", "S3"]
        assert [row["id"] for v in payload["verses"] for row in v["target"]] == ["T1", "T2", "T3"]
        # The model sees the gloss, never Bridge's positional ids.
        assert payload["verses"][0]["source"][0]["meaning"] == "God"
        assert "H001" not in json.dumps(payload) and "T001" not in json.dumps(payload)
        # The handle tables remember the positional ids the compiler needs.
        assert (sources["S1"].verse, sources["S1"].local_id) == ("3", "H001")
        assert (sources["S3"].verse, sources["S3"].local_id) == ("4", "H001")
        assert (targets["T2"].verse, targets["T2"].local_id) == ("4", "T001")
        assert payload["verses"][1]["translation"] == "கடவுள் அன்பு"

    def test_no_token_cap_a_long_window_is_offered_whole(self):
        tops = [_top(f"w{i}", f"G{i:05d}") for i in range(70)]
        bottoms = [_bottom(f"t{i}") for i in range(90)]
        payload, sources, targets = window.build_window(
            [("1", _blank(tops, bottoms), "x")], reference="PHP 1:1",
        )
        assert len(sources) == 70 and len(targets) == 90
        assert len(payload["verses"][0]["source"]) == 70


class TestDecode:
    def _tables(self):
        _, sources, targets = window.build_window(_window(), reference="PHP 1:3-4")
        return sources, targets

    def test_an_invented_id_is_refused_not_dropped(self):
        sources, targets = self._tables()
        with pytest.raises(ValueError, match="S9"):
            window.decode_reply(
                {"links": [{"source_id": "S9", "target_id": "T1", "confidence": 0.9, "reason": ""}]},
                sources, targets, error=ValueError,
            )
        with pytest.raises(ValueError, match="implicit"):
            window.decode_reply({"links": [], "implicit_source_ids": ["S42"]}, sources, targets, error=ValueError)

    def test_percent_confidence_is_scaled_and_duplicates_keep_the_first(self):
        sources, targets = self._tables()
        decoded = window.decode_reply({
            "links": [
                {"source_id": "S1", "target_id": "T2", "confidence": 85, "reason": "first"},
                {"source_id": "S1", "target_id": "T2", "confidence": 0.1, "reason": "second"},
            ],
            "implicit_source_ids": ["S2"],
            "target_only_ids": ["T3"],
            "review_notes": ["  a note ", ""],
        }, sources, targets, error=ValueError)
        assert len(decoded.edges) == 1
        assert decoded.edges[0]["confidence"] == pytest.approx(0.85)
        assert decoded.edges[0]["reason"] == "first"
        assert [e.handle for e in decoded.implicit] == ["S2"]
        assert [e.handle for e in decoded.target_only] == ["T3"]
        assert decoded.notes == ["a note"]


class TestRoute:
    def _decoded(self, links, **extra):
        _, sources, targets = window.build_window(_window(), reference="PHP 1:3-4")
        raw = {"links": links, "implicit_source_ids": [], "target_only_ids": [], "review_notes": []}
        raw.update(extra)
        return window.decode_reply(raw, sources, targets, error=ValueError)

    def test_a_same_verse_pick_is_compiled_into_that_verse_s_proposal(self):
        alignments = {v: a for v, a, _ in _window()}
        # S2 = λόγος (v3, H002) -> T1 = வார்த்தை (v3, T001)
        routed = window.route(self._decoded([
            {"source_id": "S2", "target_id": "T1", "confidence": 0.3, "reason": "the word"},
        ]), alignments, chapter="1")
        assert routed["crossVerseProposals"] == []
        assert [item["verse"] for item in routed["verseProposals"]] == ["3"]
        proposal = routed["verseProposals"][0]["proposal"]
        compiled = [g for g in proposal["groups"] if g["origin"] == "ai_compiled"]
        # Confidence 0.3 is below the compiler's default 0.72: every pick is a
        # proposal here, so the thresholds are 0 and the edge is still compiled.
        assert compiled == [{
            "top_ids": ["H002"], "bottom_ids": ["T001"], "confidence": 0.3,
            "reason": "the word", "origin": "ai_compiled", "relation": "one-to-one",
        }]
        assert proposal["thresholds"] == {"auto": 0.0, "review": 0.0}
        assert proposal["uncertain_links"] == []
        # θεός was not mentioned: it stays an explicit unresolved group, never dropped.
        assert any(g["top_ids"] == ["H001"] and g["origin"] == "unresolved" for g in proposal["groups"])

    def test_a_cross_verse_pick_is_an_acceptable_proposal_that_is_never_auto_linkable(self):
        alignments = {v: a for v, a, _ in _window()}
        # S1 = θεός (v3) -> T2 = கடவுள் (v4)
        routed = window.route(self._decoded([
            {"source_id": "S1", "target_id": "T2", "confidence": 0.9, "reason": "v.4 says God"},
        ]), alignments, chapter="1")
        assert routed["verseProposals"] == []
        [proposal] = routed["crossVerseProposals"]
        assert proposal["status"] == "PROPOSED"           # the strip offers Accept only on PROPOSED
        assert proposal["autoLinkable"] is False
        assert proposal["agreesWithCorpus"] is False
        assert proposal["source"] == {
            "chapter": "1", "verse": "3", "topId": "H001", "word": "θεός",
            "signature": THEOS.signature, "strong": "G23160", "lemma": "θεός",
        }
        assert proposal["target"] == {
            "chapter": "1", "verse": "4", "bottomId": "T001", "word": "கடவுள்", "signature": KADAVUL.signature,
        }
        assert proposal["evidence"][0]["kind"] == "MODEL_PICK"
        assert proposal["evidence"][0]["reason"] == "v.4 says God"

    def test_a_same_verse_claim_on_a_word_beats_a_cross_verse_pick_and_is_noted(self):
        alignments = {v: a for v, a, _ in _window()}
        routed = window.route(self._decoded([
            {"source_id": "S3", "target_id": "T2", "confidence": 0.8, "reason": "same verse"},   # ἀγάπη(v4) -> கடவுள்(v4)
            {"source_id": "S1", "target_id": "T2", "confidence": 0.9, "reason": "cross"},        # θεός(v3) -> கடவுள்(v4)
        ]), alignments, chapter="1")
        assert routed["crossVerseProposals"] == []
        assert routed["edges"] == {"sameVerse": 1, "crossVerse": 0, "dropped": 1}
        assert any("dropped in its favour" in note for note in routed["reviewNotes"])

    def test_two_cross_verse_picks_onto_one_word_keep_the_first(self):
        alignments = {v: a for v, a, _ in _window()}
        routed = window.route(self._decoded([
            {"source_id": "S1", "target_id": "T2", "confidence": 0.9, "reason": "a"},
            {"source_id": "S2", "target_id": "T2", "confidence": 0.9, "reason": "b"},
        ]), alignments, chapter="1")
        assert [p["source"]["topId"] for p in routed["crossVerseProposals"]] == ["H001"]
        assert routed["edges"]["dropped"] == 1

    def test_implicit_and_target_only_marks_reach_the_verse_compiler(self):
        alignments = {v: a for v, a, _ in _window()}
        routed = window.route(
            self._decoded([], implicit_source_ids=["S3"], target_only_ids=["T3"]),
            alignments, chapter="1",
        )
        [item] = routed["verseProposals"]
        assert item["verse"] == "4" and item["implicit"] == 1 and item["targetOnly"] == 1
        proposal = item["proposal"]
        assert any(g["top_ids"] == ["H001"] and g["origin"] == "implicit" for g in proposal["groups"])
        assert proposal["target_only_ids"] == ["T002"]


class TestProposeWindow:
    def test_nothing_to_ask_about_spends_no_request(self):
        calls: list = []
        result = window.propose_window(
            [("1", VerseAlignment([], []), "")],
            lambda *a: calls.append(a) or {},
            chapter="1", reference="PHP 1:1", source_name="Greek", target_name="Tamil",
        )
        assert calls == [] and result["modelConsulted"] is False
        assert result["verseProposals"] == [] and result["crossVerseProposals"] == []

    def test_too_many_verses_is_refused_before_any_request(self):
        verses = [(str(i), _blank([THEOS], [KADAVUL]), "x") for i in range(1, window.MAX_WINDOW_VERSES + 2)]
        with pytest.raises(ValueError, match="at most"):
            window.propose_window(
                verses, lambda *a: pytest.fail("must not call the model"),
                chapter="1", reference="PHP 1", source_name="Greek", target_name="Tamil", error=ValueError,
            )

    def test_the_prompt_carries_the_language_guidance_and_tells_the_model_boundaries_are_not_walls(self):
        seen: dict = {}

        def call_model(instructions: str, input_text: str) -> dict:
            seen["instructions"], seen["input"] = instructions, json.loads(input_text)
            return {"links": [], "implicit_source_ids": [], "target_only_ids": [], "review_notes": []}

        result = window.propose_window(
            _window(), call_model, chapter="1", reference="PHP 1:3-4",
            source_name="Koine Greek", target_name="Tamil", language_guidance="Tamil is agglutinative.",
        )
        assert result["modelConsulted"] is True
        assert "Koine Greek → Tamil" in seen["instructions"]
        assert "Tamil is agglutinative." in seen["instructions"]
        assert "ANOTHER verse in the window" in seen["instructions"]
        assert seen["input"]["reference"] == "PHP 1:3-4"
        assert result["window"] == {"sources": 3, "targets": 3}
