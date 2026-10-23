"""Run a callback when another process exits (#46).

A hub started from Settings > Team is a child of the desktop engine and must
never outlive it. Rust's tree kill covers a normal app exit, but an engine
that crashes and is respawned leaves its hub behind, holding the port and the
onefile extraction folder. The hub is therefore started with `--parent-pid`
and watches that pid itself.

No server imports here: this module is safe on the stdio path.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from typing import Callable

POSIX_POLL_SECONDS = 2.0


def watch_parent(pid: int, on_exit: Callable[[], None]) -> threading.Thread:
    """Call `on_exit` once `pid` has exited, from a daemon thread. A pid that
    is already gone fires at once."""

    def wait() -> None:
        if sys.platform == "win32":
            _wait_windows(pid)
        else:
            _wait_posix(pid)
        on_exit()

    thread = threading.Thread(target=wait, name="bridge-parent-watch", daemon=True)
    thread.start()
    return thread


def _wait_windows(pid: int) -> None:
    import ctypes

    synchronize = 0x00100000
    infinite = 0xFFFFFFFF
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(synchronize, False, int(pid))
    if not handle:
        return  # no such process: it has already exited
    try:
        kernel32.WaitForSingleObject(handle, infinite)
    finally:
        kernel32.CloseHandle(handle)


def _wait_posix(pid: int) -> None:
    while True:
        try:
            os.kill(int(pid), 0)
        except ProcessLookupError:
            return
        except PermissionError:
            pass  # alive, owned by someone else
        time.sleep(POSIX_POLL_SECONDS)
