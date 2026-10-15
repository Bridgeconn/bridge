"""The connector-install RPCs (#282) through the dispatcher: status carries the
install state, and installConnector returns at once while the install runs on
its own thread. The installer itself is a fake here; tests/connectors/
test_paratext_install.py covers what it does."""
import time

from bridge_service import BridgeEngine
from greek_room_engine.protocol import EngineRequest
from tc_ai_bridge import paratext_install as pi
from tc_ai_bridge.secret_store import AppSettings


def call(engine, method, params=None):
    return engine.handle_request(EngineRequest(id="t", method=method, params=params or {})).to_dict()


def test_status_and_install_through_the_protocol(tmp_path):
    engine = BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json"))
    released = []

    def install_fn():
        while not released:
            time.sleep(0.01)
        return {"message": "The Paratext connector 0.7.4 is installed."}

    engine._connector_installer = pi.ConnectorInstaller(
        install_fn=install_fn, status_fn=lambda: {"action": "install", "paratextFound": True})
    status = call(engine, "paratext.connectorStatus")
    assert status["success"], status
    assert status["result"]["action"] == "install" and status["result"]["install"]["state"] == "idle"

    started = time.monotonic()
    begun = call(engine, "paratext.installConnector")
    assert begun["success"] and begun["result"]["install"]["state"] == "running"
    assert time.monotonic() - started < 1.0, "the dispatcher must not wait for the admin prompt"
    # The engine still answers while the install waits.
    assert call(engine, "ping")["success"]
    released.append(1)
    deadline = time.monotonic() + 10
    while call(engine, "paratext.connectorStatus")["result"]["install"]["state"] == "running":
        assert time.monotonic() < deadline
        time.sleep(0.02)
    final = call(engine, "paratext.connectorStatus")["result"]["install"]
    assert final == {"state": "succeeded", "message": "The Paratext connector 0.7.4 is installed."}


def test_the_real_status_answers_on_any_machine(tmp_path):
    engine = BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json"))
    result = call(engine, "paratext.connectorStatus")["result"]
    assert result["action"] in {"install", "update", "none", "unavailable"}
    assert result["bundledVersion"] == pi.bundled_version()
    assert result["install"]["state"] == "idle"
