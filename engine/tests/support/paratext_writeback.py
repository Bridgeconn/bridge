"""Builders for the Paratext write-back tests (#347, #358): a tN-indexed book
linked to a real (synthetic) Paratext folder, so the notes index can be
ready, and a stand-in for connector 0.8.0 on its pipe."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tc_ai_bridge import paratext_link
from tc_ai_bridge.paratext_connector import ConnectorState, ParatextConnectorError
from tc_ai_bridge.secret_store import AppSettings
from tests.support.paratext_fixture import DEFAULT_GUID, build_paratext_project, write_notes_file
from tests.support.projects import call, tn_review_project

OTHER_GUID = "4ae31b0d0f1be38681160e73e9ae9b566dd4459d"
CAPABILITIES_080 = ["state", "navigation", "selection", "project_notes", "project_list",
                    "create_note", "list_notes", "add_comment", "resolve_note"]
CAPABILITIES_074 = ["state", "navigation", "selection", "project_notes"]
DVT = {"id": OTHER_GUID, "short_name": "DVT", "editable": True}
IRVT = {"id": DEFAULT_GUID, "short_name": "IRVT", "editable": True}


def open_linked_review_project(tmp_path: Path, monkeypatch) -> tuple[Any, Path]:
    """(engine, Paratext folder): the one-verse Titus of `tn_review_project`,
    linked to the Paratext project IRVT (DEFAULT_GUID) whose folder exists, and
    the notes index built. No real Paratext projects folder is searched."""
    from bridge_service import BridgeEngine

    projects = tmp_path / "pt-projects"
    projects.mkdir(exist_ok=True)
    monkeypatch.setattr(paratext_link, "paratext_projects_dir", lambda *a, **k: projects)
    folder = build_paratext_project(projects, name="IRVT")
    root = tn_review_project(tmp_path / "tit", paratext_guid=DEFAULT_GUID, paratext_name="IRVT",
                             paratext_folder=str(folder))
    engine = BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json"))
    opened = call(engine, "project.open", {"path": str(root)})
    assert opened["success"] is True, opened
    assert engine._paratext_session().wait_for_notes_index(30) == "ready"
    return engine, folder


def reread_notes(engine) -> None:
    """Refresh the link and wait for the notes index to match the files."""
    assert call(engine, "paratext.refresh")["success"] is True
    assert engine._paratext_session().wait_for_notes_index(30) == "ready"


def write_thread(folder: Path, thread: str, contents: list[str], *, user: str = "Translator",
                 date: str = "2026-10-20T08:00:00.0000000+05:30", status: str = "todo") -> None:
    write_notes_file(folder, user, [{"thread": thread, "verse_ref": "TIT 1:1", "date": date,
                                     "status": status, "contents": contents}])


def saved_resolution(engine) -> str:
    """An issue resolution on TIT 1:1, through the review panel's RPCs."""
    listed = call(engine, "check.listForVerse", {"chapter": "1", "verse": "1"})
    assert listed["success"] is True, listed
    check = listed["result"]["checks"][0]
    saved = call(engine, "issueResolution.save", {
        "chapter": "1", "verse": "1", "tool": check["tool"], "groupId": check["groupId"],
        "checkId": check["checkId"], "expectedFingerprint": check["stateFingerprint"],
        "selectedText": "", "issueSummary": "Wording to confirm with the team.",
        "reviewerNote": "Please look at this in Paratext.",
        "proposedCorrection": "AI: use a natural metaphor.", "evidence": [{"title": "Translation Academy"}],
    })
    assert saved["success"] is True, saved
    return saved["result"]["resolutionId"]


def stand_in(*, projects=(DVT, IRVT), active=DVT, capabilities=CAPABILITIES_080, offline: bool = False,
             version: str = "0.8.0"):
    """A connector class whose instances share one record of every call."""

    class StandIn:
        calls: list[tuple[str, dict]] = []

        def get_state(self):
            if StandIn.offline:
                raise ParatextConnectorError("Paratext is offline")
            return ConnectorState.from_response({
                "ok": True, "project_id": StandIn.active["id"], "project_name": StandIn.active["short_name"],
                "capabilities": list(StandIn.capabilities), "plugin_version": StandIn.version,
                "projects": [dict(p) for p in StandIn.projects],
            })

        def create_note(self, reference, selected_text, comment, **kwargs):
            StandIn.calls.append(("create_note", {"reference": reference, "comment": comment, **kwargs}))
            return {"ok": True, "author": "Yesu Selva Benz", "created": "2026-10-26T10:00:00.1234567+05:30",
                    "anchor": {"verse_ref": reference, "offset": 0, "selected_text": selected_text}}

        def add_comment(self, project_id, book, chapter, key, text, assignee=""):
            StandIn.calls.append(("add_comment", {"project_id": project_id, "book": book, "chapter": chapter,
                                                  "key": key, "text": text}))
            return {"ok": True, "author": "Yesu Selva Benz", "created": "2026-10-26T11:00:00.0000000+05:30"}

        def resolve_note(self, project_id, book, chapter, key):
            StandIn.calls.append(("resolve_note", {"project_id": project_id, "book": book, "chapter": chapter,
                                                   "key": key}))
            return {"ok": True, "resolved": True}

    StandIn.projects = list(projects)
    StandIn.active = active
    StandIn.capabilities = list(capabilities)
    StandIn.offline = offline
    StandIn.version = version
    return StandIn
