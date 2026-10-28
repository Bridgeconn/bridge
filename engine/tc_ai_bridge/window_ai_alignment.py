"""Passage-level AI alignment for cold-start projects (#214).

`cross_verse_ai_proposals.py` (#146) hands a model the *gap* tokens of a range and
forbids same-verse pairs: it is a gap filler for a chapter that is mostly aligned
already. On a freshly imported book every word is a gap, the right home for nearly
all of them is their own verse, and the 40/60 handle cap truncates the range -- so
a careful model correctly returns nothing (#188, #208). This module asks a different
question: *here is a short window of verses, source and translation in reading
order; which source word does each target word realize, wherever it sits.*

**What this keeps from #146, deliberately.** The model picks from a closed menu of
opaque `S*`/`T*` handles over the whole window, never Bridge's own ids; an id it
invents raises rather than being dropped. The window is bounded by verse count
(`MAX_WINDOW_VERSES`), not by a token cap, so nothing is silently truncated.

**What this changes.** A same-verse pick is *routed*, not discarded: edges whose
two ends share a verse are compiled per verse by
`alignment_reliability.compile_link_proposal` into legal translationCore groups,
exactly as the single-verse `alignment.aiPropose` did. Edges that cross a verse
boundary become proposals in the cross-verse strip's shape.

**Nothing here writes, and nothing it returns is applied without a click.** A
same-verse proposal is written only by `alignment.aiApplyProposal`, one verse per
click; a cross-verse proposal only by `alignment.crossVerse.link`, one pair per
Accept. Both are the existing writers. The maintainer decided on 2026-10-07 that on
a cold project every pick is a proposal: there is no second independent method to
agree with, so `autoLinkable` is always False here and the #146 agreement gate is
left exactly as it was. The compiler is therefore run with both of its confidence
thresholds at 0.0 -- the gate is the reviewer's per-verse Apply, not a number, and
the model's confidence is carried on every group as evidence about the model, not
as something known to mean anything (`WINDOW_CALIBRATION_VERSION`).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from .alignment_engine import make_inventory
from .alignment_reliability import compile_link_proposal
from .models import TokenRef, VerseAlignment

WINDOW_CALIBRATION_VERSION = "window-ai-uncalibrated-v1"

#: A window is bounded in verses, not tokens. Five unaligned verses of Greek is
#: roughly a hundred handles a side, well inside one request; a whole chapter is
#: a sequence of windows (a later slice), not one prompt.
MAX_WINDOW_VERSES = 5
DEFAULT_WINDOW_VERSES = 3

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["links", "implicit_source_ids", "target_only_ids", "review_notes"],
    "properties": {
        "links": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["source_id", "target_id", "confidence", "reason"],
                "properties": {
                    "source_id": {"type": "string"},
                    "target_id": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "reason": {"type": "string"},
                },
            },
        },
        "implicit_source_ids": {"type": "array", "items": {"type": "string"}},
        "target_only_ids": {"type": "array", "items": {"type": "string"}},
        "review_notes": {"type": "array", "items": {"type": "string"}},
    },
}


def build_instructions(*, source_name: str, target_name: str, language_guidance: str) -> str:
    """The prompt. Same discipline as `ai_client.propose_alignment`'s single-verse
    one (individual edges, closed id menu, implicit and target-only lists), widened
    to a window and told explicitly that a verse boundary is not a wall."""
    guidance = f" {language_guidance.strip()}" if language_guidance and language_guidance.strip() else ""
    return (
        f"You are a Bible translation word-alignment reviewer for {source_name} → {target_name}. "
        "You are given a short window of consecutive verses: for each verse, the original-language "
        "source words in order (with Strong's number, lemma and a short English meaning) and the "
        "translation's words in order. Return INDIVIDUAL linguistic links from a source word to the "
        "target word that realizes it. The application compiles links deterministically into legal "
        "alignment groups; you never build groups yourself.\n"
        "Rules:\n"
        "- Use ONLY the `id` values given. Never invent an id, a word or a verse.\n"
        "- A target word may realize a source word from its OWN verse or from ANOTHER verse in the "
        "window. Translators redistribute meaning across verse boundaries, so when a verse's "
        "translation carries a clause from a neighbouring verse, link across the boundary. Do not "
        "force a source word onto its own verse when its meaning is plainly carried elsewhere.\n"
        "- Several source words may link to one target word and one source word to several target "
        "words; return each edge separately. Confidence (0-1) belongs to that individual edge.\n"
        "- Put a source id in `implicit_source_ids` only when its meaning is genuinely carried "
        "grammatically with no separate target word (an article absorbed into a case ending, a "
        "particle rendered by word order). Put a target id in `target_only_ids` only when it is "
        "target-language grammatical or natural material with no source counterpart.\n"
        "- Omit an edge rather than guess. A short, correct list is worth more than a complete one.\n"
        "- `reason` is one short sentence a reviewer who reads neither original language can check."
        f"{guidance} English or reference word order is secondary and must not control the "
        "alignment. Return only the schema."
    )


@dataclass
class WindowEntry:
    """One token of the window: its opaque handle, its verse, and the positional id
    (`H001`/`T001`) that `make_inventory` gives it inside that verse -- which is what
    the compiler, the link store and the frontend all key on."""

    handle: str
    verse: str
    local_id: str
    token: TokenRef


@dataclass
class DecodedWindow:
    edges: list[dict[str, Any]] = field(default_factory=list)
    implicit: list[WindowEntry] = field(default_factory=list)
    target_only: list[WindowEntry] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def build_window(
    verses: list[tuple[str, VerseAlignment, str]],
    *,
    reference: str,
    glosses: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, WindowEntry], dict[str, WindowEntry]]:
    """Build the payload and the two handle tables that decode the reply.

    `verses` is `(verse, alignment, plain target text)` in reading order; verse
    strings stay opaque throughout (bridges "3-4", segments "3a" -- CLAUDE.md gotcha
    12). Every token of every verse is offered: on a cold project that *is* the gap
    list, and on a warm one the compiler protects what is already aligned.
    """
    glosses = glosses or {}
    sources: dict[str, WindowEntry] = {}
    targets: dict[str, WindowEntry] = {}
    payload_verses: list[dict[str, Any]] = []
    for verse, alignment, text in verses:
        inventory = make_inventory(alignment)
        source_rows: list[dict[str, Any]] = []
        for local_id, token in inventory.top_ids.items():
            handle = f"S{len(sources) + 1}"
            sources[handle] = WindowEntry(handle, verse, local_id, token)
            row: dict[str, Any] = {
                "id": handle,
                "word": token.word,
                "lemma": token.lemma or "",
                "strong": token.strong or "",
                "occurrence": token.occurrence,
                "occurrences": token.occurrences,
            }
            gloss = glosses.get(str(token.strong or ""), "")
            if gloss:
                row["meaning"] = gloss
            source_rows.append(row)
        target_rows: list[dict[str, Any]] = []
        for local_id, token in inventory.bottom_ids.items():
            handle = f"T{len(targets) + 1}"
            targets[handle] = WindowEntry(handle, verse, local_id, token)
            target_rows.append({
                "id": handle, "word": token.word,
                "occurrence": token.occurrence, "occurrences": token.occurrences,
            })
        payload_verses.append({
            "verse": verse, "source": source_rows, "translation": text, "target": target_rows,
        })
    return {"reference": reference, "verses": payload_verses}, sources, targets


def _confidence(value: Any) -> float:
    """Clamp to 0..1. A provider that answers in percent (an integer above 1) is
    scaled rather than clamped to 1.0, which would have read as certainty."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number > 1.0:
        number = number / 100.0
    return max(0.0, min(1.0, number))


def decode_reply(
    raw: dict[str, Any],
    sources: dict[str, WindowEntry],
    targets: dict[str, WindowEntry],
    *,
    error: Callable[[str], Exception],
) -> DecodedWindow:
    """Resolve handles back to tokens, refusing anything invented.

    An unknown handle raises: a model returning ids Bridge never sent is a sign
    the prompt or the provider is wrong, and dropping it quietly would hide that
    for good (same rule as `cross_verse_ai_proposals._decode_links`). A duplicate
    edge keeps its first occurrence.
    """
    if not isinstance(raw, dict):
        raise error("The model's window-alignment reply was not a JSON object.")
    decoded = DecodedWindow()
    links = raw.get("links")
    if links is None:
        links = []
    if not isinstance(links, list):
        raise error("The model's window-alignment reply had a 'links' field that was not a list.")
    seen: set[tuple[str, str]] = set()
    for item in links:
        if not isinstance(item, dict):
            raise error("The model returned a window-alignment link that was not an object.")
        source_handle = str(item.get("source_id") or "")
        target_handle = str(item.get("target_id") or "")
        if source_handle not in sources:
            raise error(
                f"The model returned source id {source_handle!r}, which was not in the list it was given."
            )
        if target_handle not in targets:
            raise error(
                f"The model returned target id {target_handle!r}, which was not in the list it was given."
            )
        key = (source_handle, target_handle)
        if key in seen:
            continue
        seen.add(key)
        decoded.edges.append({
            "source": sources[source_handle],
            "target": targets[target_handle],
            "confidence": _confidence(item.get("confidence", 0)),
            "reason": str(item.get("reason") or "").strip(),
        })
    for handle in _string_list(raw.get("implicit_source_ids"), error, "implicit_source_ids"):
        if handle not in sources:
            raise error(f"The model marked source id {handle!r} implicit, which was not in the list it was given.")
        decoded.implicit.append(sources[handle])
    for handle in _string_list(raw.get("target_only_ids"), error, "target_only_ids"):
        if handle not in targets:
            raise error(f"The model marked target id {handle!r} target-only, which was not in the list it was given.")
        decoded.target_only.append(targets[handle])
    notes = raw.get("review_notes")
    if isinstance(notes, list):
        decoded.notes = [str(note).strip() for note in notes if str(note).strip()]
    return decoded


def _string_list(value: Any, error: Callable[[str], Exception], name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise error(f"The model's window-alignment reply had a '{name}' field that was not a list.")
    return [str(x) for x in value if str(x)]


def _cross_verse_proposal(edge: dict[str, Any], *, chapter: str) -> dict[str, Any]:
    """The cross-verse strip's proposal shape (`cross_verse_proposals.propose`),
    so the UI renders it through the one path it already has.

    `status` is PROPOSED, not AMBIGUOUS: the strip offers Accept only on PROPOSED,
    and the maintainer's decision is that every pick is acceptable. `autoLinkable`
    is False and `agreesWithCorpus` is False, always -- see the module docstring.
    """
    source: WindowEntry = edge["source"]
    target: WindowEntry = edge["target"]
    return {
        "status": "PROPOSED",
        "confidence": round(edge["confidence"], 4),
        "margin": 0.0,
        "contested": False,
        "agreesWithCorpus": False,
        "autoLinkable": False,
        "source": {
            "chapter": chapter, "verse": source.verse, "topId": source.local_id,
            "word": source.token.word, "signature": source.token.signature,
            "strong": source.token.strong or "", "lemma": source.token.lemma or "",
        },
        "target": {
            "chapter": chapter, "verse": target.verse, "bottomId": target.local_id,
            "word": target.token.word, "signature": target.token.signature,
        },
        "evidence": [{
            "kind": "MODEL_PICK",
            "rawScore": round(edge["confidence"], 4),
            "weight": 1.0,
            "weightedScore": round(edge["confidence"], 4),
            "modelConfidence": int(round(edge["confidence"] * 100)),
            "reason": edge["reason"],
        }],
        "alternatives": [],
    }


def route(
    decoded: DecodedWindow,
    alignments: dict[str, VerseAlignment],
    *,
    chapter: str,
) -> dict[str, Any]:
    """Split the model's edges by where their ends sit, and compile each side.

    Same-verse edges, implicit marks and target-only marks go to the per-verse
    compiler in `gap_fill` mode (existing non-empty groups stay protected, so on a
    warm project the model cannot remap a human's work). A verse with nothing to
    say gets no proposal: applying an empty one would change nothing.

    A target word claimed by a same-verse edge wins over a cross-verse edge onto
    the same word: translationCore alignment data is where that word's group
    lives, and a cross-verse link onto an aligned word would be refused on Accept
    anyway. The drop is recorded in `reviewNotes`, not swallowed.
    """
    same_by_verse: dict[str, list[dict[str, Any]]] = {}
    claimed_same_verse: set[tuple[str, str]] = set()
    cross_edges: list[dict[str, Any]] = []
    for edge in decoded.edges:
        source: WindowEntry = edge["source"]
        target: WindowEntry = edge["target"]
        if source.verse == target.verse:
            same_by_verse.setdefault(source.verse, []).append(edge)
            claimed_same_verse.add((target.verse, target.local_id))
        else:
            cross_edges.append(edge)

    notes = list(decoded.notes)
    cross_proposals: list[dict[str, Any]] = []
    seen_targets: set[tuple[str, str]] = set()
    dropped = 0
    for edge in cross_edges:
        target: WindowEntry = edge["target"]
        key = (target.verse, target.local_id)
        if key in claimed_same_verse:
            dropped += 1
            notes.append(
                f"{chapter}:{target.verse} “{target.token.word}” was also linked within its own "
                f"verse; the cross-verse pick from {chapter}:{edge['source'].verse} "
                f"“{edge['source'].token.word}” was dropped in its favour."
            )
            continue
        if key in seen_targets:
            # One target word realizes one source word across verses; a second
            # pick onto it cannot be accepted after the first, so it is a note.
            dropped += 1
            notes.append(
                f"{chapter}:{target.verse} “{target.token.word}” was picked by two source words "
                f"in other verses; only the first was kept."
            )
            continue
        seen_targets.add(key)
        cross_proposals.append(_cross_verse_proposal(edge, chapter=chapter))

    implicit_by_verse: dict[str, list[str]] = {}
    for entry in decoded.implicit:
        implicit_by_verse.setdefault(entry.verse, []).append(entry.local_id)
    target_only_by_verse: dict[str, list[str]] = {}
    for entry in decoded.target_only:
        target_only_by_verse.setdefault(entry.verse, []).append(entry.local_id)

    verse_proposals: list[dict[str, Any]] = []
    for verse, alignment in alignments.items():
        edges = same_by_verse.get(verse, [])
        implicit = implicit_by_verse.get(verse, [])
        target_only = target_only_by_verse.get(verse, [])
        if not edges and not implicit:
            continue
        raw_for_compiler = {
            "links": [
                {
                    "top_id": edge["source"].local_id,
                    "bottom_id": edge["target"].local_id,
                    "confidence": edge["confidence"],
                    "reason": edge["reason"],
                }
                for edge in edges
            ],
            "implicit_top_ids": implicit,
            "target_only_ids": target_only,
            "review_notes": [],
        }
        proposal = compile_link_proposal(
            alignment, raw_for_compiler, mode="gap_fill",
            # Every pick is a proposal the reviewer applies per verse; a threshold
            # on the model's own number would be a second, uncalibrated gate.
            auto_threshold=0.0, review_threshold=0.0,
        )
        compiled = [g for g in proposal["groups"] if g.get("origin") in ("ai_compiled", "extended_protected")]
        verse_proposals.append({
            "verse": verse,
            "proposal": proposal,
            "edges": len(edges),
            "compiledGroups": len(compiled),
            "implicit": len(implicit),
            "targetOnly": len(target_only),
            "conflicts": len(proposal.get("conflicts") or []),
        })

    return {
        "verseProposals": verse_proposals,
        "crossVerseProposals": cross_proposals,
        "reviewNotes": notes,
        "edges": {
            "sameVerse": sum(len(v) for v in same_by_verse.values()),
            "crossVerse": len(cross_proposals),
            "dropped": dropped,
        },
    }


def propose_window(
    verses: list[tuple[str, VerseAlignment, str]],
    call_model: Callable[[str, str], dict[str, Any]],
    *,
    chapter: str,
    reference: str,
    source_name: str,
    target_name: str,
    language_guidance: str = "",
    glosses: dict[str, str] | None = None,
    error: Callable[[str], Exception] = RuntimeError,
) -> dict[str, Any]:
    """Ask the model about one window and route its answer.

    `call_model(instructions, input_json)` is injected rather than a client so
    this stays testable without a key or a transport (the #146 pattern).
    """
    if not verses:
        raise error("A window needs at least one verse.")
    if len(verses) > MAX_WINDOW_VERSES:
        raise error(
            f"A window is at most {MAX_WINDOW_VERSES} verses; {len(verses)} were requested. "
            "Narrow the range, or run it as consecutive windows."
        )
    payload, sources, targets = build_window(verses, reference=reference, glosses=glosses)
    base = {
        "chapter": chapter,
        "verses": [verse for verse, _, _ in verses],
        "window": {"sources": len(sources), "targets": len(targets)},
        "calibrationVersion": WINDOW_CALIBRATION_VERSION,
    }
    if not sources or not targets:
        # Nothing to ask about: a verse with no source tokens (no bundled original)
        # or no target words. A billed round trip would only say so.
        return {
            **base, "modelConsulted": False,
            "verseProposals": [], "crossVerseProposals": [], "reviewNotes": [],
            "edges": {"sameVerse": 0, "crossVerse": 0, "dropped": 0},
        }
    instructions = build_instructions(
        source_name=source_name, target_name=target_name, language_guidance=language_guidance,
    )
    raw = call_model(instructions, json.dumps(payload, ensure_ascii=False))
    decoded = decode_reply(raw, sources, targets, error=error)
    routed = route(decoded, {verse: alignment for verse, alignment, _ in verses}, chapter=chapter)
    return {**base, "modelConsulted": True, **routed}
