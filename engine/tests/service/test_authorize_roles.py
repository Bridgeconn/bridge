"""#236: three roles, one authorize() rule, a refusal per role.

The dispatcher asks `authorize()` before every method. The table that
classifies methods is pinned against `Methods` here, so a new method cannot
arrive unclassified. #183 rides with it: a request that names its own actor
is refused and nothing is written.
"""
from __future__ import annotations

import pytest

from bridge_service import BridgeEngine, Methods
from tc_ai_bridge.authorization import (
    ACTOR_WIRE_KEYS, METHOD_ACTIONS, ROLE_ACTIONS, Action, AuthorizationError, Role, authorize, parse_role,
)
from tc_ai_bridge.secret_store import AppSettings

from tests.support.projects import call, fixture_project  # noqa: F401


def _engine(tmp_path, root, role: str = "project_admin") -> BridgeEngine:
    engine = BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json"))
    user = engine.local_user()
    engine.workspace.set_user_role(user["userId"], role)
    engine.refresh_local_user()
    assert call(engine, "project.open", {"path": str(root), "awaitSemantic": True})["success"] is True
    return engine


def _every_method() -> set[str]:
    return {
        value for name, value in vars(Methods).items()
        if name.isupper() and isinstance(value, str)
    }


def test_every_engine_method_is_classified_and_nothing_else_is():
    methods = _every_method()
    assert methods, "Methods has constants"
    missing = sorted(methods - set(METHOD_ACTIONS))
    assert missing == [], f"classify these in authorization.METHOD_ACTIONS: {missing}"
    stale = sorted(set(METHOD_ACTIONS) - methods)
    assert stale == [], f"these are classified but no longer exist: {stale}"


def test_the_role_table_is_what_the_requirement_says():
    assert ROLE_ACTIONS[Role.REPORTER] == {Action.READ}
    assert ROLE_ACTIONS[Role.EDITOR] == {Action.READ, Action.RUN_CHECKS, Action.WRITE}
    assert ROLE_ACTIONS[Role.PROJECT_ADMIN] == set(Action)
    # A row written before the role column existed is an admin: that is what
    # a single-user installation always was.
    assert parse_role(None) is Role.PROJECT_ADMIN and parse_role("nonsense") is Role.PROJECT_ADMIN
    with pytest.raises(AuthorizationError, match="reporter"):
        authorize({"userId": "u", "displayName": "Rina", "role": "reporter"}, None, Action.WRITE)
    with pytest.raises(AuthorizationError, match="only reading"):
        authorize(None, None, Action.WRITE)
    authorize(None, None, Action.READ)


REPORTER_REFUSED = [
    ("verse.decide", {"chapter": "1", "verse": "1", "findingId": "f", "status": "accepted"}),
    ("verse.edit", {"chapter": "1", "verse": "1", "newText": "x"}),
    ("checks.start", {"scope": "chapter", "chapters": ["1"], "checks": ["local"]}),
    ("project.rename", {"projectId": "p", "name": "x"}),
]
EDITOR_REFUSED = [
    ("project.rename", {"projectId": "p", "name": "x"}),
    ("project.archive", {"projectId": "p"}),
    ("project.import.start", {"path": "C:/nowhere", "metadata": {}}),
]


@pytest.mark.parametrize("method,params", REPORTER_REFUSED)
def test_a_reporter_cannot_write_or_run_checks_or_manage(tmp_path, fixture_project, method, params):
    engine = _engine(tmp_path, fixture_project, "reporter")
    before = engine.project.workbench.max_seq(project_id=engine.project.workbench_identity.project_id)
    response = call(engine, method, params)
    assert response["success"] is False, response
    assert response["error"]["code"] == "forbidden"
    assert "reporter" in response["error"]["message"]
    assert engine.project.workbench.max_seq(project_id=engine.project.workbench_identity.project_id) == before
    # Reading is still theirs.
    assert call(engine, "verse.get", {"chapter": "1", "verse": "1"})["success"] is True
    assert call(engine, "project.list")["success"] is True


@pytest.mark.parametrize("method,params", EDITOR_REFUSED)
def test_an_editor_cannot_manage_projects(tmp_path, fixture_project, method, params):
    engine = _engine(tmp_path, fixture_project, "editor")
    response = call(engine, method, params)
    assert response["success"] is False and response["error"]["code"] == "forbidden", response
    assert "editor" in response["error"]["message"]


def test_an_editor_can_write_and_run_checks(tmp_path, fixture_project):
    engine = _engine(tmp_path, fixture_project, "editor")
    assert call(engine, "verse.edit", {"chapter": "1", "verse": "1", "newText": "edited by an editor"})["success"] is True
    started = call(engine, "checks.start", {"scope": "chapter", "chapters": ["1"], "checks": ["local"]})
    assert started["success"] is True, started
    call(engine, "checks.cancel", {"jobId": started["result"]["jobId"]})


def test_a_project_admin_can_do_everything_and_is_the_default(tmp_path, fixture_project):
    engine = BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json"))
    assert engine.local_user()["role"] == "project_admin"
    assert call(engine, "project.open", {"path": str(fixture_project), "awaitSemantic": True})["success"] is True
    assert call(engine, "verse.edit", {"chapter": "1", "verse": "1", "newText": "edited by the admin"})["success"] is True
    listed = call(engine, "project.list")["result"]["projects"]
    assert call(engine, "project.rename", {"projectId": listed[0]["projectId"], "name": "Admin's"})["success"] is True
    assert call(engine, "settings.get")["result"]["localUserRole"] == "project_admin"


@pytest.mark.parametrize("key", ACTOR_WIRE_KEYS)
def test_a_request_that_names_its_actor_is_refused_and_writes_nothing(tmp_path, fixture_project, key):
    engine = _engine(tmp_path, fixture_project)
    before = engine.project.workbench.max_seq(project_id=engine.project.workbench_identity.project_id)
    params = {"chapter": "1", "verse": "1", "findingId": "f", "status": "accepted", key: "someone-else"}
    response = call(engine, "verse.decide", params)
    assert response["success"] is False and response["error"]["code"] == "forbidden", response
    assert key in response["error"]["message"]
    assert engine.project.workbench.max_seq(project_id=engine.project.workbench_identity.project_id) == before
