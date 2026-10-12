"""Startup stage lines (#233): the sidecar names what it is doing before
the ready handshake, so the shell's loading screen can show real stages.
The live ordering is asserted over a real process in test_stdio_e2e.py;
these are the cheap source-level checks."""
from __future__ import annotations

import io
import json

from greek_room_engine.transport.stdio_transport import send_stage
from tests.support.paths import ENGINE_ROOT


def test_send_stage_writes_one_line_in_the_response_envelope():
    out = io.StringIO()
    send_stage("modules", "Loading engine modules", stream=out)
    lines = out.getvalue().splitlines()
    assert len(lines) == 1
    frame = json.loads(lines[0])
    assert frame["id"] == "__stage__"
    assert frame["success"] is True
    assert frame["result"] == {"stage": "modules", "label": "Loading engine modules"}


def test_main_reports_each_stage_before_the_work_it_names():
    """The whole point is that "Loading engine modules" is on the wire before
    the import runs and "Starting the engine" before BridgeEngine() does; an
    import hoisted back to the top of main.py would silently make the first
    stage describe the past."""
    source = (ENGINE_ROOT / "main.py").read_text(encoding="utf-8")
    modules_stage = source.index('send_stage("modules"')
    engine_import = source.index("from bridge_service import BridgeEngine")
    engine_stage = source.index('send_stage("engine"')
    engine_built = source.index("engine = BridgeEngine()")
    assert modules_stage < engine_import < engine_stage < engine_built
    # And importing main for its CLI helper must stay free of all of it.
    assert source.index("def _start") < source.index('if __name__ == "__main__"')
