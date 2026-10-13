"""#237: the users RPCs behind authorize(), the startup choice and legacy:human.

users.list and users.setCurrent are anyone's (the picker); create, rename,
deactivate and setRole are a project_admin's. A rename keeps the user id, so
history written under it does not split. A row written as "human" before
identity existed is shown as legacy:human and never rewritten.
"""
from __future__ import annotations

import pytest

from bridge_service import BridgeEngine
from tc_ai_bridge.authorization import display_actor_id
from tc_ai_bridge.secret_store import AppSettings

from tests.support.projects import call, fixture_project  # noqa: F401


def _engine(tmp_path) -> BridgeEngine:
    return BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json"))


def test_the_first_install_has_one_admin_and_needs_no_choice(tmp_path):
    engine = _engine(tmp_path)
    listed = call(engine, "users.list")["result"]
    assert len(listed["users"]) == 1
    me = listed["users"][0]
    assert me["role"] == "project_admin" and me["active"] is True and me["current"] is True
    assert listed["currentUserId"] == me["userId"]
    assert call(engine, "settings.get")["result"]["needsUserChoice"] is False


def test_an_admin_adds_users_and_the_picker_is_needed_until_one_is_chosen(tmp_path):
    engine = _engine(tmp_path)
    created = call(engine, "users.create", {"displayName": "  Rina ", "role": "reporter"})
    assert created["success"] is True, created
    rina = created["result"]
    assert rina["displayName"] == "Rina" and rina["role"] == "reporter" and rina["active"] is True
    # Two active users, nobody chosen: the picker comes before Home.
    assert call(engine, "settings.get")["result"]["needsUserChoice"] is True

    chosen = call(engine, "users.setCurrent", {"userId": rina["userId"]})
    assert chosen["success"] is True, chosen
    assert chosen["result"]["currentUserId"] == rina["userId"] and chosen["result"]["role"] == "reporter"
    assert call(engine, "settings.get")["result"]["needsUserChoice"] is False
    settings = call(engine, "settings.get")["result"]
    assert settings["localUserId"] == rina["userId"] and settings["reviewerName"] == "Rina"
    assert settings["localUserRole"] == "reporter"

    # The choice survives a restart on the same workspace.
    again = _engine(tmp_path)
    assert again.current_actor_id() == rina["userId"]
    # ... and a reporter cannot manage users, but can see them and switch.
    refused = call(again, "users.create", {"displayName": "Anju", "role": "editor"})
    assert refused["success"] is False and refused["error"]["code"] == "forbidden"
    assert call(again, "users.list")["success"] is True
    admin = next(u for u in call(again, "users.list")["result"]["users"] if u["role"] == "project_admin")
    assert call(again, "users.setCurrent", {"userId": admin["userId"]})["success"] is True
    assert call(again, "settings.get")["result"]["localUserRole"] == "project_admin"


def test_rename_keeps_the_id_so_history_does_not_split(tmp_path, fixture_project):
    engine = _engine(tmp_path)
    assert call(engine, "project.open", {"path": str(fixture_project), "awaitSemantic": True})["success"] is True
    me = engine.local_user()
    edited = call(engine, "verse.edit", {"chapter": "1", "verse": "1", "newText": "first wording"})
    assert edited["success"] is True, edited
    renamed = call(engine, "users.rename", {"userId": me["userId"], "displayName": "Revant C."})
    assert renamed["success"] is True, renamed
    assert renamed["result"]["userId"] == me["userId"] and renamed["result"]["displayName"] == "Revant C."
    assert call(engine, "settings.get")["result"]["reviewerName"] == "Revant C."
    assert engine.current_actor_id() == me["userId"]
    # The change_log rows written before the rename carry the same actor id.
    rows = engine.project.workbench.change_log_entries(engine.project.workbench_identity.project_id)
    assert rows and all(row["actor_id"] == me["userId"] for row in rows if row["actor_id"] != "ai-auto")
    # The names the projects list shows resolve by id, so they follow the rename.
    assert engine.workspace.user_display_names()[me["userId"]] == "Revant C."


def test_deactivation_keeps_the_rows_and_protects_the_last_admin_and_yourself(tmp_path):
    engine = _engine(tmp_path)
    me = engine.local_user()
    anju = call(engine, "users.create", {"displayName": "Anju", "role": "editor"})["result"]
    me_refused = call(engine, "users.deactivate", {"userId": me["userId"]})
    assert me_refused["success"] is False and "yourself" in me_refused["error"]["message"]
    demote = call(engine, "users.setRole", {"userId": me["userId"], "role": "editor"})
    assert demote["success"] is False and "last project admin" in demote["error"]["message"]

    deactivated = call(engine, "users.deactivate", {"userId": anju["userId"]})
    assert deactivated["success"] is True and deactivated["result"]["active"] is False
    listed = call(engine, "users.list")["result"]["users"]
    assert any(u["userId"] == anju["userId"] and u["displayName"] == "Anju" and not u["active"] for u in listed)
    assert call(engine, "settings.get")["result"]["needsUserChoice"] is False
    cannot_pick = call(engine, "users.setCurrent", {"userId": anju["userId"]})
    assert cannot_pick["success"] is False and "deactivated" in cannot_pick["error"]["message"]
    unknown = call(engine, "users.setRole", {"userId": "nope", "role": "editor"})
    assert unknown["success"] is False
    bad_role = call(engine, "users.setRole", {"userId": anju["userId"], "role": "king"})
    assert bad_role["success"] is False


@pytest.mark.parametrize("actor_id,shown", [("human", "legacy:human"), ("9143bbc0", "9143bbc0"), ("", "")])
def test_legacy_human_is_shown_as_legacy_and_never_rewritten(actor_id, shown):
    assert display_actor_id(actor_id) == shown
