"""#338: a damaged workspace.sqlite3 no longer crash-loops the engine.

The recovery ladder (Revant, 2026-10-24, docs/DECISIONS.md): the engine always
starts; the damaged file and its -wal/-shm are quarantined beside it under a
timestamped name, nothing deleted; the last-good backup written at the
previous healthy start is restored when it exists and opens; otherwise a fresh
database is built; data\\projects is rediscovered whatever survived; the
outcome is reported on engine.info and project.open, never as an error; and a
hub-joined install re-pulls users and roles from the hub.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import bridge_server
from bridge_service import BridgeEngine
from tc_ai_bridge.project_import import import_source
from tc_ai_bridge.secret_store import AppSettings
from tests.support.projects import call

TITUS = "\\id TIT\n\\h Titus\n\\c 1\n\\p\n\\v 1 Paul, a servant of God.\n\\v 2 in hope of eternal life.\n"
METADATA = {"languageId": "eng", "languageName": "English", "languageDirection": "ltr",
            "projectName": "Titus review", "bibleName": "Test Bible"}
HUB_URL = "http://hub.test"


def _data_dir(tmp_path: Path) -> Path:
    return tmp_path / "app" / "data"


def _healthy_engine(tmp_path: Path) -> BridgeEngine:
    """A first start with one managed project: writes the last-good backup."""
    engine = BridgeEngine(settings=AppSettings(path=_data_dir(tmp_path) / "settings.json"))
    source = tmp_path / "57-TIT.usfm"
    source.write_text(TITUS, encoding="utf-8")
    imported = call(engine, "project.import", {"path": str(source), "metadata": METADATA})
    assert imported["success"], imported
    return engine


def _damage(tmp_path: Path) -> None:
    data = _data_dir(tmp_path)
    (data / "workspace.sqlite3").write_bytes(b"this is not a sqlite database at all" * 40)
    for suffix in ("-wal", "-shm"):
        Path(str(data / "workspace.sqlite3") + suffix).unlink(missing_ok=True)


def test_a_damaged_workspace_is_quarantined_restored_from_the_last_good_backup_and_reported(tmp_path):
    first = _healthy_engine(tmp_path)
    data = _data_dir(tmp_path)
    backup = data / "workspace.last-good.sqlite3"
    assert backup.is_file(), "a healthy start writes the last-good backup beside the database"
    user_id = first.local_user()["userId"]
    project_path = Path(call(first, "project.list")["result"]["projects"][0]["path"])
    assert project_path.is_dir()
    del first
    # The backup is written at startup, so the one from the first start holds
    # nothing the first session wrote; the next healthy start's does.
    second = BridgeEngine(settings=AppSettings(path=data / "settings.json"))
    assert second.local_user()["userId"] == user_id
    del second
    conn = sqlite3.connect(str(backup))
    try:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] >= 1
        assert conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1
    finally:
        conn.close()

    _damage(tmp_path)
    engine = BridgeEngine(settings=AppSettings(path=data / "settings.json"))  # must not raise
    info = call(engine, "engine.info")["result"]
    recovery = info["workspaceRecovery"]
    assert recovery["outcome"] == "restored"
    assert recovery["quarantined"].startswith("workspace.quarantined-") and recovery["quarantined"].endswith(".sqlite3")
    assert (data / recovery["quarantined"]).is_file(), "the damaged file is kept beside the database, not deleted"
    assert "not a database" in recovery["error"]
    assert recovery["backup"] == "workspace.last-good.sqlite3" and recovery["backupWrittenAt"]
    assert recovery["lost"] and "since the backup" in recovery["lost"][0]
    assert recovery["hubJoined"] is False and recovery["hubRepull"]["state"] == "not-joined"
    # Restored: the same local user id; rediscovered: the managed project is listed.
    assert engine.local_user()["userId"] == user_id
    assert recovery["rediscoveredManaged"] == 1
    listed = call(engine, "project.list")["result"]["projects"]
    assert [Path(p["path"]) for p in listed] == [project_path]
    # The report rides on project.open too, and is never an error.
    opened = call(engine, "project.open", {"path": str(project_path)})
    assert opened["success"], opened
    assert opened["result"]["workspaceRecovery"]["outcome"] == "restored"
    # A healthy database again: the next start reports nothing.
    del engine
    assert call(BridgeEngine(settings=AppSettings(path=data / "settings.json")), "engine.info")["result"]["workspaceRecovery"] is None


def test_without_a_backup_the_database_is_rebuilt_and_the_projects_folder_rediscovered(tmp_path):
    first = _healthy_engine(tmp_path)
    data = _data_dir(tmp_path)
    old_user = first.local_user()["userId"]
    project_path = Path(call(first, "project.list")["result"]["projects"][0]["path"])
    del first
    (data / "workspace.last-good.sqlite3").unlink()
    _damage(tmp_path)

    engine = BridgeEngine(settings=AppSettings(path=data / "settings.json"))
    recovery = call(engine, "engine.info")["result"]["workspaceRecovery"]
    assert recovery["outcome"] == "rebuilt" and recovery["backup"] == ""
    assert any("users and their roles" in line for line in recovery["lost"])
    assert recovery["rediscoveredManaged"] == 1
    assert [Path(p["path"]) for p in call(engine, "project.list")["result"]["projects"]] == [project_path]
    assert engine.local_user()["userId"] != old_user  # a fresh database mints a new local user
    quarantined = sorted(data.glob("workspace.quarantined-*.sqlite3"))
    assert len(quarantined) == 1
    assert (data / "workspace.last-good.sqlite3").is_file(), "the rebuilt database is backed up at once"


def test_a_damaged_backup_is_quarantined_too_and_the_database_rebuilt(tmp_path):
    _healthy_engine(tmp_path)
    data = _data_dir(tmp_path)
    (data / "workspace.last-good.sqlite3").write_bytes(b"garbage" * 100)
    _damage(tmp_path)
    engine = BridgeEngine(settings=AppSettings(path=data / "settings.json"))
    recovery = call(engine, "engine.info")["result"]["workspaceRecovery"]
    assert recovery["outcome"] == "rebuilt"
    assert recovery["backupError"] and recovery["backupQuarantined"].endswith("-backup.sqlite3")
    assert (data / recovery["backupQuarantined"]).is_file()
    assert len(list(data.glob("workspace.quarantined-*.sqlite3"))) == 2


@pytest.fixture
def hub(tmp_path):
    root = tmp_path / "hub"
    store = bridge_server.build_store(root)
    client = TestClient(bridge_server.create_app(bridge_server.build_engine(root), store))
    admin_code = (root / "admin-join-code.txt").read_text(encoding="utf-8").splitlines()[0]

    def transport(method, url, headers, body, timeout):
        response = client.request(method, url[len(HUB_URL):], headers=headers, content=body)
        return response.status_code, response.content

    return {"client": client, "store": store, "admin_code": admin_code, "transport": transport}


def test_a_hub_joined_install_re_pulls_users_and_roles_after_a_recovery(tmp_path, hub):
    first = _healthy_engine(tmp_path)
    first._hub_transport = hub["transport"]
    first.HUB_SYNC_INTERVAL_SECONDS = 3600
    joined = call(first, "hub.join", {"url": HUB_URL, "joinCode": hub["admin_code"], "displayName": "Admin"})
    assert joined["success"], joined
    my_hub_id = joined["result"]["identity"]["userId"]
    # A second person on the hub, whom this device has never seen locally.
    other_code = hub["client"].post("/hub/join-codes", json={"role": "editor"},
                                    headers={"Authorization": f"Bearer {first.settings.get_hub_token()}"}).json()["joinCode"]
    other = hub["client"].post("/hub/join", json={"joinCode": other_code, "displayName": "Priya",
                                                  "deviceId": "dev-2", "userId": "user-priya"}).json()
    assert other["userId"] == "user-priya"
    data = _data_dir(tmp_path)
    # The hub join settings are in the backup (written at start) only if a
    # start follows; take a fresh healthy start so the backup holds them.
    del first
    second = BridgeEngine(settings=AppSettings(path=data / "settings.json"))
    assert second.settings.hub_url == HUB_URL
    del second

    _damage(tmp_path)
    engine = BridgeEngine(settings=AppSettings(path=data / "settings.json"))
    engine._hub_transport = hub["transport"]
    engine.HUB_SYNC_INTERVAL_SECONDS = 3600
    recovery = call(engine, "engine.info")["result"]["workspaceRecovery"]
    assert recovery["outcome"] == "restored" and recovery["hubJoined"] is True
    assert recovery["hubRepull"]["state"] == "pending"
    engine._hub_repull_users()  # what start_background_warmup runs on its thread
    assert recovery["hubRepull"] == {"state": "done", "users": 2}
    users = {u["userId"]: u for u in engine.workspace.list_users()}
    assert users["user-priya"]["displayName"] == "Priya" and users["user-priya"]["role"] == "editor"
    assert users[my_hub_id]["role"] == "project_admin"
