"""#492: a stored gpt-5.6 becomes gpt-5.6-terra once, and only a project admin
changes the AI model.

Settings > Save writes the whole form, so an installation that saved anything
before 0.25 has the old default stored and never saw #479's. The switch runs
once per installation; the same model chosen again afterwards is kept.
"""
from __future__ import annotations

import pytest

from bridge_service import BridgeEngine
from tc_ai_bridge.secret_store import AppSettings
from tc_ai_bridge.workspace_repository import WorkspaceRepository

from tests.support.projects import call


def _stored_before_the_switch(tmp_path, **values) -> None:
    """A workspace as a pre-0.25 build left it: settings saved, no marker."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    WorkspaceRepository(tmp_path / "workspace.sqlite3").replace_settings(values)


def _settings(tmp_path) -> AppSettings:
    return AppSettings(path=tmp_path / "settings.json")


def test_a_stored_gpt_5_6_is_switched_once_and_a_later_choice_is_kept(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    _stored_before_the_switch(tmp_path, model="gpt-5.6", provider="openai")

    upgraded = _settings(tmp_path)
    assert upgraded.model == "gpt-5.6-terra"
    assert upgraded.review_model_switched_from == "gpt-5.6"
    got = call(BridgeEngine(settings=upgraded), "settings.get")["result"]
    assert (got["model"], got["reviewModelSwitchedFrom"]) == ("gpt-5.6-terra", "gpt-5.6")
    assert _settings(tmp_path).model == "gpt-5.6-terra"

    upgraded.model = "gpt-5.6"
    again = _settings(tmp_path)
    assert again.model == "gpt-5.6"
    assert again.review_model_switched_from == ""


def test_the_per_task_review_model_is_switched_and_the_other_tasks_are_not(tmp_path):
    _stored_before_the_switch(tmp_path, model="some-other-model", ai_tasks={
        "useOneModel": False,
        "tasks": {"review": {"model": "gpt-5.6"}, "triage": {"model": "gpt-5.6"}},
    })
    upgraded = _settings(tmp_path)
    assert upgraded.model == "some-other-model"
    tasks = upgraded.ai_tasks["tasks"]
    assert tasks["review"]["model"] == "gpt-5.6-terra"
    assert tasks["triage"]["model"] == "gpt-5.6"


@pytest.mark.parametrize("stored", [{}, {"model": "gpt-5.6-sol"}, {"model": "gpt-5.6-terra"}])
def test_any_other_stored_model_is_left_alone_and_nothing_is_reported(tmp_path, stored):
    _stored_before_the_switch(tmp_path, **stored)
    upgraded = _settings(tmp_path)
    assert upgraded.model == (stored.get("model") or "gpt-5.6-terra")
    assert upgraded.review_model_switched_from == ""


def _engine_as(tmp_path, role: str) -> BridgeEngine:
    engine = BridgeEngine(settings=_settings(tmp_path))
    if role != "project_admin":
        other = call(engine, "users.create", {"displayName": "Anju", "role": role})["result"]
        assert call(engine, "users.setCurrent", {"userId": other["userId"]})["success"] is True
    return engine


@pytest.mark.parametrize("change", [
    {"model": "gpt-5.6"},
    {"aiTasks": {"useOneModel": False}},
    {"aiTasks": {"tasks": {"review": {"model": "gpt-5.6"}}}},
    {"aiTasks": {"tasks": {"review": {"reasoningEffort": "xhigh"}}}},
])
def test_an_editor_cannot_change_the_model_and_nothing_else_in_the_call_is_saved(tmp_path, change):
    engine = _engine_as(tmp_path, "editor")
    before = call(engine, "settings.get")["result"]

    refused = call(engine, "settings.set", {"paratextNavigation": not before["paratextNavigation"], **change})

    assert refused["success"] is False and refused["error"]["code"] == "forbidden"
    assert "project admin" in refused["error"]["message"]
    after = call(engine, "settings.get")["result"]
    assert (after["model"], after["aiTasks"]) == (before["model"], before["aiTasks"])
    assert after["paratextNavigation"] == before["paratextNavigation"]


def test_an_editor_saving_the_form_unchanged_is_not_refused(tmp_path):
    engine = _engine_as(tmp_path, "editor")
    before = call(engine, "settings.get")["result"]

    saved = call(engine, "settings.set", {
        "model": before["model"], "aiTasks": before["aiTasks"], "logosNavigation": True,
    })

    assert saved["success"] is True and saved["result"]["logosNavigation"] is True


def test_a_project_admin_changes_the_model(tmp_path):
    engine = _engine_as(tmp_path, "project_admin")
    saved = call(engine, "settings.set", {"model": "gpt-5.6"})
    assert saved["success"] is True and saved["result"]["model"] == "gpt-5.6"
