"""#80: the team hub's first slice, two devices through an in-process hub.

The hub is `bridge_server.create_app` behind FastAPI's test client; each
device is a BridgeEngine with its own settings and workspace, talking to the
hub through `HubClient` with the test client as its transport, so the same
code paths run as over a LAN without a socket.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

import bridge_server  # noqa: E402
from bridge_service import BridgeEngine  # noqa: E402
from greek_room_engine.protocol import EngineRequest  # noqa: E402
from tc_ai_bridge.hub_sync import NOT_SYNCED_TABLES, SYNCED_TABLES  # noqa: E402
from tc_ai_bridge.secret_store import AppSettings  # noqa: E402
from tc_ai_bridge.workbench_repository import MUTABLE_TABLES  # noqa: E402

TITUS = "\\id TIT\n\\h Titus\n\\c 1\n\\p\n\\v 1 Paul, a servant of God.\n\\v 2 in hope of eternal life.\n"
METADATA = {
    "languageId": "eng", "languageName": "English", "languageDirection": "ltr",
    "projectName": "Titus review", "bibleName": "Test Bible",
}
HUB_URL = "http://hub.test"


def _call(engine, method, params=None):
    return engine.handle_request(EngineRequest(id="t", method=method, params=params or {})).to_dict()


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


def _device(tmp_path, name, hub, source):
    engine = BridgeEngine(settings=AppSettings(path=tmp_path / name / "settings.json"))
    engine._hub_transport = hub["transport"]
    engine.HUB_SYNC_INTERVAL_SECONDS = 3600  # tests drive the passes themselves
    imported = _call(engine, "project.import", {"path": str(source), "metadata": METADATA})
    assert imported["success"] is True, imported
    return engine


def _decide(engine, status):
    response = _call(engine, "verse.decide", {"chapter": "1", "verse": "1", "findingId": "f-1", "status": status})
    assert response["success"] is True, response


def _decisions(engine):
    project = engine.project
    rows = project.workbench.rows("human_decisions", project_id=project.workbench_identity.project_id)
    return {row["id"]: row for row in rows}


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "TIT.usfm"
    path.write_text(TITUS, encoding="utf-8")
    return path


def test_every_workbench_table_is_classified_for_sync():
    assert set(SYNCED_TABLES) | set(NOT_SYNCED_TABLES) == set(MUTABLE_TABLES)
    assert not set(SYNCED_TABLES) & set(NOT_SYNCED_TABLES)
    assert len(SYNCED_TABLES) == 12
    for derived in ("progress_totals", "check_findings", "language_qa_cache", "alignment_verdicts"):
        assert derived in NOT_SYNCED_TABLES


def test_two_devices_exchange_a_decision_and_a_conflict_lands_on_both(tmp_path, hub, source):
    a = _device(tmp_path, "a", hub, source)
    joined = _call(a, "hub.join", {"url": HUB_URL, "joinCode": hub["admin_code"], "displayName": "Revant"})
    assert joined["success"] is True, joined
    assert joined["result"]["identity"]["role"] == "project_admin"
    linked_a = _call(a, "hub.link")
    assert linked_a["success"] is True and linked_a["result"]["created"] is True, linked_a
    hub_id = linked_a["result"]["linkedHubProjectId"]
    assert hub_id == a.project.workbench_identity.project_id

    # The admin invites an editor; device B imports the same book and links,
    # adopting the hub's project id.
    admin_token = a.settings.get_hub_token()
    code = hub["client"].post("/hub/join-codes", json={"role": "editor"},
                              headers={"Authorization": f"Bearer {admin_token}"}).json()["joinCode"]
    b = _device(tmp_path, "b", hub, source)
    assert b.project.workbench_identity.project_id != hub_id
    assert _call(b, "hub.join", {"url": HUB_URL, "joinCode": code, "displayName": "Rina"})["success"] is True
    linked_b = _call(b, "hub.link")
    assert linked_b["success"] is True and linked_b["result"]["created"] is False, linked_b
    assert b.project.workbench_identity.project_id == hub_id

    # A decides; one pass each carries it across.
    _decide(a, "accepted")
    assert a.hub_sync_once()["pushed"] >= 1
    assert b.hub_sync_once()["applied"] >= 1
    row_id, row = next(iter(_decisions(a).items()))
    assert _decisions(b)[row_id]["payload_json"] == row["payload_json"]

    # Both change the same decision before syncing: each side keeps its own
    # and records the other's as a conflict. Nothing is overwritten.
    _decide(a, "rejected")
    _decide(b, "ignored")
    a.hub_sync_once()
    b.hub_sync_once()
    a.hub_sync_once()
    assert '"rejected"' in _decisions(a)[row_id]["payload_json"]
    assert '"ignored"' in _decisions(b)[row_id]["payload_json"]
    conflicts_a = _call(a, "hub.conflicts")["result"]["conflicts"]
    conflicts_b = _call(b, "hub.conflicts")["result"]["conflicts"]
    assert len(conflicts_a) == 1 and len(conflicts_b) == 1
    assert conflicts_a[0]["table"] == "human_decisions" and conflicts_a[0]["reason"] == "revision_mismatch"
    assert conflicts_a[0]["theirPayload"]["decision"] == "ignored"
    assert _call(a, "hub.status")["result"]["openConflicts"] == 1

    # Settling a conflict marks it; it never applies the other side's row.
    settled = _call(a, "hub.resolveConflict", {"conflictId": conflicts_a[0]["id"], "resolution": "kept-mine"})
    assert settled["success"] is True and settled["result"]["conflicts"] == []
    assert '"rejected"' in _decisions(a)[row_id]["payload_json"]

    # A pull again is idempotent: no new conflict, nothing applied twice.
    again = a.hub_sync_once()
    assert again["conflicts"] == 0 and again["applied"] == 0


def test_a_reporter_token_is_refused_on_writes(tmp_path, hub, source):
    a = _device(tmp_path, "a", hub, source)
    _call(a, "hub.join", {"url": HUB_URL, "joinCode": hub["admin_code"], "displayName": "Revant"})
    admin = {"Authorization": f"Bearer {a.settings.get_hub_token()}"}
    code = hub["client"].post("/hub/join-codes", json={"role": "reporter"}, headers=admin).json()["joinCode"]
    reporter = hub["client"].post("/hub/join", json={"joinCode": code, "displayName": "Rina"}).json()
    assert reporter["role"] == "reporter"
    headers = {"Authorization": f"Bearer {reporter['token']}"}

    decided = hub["client"].post("/rpc", headers=headers, json={
        "id": "1", "method": "qaReview.decideFinding", "params": {"findingId": "x", "disposition": "CONFIRMED"},
    }).json()
    assert decided["success"] is False and decided["error"]["code"] == "forbidden"
    assert "reporter" in decided["error"]["message"]
    assert hub["client"].post("/rpc", headers=headers, json={"id": "2", "method": "ping"}).json()["success"] is True
    pushed = hub["client"].post("/sync/push", headers=headers, json={"hubProjectId": "x", "events": []})
    assert pushed.status_code == 403
    # Nobody joins with a made-up code, and /rpc without a token is refused.
    assert hub["client"].post("/hub/join", json={"joinCode": "NOPE", "displayName": "X"}).status_code == 403
    assert hub["client"].post("/rpc", json={"id": "3", "method": "ping"}).status_code == 401


def test_the_hub_refuses_tables_that_never_travel(tmp_path, hub, source):
    a = _device(tmp_path, "a", hub, source)
    _call(a, "hub.join", {"url": HUB_URL, "joinCode": hub["admin_code"], "displayName": "Revant"})
    hub_id = _call(a, "hub.link")["result"]["linkedHubProjectId"]
    headers = {"Authorization": f"Bearer {a.settings.get_hub_token()}"}
    refused = hub["client"].post("/sync/push", headers=headers, json={"hubProjectId": hub_id, "events": [
        {"event_id": "e-1", "table_name": "progress_totals", "project_id": hub_id},
    ]})
    assert refused.status_code == 400 and "does not travel" in refused.json()["detail"]


def test_an_unreachable_hub_leaves_the_desktop_untouched(tmp_path, source):
    engine = BridgeEngine(settings=AppSettings(path=tmp_path / "d" / "settings.json"))
    engine.HUB_SYNC_INTERVAL_SECONDS = 3600
    assert _call(engine, "project.import", {"path": str(source), "metadata": METADATA})["success"] is True
    engine.settings.set_hub("http://127.0.0.1:9", "token", {"displayName": "Revant", "role": "editor"})
    engine.settings.set_hub_link(str(engine.project.path), engine.project.workbench_identity.project_id)

    def unreachable(method, url, headers, body, timeout):
        raise OSError("connection refused")

    engine._hub_transport = unreachable
    result = engine.hub_sync_once()
    assert "could not be reached" in result["error"]
    # Work goes on; the error is recorded, not raised.
    assert _call(engine, "verse.edit", {"chapter": "1", "verse": "1", "newText": "offline edit"})["success"] is True
    status = _call(engine, "hub.status")["result"]
    assert "could not be reached" in status["sync"]["lastError"]
    joined = _call(engine, "hub.join", {"url": "http://127.0.0.1:9", "joinCode": "X", "displayName": "R"})
    assert joined["success"] is False and "could not be reached" in joined["error"]["message"]


@pytest.mark.slow
def test_a_days_work_of_500_decisions_syncs_well_inside_the_budget(tmp_path, hub, source):
    """The requirement: about 500 decisions sync in under 30 s on a LAN. This
    is the in-process measurement (no network); the LAN figure is the
    field's."""
    import time

    a = _device(tmp_path, "a", hub, source)
    _call(a, "hub.join", {"url": HUB_URL, "joinCode": hub["admin_code"], "displayName": "Revant"})
    hub_id = _call(a, "hub.link")["result"]["linkedHubProjectId"]
    for n in range(500):
        _call(a, "verse.decide", {"chapter": "1", "verse": "1", "findingId": f"f-{n}", "status": "accepted"})
    admin = {"Authorization": f"Bearer {a.settings.get_hub_token()}"}
    code = hub["client"].post("/hub/join-codes", json={"role": "editor"}, headers=admin).json()["joinCode"]
    b = _device(tmp_path, "b", hub, source)
    _call(b, "hub.join", {"url": HUB_URL, "joinCode": code, "displayName": "Rina"})
    _call(b, "hub.link")

    started = time.perf_counter()
    pushed = a.hub_sync_once()
    pulled = b.hub_sync_once()
    elapsed = time.perf_counter() - started
    assert pushed["pushed"] >= 500 and pulled["applied"] >= 500
    assert elapsed < 30.0, f"500 decisions took {elapsed:.1f} s"
    assert len(_decisions(b)) == len(_decisions(a))
    print(f"500 decisions push+pull in-process: {elapsed:.2f} s")
