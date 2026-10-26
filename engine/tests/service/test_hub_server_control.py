"""#46: Settings > Team > Start a hub. The desktop engine runs the hub as its
own child (DECISIONS 2026-10-23), and the child never outlives it."""
from __future__ import annotations

import http.server
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import bridge_service
from bridge_service import BridgeEngine
from tc_ai_bridge import hub_sync
from tc_ai_bridge.process_watch import watch_parent
from tc_ai_bridge.secret_store import AppSettings

from tests.support.projects import call


@pytest.mark.subprocess
def test_watch_parent_fires_when_the_watched_process_exits():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.5)"])
    fired = threading.Event()
    watch_parent(child.pid, fired.set)
    assert not fired.wait(0.1)
    child.wait(10)
    assert fired.wait(10)


def test_watch_parent_fires_at_once_for_a_pid_that_is_gone():
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait(10)
    fired = threading.Event()
    watch_parent(child.pid, fired.set)
    assert fired.wait(10)


# -- hub.start / hub.stop / hub.probe -----------------------------------------


class _FakeProc:
    def __init__(self, argv, **kwargs):
        self.argv = argv
        self.kwargs = kwargs
        self.pid = 4321
        self.returncode = None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def terminate(self):
        self.returncode = 1

    def kill(self):
        self.returncode = 1


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _engine(tmp_path):
    return BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json"))


def _wait_state(engine, wanted, timeout=10.0):
    deadline = time.monotonic() + timeout
    server = {}
    while time.monotonic() < deadline:
        server = call(engine, "hub.status")["result"]["server"]
        if server["state"] in wanted:
            return server
        time.sleep(0.05)
    raise AssertionError(f"hub server stayed {server.get('state')}: {server}")


@pytest.fixture
def spawned(monkeypatch):
    procs: list[_FakeProc] = []

    def popen(argv, **kwargs):
        proc = _FakeProc(argv, **kwargs)
        procs.append(proc)
        return proc

    monkeypatch.setattr(subprocess, "Popen", popen)
    killed: list[int] = []
    monkeypatch.setattr(BridgeEngine, "_kill_hub_tree", staticmethod(lambda proc: killed.append(proc.pid)))
    return {"procs": procs, "killed": killed}


def _hub_answers(monkeypatch, reachable=True):
    monkeypatch.setattr(hub_sync, "probe_hub", lambda url, **kw: {"url": url, "reachable": reachable})


def test_the_serve_command_is_the_exe_itself_when_frozen_and_main_py_from_source(monkeypatch):
    monkeypatch.setattr(sys, "executable", "C:/Bridge/bridge-engine.exe")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert BridgeEngine.hub_serve_command("0.0.0.0", 8765, "D:/hub", 99) == [
        "C:/Bridge/bridge-engine.exe", "--serve", "--data-dir", "D:/hub", "--host", "0.0.0.0",
        "--port", "8765", "--parent-pid", "99"]
    monkeypatch.delattr(sys, "frozen")
    monkeypatch.setattr(sys, "executable", "C:/py/python.exe")
    argv = BridgeEngine.hub_serve_command("0.0.0.0", 8765, "D:/hub", 99)
    assert argv[0] == "C:/py/python.exe"
    assert Path(argv[1]) == Path(bridge_service.__file__).resolve().parent / "main.py"
    assert argv[2:4] == ["--serve", "--data-dir"]


def test_start_runs_the_hub_as_a_child_whose_output_never_reaches_the_protocol_pipe(tmp_path, monkeypatch, spawned):
    _hub_answers(monkeypatch)
    engine = _engine(tmp_path)
    port = _free_port()
    started = call(engine, "hub.start", {"port": port, "dataDir": str(tmp_path / "hub")})
    assert started["success"] is True, started
    (proc,) = spawned["procs"]
    assert proc.argv[proc.argv.index("--port") + 1] == str(port)
    assert proc.argv[proc.argv.index("--host") + 1] == "0.0.0.0"
    assert proc.argv[proc.argv.index("--parent-pid") + 1] == str(os.getpid())
    assert proc.kwargs["stdin"] is subprocess.DEVNULL
    assert proc.kwargs["stderr"] is subprocess.STDOUT
    assert Path(proc.kwargs["stdout"].name) == tmp_path / "hub" / "hub.log"
    (tmp_path / "hub" / "admin-join-code.txt").write_text("1A2B-3C4D-5E6F\nJoin with this code\n", encoding="utf-8")
    server = _wait_state(engine, {"running"})
    assert server["pid"] == 4321 and server["url"] == f"http://127.0.0.1:{port}"
    assert server["adminJoinCode"] == "1A2B-3C4D-5E6F" and server["portInUse"] is False
    assert server["lanUrl"] == f"http://{socket.gethostname()}:{port}"
    assert AppSettings(path=tmp_path / "settings.json").hub_server_autostart is True

    again = call(engine, "hub.start", {"port": port, "dataDir": str(tmp_path / "hub")})
    assert again["success"] is False and "already running" in again["error"]["message"]
    assert len(spawned["procs"]) == 1


def test_stop_ends_only_its_own_child_and_clears_autostart(tmp_path, monkeypatch, spawned):
    _hub_answers(monkeypatch)
    engine = _engine(tmp_path)
    call(engine, "hub.start", {"port": _free_port(), "dataDir": str(tmp_path / "hub")})
    _wait_state(engine, {"running"})
    stopped = call(engine, "hub.stop")["result"]["server"]
    assert stopped["state"] == "stopped" and stopped["pid"] is None and stopped["adminJoinCode"] is None
    assert spawned["killed"] == [4321]
    assert AppSettings(path=tmp_path / "settings.json").hub_server_autostart is False
    assert call(engine, "hub.stop")["success"] is True  # idempotent
    assert spawned["killed"] == [4321]


def test_closing_bridge_ends_the_hub_but_keeps_autostart(tmp_path, monkeypatch, spawned):
    _hub_answers(monkeypatch)
    engine = _engine(tmp_path)
    call(engine, "hub.start", {"port": _free_port(), "dataDir": str(tmp_path / "hub")})
    _wait_state(engine, {"running"})
    engine._kill_hub_on_exit()
    assert spawned["killed"] == [4321]
    assert AppSettings(path=tmp_path / "settings.json").hub_server_autostart is True


def test_autostart_brings_the_hub_back_on_the_next_launch(tmp_path, monkeypatch, spawned):
    _hub_answers(monkeypatch)
    settings = AppSettings(path=tmp_path / "settings.json")
    settings.set_hub_server_autostart(True)
    engine = BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json"))
    monkeypatch.setattr(engine.greek_room, "preload_async", lambda: None)
    engine.start_background_warmup()
    assert len(spawned["procs"]) == 1
    assert _wait_state(engine, {"running"})["autostart"] is True


def test_a_child_that_exits_during_start_is_reported_with_its_log(tmp_path, monkeypatch, spawned):
    _hub_answers(monkeypatch, reachable=False)
    engine = _engine(tmp_path)
    (tmp_path / "hub").mkdir()
    (tmp_path / "hub" / "hub.log").write_text("Traceback: no module named uvicorn\n", encoding="utf-8")
    call(engine, "hub.start", {"port": _free_port(), "dataDir": str(tmp_path / "hub")})
    spawned["procs"][0].returncode = 1
    server = _wait_state(engine, {"failed"})
    assert "no module named uvicorn" in server["error"]
    assert AppSettings(path=tmp_path / "settings.json").hub_server_autostart is False
    # Start is offered again.
    assert call(engine, "hub.start", {"port": _free_port(), "dataDir": str(tmp_path / "hub")})["success"] is True


def test_a_port_already_answering_refuses_start_and_shows_in_status(tmp_path, spawned):
    engine = _engine(tmp_path)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        refused = call(engine, "hub.start", {"port": port, "dataDir": str(tmp_path / "hub")})
        assert refused["success"] is False and "Join it instead" in refused["error"]["message"]
        engine._hub_server_state()["port"] = port
        assert call(engine, "hub.status")["result"]["server"]["portInUse"] is True
    assert spawned["procs"] == []


def test_probe_says_whether_a_hub_answers_health(tmp_path):
    class Health(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 -- the stdlib names it
            found = self.path == "/health"
            self.send_response(200 if found else 404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"} if found else {}).encode())

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Health)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    engine = _engine(tmp_path)
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        assert call(engine, "hub.probe", {"url": url})["result"] == {
            "url": url, "reachable": True, "status": "ok", "error": None}
    finally:
        server.shutdown()
        server.server_close()
    started = time.monotonic()
    gone = call(engine, "hub.probe", {"url": f"http://127.0.0.1:{_free_port()}"})["result"]
    assert gone["reachable"] is False and gone["error"] and time.monotonic() - started < 5
    bad = call(engine, "hub.probe", {"url": "team-hub:8765"})
    assert bad["success"] is False and "http://" in bad["error"]["message"]


@pytest.mark.subprocess
def test_a_real_hub_starts_from_source_answers_and_stops(tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("uvicorn")
    engine = _engine(tmp_path)
    port = _free_port()
    started = call(engine, "hub.start", {"host": "127.0.0.1", "port": port, "dataDir": str(tmp_path / "hub")})
    assert started["success"] is True, started
    try:
        server = _wait_state(engine, {"running", "failed"}, timeout=60)
        assert server["state"] == "running", server
        assert server["adminJoinCode"]
        assert call(engine, "hub.probe", {"url": server["url"]})["result"]["reachable"] is True
    finally:
        call(engine, "hub.stop")
    assert not BridgeEngine._port_in_use(port)
    assert "Bridge hub on" in (tmp_path / "hub" / "hub.log").read_text(encoding="utf-8")
