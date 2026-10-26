"""#347: the Paratext project a note goes to, and that navigation is checked
against, is the one the open book was imported from (its link Guid in
``.bridge/collection.json``, #356), never the project Paratext has active.

Over the protocol, with a stand-in connector that reports a different project.
The coordinator's own hold-both-ways behaviour is in test_navigation.py; here
is the wiring: the engine hands the coordinator the open book's link, and the
note handoff refuses by name and keeps the note queued.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import bridge_service as bridge_service_module
from bridge_service import BridgeEngine
from tc_ai_bridge import paratext_link
from tc_ai_bridge.project_import import import_source
from tc_ai_bridge.secret_store import AppSettings
from tests.support.paratext_fixture import DEFAULT_GUID, build_paratext_project
from tests.support.projects import call, tn_review_project

OTHER_GUID = "4ae31b0d0f1be38681160e73e9ae9b566dd4459d"


@pytest.fixture
def no_paratext_install(monkeypatch, tmp_path):
    """No real Paratext projects folder is ever searched by these tests."""
    projects = tmp_path / "pt-projects"
    projects.mkdir()
    monkeypatch.setattr(paratext_link, "paratext_projects_dir", lambda *a, **k: projects)
    return projects


def _open_imported(tmp_path: Path, projects: Path) -> tuple[BridgeEngine, Path]:
    source = build_paratext_project(projects, name="IRVT", full_name="IRV Tamil")
    result = import_source(source, tmp_path / "projects", {"languageName": "Tamil"})
    engine = BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json"))
    opened = call(engine, "project.open", {"path": result["primaryProjectPath"]})
    assert opened["success"] is True, opened
    return engine, Path(result["primaryProjectPath"])


def _open_linked(tmp_path: Path) -> BridgeEngine:
    """A tN-indexed book linked to the Paratext project IRVT (DEFAULT_GUID)."""
    root = tn_review_project(tmp_path / "tit", paratext_guid=DEFAULT_GUID, paratext_name="IRVT")
    engine = BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json"))
    opened = call(engine, "project.open", {"path": str(root)})
    assert opened["success"] is True, opened
    return engine


class StandInConnector:
    """The companion on its pipe, reporting whatever project it is told to."""

    project_id = OTHER_GUID
    project_name = "DVT"
    created: list[dict] = []

    def get_state(self):
        return SimpleNamespace(
            connected=True, capabilities=["state", "create_note"], reference="TIT 1:1",
            project_id=type(self).project_id, project_name=type(self).project_name,
        )

    def set_reference(self, reference, origin_id=""):
        return {"ok": True}

    def create_note(self, reference, selected_text, comment, **kwargs):
        type(self).created.append({"reference": reference, "comment": comment, **kwargs})
        return {"ok": True}


@pytest.fixture
def stand_in(monkeypatch):
    StandInConnector.project_id = OTHER_GUID
    StandInConnector.project_name = "DVT"
    StandInConnector.created = []
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", StandInConnector)
    return StandInConnector


def test_the_coordinator_is_handed_the_open_books_link_not_the_active_project(tmp_path, no_paratext_install):
    engine, _ = _open_imported(tmp_path, no_paratext_install)

    expected = engine._navigation._paratext_expected()

    assert expected == {"id": DEFAULT_GUID, "name": "IRVT"}
    link = json.loads((Path(engine.project.path) / ".bridge" / "collection.json").read_text(encoding="utf-8"))
    assert link["paratext"]["guid"] == DEFAULT_GUID


def test_no_project_open_means_no_expected_project(tmp_path):
    engine = BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json"))
    assert engine._navigation._paratext_expected() == {}


def test_a_note_for_a_book_whose_project_is_not_active_is_refused_by_name_and_kept_queued(
    tmp_path, stand_in,
):
    engine = _open_linked(tmp_path)
    resolution_id = _saved_resolution(engine)

    result = call(engine, "issueResolution.queueParatext",
                  {"chapter": "1", "verse": "1", "resolutionId": resolution_id})

    assert result["success"] is True, result
    handoff = result["result"]["handoff"]
    assert handoff["status"] == "queued"
    assert handoff["expectedProjectId"] == DEFAULT_GUID
    assert "DVT (4ae31b0d…)" in handoff["lastError"]
    assert f"IRVT ({DEFAULT_GUID[:8]}…)" in handoff["lastError"]
    assert "does not match" in handoff["lastError"]
    assert stand_in.created == []

    # The reviewer switches Paratext to the book's project: the queued note goes
    # out on retry, addressed to the link's Guid.
    stand_in.project_id = DEFAULT_GUID
    stand_in.project_name = "IRVT"
    retried = call(engine, "issueResolution.retryParatext",
                   {"chapter": "1", "verse": "1", "resolutionId": resolution_id})
    assert retried["result"]["handoff"]["status"] == "sent"
    assert len(stand_in.created) == 1
    assert stand_in.created[0]["project_id"] == DEFAULT_GUID


def test_a_queue_request_never_takes_a_project_id_from_the_caller(tmp_path, stand_in):
    engine = _open_linked(tmp_path)
    resolution_id = _saved_resolution(engine)

    # The active project is named by the caller, as the UI used to do: ignored.
    result = call(engine, "issueResolution.queueParatext",
                  {"chapter": "1", "verse": "1", "resolutionId": resolution_id,
                   "expectedProjectId": OTHER_GUID})

    assert result["result"]["handoff"]["status"] == "queued"
    assert result["result"]["handoff"]["expectedProjectId"] == DEFAULT_GUID
    assert stand_in.created == []


def _saved_resolution(engine: BridgeEngine) -> str:
    """An issue resolution on TIT 1:1 of the imported book, through the same
    RPCs the review panel uses."""
    listed = call(engine, "check.listForVerse", {"chapter": "1", "verse": "1"})
    assert listed["success"] is True, listed
    checks = listed["result"]["checks"]
    assert checks, "the book has no tN/tW checks on TIT 1:1 to resolve"
    check = checks[0]
    saved = call(engine, "issueResolution.save", {
        "chapter": "1", "verse": "1", "tool": check["tool"], "groupId": check["groupId"],
        "checkId": check["checkId"], "expectedFingerprint": check["stateFingerprint"],
        "selectedText": "", "issueSummary": "Wording to confirm with the team.",
        "reviewerNote": "Please look at this in Paratext.", "proposedCorrection": "", "evidence": [],
    })
    assert saved["success"] is True, saved
    return saved["result"]["resolutionId"]
