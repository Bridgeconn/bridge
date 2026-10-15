"""
Protocol-level tests for the Phase 7 paratext.*/logos.* methods added to
bridge_service.py. Paratext tests deliberately inject a nonexistent named
pipe so they never read or navigate a developer's live Paratext session.
These confirm the wiring (method dispatch, error-code mapping, the Logos
persistent-subprocess lifecycle) rather than real live-navigation behavior — see
paratext_plugin/README.md and engine/logos_connector/README.md for what
remains genuinely unverified end to end.
"""
import shutil

import pytest

import bridge_service
from bridge_service import BridgeEngine
from greek_room_engine.protocol import EngineRequest
from tc_ai_bridge.logos_connector import LogosConnectorClient
from tc_ai_bridge.paratext_connector import ParatextConnectorClient
from tests.support.waits import job_timeout


def call(engine, method, params=None):
    return engine.handle_request(EngineRequest(id="t", method=method, params=params or {})).to_dict()


def _isolate_paratext(monkeypatch):
    monkeypatch.setattr(
        bridge_service,
        "ParatextConnectorClient",
        lambda: ParatextConnectorClient(
            pipe_name=r"\\.\pipe\translationCoreAIBridge-pytest-not-running",
            timeout_ms=1,
        ),
    )


def test_paratext_get_state_fails_cleanly_with_no_companion_plugin_running(monkeypatch):
    _isolate_paratext(monkeypatch)
    engine = BridgeEngine()
    result = call(engine, "paratext.getState")
    assert result["success"] is False
    assert result["error"]["code"] == "paratext_connector_error"


def test_paratext_set_reference_fails_cleanly_with_no_companion_plugin_running(monkeypatch):
    _isolate_paratext(monkeypatch)
    engine = BridgeEngine()
    result = call(engine, "paratext.setReference", {"reference": "TIT 1:1"})
    assert result["success"] is False
    assert result["error"]["code"] == "paratext_connector_error"


@pytest.mark.skipif(
    not shutil.which("powershell.exe") and not shutil.which("powershell"),
    reason="Windows PowerShell is required to run the real logos_bridge.ps1 helper.",
)
def test_logos_get_state_spawns_the_real_helper_and_returns_environment_safe_result():
    engine = BridgeEngine()
    # The helper's startup budget scales like a background-job wait (#247).
    # PowerShell -STA with Add-Type takes ~0.7 s idle but 11-17 s with every
    # core busy, past the client's 10 s default: the client then stops the
    # helper (correct), getState reports logos_connector_error, and `running`
    # below was False. A bigger budget is only spent on a run that was slow.
    engine._logos_client = LogosConnectorClient(startup_timeout=job_timeout(10.0))
    try:
        result = call(engine, "logos.getState")
        if result["success"]:
            assert isinstance(result["result"]["connected"], bool)
        else:
            assert result["error"]["code"] == "logos_connector_error"
        # The same BridgeEngine reuses one persistent helper process rather than
        # spawning a fresh one for every call — the real point of caching it.
        assert engine._logos_client is not None
        assert engine._logos_client.running is True
        helper = engine._logos_client._process
        call(engine, "logos.getState")
        assert engine._logos_client._process is helper and engine._logos_client.running is True
    finally:
        if engine._logos_client is not None:
            engine._logos_client.close()


@pytest.mark.skipif(
    not shutil.which("powershell.exe") and not shutil.which("powershell"),
    reason="Windows PowerShell is required to run the real logos_bridge.ps1 helper.",
)
def test_logos_set_reference_rejects_an_unmapped_book_without_touching_logos():
    engine = BridgeEngine()
    try:
        # Invalid book mapping fails before connector I/O, so this protocol test can
        # never move a developer's live Logos session.
        result = call(engine, "logos.setReference", {"reference": "ZZZ 1:1"})
        assert result["success"] is False
        assert result["error"]["code"] == "logos_connector_error"
    finally:
        if engine._logos_client is not None:
            engine._logos_client.close()
