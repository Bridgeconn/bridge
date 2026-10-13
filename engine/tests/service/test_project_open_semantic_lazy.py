"""#112 step two: project.open returns before the PassageSemanticRuntime is
built; a worker builds it afterwards.

What must stay true: a read never waits for the build; a Scripture edit (or
anything else that reads the runtime) waits for it, so the edit neither races
the build nor slips past it without its semantic intent; the status poll
stays interactive and says BUILDING; a failed build degrades to
RECOVERY_REQUIRED with Scripture access intact; an open issued while a build
is in flight waits for it before replacing the project.
"""
from __future__ import annotations

import threading
import time

import pytest

import bridge_service
from bridge_service import BridgeEngine
from tc_ai_bridge.passage_semantic_runtime import PassageSemanticRuntime
from tc_ai_bridge.secret_store import AppSettings

from tests.support.projects import call, fixture_project  # noqa: F401
from tests.support.waits import job_timeout


class GatedRuntime(PassageSemanticRuntime):
    """The real runtime, whose constructor first waits for the test's gate."""
    gate = threading.Event()
    entered = threading.Event()

    def __init__(self, project, project_id, **kwargs):
        GatedRuntime.entered.set()
        assert GatedRuntime.gate.wait(job_timeout(10.0)), "the test never released the build"
        super().__init__(project, project_id, **kwargs)


@pytest.fixture
def gated(monkeypatch):
    GatedRuntime.gate = threading.Event()
    GatedRuntime.entered = threading.Event()
    monkeypatch.setattr(bridge_service, "PassageSemanticRuntime", GatedRuntime)
    return GatedRuntime


def _engine(tmp_path):
    return BridgeEngine(settings=AppSettings(path=tmp_path / "settings.json"))


def _wait_ready(engine, timeout=10.0):
    deadline = time.monotonic() + job_timeout(timeout)
    while time.monotonic() < deadline:
        status = call(engine, "passageSemantic.status")["result"]
        if status["state"] != "BUILDING":
            return status
        time.sleep(0.01)
    raise AssertionError("the semantic runtime never finished building")


def test_open_returns_while_the_runtime_builds_and_a_write_waits_for_it(tmp_path, fixture_project, gated):
    engine = _engine(tmp_path)

    opened = call(engine, "project.open", {"path": str(fixture_project)})
    assert opened["success"] is True, opened
    assert opened["result"]["passageSemantic"]["state"] == "BUILDING"
    assert opened["result"]["bookId"] == "rut"
    assert gated.entered.wait(job_timeout(5.0))

    # Reads answer while the build is held open, and the poll never waits.
    assert call(engine, "verse.get", {"chapter": "1", "verse": "1"})["success"] is True
    assert call(engine, "passageSemantic.status")["result"]["state"] == "BUILDING"
    assert engine.semantic_runtime_pending() is True

    # A write waits for the build: it must not race it, and it must carry
    # its semantic intent, which only an attached runtime can give it.
    edited: list[dict] = []

    def edit():
        edited.append(call(engine, "verse.edit", {"chapter": "1", "verse": "1", "newText": "புதிய வசனம்."}))

    writer = threading.Thread(target=edit, daemon=True)
    writer.start()
    writer.join(0.3)
    assert writer.is_alive() and edited == [], "the edit went through before the runtime existed"

    gated.gate.set()
    writer.join(job_timeout(10.0))
    assert not writer.is_alive()
    assert edited and edited[0]["success"] is True, edited
    status = _wait_ready(engine)
    assert status["state"] == "READY" and status["available"] is True
    assert engine.passage_semantic_runtime is not None
    # The runtime saw the edit as its own: the text revision is current.
    assert call(engine, "verse.get", {"chapter": "1", "verse": "1"})["result"]["text"] == "புதிய வசனம்."


def test_await_semantic_returns_ready_like_the_old_open(tmp_path, fixture_project, gated):
    engine = _engine(tmp_path)
    gated.gate.set()
    opened = call(engine, "project.open", {"path": str(fixture_project), "awaitSemantic": True})
    assert opened["success"] is True, opened
    assert opened["result"]["passageSemantic"]["state"] == "READY"
    assert engine.semantic_runtime_pending() is False


def test_a_failed_build_degrades_to_recovery_required_with_scripture_usable(tmp_path, fixture_project, monkeypatch):
    class Broken(PassageSemanticRuntime):
        def __init__(self, project, project_id, **kwargs):
            raise RuntimeError("companion database is locked")

    monkeypatch.setattr(bridge_service, "PassageSemanticRuntime", Broken)
    engine = _engine(tmp_path)
    opened = call(engine, "project.open", {"path": str(fixture_project)})
    assert opened["success"] is True, opened
    status = _wait_ready(engine)
    assert status["state"] == "RECOVERY_REQUIRED" and "locked" in status["error"]
    assert engine.passage_semantic_runtime is None
    assert call(engine, "verse.edit", {"chapter": "1", "verse": "1", "newText": "ok."})["success"] is True
    semantic = call(engine, "passageSemantic.getCurrentPassage", {"chapter": "1", "verse": "1"})
    assert semantic["success"] is False and "unavailable" in semantic["error"]["message"]


def test_opening_another_project_waits_for_the_build_in_flight(tmp_path, fixture_project, gated):
    engine = _engine(tmp_path)
    second_root = tmp_path / "rut2"
    import shutil
    shutil.copytree(fixture_project, second_root)

    assert call(engine, "project.open", {"path": str(fixture_project)})["success"] is True
    assert gated.entered.wait(job_timeout(5.0))
    first_project = engine.project
    threading.Timer(0.2, gated.gate.set).start()

    started = time.monotonic()
    opened = call(engine, "project.open", {"path": str(second_root)})
    assert opened["success"] is True, opened
    assert time.monotonic() - started >= 0.15, "the second open did not wait for the first build"
    # The first build attached to the first project only; the second has its own.
    assert first_project._passage_semantic_runtime_value is not None
    assert first_project._passage_semantic_runtime_value.project is first_project
    status = _wait_ready(engine)
    assert status["state"] == "READY"
    assert engine.passage_semantic_runtime.project is engine.project
    assert engine.project is not first_project
