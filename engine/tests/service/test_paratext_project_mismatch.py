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

import pytest

import bridge_service as bridge_service_module
from bridge_service import BridgeEngine
from tc_ai_bridge import paratext_link
from tc_ai_bridge.project_import import import_source
from tc_ai_bridge.secret_store import AppSettings
from tests.support.paratext_fixture import DEFAULT_GUID, build_paratext_project
from tests.support.paratext_writeback import (
    DVT, IRVT, OTHER_GUID, open_linked_review_project, saved_resolution, stand_in,
)
from tests.support.projects import call



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


def test_the_coordinator_is_handed_the_open_books_link_not_the_active_project(tmp_path, no_paratext_install):
    engine, _ = _open_imported(tmp_path, no_paratext_install)

    expected = engine._navigation._paratext_expected()

    assert expected == {"id": DEFAULT_GUID, "name": "IRVT"}
    link = json.loads((Path(engine.project.path) / ".bridge" / "collection.json").read_text(encoding="utf-8"))
    assert link["paratext"]["guid"] == DEFAULT_GUID


def test_no_project_open_means_no_expected_project(tmp_path):
    engine = BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json"))
    assert engine._navigation._paratext_expected() == {}


def test_a_note_never_goes_to_another_project_and_names_the_linked_one_while_it_waits(tmp_path, monkeypatch):
    """With connector 0.8.0 a note is addressed by the link's Guid (#358), so the
    project Paratext has active no longer matters for notes; navigation keeps
    the active-window check. The link's project missing from the PC holds the
    note, named."""
    connector = stand_in(projects=(DVT,), active=DVT)
    monkeypatch.setattr(bridge_service_module, "ParatextConnectorClient", connector)
    engine, _ = open_linked_review_project(tmp_path, monkeypatch)
    resolution_id = saved_resolution(engine)

    # The caller names DVT, the active project: ignored.
    result = call(engine, "issueResolution.queueParatext",
                  {"chapter": "1", "verse": "1", "resolutionId": resolution_id, "expectedProjectId": OTHER_GUID})

    handoff = result["result"]["handoff"]
    assert handoff["status"] == "queued"
    assert handoff["expectedProjectId"] == DEFAULT_GUID
    assert f"IRVT ({DEFAULT_GUID[:8]}…)" in handoff["lastError"]
    assert connector.calls == []

    connector.projects = [DVT, IRVT]
    retried = call(engine, "issueResolution.retryParatext",
                   {"chapter": "1", "verse": "1", "resolutionId": resolution_id})
    assert retried["result"]["handoff"]["status"] == "sent"
    [(_, sent)] = connector.calls
    assert sent["project_id"] == DEFAULT_GUID
