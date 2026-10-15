"""#79: the engine session model and the hub's HTTP transport.

Two sessions on two projects do not clobber each other; the desktop's
default session is untouched by a hub session; `POST /rpc` answers with the
stdio envelope; `--serve` is parsed by main.py and the stdio path never
imports the server.
"""
from __future__ import annotations

import ast
import shutil
from pathlib import Path

import pytest

from bridge_service import BridgeEngine
from greek_room_engine.protocol import EngineRequest
from tc_ai_bridge.secret_store import AppSettings

from tests.support.paths import ENGINE_ROOT
from tests.support.projects import fixture_project  # noqa: F401


def _call(engine, method, params=None, session=""):
    return engine.handle_request(EngineRequest(id="t", method=method, params=params or {}, session=session)).to_dict()


def _two_projects(tmp_path, root):
    second = tmp_path / "rut-second"
    shutil.copytree(root, second)
    (second / "rut" / "1.json").write_text('{"1": "second project text"}', encoding="utf-8")
    return root, second


def test_two_sessions_on_two_projects_do_not_clobber_each_other(tmp_path, fixture_project):
    first, second = _two_projects(tmp_path, fixture_project)
    engine = BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json"))
    assert _call(engine, "project.open", {"path": str(first), "awaitSemantic": True})["success"] is True
    opened = _call(engine, "project.open", {"path": str(second), "awaitSemantic": True}, session="hub-a")
    assert opened["success"] is True, opened

    # Each session reads its own project, in any order.
    own = _call(engine, "verse.get", {"chapter": "1", "verse": "1"}, session="hub-a")["result"]["text"]
    desktop = _call(engine, "verse.get", {"chapter": "1", "verse": "1"})["result"]["text"]
    again = _call(engine, "verse.get", {"chapter": "1", "verse": "1"}, session="hub-a")["result"]["text"]
    assert own == again == "second project text"
    assert desktop != own
    assert engine.session_keys() == ["", "hub-a"]

    # A write in one session lands in its project only.
    assert _call(engine, "verse.edit", {"chapter": "1", "verse": "1", "newText": "edited by the hub"}, session="hub-a")["success"]
    assert _call(engine, "verse.get", {"chapter": "1", "verse": "1"})["result"]["text"] == desktop
    assert _call(engine, "verse.get", {"chapter": "1", "verse": "1"}, session="hub-a")["result"]["text"] == "edited by the hub"

    # A fresh session has no project until it opens one.
    empty = _call(engine, "verse.get", {"chapter": "1", "verse": "1"}, session="hub-b")
    assert empty["success"] is False


def test_language_qa_stays_with_the_desktop_session(tmp_path, fixture_project):
    engine = BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json"))
    refused = _call(engine, "languageQa.status", {"projectPath": str(fixture_project)}, session="hub-a")
    assert refused["success"] is False and refused["error"]["code"] == "session_unsupported"


def test_main_parses_serve_and_the_desktop_default_is_stdio():
    import main

    assert main._serve_args(["--resources-dir", "x"]) is None
    assert main._serve_args(["--serve"]) == {"data_dir": "", "host": "127.0.0.1", "port": 8765}
    assert main._serve_args(["--serve", "--data-dir", "D:/hub", "--host", "0.0.0.0", "--port", "9000"]) == {
        "data_dir": "D:/hub", "host": "0.0.0.0", "port": 9000,
    }


def test_the_stdio_path_never_imports_the_server():
    for name in ("bridge_service.py", "greek_room_engine/transport/stdio_transport.py"):
        tree = ast.parse((ENGINE_ROOT / name).read_text(encoding="utf-8"))
        imported = {
            alias.name.split(".")[0] for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in (node.names if isinstance(node, ast.Import) else [ast.alias(name=node.module or "")])
        }
        assert not imported & {"bridge_server", "fastapi", "starlette", "uvicorn"}, name
    spec = (ENGINE_ROOT / "bridge-engine.spec").read_text(encoding="utf-8")
    assert "'bridge_server'" in spec and "'fastapi'" in spec and "'uvicorn'" in spec


def test_serve_answers_rpc_with_the_stdio_envelope(tmp_path, fixture_project):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    import bridge_server

    engine = bridge_server.build_engine(tmp_path / "hub")
    assert Path(engine.settings.path).parent == (tmp_path / "hub").resolve()
    client = TestClient(bridge_server.create_app(engine))
    assert client.get("/health").json() == {"status": "ok"}

    pong = client.post("/rpc", json={"id": "1", "method": "ping", "params": {}}).json()
    assert pong["id"] == "1" and pong["success"] is True and "protocolVersion" in pong

    opened = client.post("/rpc", json={
        "id": "2", "method": "project.open", "params": {"path": str(fixture_project), "awaitSemantic": True},
        "session": "hub-a",
    }).json()
    assert opened["success"] is True, opened
    assert opened["result"]["bookId"] == "rut"

    bad = client.post("/rpc", content=b"not json", headers={"content-type": "application/json"}).json()
    assert bad["success"] is False and bad["error"]["code"] == "bad_request"
    unknown = client.post("/rpc", json={"id": "3", "method": "no.such", "params": {}}).json()
    assert unknown["success"] is False
