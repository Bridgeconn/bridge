"""#279: one person, two projects, two roles, enforced in authorize() only.

A user's role on a project (a `team_members` row, workbench v10) decides every
action there but managing users, which stays with the installation or
hub-token role. Desktop, /rpc and the dashboard's hub endpoints all ask the
same authorize().
"""
from __future__ import annotations

import pytest

from bridge_service import BridgeEngine
from tc_ai_bridge.authorization import Action, AuthorizationError, Role, authorize, effective_role
from tc_ai_bridge.secret_store import AppSettings
from tests.support.projects import _write_minimal_book, call


class _Project:
    def __init__(self, roles):
        self.roles = roles

    def team_role(self, user_id):
        return self.roles.get(user_id)


def test_the_role_on_the_project_decides_everything_but_managing_users():
    rina = {"userId": "u-rina", "displayName": "Rina", "role": "editor"}
    reporter_here = _Project({"u-rina": "reporter"})
    with pytest.raises(AuthorizationError, match="reporter on this project"):
        authorize(rina, reporter_here, Action.WRITE)
    admin_here = _Project({"u-rina": "project_admin"})
    authorize(rina, admin_here, Action.MANAGE_PROJECTS)
    with pytest.raises(AuthorizationError):
        authorize(rina, admin_here, Action.MANAGE_USERS)  # the user list is not a project's
    authorize(rina, _Project({}), Action.WRITE)  # no row: the installation role
    assert effective_role(rina, None) is Role.EDITOR


@pytest.fixture
def two_projects(tmp_path):
    a, b = tmp_path / "rut", tmp_path / "jon"
    _write_minimal_book(a, "rut", "ஆதியிலே தேவன்.")
    _write_minimal_book(b, "jon", "யோனா எழுந்தான்.")
    return a, b


def _open(engine, root):
    assert call(engine, "project.open", {"path": str(root), "awaitSemantic": True})["success"] is True


def _decide(engine):
    return call(engine, "verse.decide", {"chapter": "1", "verse": "1", "findingId": "f-1", "status": "ignored"})


def test_editor_on_one_project_and_reporter_on_another_on_the_desktop(tmp_path, two_projects):
    a, b = two_projects
    engine = BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json"))
    rina = call(engine, "users.create", {"displayName": "Rina", "role": "editor"})["result"]
    _open(engine, a)
    assert call(engine, "team.setRole", {"userId": rina["userId"], "role": "editor"})["success"]
    _open(engine, b)
    assert call(engine, "team.setRole", {"userId": rina["userId"], "role": "reporter"})["success"]
    assert call(engine, "users.setCurrent", {"userId": rina["userId"]})["success"]

    _open(engine, a)
    assert _decide(engine)["success"] is True
    assert call(engine, "team.roles")["result"]["effectiveRole"] == "editor"

    _open(engine, b)
    refused = _decide(engine)
    assert refused["success"] is False and refused["error"]["code"] == "forbidden"
    assert "reporter on this project" in refused["error"]["message"]
    roles = call(engine, "team.roles")["result"]
    assert (roles["effectiveRole"], roles["projectRole"]) == ("reporter", "reporter")


def test_a_project_admin_on_one_project_manages_it_but_not_the_users(tmp_path, two_projects):
    a, _b = two_projects
    engine = BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json"))
    rina = call(engine, "users.create", {"displayName": "Rina", "role": "editor"})["result"]
    _open(engine, a)
    assert call(engine, "team.setRole", {"userId": rina["userId"], "role": "project_admin"})["success"]
    assert call(engine, "users.setCurrent", {"userId": rina["userId"]})["success"]
    _open(engine, a)

    assert call(engine, "assignments.set", {"chapter": "1", "userId": rina["userId"]})["success"] is True
    refused = call(engine, "team.setRole", {"userId": rina["userId"], "role": "reporter"})
    assert refused["success"] is False and refused["error"]["code"] == "forbidden"


def test_clearing_a_project_role_returns_the_installation_role(tmp_path, two_projects):
    a, _b = two_projects
    engine = BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json"))
    rina = call(engine, "users.create", {"displayName": "Rina", "role": "editor"})["result"]
    _open(engine, a)
    call(engine, "team.setRole", {"userId": rina["userId"], "role": "reporter"})
    assert engine.project.team_role(rina["userId"]) == "reporter"
    listed = call(engine, "team.setRole", {"userId": rina["userId"], "role": None})["result"]
    assert engine.project.team_role(rina["userId"]) is None
    assert next(u for u in listed["users"] if u["userId"] == rina["userId"])["projectRole"] is None


# -- through the hub: /rpc and the dashboard endpoints ------------------------------

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")


@pytest.fixture
def hub(tmp_path):
    from fastapi.testclient import TestClient

    import bridge_server

    root = tmp_path / "hub"
    engine = bridge_server.build_engine(root)
    client = TestClient(bridge_server.create_app(engine, bridge_server.build_store(root)))
    code = (root / "admin-join-code.txt").read_text(encoding="utf-8").splitlines()[0]
    admin = client.post("/hub/join", json={"joinCode": code, "displayName": "Revant"}).json()
    return {"client": client, "engine": engine,
            "admin": {"Authorization": f"Bearer {admin['token']}"}, "admin_user": admin}


def _join(hub, role, name):
    code = hub["client"].post("/hub/join-codes", json={"role": role}, headers=hub["admin"]).json()["joinCode"]
    joined = hub["client"].post("/hub/join", json={"joinCode": code, "displayName": name}).json()
    return joined, {"Authorization": f"Bearer {joined['token']}"}


def _rpc(hub, headers, method, params):
    return hub["client"].post("/rpc", headers=headers, json={"id": "r", "method": method, "params": params}).json()


def test_editor_on_one_project_and_reporter_on_another_through_rpc(hub, two_projects):
    a, b = two_projects
    rina, headers = _join(hub, "editor", "Rina")
    engine = hub["engine"]
    for root, role in ((a, "editor"), (b, "reporter")):
        assert _rpc(hub, headers, "project.open", {"path": str(root), "awaitSemantic": True})["success"]
        engine.project.set_team_role(rina["userId"], role, set_by="u-admin")

    assert _rpc(hub, headers, "project.open", {"path": str(a), "awaitSemantic": True})["success"]
    decided = _rpc(hub, headers, "verse.decide", {"chapter": "1", "verse": "1", "findingId": "f-1", "status": "ignored"})
    assert decided["success"] is True, decided
    assert _rpc(hub, headers, "project.open", {"path": str(b), "awaitSemantic": True})["success"]
    refused = _rpc(hub, headers, "verse.decide", {"chapter": "1", "verse": "1", "findingId": "f-1", "status": "ignored"})
    assert refused["success"] is False and refused["error"]["code"] == "forbidden"
    assert "reporter on this project" in refused["error"]["message"]


def test_the_dashboard_sets_a_project_role_and_assignments_follow_it(hub):
    client = hub["client"]
    linked = client.post("/hub/projects/link", headers=hub["admin"],
                         json={"bookId": "tit", "sourceSha256": "abc", "localProjectId": "p-tit"}).json()
    hub_id = linked["hubProjectId"]
    rina, headers = _join(hub, "editor", "Rina")

    # A token editor is no project admin anywhere yet: assigning is refused.
    assert client.post("/hub/assignments", headers=headers,
                       json={"hubProjectId": hub_id, "chapter": "", "userId": rina["userId"]}).status_code == 403
    set_role = client.post("/hub/team-roles", headers=hub["admin"],
                           json={"hubProjectId": hub_id, "userId": rina["userId"], "role": "project_admin"})
    assert set_role.status_code == 200 and set_role.json()["changed"] is True
    [project] = client.get("/hub/projects", headers=headers).json()["projects"]
    assert project["myRole"] == "project_admin"
    assert client.post("/hub/assignments", headers=headers,
                       json={"hubProjectId": hub_id, "chapter": "", "userId": rina["userId"]}).status_code == 200
    # Only a token admin manages users, per-project roles included.
    assert client.post("/hub/team-roles", headers=headers,
                       json={"hubProjectId": hub_id, "userId": rina["userId"], "role": "editor"}).status_code == 403

    # A per-project reporter pushes nothing to that project.
    client.post("/hub/team-roles", headers=hub["admin"],
                json={"hubProjectId": hub_id, "userId": rina["userId"], "role": "reporter"})
    pushed = client.post("/sync/push", headers=headers, json={"hubProjectId": hub_id, "events": []})
    assert pushed.status_code == 403 and "reporter on this project" in pushed.json()["detail"]
