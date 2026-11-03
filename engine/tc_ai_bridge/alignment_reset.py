"""Explicit, resumable verse reset (#381), over the existing alignment writers.

The workbench intent survives a process interruption between file and SQLite
writes. It retains before snapshots; recovery repeats only idempotent steps.
An incomplete operation blocks other alignment writes until resumed.
"""
from __future__ import annotations

import copy
import hashlib
import json
import uuid

from .alignment_engine import AlignmentError, make_inventory
from .models import AlignmentGroup, VerseAlignment
from .cross_verse_links import group_of
from .workbench_repository import natural_row_id
from . import alignment_source_split

KEY = "alignment-reset"


def record(project):
    identity = project.workbench_identity
    rows = project.workbench.payloads("project_state", project_id=identity.project_id,
                                      book_id=project.book_id, equals={"key": KEY})
    return rows[0] if rows else None


def write(project, value):
    identity = project.workbench_identity
    project.workbench._write("project_state", natural_row_id(identity.project_id, project.book_id, KEY),
        project_id=identity.project_id, book_id=project.book_id, payload=value,
        actor_id=identity.actor_id, device_id=identity.device_id, expected_revision=None,
        extra_columns={"key": KEY})


def snapshot(project, refs):
    return {f"{c}:{v}": {
        "alignment": project.load_verse_alignment(c, v).to_dict(),
        "text": project.target_verse_text(c, v),
        "layout": alignment_source_split.layout(project, c, v),
        "links": sorted(project.cross_verse_links.links_for_verse(c, v), key=lambda x: x["id"]),
        "nulls": sorted(project.null_decisions.decisions_for_verse(c, v), key=lambda x: x["id"]),
    } for c, v in refs}


def summary(project, chapter, verse):
    value = record(project)
    pending = value and value["state"] in {"resetting", "restoring"}
    own = value and (value["chapter"], value["verse"]) == (chapter, verse)
    links = project.cross_verse_links.links_for_verse(chapter, verse)
    refs = {(chapter, verse)}
    for link in links:
        refs.update((link[side]["chapter"], link[side]["verse"]) for side in ("source", "target"))
    current = snapshot(project, refs)
    alignment = current[f"{chapter}:{verse}"]["alignment"]
    return {"pending": bool(pending), "chapter": value["chapter"] if value else "",
            "verse": value["verse"] if value else "", "state": value["state"] if value else "",
            "token": hashlib.sha256(json.dumps(current, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest(),
            "alignment": alignment, "partners": [f"{c}:{v}" for c, v in sorted(refs) if (c, v) != (chapter, verse)],
            "groups": sum(bool(g["bottomWords"]) or len(g["topWords"]) > 1 for g in alignment["alignments"]),
            "links": len({group_of(link) for link in links}), "decisions": len(current[f"{chapter}:{verse}"]["nulls"]),
            "canUndo": bool(own and value["state"] == "reset" and snapshot(project, value["refs"]) == value.get("after"))}


def reset(engine, chapter, verse, expected, job_id="", expected_state_token=None):
    project = engine.project
    chapter, verse = str(chapter), str(verse)
    if verse not in project.verses(chapter):
        raise AlignmentError("That verse does not exist.")
    value = record(project)
    if value and value["state"] in {"resetting", "restoring"}:
        if (chapter, verse) != (value["chapter"], value["verse"]):
            raise AlignmentError(f"Resume the alignment reset at {value['chapter']}:{value['verse']} first.")
        if value["state"] == "restoring":
            return restore(engine, chapter, verse)
    else:
        if expected_state_token is not None and expected_state_token != summary(project, chapter, verse)["token"]:
            raise AlignmentError("Alignment or cross-verse decisions changed since the reset preview. Review it again.")
        current = project.load_verse_alignment(chapter, verse)
        if current.to_dict() != expected:
            raise AlignmentError("Alignment changed. Reload before resetting.")
        links = project.cross_verse_links.links_for_verse(chapter, verse)
        nulls = project.null_decisions.decisions_for_verse(chapter, verse)
        if not any(g.bottom_words for g in current.alignments) and not links and not nulls and all(len(g.top_words) <= 1 for g in current.alignments):
            return {"contexts": [engine._alignment_context(chapter, verse)], "changed": False}
        refs = {(chapter, verse)}
        for link in links:
            for side in ("source", "target"):
                refs.add((link[side]["chapter"], link[side]["verse"]))
        inv = make_inventory(current)
        cleared = VerseAlignment([AlignmentGroup([t], []) for t in inv.top], inv.bottom).to_dict()
        value = {"id": uuid.uuid4().hex, "chapter": chapter, "verse": verse,
                 "refs": sorted(refs), "state": "resetting", "jobId": job_id, "before": snapshot(project, refs),
                 "cleared": cleared, "links": links, "nulls": nulls,
                 "verdict": engine._auto_verdict(chapter, verse)}
        write(project, value)
    # Recheck native/text snapshots even during recovery; never overwrite a new edit.
    for key, old in value["before"].items():
        c, v = key.split(":", 1)
        current = project.load_verse_alignment(c, v).to_dict()
        allowed = [old["alignment"]] + ([value["cleared"]] if (c, v) == (chapter, verse) else [])
        if current not in allowed or project.target_verse_text(c, v) != old["text"]:
            raise AlignmentError("A verse changed during reset recovery. Restore its snapshot before resuming.")
    for link in value["links"]:
        existing = project.cross_verse_links.get(link["id"])
        if existing is not None and existing != link:
            raise AlignmentError("A cross-verse decision changed during reset recovery.")
        if project.cross_verse_links.get(link["id"]):
            project.cross_verse_links.unlink(link["id"], origin="human", extra={"resetId": value["id"]})
    for decision in value["nulls"]:
        existing = project.null_decisions.get(decision["id"])
        if existing is not None and existing != decision:
            raise AlignmentError("A no-counterpart decision changed during reset recovery.")
        if project.null_decisions.get(decision["id"]):
            project.null_decisions.clear(decision["id"], extra={"resetId": value["id"]})
    old_layout = value["before"][f"{chapter}:{verse}"].get("layout", {})
    if old_layout:
        alignment_source_split.write_layout(project, chapter, verse, {"order": old_layout.get("order", []), "placements": {}})
    current = project.load_verse_alignment(chapter, verse).to_dict()
    if current != value["cleared"]:
        engine._save_alignment(chapter, verse, VerseAlignment.from_dict(value["cleared"]), current, "reset")
    if value["verdict"]:
        engine._write_auto_verdict(chapter, verse, {**value["verdict"], "verdict": "REVERTED", "applied": {}})
    contexts = [engine._finish_alignment_mutation(c, v) for c, v in value["refs"]]
    value["state"] = "reset"
    value["after"] = snapshot(project, value["refs"])
    write(project, value)
    return {"contexts": contexts, "changed": True}


def restore(engine, chapter, verse):
    project = engine.project
    value = record(project)
    if not value or (value["chapter"], value["verse"]) != (chapter, verse) or value["state"] not in {"reset", "restoring"}:
        raise AlignmentError("There is no reset to undo for this verse.")
    if value["state"] == "reset":
        if snapshot(project, value["refs"]) != value["after"]:
            raise AlignmentError("Alignment changed after reset. Undo reset would overwrite newer work.")
        value["state"] = "restoring"
        write(project, value)
    # The main reset intent prevents any competing alignment writes during recovery.
    for key, before in value["before"].items():
        c, v = key.split(":", 1)
        native = project.load_verse_alignment(c, v).to_dict()
        if native not in [before["alignment"], value["after"][key]["alignment"]] or project.target_verse_text(c, v) != before["text"]:
            raise AlignmentError("Verse text or alignment changed during undo recovery.")
    before = value["before"][f"{chapter}:{verse}"]["alignment"]
    current = project.load_verse_alignment(chapter, verse).to_dict()
    if current != before:
        engine._save_alignment(chapter, verse, VerseAlignment.from_dict(before), current, "restoreReset")
    groups = {}
    for link in value["links"]:
        groups.setdefault(group_of(link), []).append(link)
    for members in groups.values():
        first = members[0]
        existing = [project.cross_verse_links.get(member["id"]) for member in members]
        if all(existing):
            continue
        # A process may stop between the individual pair writes of an N x M
        # group. Rebuild that partial group rather than treating its first row
        # as proof that the whole realization was restored.
        partial = next((member for member in existing if member), None)
        if partial:
            project.cross_verse_links.unlink(partial["id"], origin="human", extra={"resetId": value["id"]})
        def refs(side):
            out = {}
            for member in members:
                end = member[side]
                inv = make_inventory(project.load_verse_alignment(end["chapter"], end["verse"]))
                ids = inv.top_sig_to_id if side == "source" else inv.bottom_sig_to_id
                out[end["signature"]] = {"chapter": end["chapter"], "verse": end["verse"],
                    "topId" if side == "source" else "bottomId": ids[end["signature"]]}
            return list(out.values())
        if first.get("state") == "active":
            engine.link_cross_verse(None, None, sources=refs("source"), targets=refs("target"), origin="human")
        else:
            for member in members:
                project.cross_verse_links._write_row(copy.deepcopy(member))
                project.cross_verse_links._event(member["id"], "crossVerseRestoreReset", member)
    for decision in value["nulls"]:
        if project.null_decisions.get(decision["id"]):
            continue
        inv = make_inventory(project.load_verse_alignment(chapter, verse))
        ids = inv.top_sig_to_id if decision["side"] == "source" else inv.bottom_sig_to_id
        if decision.get("state") == "active":
            engine.set_null_decision({"chapter": chapter, "verse": verse, "side": decision["side"],
                "id": ids[decision["token"]["signature"]], "reason": decision["reason"], "note": decision.get("note", "")})
        else:
            project.null_decisions._write_row(copy.deepcopy(decision))
            project.null_decisions._event(decision["id"], "nullRestoreReset", decision)
    if value["verdict"]:
        # Restored links are human restores, not writes still owned by an AI run.
        engine._write_auto_verdict(chapter, verse, {**value["verdict"], "verdict": "REVERTED", "applied": {}})
    alignment_source_split.write_layout(project, chapter, verse, copy.deepcopy(value["before"][f"{chapter}:{verse}"].get("layout", {})))
    contexts = [engine._finish_alignment_mutation(c, v) for c, v in value["refs"]]
    value["state"] = "restored"
    write(project, value)
    return {"contexts": contexts, "changed": True}
