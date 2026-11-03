"""Persisted chapter reset, advanced one verse per dispatcher request.

No worker can race a project switch or a manual alignment write. Between
steps the UI can report progress, cancel, or resume after an application exit.
"""
import hashlib
import json
import uuid

from .alignment_engine import AlignmentError
from . import alignment_reset
from .workbench_repository import natural_row_id

KEY = "alignment-reset-chapter"


def status(project):
    rows = project.workbench.payloads("project_state", project_id=project.workbench_identity.project_id,
                                      book_id=project.book_id, equals={"key": KEY})
    return rows[0] if rows else {"state": "idle", "completed": 0, "total": 0}


def write(project, value):
    identity = project.workbench_identity
    project.workbench._write("project_state", natural_row_id(identity.project_id, project.book_id, KEY),
        project_id=identity.project_id, book_id=project.book_id, payload=value,
        actor_id=identity.actor_id, device_id=identity.device_id, expected_revision=None, extra_columns={"key": KEY})


def view(value):
    return {key: value.get(key) for key in ("id", "chapter", "state", "completed", "total", "error", "currentVerse")}


def preview(project, chapter):
    verses = [str(v) for v in project.verses(chapter) if str(v) != "front"]
    data = alignment_reset.snapshot(project, [(chapter, v) for v in verses])
    token = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    links = {link.get("groupId", link["id"]) for item in data.values() for link in item["links"]}
    return {"token": token, "verses": verses, "data": data, "groups": sum(
        bool(g["bottomWords"]) or len(g["topWords"]) > 1 for item in data.values() for g in item["alignment"]["alignments"]),
        "links": len(links), "decisions": sum(len(item["nulls"]) for item in data.values())}


def start(project, chapter, token):
    old = status(project)
    pending = alignment_reset.record(project)
    if pending and pending["state"] in {"resetting", "restoring"} and pending.get("jobId") != old.get("id"):
        raise AlignmentError(f"Resume the verse reset at {pending['chapter']}:{pending['verse']} first.")
    if old["state"] in {"running", "failed", "cancelled"} and old.get("chapter") == chapter and old.get("completed", 0) < old.get("total", 0):
        if old["state"] != "running":
            fresh = preview(project, chapter)
            if token != fresh["token"]:
                raise AlignmentError("Chapter changed since the reset preview.")
            for verse in old["verses"][old["completed"]:]:
                old["before"][f"{chapter}:{verse}"] = fresh["data"][f"{chapter}:{verse}"]
        old["state"] = "running"
        old["error"] = ""
        write(project, old)
        return view(old)
    if old["state"] == "running":
        raise AlignmentError("Finish or cancel the existing chapter reset first.")
    data = preview(project, chapter)
    if token != data["token"]:
        raise AlignmentError("Chapter alignment changed since the preview. Review the reset again.")
    value = {"id": uuid.uuid4().hex, "chapter": chapter, "state": "running", "completed": 0,
             "total": len(data["verses"]), "verses": data["verses"], "before": data["data"], "error": ""}
    write(project, value)
    return view(value)


def step(engine, job_id):
    project = engine.project
    value = status(project)
    if value.get("id") != job_id:
        raise AlignmentError("That chapter reset is no longer current.")
    if value["state"] != "running":
        return {"job": view(value), "contexts": []}
    if value["completed"] >= value["total"]:
        value["state"] = "succeeded"
        write(project, value)
        return {"job": view(value), "contexts": []}
    verse = value["verses"][value["completed"]]
    chapter = value["chapter"]
    value["currentVerse"] = verse
    write(project, value)
    try:
        last = alignment_reset.record(project)
        if last and last.get("jobId") == job_id and (last["chapter"], last["verse"]) == (chapter, verse) and last["state"] == "reset":
            if alignment_reset.snapshot(project, last["refs"]) != last["after"]:
                raise AlignmentError("Alignment changed after the interrupted chapter reset step.")
            result = {"contexts": [engine._alignment_context(chapter, verse)]}
        else:
            before = value["before"][f"{chapter}:{verse}"]
            if project.target_verse_text(chapter, verse) != before["text"]:
                raise AlignmentError(f"Text of {chapter}:{verse} changed. Remaining verses were not reset.")
            result = alignment_reset.reset(engine, chapter, verse, before["alignment"], job_id=job_id)
        value["completed"] += 1
        if value["completed"] == value["total"]:
            value["state"] = "succeeded"
        write(project, value)
        return {"job": view(value), "contexts": result["contexts"]}
    except Exception as exc:
        value["state"] = "failed"
        value["error"] = str(exc)
        write(project, value)
        return {"job": view(value), "contexts": []}


def cancel(project, job_id):
    value = status(project)
    if value.get("id") != job_id:
        raise AlignmentError("That chapter reset is no longer current.")
    if value["state"] == "running":
        value["state"] = "cancelled"
        write(project, value)
    return view(value)
