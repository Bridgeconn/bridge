"""Separate existing source tokens; never tokenize or rewrite source Scripture."""
import copy

from .alignment_engine import AlignmentError, make_inventory
from .models import AlignmentGroup
from .workbench_repository import natural_row_id


def layout(project, chapter, verse):
    key = f"alignment-source-layout:{chapter}:{verse}"
    values = project.workbench.payloads("project_state", project_id=project.workbench_identity.project_id,
        book_id=project.book_id, equals={"key": key})
    return values[0] if values else {}


def pending_split(project):
    values = project.workbench.payloads("project_state", project_id=project.workbench_identity.project_id,
                                      book_id=project.book_id)
    return next((v["pending"] for v in values if v.get("pending", {}).get("kind") == "sourceSplit"), None)


def write_layout(project, chapter, verse, value):
    key = f"alignment-source-layout:{chapter}:{verse}"
    identity = project.workbench_identity
    project.workbench._write("project_state", natural_row_id(identity.project_id, project.book_id, key),
        project_id=identity.project_id, book_id=project.book_id, payload=value,
        actor_id=identity.actor_id, device_id=identity.device_id, expected_revision=None, extra_columns={"key": key})


def split(engine, chapter, verse, top_id, direction, expected, undo=False):
    project = engine.project
    interrupted = pending_split(project)
    if interrupted and (interrupted["chapter"], interrupted["verse"]) != (chapter, verse):
        raise AlignmentError("Resume the interrupted source separation in its original verse first.")
    if direction not in {"left", "right"}:
        raise AlignmentError("Choose left or right for the separated word.")
    current = project.load_verse_alignment(chapter, verse)
    if current.to_dict() != expected:
        raise AlignmentError("Alignment changed. Reload before separating a source word.")
    inventory = make_inventory(current)
    token = inventory.top_ids.get(top_id)
    if token is None:
        raise AlignmentError("Source word no longer exists. Reload first.")
    old = layout(project, chapter, verse)
    pending = old.get("pending")
    if undo and not pending:
        pending = copy.deepcopy(old.get("lastSplit"))
        if not pending:
            raise AlignmentError("There is no cross-verse separation to undo.")
        pending["undo"] = True
    if pending:
        undo = bool(pending.get("undo"))
    if pending and (pending["signature"] != token.signature or pending["direction"] != direction):
        raise AlignmentError("Resume the interrupted source separation first.")
    group = next((g for g in current.alignments if any(t.signature == token.signature for t in g.top_words)), None)
    cross = next((g for g in engine._alignment_context(chapter, verse)["crossVerseGroups"]
                  if top_id in g["sourceTopIds"] and g["state"] == "active"), None)
    members = []
    if pending:
        members = pending["members"]
        signatures = list(dict.fromkeys(m["source"]["signature"] for m in members))
    elif cross and len(cross["sourceTopIds"]) > 1:
        # Keep the composite link's targets on the remaining source members.
        members = project.cross_verse_links.group_members(cross["groupId"])
        signatures = list(dict.fromkeys(m["source"]["signature"] for m in members))
    elif group and len(group.top_words) > 1:
        signatures = [t.signature for t in group.top_words]
    else:
        raise AlignmentError("Choose a source word in a group with several source words.")
    value = {"order": old.get("order") or [t.signature for t in inventory.top],
             "placements": {**old.get("placements", {}), token.signature: {"direction": direction, "members": signatures}}}
    if members:
        first = members[0]
        if not pending:
            pending = {"kind": "sourceSplit", "chapter": chapter, "verse": verse,
                "signature": token.signature, "direction": direction, "members": members,
                "source": current.to_dict(), "target": project.load_verse_alignment(first["target"]["chapter"], first["target"]["verse"]).to_dict(),
                "sourceText": project.target_verse_text(chapter, verse), "targetText": project.target_verse_text(first["target"]["chapter"], first["target"]["verse"])}
        if pending["source"] != current.to_dict() or pending["target"] != project.load_verse_alignment(first["target"]["chapter"], first["target"]["verse"]).to_dict() or pending["sourceText"] != project.target_verse_text(chapter, verse) or pending["targetText"] != project.target_verse_text(first["target"]["chapter"], first["target"]["verse"]):
            raise AlignmentError("Text or alignment changed during source-separation recovery.")
        value["pending"] = pending
    value["lastSplit"] = old.get("lastSplit")
    key = f"alignment-source-layout:{chapter}:{verse}"
    identity = project.workbench_identity
    # Record only personal display placement. If the save fails the preference
    # is dormant because the token is still in the joined group.
    if not members:
        project.workbench._write("project_state", natural_row_id(identity.project_id, project.book_id, key),
            project_id=identity.project_id, book_id=project.book_id, payload=value,
            actor_id=identity.actor_id, device_id=identity.device_id, expected_revision=None, extra_columns={"key": key})
    if members:
        # Removing selected pair rows alone would destroy the group claim. The
        # store removes/replaces the entire group and journals both changes.
        first = members[0]
        sources = [t for t in inventory.top if t.signature in signatures and (undo or t.signature != token.signature)]
        target_inv = make_inventory(project.load_verse_alignment(first["target"]["chapter"], first["target"]["verse"]))
        target_sigs = {m["target"]["signature"] for m in members}
        targets = [t for t in target_inv.bottom if t.signature in target_sigs]
        from .cross_verse_links import group_of, group_id_for, _end
        original_group = pending["newGroupId"] if undo else group_of(first)
        target_chapter, target_verse = first["target"]["chapter"], first["target"]["verse"]
        desired_group = group_id_for([_end(chapter, verse, t, source=True) for t in sources],
                                    [_end(target_chapter, target_verse, t, source=False) for t in targets])
        # Validate all homes before unlinking anything, including a word
        # separated earlier and since assigned by another manual operation.
        for side, tokens, c, v in [("source", sources, chapter, verse), ("target", targets, target_chapter, target_verse)]:
            for item in tokens:
                engine._refuse_if_null_decided(c, v, side, item)
                if any(group_of(link) not in {original_group, desired_group} for link in engine._active_links_for_end(c, v, side, item.signature)):
                    raise AlignmentError("A word acquired a different cross-verse home. Undo would overwrite newer work.")
        project.workbench._write("project_state", natural_row_id(identity.project_id, project.book_id, key),
            project_id=identity.project_id, book_id=project.book_id, payload=value,
            actor_id=identity.actor_id, device_id=identity.device_id, expected_revision=None, extra_columns={"key": key})
        existing_new = project.cross_verse_links.group_members(desired_group)
        if existing_new and len(existing_new) != len(sources) * len(targets):
            # A crash can interrupt the existing store's pair-by-pair writes.
            # Rebuild the whole intended composite group, never bless a subset.
            project.cross_verse_links.unlink_group(desired_group, origin="human")
            existing_new = []
        if project.cross_verse_links.group_members(original_group):
            project.cross_verse_links.unlink_group(original_group, origin="human")
        try:
            if not existing_new:
                project.cross_verse_links.link_group(chapter, verse, sources,
                first["target"]["chapter"], first["target"]["verse"], targets, origin="human")
        except Exception:
            # The durable pending snapshot remains; the next explicit resume
            # repairs the complete group through these same writers.
            raise
        value.pop("pending", None)
        if not undo:
            value["lastSplit"] = {**pending, "newGroupId": desired_group}
        else:
            value["placements"].pop(token.signature, None)
            value.pop("lastSplit", None)
        project.workbench._write("project_state", natural_row_id(identity.project_id, project.book_id, key),
            project_id=identity.project_id, book_id=project.book_id, payload=value,
            actor_id=identity.actor_id, device_id=identity.device_id, expected_revision=None, extra_columns={"key": key})
        return {"contexts": [engine._finish_alignment_mutation(chapter, verse),
            engine._finish_alignment_mutation(first["target"]["chapter"], first["target"]["verse"])]}
    proposed = copy.deepcopy(current)
    result = []
    for original in proposed.alignments:
        if any(t.signature == token.signature for t in original.top_words):
            remaining = [t for t in original.top_words if t.signature != token.signature]
            result.extend([AlignmentGroup(remaining, original.bottom_words), AlignmentGroup([token], [])])
        else:
            result.append(original)
    proposed.alignments = result
    return {"contexts": [engine._save_alignment(chapter, verse, proposed, expected, "splitSource")]}
