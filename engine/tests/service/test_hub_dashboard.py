"""#81: the hub dashboard's API, end to end with a device.

The issue's manual check, driven in-process: a 3-book collection's books
appear on the dashboard with their progress, and an assignment made on the
dashboard appears in the desktop's "My work" after the next sync.
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

import bridge_server  # noqa: E402
from bridge_service import BridgeEngine  # noqa: E402
from greek_room_engine.protocol import EngineRequest  # noqa: E402
from tc_ai_bridge.secret_store import AppSettings  # noqa: E402

HUB_URL = "http://hub.test"
METADATA = {
    "languageId": "eng", "languageName": "English", "languageDirection": "ltr",
    "projectName": "Pastorals", "bibleName": "Test Bible",
}
BOOKS = {
    "54TIT.SFM": "\\id TIT\n\\h Titus\n\\c 1\n\\p\n\\v 1 Paul.\n\\c 2\n\\v 1 But speak.\n",
    "55PHM.SFM": "\\id PHM\n\\h Philemon\n\\c 1\n\\v 1 Paul, a prisoner.\n",
    "56JUD.SFM": "\\id JUD\n\\h Jude\n\\c 1\n\\v 1 Jude, a servant.\n",
}


def _call(engine, method, params=None):
    return engine.handle_request(EngineRequest(id="t", method=method, params=params or {})).to_dict()


@pytest.fixture
def hub(tmp_path):
    root = tmp_path / "hub"
    dashboard = tmp_path / "dashboard"
    dashboard.mkdir()
    (dashboard / "index.html").write_text("<!doctype html><title>Bridge team dashboard</title>", encoding="utf-8")
    client = TestClient(bridge_server.create_app(
        bridge_server.build_engine(root), bridge_server.build_store(root), dashboard_dir=dashboard,
    ))
    code = (root / "admin-join-code.txt").read_text(encoding="utf-8").splitlines()[0]

    def transport(method, url, headers, body, timeout):
        response = client.request(method, url[len(HUB_URL):], headers=headers, content=body)
        return response.status_code, response.content

    return {"client": client, "admin_code": code, "transport": transport}


def test_a_collection_on_the_dashboard_and_an_assignment_back_on_the_desktop(tmp_path, hub):
    source = tmp_path / "Paratext"
    source.mkdir()
    for name, text in BOOKS.items():
        (source / name).write_text(text, encoding="utf-8")
    desk = BridgeEngine(settings=AppSettings(path=tmp_path / "desk" / "settings.json"))
    desk._hub_transport = hub["transport"]
    desk.HUB_SYNC_INTERVAL_SECONDS = 3600
    imported = _call(desk, "project.import", {"path": str(source), "metadata": METADATA})
    assert imported["success"] is True, imported
    me = desk.local_user()
    joined = _call(desk, "hub.join", {"url": HUB_URL, "joinCode": hub["admin_code"], "displayName": "Revant"})
    assert joined["success"] is True, joined
    # The hub keeps the desktop's own user id (#81).
    assert joined["result"]["identity"]["userId"] == me["userId"]

    # Link and sync every book of the collection, as a reviewer opening each would.
    for book in imported["result"]["importedProjects"]:
        assert _call(desk, "project.open", {"path": book["path"], "awaitSemantic": True})["success"] is True
        assert _call(desk, "hub.link")["success"] is True
        assert "error" not in desk.hub_sync_once()

    # The dashboard: the browser signs in with a join code of its own.
    admin = {"Authorization": f"Bearer {desk.settings.get_hub_token()}"}
    code = hub["client"].post("/hub/join-codes", json={"role": "project_admin"}, headers=admin).json()["joinCode"]
    browser = hub["client"].post("/hub/join", json={"joinCode": code, "displayName": "Benz (browser)"}).json()
    web = {"Authorization": f"Bearer {browser['token']}"}
    assert hub["client"].get("/hub/me", headers=web).json()["role"] == "project_admin"
    projects = hub["client"].get("/hub/projects", headers=web).json()["projects"]
    assert sorted(p["bookId"] for p in projects) == ["jud", "phm", "tit"]
    titus = next(p for p in projects if p["bookId"] == "tit")
    assert titus["bookName"] == "Titus" and titus["chapters"] == ["1", "2"]
    assert titus["totals"]["chapterCount"] == 2 and titus["progressPostedAt"]
    users = hub["client"].get("/hub/users", headers=web).json()["users"]
    assert {u["displayName"] for u in users} == {"Revant", "Benz (browser)"}

    # Assign Titus chapter 2 to the desktop's user from the dashboard.
    assigned = hub["client"].post("/hub/assignments", headers=web, json={
        "hubProjectId": titus["hubProjectId"], "chapter": "2", "userId": me["userId"],
    })
    assert assigned.status_code == 200 and assigned.json()["changed"] is True, assigned.text
    shown = next(p for p in hub["client"].get("/hub/projects", headers=web).json()["projects"] if p["bookId"] == "tit")
    assert [(a["chapter"], a["assigneeName"]) for a in shown["assignments"]] == [("2", "Revant")]
    assert hub["client"].post("/hub/assignments", headers=web, json={
        "hubProjectId": titus["hubProjectId"], "chapter": "9", "userId": me["userId"],
    }).status_code == 400

    # The desktop pulls it on its next pass for that book: it is "my work".
    titus_path = next(b["path"] for b in imported["result"]["importedProjects"] if b["bookId"] == "tit")
    assert _call(desk, "project.open", {"path": titus_path, "awaitSemantic": True})["success"] is True
    assert desk.hub_sync_once()["applied"] >= 1
    mine = _call(desk, "assignments.list")["result"]["assignments"]
    # Same person, same id; the desktop shows its own name for them.
    assert [(a["chapter"], a["assigneeId"], a["assigneeName"]) for a in mine] == [("2", me["userId"], me["displayName"])]
    books = {b["bookId"]: b for b in _call(desk, "project.listBookProgress")["result"]["books"]}
    assert [a["chapter"] for a in books["tit"]["assignments"]] == ["2"]

    # Clearing it on the dashboard clears it on the desktop.
    cleared = hub["client"].post("/hub/assignments", headers=web, json={
        "hubProjectId": titus["hubProjectId"], "chapter": "2", "userId": "",
    })
    assert cleared.json()["changed"] is True
    desk.hub_sync_once()
    assert _call(desk, "assignments.list")["result"]["assignments"] == []

    # The dashboard bundle is served at "/", after every API route.
    assert "Bridge team dashboard" in hub["client"].get("/").text


def test_only_admins_assign_or_see_users_and_everyone_signed_in_reads_projects(tmp_path, hub):
    admin_join = hub["client"].post("/hub/join", json={"joinCode": hub["admin_code"], "displayName": "Revant"}).json()
    admin = {"Authorization": f"Bearer {admin_join['token']}"}
    code = hub["client"].post("/hub/join-codes", json={"role": "reporter"}, headers=admin).json()["joinCode"]
    reporter = hub["client"].post("/hub/join", json={"joinCode": code, "displayName": "Rina"}).json()
    headers = {"Authorization": f"Bearer {reporter['token']}"}
    assert hub["client"].get("/hub/projects", headers=headers).status_code == 200
    assert hub["client"].get("/hub/users", headers=headers).status_code == 403
    assert hub["client"].post("/hub/assignments", headers=headers, json={"hubProjectId": "x"}).status_code == 403
    assert hub["client"].post("/hub/join-codes", headers=headers, json={"role": "editor"}).status_code == 403
    assert hub["client"].get("/hub/projects").status_code == 401
