"""#46: Settings > Team > Start a hub. The desktop engine runs the hub as its
own child (DECISIONS 2026-10-23), and the child never outlives it."""
from __future__ import annotations

import subprocess
import sys
import threading

import pytest

from tc_ai_bridge.process_watch import watch_parent


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
